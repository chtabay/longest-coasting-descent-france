"""Regional Oisans rerun under the definitive objective: maximum distance.

Offline. It reuses, unchanged, everything the change of objective does not
touch: the frozen Overpass extract, the usability classes, the surface and Crr
scenarios, ``raw_25m`` for the longitudinal profile, the 5 m geometry for bends,
the turn restrictions, and the acquired RGE ALTI elevations.

What changes is the question. Phase 2 maximised elapsed time and found a
degenerate optimum near equilibrium. The objective is now

    max distance travelled until the definitive physical stop

with no condition on grade, descent, mean speed or duration, and with braking
reduced to the minimum a speed envelope demands rather than anything the search
may choose.
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import time
from collections import Counter
from pathlib import Path

from coastdown.coasting import DEFAULT_BRAKE_DECELERATION_M_S2
from coastdown.curvature import LATERAL_LIMIT_SCENARIOS_M_S2
from coastdown.distance_search import (
    DistanceBudget,
    DistanceRoute,
    brute_force_distance_routes,
    distinct_longest,
    evaluate_distance_route,
    search_distance_from_edge,
    start_offsets,
    trim_edge_profile,
)
from coastdown.elevation_profile import build_profile
from coastdown.elevation_store import elevations_for, load_store
from coastdown.graph import RoutableGraph, build_graph, graph_summary
from coastdown.models import BicycleSystem
from coastdown.search import EdgeProfile, build_edge_profile
from coastdown.textio import write_text_lf

PRODUCTION_METHOD = "raw_25m"
SCENARIOS = ("paved_reference", "reference_vtc")
TOP_N = 20
MAX_EXPANSIONS = 5_000
SCREENING_OFFSET_STEP_M = 100.0
REFINING_OFFSET_STEP_M = 25.0


def build_profiles(
    graph: RoutableGraph, store: dict[str, float], method: str, crr_variant: str = "central"
) -> dict[str, EdgeProfile]:
    profiles: dict[str, EdgeProfile] = {}
    for edge_id, edge in graph.edges.items():
        base = elevations_for(store, edge.samples)
        if base is None:
            continue
        try:
            built = build_profile(method, edge.samples, base)
        except ValueError:
            continue
        profiles[edge_id] = build_edge_profile(
            edge,
            built.samples,
            built.elevations_m,
            crr_variant=crr_variant,
            geometry_samples=edge.samples,
        )
    return profiles


def run_search(
    graph: RoutableGraph,
    profiles: dict[str, EdgeProfile],
    **kwargs,
) -> tuple[list[DistanceRoute], dict[str, int]]:
    routes: list[DistanceRoute] = []
    expansions = 0
    exhausted = 0
    seeds = [edge_id for edge_id, item in profiles.items() if item.simulable]
    for seed in seeds:
        found, budget = search_distance_from_edge(
            graph,
            profiles,
            seed,
            budget=DistanceBudget(max_expansions=MAX_EXPANSIONS),
            keep_best=2,
            **kwargs,
        )
        routes.extend(found)
        expansions += budget.expansions
        exhausted += int(budget.exhausted)
    return routes, {
        "seeds": len(seeds),
        "expansions": expansions,
        "seeds_with_exhausted_budget": exhausted,
    }


def route_row(graph: RoutableGraph, route: DistanceRoute, rank: int) -> dict[str, object]:
    first = graph.edges[route.edge_ids[0]]
    last = graph.edges[route.edge_ids[-1]]
    names: list[str] = []
    for edge_id in route.edge_ids:
        name = graph.edges[edge_id].name
        if name and (not names or names[-1] != name):
            names.append(name)
    surface = dict(route.surface_metres)
    total = sum(surface.values()) or 1.0
    return {
        "rank": rank,
        "distance_m": round(route.distance_m, 1),
        "elapsed_time_s": round(route.elapsed_time_s, 1),
        "moving_time_s": round(route.moving_time_s, 1),
        "start_elevation_m": round(route.start_elevation_m, 1),
        "end_elevation_m": round(route.end_elevation_m, 1),
        "net_dz_m": round(route.net_dz_m, 1),
        "ascent_crossed_m": round(route.ascent_m, 1),
        "descent_m": round(route.descent_m, 1),
        "mean_speed_km_h": round(route.mean_speed_m_s * 3.6, 2),
        "max_speed_km_h": round(route.max_speed_m_s * 3.6, 2),
        "max_free_speed_km_h": round(route.max_free_speed_m_s * 3.6, 2),
        "min_speed_before_stop_km_h": round(route.minimum_speed_before_stop_m_s * 3.6, 2),
        "braking_constrained": route.active_constraints > 0,
        "braking_energy_j": round(route.braking_energy_j, 1),
        "braking_distance_m": round(route.braking_distance_m, 1),
        "active_constraints": route.active_constraints,
        "braking_substeps": route.braking_substeps,
        "restart_count": route.restart_count,
        "distance_to_5kmh_m": (
            round(route.distance_to_5kmh_m, 1) if route.distance_to_5kmh_m is not None else ""
        ),
        "distance_to_1kmh_m": (
            round(route.distance_to_1kmh_m, 1) if route.distance_to_1kmh_m is not None else ""
        ),
        "distance_to_030ms_m": (
            round(route.distance_to_030ms_m, 1) if route.distance_to_030ms_m is not None else ""
        ),
        "surface_mix": ";".join(
            f"{name}={value / total:.0%}" for name, value in sorted(surface.items())
        ),
        "surface_assumed_share": round(route.surface_is_assumed_m / total, 3),
        "termination": route.termination,
        "stop_reason": route.stop_reason,
        "start_lat": round(first.samples[0].latitude, 6),
        "start_lon": round(first.samples[0].longitude, 6),
        "end_lat": round(last.samples[-1].latitude, 6),
        "end_lon": round(last.samples[-1].longitude, 6),
        "start_offset_m": round(route.start_offset_m, 1),
        "roads": " > ".join(names[:10]) + (" ..." if len(names) > 10 else ""),
        "edges_used": route.edges_used,
        "osm_way_ids": ";".join(
            str(way)
            for way in dict.fromkeys(graph.edges[edge].osm_way_id for edge in route.edge_ids)
        ),
        "start_osm_url": f"https://www.openstreetmap.org/way/{first.osm_way_id}",
        "edge_ids": ";".join(route.edge_ids),
    }


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        write_text_lf(path, "")
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def route_map_svg(graph: RoutableGraph, routes: list[DistanceRoute], title: str) -> str:
    points = [
        (sample.longitude, sample.latitude)
        for edge in graph.edges.values()
        for sample in edge.samples
    ]
    min_lon, max_lon = min(p[0] for p in points), max(p[0] for p in points)
    min_lat, max_lat = min(p[1] for p in points), max(p[1] for p in points)
    width, height, margin = 960, 820, 40

    def place(lon: float, lat: float) -> tuple[float, float]:
        return (
            margin + (width - 2 * margin) * (lon - min_lon) / max(1e-9, max_lon - min_lon),
            height
            - margin
            - (height - 2 * margin) * (lat - min_lat) / max(1e-9, max_lat - min_lat),
        )

    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">',
        '<rect width="100%" height="100%" fill="white"/>',
    ]
    drawn: set[tuple[int, int]] = set()
    for edge in graph.edges.values():
        key = (edge.osm_way_id, edge.piece_index)
        if key in drawn:
            continue
        drawn.add(key)
        pixels: list[tuple[float, float]] = []
        for sample in edge.samples:
            position = place(sample.longitude, sample.latitude)
            if (
                not pixels
                or max(abs(position[0] - pixels[-1][0]), abs(position[1] - pixels[-1][1])) >= 1.0
            ):
                pixels.append(position)
        if len(pixels) >= 2:
            lines.append(
                '<polyline points="'
                + " ".join(f"{x:.1f},{y:.1f}" for x, y in pixels)
                + '" fill="none" stroke="#dddddd" stroke-width="0.8"/>'
            )
    palette = ["#b2182b", "#ef8a62", "#67a9cf", "#2166ac", "#1b7837"]
    for index, route in enumerate(routes):
        pixels = [
            place(sample.longitude, sample.latitude)
            for edge_id in route.edge_ids
            for sample in graph.edges[edge_id].samples
        ]
        if len(pixels) < 2:
            continue
        lines.append(
            '<polyline points="'
            + " ".join(f"{x:.1f},{y:.1f}" for x, y in pixels)
            + f'" fill="none" stroke="{palette[index % len(palette)]}" stroke-width="2.8"/>'
        )
        lines.append(
            f'<circle cx="{pixels[0][0]:.1f}" cy="{pixels[0][1]:.1f}" r="5" '
            f'fill="{palette[index % len(palette)]}"/>'
        )
        lines.append(
            f'<text x="{pixels[0][0] + 7:.1f}" y="{pixels[0][1] - 7:.1f}" '
            f'font-family="sans-serif" font-size="12">{index + 1} '
            f"({route.distance_m / 1000:.2f} km)</text>"
        )
    lines.append(f'<text x="24" y="26" font-family="sans-serif" font-size="15">{title}</text>')
    lines.append(
        '<text x="24" y="46" font-family="sans-serif" font-size="11">'
        "Experimental regional prototype — maximum coasting distance — not a national claim</text>"
    )
    lines.append("</svg>")
    return "\n".join(lines)


def profile_svg(profiles: dict[str, EdgeProfile], route: DistanceRoute, title: str) -> str:
    distance = 0.0
    xs = [0.0]
    elevation = profiles[route.edge_ids[0]].start_elevation_m
    ys = [elevation]
    for edge_id in route.edge_ids:
        item = profiles[edge_id]
        for length, grade in zip(item.segment_horizontal_m, item.segment_grade_ratio):
            distance += length
            elevation += grade * length
            xs.append(distance)
            ys.append(elevation)
    width, height, left, bottom = 900, 380, 70, 50
    span_x = max(xs) - min(xs) or 1.0
    span_y = max(ys) - min(ys) or 1.0
    points = " ".join(
        f"{left + (width - left - 20) * (x - min(xs)) / span_x:.1f},"
        f"{height - bottom - (height - bottom - 40) * (y - min(ys)) / span_y:.1f}"
        for x, y in zip(xs, ys)
    )
    return "\n".join(
        [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">',
            '<rect width="100%" height="100%" fill="white"/>',
            f'<text x="20" y="24" font-family="sans-serif" font-size="14">{title}</text>',
            (
                f'<line x1="{left}" y1="{height - bottom}" x2="{width - 20}" '
                f'y2="{height - bottom}" stroke="#333"/>'
            ),
            f'<line x1="{left}" y1="30" x2="{left}" y2="{height - bottom}" stroke="#333"/>',
            f'<polyline points="{points}" fill="none" stroke="#2166ac" stroke-width="2"/>',
            (
                f'<text x="{left}" y="{height - 18}" font-family="sans-serif" font-size="11">'
                f"0 m</text>"
            ),
            (
                f'<text x="{width - 110}" y="{height - 18}" font-family="sans-serif" '
                f'font-size="11">{max(xs):.0f} m</text>'
            ),
            f'<text x="12" y="40" font-family="sans-serif" font-size="11">{max(ys):.0f} m</text>',
            (
                f'<text x="12" y="{height - bottom}" font-family="sans-serif" font-size="11">'
                f"{min(ys):.0f} m</text>"
            ),
            "</svg>",
        ]
    )


def optimise_start(
    graph: RoutableGraph,
    profiles: dict[str, EdgeProfile],
    route: DistanceRoute,
    step_m: float,
) -> tuple[float, float]:
    """Best in-edge start offset for one route, and the distance it gains.

    The baseline is measured with the SAME procedure as the candidates, at
    offset zero. Comparing a candidate search against ``route.distance_m``
    manufactured the whole reported gain: ``route`` is a *distinct-ranked*
    route, while ``search_distance_from_edge(keep_best=1)`` returns the seed's
    own best route, which is a different and usually longer one. On the two
    published seeds the difference between those two numbers was exactly the
    "gain" reported (4494.85 - 4178.98 = 315.87 m), and the true answer at every
    offset was that starting later only removes road.
    """
    seed_id = route.edge_ids[0]
    seed = profiles[seed_id]
    baseline, baseline_budget = search_distance_from_edge(
        graph, profiles, seed_id, budget=DistanceBudget(max_expansions=MAX_EXPANSIONS), keep_best=1
    )
    if baseline_budget.exhausted or not baseline:
        return 0.0, 0.0
    best_offset = 0.0
    best_distance = baseline[0].distance_m
    reference = best_distance
    for offset in start_offsets(seed, step_m):
        if offset <= 0:
            continue
        try:
            trim_edge_profile(seed, offset)
        except ValueError:
            continue
        found, budget = search_distance_from_edge(
            graph,
            profiles,
            route.edge_ids[0],
            start_offset_m=offset,
            budget=DistanceBudget(max_expansions=MAX_EXPANSIONS),
            keep_best=1,
        )
        if budget.exhausted or not found:
            continue
        if found[0].distance_m > best_distance:
            best_distance = found[0].distance_m
            best_offset = offset
    return best_offset, best_distance - reference


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--overpass-cache", default=".cache/phase1b-live/oisans-overpass.json")
    parser.add_argument("--elevations", default=".cache/phase2/elevations.json")
    parser.add_argument("--output", default="outputs/phase3")
    arguments = parser.parse_args()

    started = time.monotonic()
    output = Path(arguments.output)
    (output / "maps").mkdir(parents=True, exist_ok=True)
    (output / "profiles").mkdir(parents=True, exist_ok=True)
    osm = json.loads(Path(arguments.overpass_cache).read_bytes())
    store = load_store(arguments.elevations)

    graphs: dict[str, RoutableGraph] = {}
    profile_sets: dict[str, dict[str, EdgeProfile]] = {}
    tops: dict[str, list[DistanceRoute]] = {}
    summaries: dict[str, object] = {}
    all_rows: list[dict[str, object]] = []

    for scenario in SCENARIOS:
        graph = build_graph(osm, scenario)
        profiles = build_profiles(graph, store, PRODUCTION_METHOD)
        graphs[scenario] = graph
        profile_sets[scenario] = profiles
        routes, stats = run_search(graph, profiles)
        top = distinct_longest(routes, TOP_N)
        tops[scenario] = top
        print(
            f"[{scenario}] {stats['seeds']} seeds, {stats['expansions']} expansions, "
            f"{len(routes)} routes, {stats['seeds_with_exhausted_budget']} budget-limited, "
            f"best {top[0].distance_m:.0f} m"
        )
        for rank, route in enumerate(top, start=1):
            row = route_row(graph, route, rank)
            row["scenario"] = scenario
            all_rows.append(row)
        summaries[scenario] = {
            **graph_summary(graph),
            "profiled_edges": len(profiles),
            "simulable_edges": sum(1 for item in profiles.values() if item.simulable),
            "search": stats,
            "routes_found": len(routes),
            "distinct_ranked": len(top),
            "stop_reasons": dict(Counter(route.stop_reason for route in routes).most_common()),
            "routes_with_a_restart": sum(1 for route in routes if route.restart_count),
        }

    write_csv(output / "candidate_routes.csv", all_rows)
    write_csv(
        output / "top20_paved.csv",
        [row for row in all_rows if row["scenario"] == "paved_reference"],
    )
    write_csv(
        output / "top20_vtc.csv",
        [row for row in all_rows if row["scenario"] == "reference_vtc"],
    )

    # --- braking model comparison -------------------------------------------
    braking_rows = []
    for scenario, top in tops.items():
        for rank, route in enumerate(top, start=1):
            variants = {}
            for model in ("none", "ideal", "anticipated"):
                variants[model] = evaluate_distance_route(
                    graphs[scenario],
                    profile_sets[scenario],
                    route.edge_ids,
                    seed_edge_id=route.seed_edge_id,
                    start_offset_m=route.start_offset_m,
                    braking=model,
                )
            ideal, anticipated, free = (
                variants["ideal"],
                variants["anticipated"],
                variants["none"],
            )
            braking_rows.append(
                {
                    "scenario": scenario,
                    "rank": rank,
                    "distance_unbraked_m": round(free.distance_m, 1),
                    "distance_ideal_m": round(ideal.distance_m, 1),
                    "distance_anticipated_m": round(anticipated.distance_m, 1),
                    "relative_difference": round(
                        abs(anticipated.distance_m - ideal.distance_m)
                        / max(ideal.distance_m, 1e-9),
                        6,
                    ),
                    "braking_cost_vs_unbraked": round(
                        (free.distance_m - ideal.distance_m) / max(free.distance_m, 1e-9), 6
                    ),
                    "energy_ideal_j": round(ideal.braking_energy_j, 1),
                    "energy_anticipated_j": round(anticipated.braking_energy_j, 1),
                    "braking_distance_ideal_m": round(ideal.braking_distance_m, 1),
                    "braking_distance_anticipated_m": round(anticipated.braking_distance_m, 1),
                    "binding_constraints_ideal": ideal.active_constraints,
                    "binding_constraints_anticipated": anticipated.active_constraints,
                    "braking_substeps_ideal": ideal.braking_substeps,
                    "braking_substeps_anticipated": anticipated.braking_substeps,
                    "max_free_speed_km_h": round(ideal.max_free_speed_m_s * 3.6, 1),
                    "max_speed_reached_km_h": round(ideal.max_speed_m_s * 3.6, 1),
                    "brake_deceleration_m_s2": DEFAULT_BRAKE_DECELERATION_M_S2,
                }
            )
    write_csv(output / "braking_model_comparison.csv", braking_rows)
    differences = [row["relative_difference"] for row in braking_rows]
    print(
        f"braking models: max relative distance difference "
        f"{max(differences) if differences else 0:.2%}"
    )

    # --- routing validation --------------------------------------------------
    validation_rows = []
    graph = graphs["paved_reference"]
    profiles = profile_sets["paved_reference"]
    checked = 0
    for seed in sorted(edge_id for edge_id, item in profiles.items() if item.simulable):
        if checked >= 40:
            break
        engine, budget = search_distance_from_edge(
            graph, profiles, seed, budget=DistanceBudget(max_expansions=200_000), keep_best=1
        )
        if budget.exhausted or not engine:
            continue
        reference = brute_force_distance_routes(graph, profiles, seed)
        if not reference or len(reference) > 400:
            continue
        checked += 1
        best = max(reference, key=lambda item: item.distance_m)
        validation_rows.append(
            {
                "seed_edge_id": seed,
                "brute_force_routes": len(reference),
                "engine_best_distance_m": round(engine[0].distance_m, 6),
                "brute_force_best_distance_m": round(best.distance_m, 6),
                "identical_distance": abs(engine[0].distance_m - best.distance_m) < 1e-9,
                "identical_path": engine[0].edge_ids == best.edge_ids,
                "expansions": budget.expansions,
            }
        )
    write_csv(output / "routing_validation.csv", validation_rows)
    agreed = sum(1 for row in validation_rows if row["identical_path"])
    print(f"routing validation: {agreed}/{len(validation_rows)} match brute force")

    # --- start point ---------------------------------------------------------
    start_rows = []
    for scenario, top in tops.items():
        for rank, route in enumerate(top[:10], start=1):
            screen_offset, screen_gain = optimise_start(
                graphs[scenario], profile_sets[scenario], route, SCREENING_OFFSET_STEP_M
            )
            fine_offset, fine_gain = optimise_start(
                graphs[scenario], profile_sets[scenario], route, REFINING_OFFSET_STEP_M
            )
            start_rows.append(
                {
                    "scenario": scenario,
                    "rank": rank,
                    "node_start_distance_m": round(route.distance_m, 1),
                    "screening_step_m": SCREENING_OFFSET_STEP_M,
                    "screening_best_offset_m": round(screen_offset, 1),
                    "screening_gain_m": round(screen_gain, 1),
                    "refining_step_m": REFINING_OFFSET_STEP_M,
                    "refining_best_offset_m": round(fine_offset, 1),
                    "refining_gain_m": round(fine_gain, 1),
                    "refining_relative_gain": round(fine_gain / max(route.distance_m, 1e-9), 4),
                    "screening_captured_share": round(
                        screen_gain / fine_gain if fine_gain > 1e-9 else 1.0, 3
                    ),
                }
            )
    write_csv(output / "start_point_strategy.csv", start_rows)
    gains = [row["refining_relative_gain"] for row in start_rows]
    print(f"start point: max relative gain {max(gains) if gains else 0:.1%}")

    # --- sensitivity ---------------------------------------------------------
    baseline_scenario = "paved_reference"
    baseline = tops[baseline_scenario]
    graph = graphs[baseline_scenario]
    variants: list[tuple[str, str, dict]] = [
        ("baseline", "central Crr, CdA 0.55, rotating 1.5 kg, dt 0.05, raw_25m, ideal", {}),
        ("crr_low", "low Crr bound for every surface", {"crr_variant": "low"}),
        ("crr_high", "high Crr bound for every surface", {"crr_variant": "high"}),
        ("cda_low", "drag area 0.45 m2", {"bicycle": BicycleSystem(drag_area_m2=0.45)}),
        ("cda_high", "drag area 0.65 m2", {"bicycle": BicycleSystem(drag_area_m2=0.65)}),
        (
            "rotating_zero",
            "rotating equivalent mass disabled",
            {"bicycle": BicycleSystem(rotating_equivalent_mass_kg=0.0)},
        ),
        (
            "rotating_high",
            "rotating equivalent mass 3 kg",
            {"bicycle": BicycleSystem(rotating_equivalent_mass_kg=3.0)},
        ),
        ("method_raw_10m", "elevation method raw_10m", {"method": "raw_10m"}),
        ("method_net_dz", "elevation method net_dz_constrained", {"method": "net_dz_constrained"}),
        ("lateral_conservative", "lateral limit 0.20 g", {"lateral_scenario": "conservative"}),
        ("lateral_committed", "lateral limit 0.50 g", {"lateral_scenario": "committed"}),
        ("braking_none", "no speed envelope at all", {"braking": "none"}),
        ("braking_anticipated", "anticipated braking at 1.5 m/s2", {"braking": "anticipated"}),
        ("time_step_fine", "integrator step 0.01 s", {"time_step_s": 0.01}),
        ("time_step_coarse", "integrator step 0.20 s", {"time_step_s": 0.20}),
        ("zero_epsilon_loose", "zero detected at 1e-3 m/s", {"zero_speed_epsilon_m_s": 1e-3}),
        ("zero_epsilon_tight", "zero detected at 1e-9 m/s", {"zero_speed_epsilon_m_s": 1e-9}),
    ]
    sensitivity_rows = []
    for name, description, options in variants:
        method = options.get("method", PRODUCTION_METHOD)
        crr_variant = options.get("crr_variant", "central")
        variant_profiles = (
            profile_sets[baseline_scenario]
            if method == PRODUCTION_METHOD and crr_variant == "central"
            else build_profiles(graph, store, method, crr_variant)
        )
        distances: list[float | None] = []
        for route in baseline:
            if any(
                edge_id not in variant_profiles or not variant_profiles[edge_id].simulable
                for edge_id in route.edge_ids
            ):
                distances.append(None)
                continue
            recomputed = evaluate_distance_route(
                graph,
                variant_profiles,
                route.edge_ids,
                seed_edge_id=route.seed_edge_id,
                start_offset_m=route.start_offset_m,
                bicycle=options.get("bicycle"),
                time_step_s=options.get("time_step_s", 0.05),
                lateral_scenario=options.get("lateral_scenario", "nominal"),
                braking=options.get("braking", "ideal"),
                zero_speed_epsilon_m_s=options.get("zero_speed_epsilon_m_s", 1e-6),
            )
            distances.append(recomputed.distance_m)
        usable = [(index, value) for index, value in enumerate(distances) if value is not None]
        reordered = [index for index, _ in sorted(usable, key=lambda item: -item[1])]
        original = [index for index, _ in usable]
        changed = sum(1 for a, b in zip(reordered, original) if a != b)
        base_values = [route.distance_m for route in baseline]
        deltas = [
            (value - base_values[index]) / max(base_values[index], 1e-9) for index, value in usable
        ]
        sensitivity_rows.append(
            {
                "variant": name,
                "description": description,
                "routes_evaluated": len(usable),
                "top1_unchanged": bool(reordered and reordered[0] == 0),
                "positions_changed": changed,
                "order_stability": round(1.0 - changed / max(1, len(usable)), 3),
                "median_distance_delta": round(statistics.median(deltas), 5) if deltas else "",
                "min_distance_delta": round(min(deltas), 5) if deltas else "",
                "max_distance_delta": round(max(deltas), 5) if deltas else "",
                "top1_distance_m": round(max(value for _, value in usable), 1) if usable else "",
            }
        )
    write_csv(output / "sensitivity.csv", sensitivity_rows)

    # --- objective comparison ------------------------------------------------
    comparison_rows = []
    for rank, route in enumerate(tops[baseline_scenario][:10], start=1):
        comparison_rows.append(
            {
                "rank": rank,
                "objective": "max_distance",
                "distance_m": round(route.distance_m, 1),
                "elapsed_time_s": round(route.elapsed_time_s, 1),
                "mean_speed_km_h": round(route.mean_speed_m_s * 3.6, 2),
                "net_dz_m": round(route.net_dz_m, 1),
                "edges_used": route.edges_used,
                "roads": route_row(graph, route, rank)["roads"],
            }
        )
    write_csv(output / "objective_comparison.csv", comparison_rows)

    # --- maps and profiles ---------------------------------------------------
    for scenario, top in tops.items():
        write_text_lf(
            output / "maps" / f"top_routes_{scenario}.svg",
            route_map_svg(
                graphs[scenario],
                top[:5],
                f"Oisans maximum coasting distance — {scenario} (top 5 of {len(top)})",
            ),
        )
        for rank, route in enumerate(top[:5], start=1):
            write_text_lf(
                output / "profiles" / f"{scenario}_rank{rank}.svg",
                profile_svg(
                    profile_sets[scenario],
                    route,
                    f"{scenario} rank {rank}: {route.distance_m:.0f} m, "
                    f"{route.net_dz_m:.0f} m net, {route.elapsed_time_s:.0f} s",
                ),
            )

    elapsed = time.monotonic() - started
    summary = {
        "objective": "max distance travelled until the definitive physical stop",
        "replaces": "max elapsed_time (Phase 2)",
        "initial_speed_km_h": 15.0,
        "definitive_stop": (
            "speed reaches zero and no spontaneous forward acceleration restarts the "
            "bicycle; a zero on a segment boundary is decided by the segment entered"
        ),
        "braking": (
            "no discretionary braking; only the minimum needed to respect a bend speed "
            "envelope, compared under an ideal and an anticipated representation"
        ),
        "brake_deceleration_m_s2": DEFAULT_BRAKE_DECELERATION_M_S2,
        "cycle_rule": "each physical way piece at most once per trip, whichever direction",
        "production_elevation_method": PRODUCTION_METHOD,
        "lateral_limits_m_s2": {
            name: round(value, 3) for name, value in LATERAL_LIMIT_SCENARIOS_M_S2.items()
        },
        "scenarios": summaries,
        "runtime_s": round(elapsed, 1),
        "claim": "experimental regional prototype; no national claim",
    }
    write_text_lf(
        output / "regional_distance_summary.json",
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
    )
    best = tops["paved_reference"][0]
    print(
        f"\nregional record (paved_reference): {best.distance_m:.0f} m, "
        f"{best.net_dz_m:.0f} m net, {best.elapsed_time_s:.0f} s, "
        f"{best.max_speed_m_s * 3.6:.1f} km/h max"
    )
    print(f"wrote {output} in {elapsed:.0f}s")


if __name__ == "__main__":
    main()
