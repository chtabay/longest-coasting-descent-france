"""Regional Oisans coasting search: graph, ranking, audit and sensitivity.

Offline: it consumes the frozen Overpass extract and the elevations acquired by
``phase2_acquire_elevations.py``.  Nothing here touches the network, so the
ranking is reproducible from the two cached inputs.

The ranking is experimental and regional.  It exists to exercise the engine
against real terrain and to expose where the definition of the event, not the
software, decides the answer.  No national claim follows from it.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import time
from collections import Counter
from pathlib import Path

from coastdown.curvature import LATERAL_LIMIT_SCENARIOS_M_S2
from coastdown.elevation_profile import METHOD_NAMES, build_profile
from coastdown.elevation_store import elevations_for, load_store
from coastdown.graph import RoutableGraph, build_graph, graph_summary
from coastdown.models import BicycleSystem
from coastdown.search import (
    INITIAL_SPEED_M_S,
    EdgeProfile,
    RouteCandidate,
    SearchBudget,
    brute_force_routes,
    build_edge_profile,
    evaluate_route,
    search_from_edge,
)
from coastdown.surfaces import all_scenarios
from coastdown.textio import write_text_lf

PRODUCTION_METHOD = "raw_25m"
SCENARIOS = ("paved_reference", "reference_vtc")
TOP_N = 20
MAX_EXPANSIONS = 5_000


def build_profiles(
    graph: RoutableGraph,
    store: dict[str, float],
    method: str,
    *,
    crr_variant: str = "central",
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
    *,
    bicycle: BicycleSystem | None = None,
    initial_speed_m_s: float = INITIAL_SPEED_M_S,
    lateral_scenario: str = "nominal",
    max_expansions: int = MAX_EXPANSIONS,
) -> tuple[list[RouteCandidate], dict[str, int]]:
    candidates: list[RouteCandidate] = []
    exhausted = 0
    expansions = 0
    seeds = [edge_id for edge_id, profile in profiles.items() if profile.simulable]
    for seed in seeds:
        routes, budget = search_from_edge(
            graph,
            profiles,
            seed,
            bicycle=bicycle,
            initial_speed_m_s=initial_speed_m_s,
            lateral_scenario=lateral_scenario,
            budget=SearchBudget(max_expansions=max_expansions),
            keep_best=2,
        )
        candidates.extend(routes)
        expansions += budget.expansions
        exhausted += int(budget.exhausted)
    return candidates, {
        "seeds": len(seeds),
        "expansions": expansions,
        "seeds_with_exhausted_budget": exhausted,
    }


def distinct_best(candidates: list[RouteCandidate], limit: int) -> list[RouteCandidate]:
    """Keep the best routes that are not sub-paths of an already-kept one.

    Every interior node of a long descent is also a seed, so the same descent
    reappears as dozens of shorter suffixes.  Ranking them all would fill the
    table with one road.
    """
    ordered = sorted(candidates, key=lambda item: -item.admissible_time_s)
    kept: list[RouteCandidate] = []
    covered: list[set[str]] = []
    for candidate in ordered:
        edges = set(candidate.edge_ids)
        if any(edges <= seen or seen <= edges for seen in covered):
            continue
        kept.append(candidate)
        covered.append(edges)
        if len(kept) >= limit:
            break
    return kept


def route_row(graph: RoutableGraph, candidate: RouteCandidate, rank: int) -> dict[str, object]:
    first = graph.edges[candidate.edge_ids[0]]
    last = graph.edges[candidate.edge_ids[-1]]
    names: list[str] = []
    for edge_id in candidate.edge_ids:
        name = graph.edges[edge_id].name
        if name and (not names or names[-1] != name):
            names.append(name)
    surface = dict(candidate.surface_metres)
    total = sum(surface.values()) or 1.0
    return {
        "rank": rank,
        "admissible_time_s": round(candidate.admissible_time_s, 2),
        "elapsed_time_s": round(candidate.elapsed_time_s, 2),
        "moving_time_s": round(candidate.moving_time_s, 2),
        "stationary_time_s": round(candidate.stationary_time_s, 2),
        "distance_m": round(candidate.distance_m, 1),
        "horizontal_length_m": round(candidate.horizontal_length_m, 1),
        "net_dz_m": round(candidate.net_dz_m, 1),
        "descent_m": round(candidate.descent_m, 1),
        "ascent_m": round(candidate.ascent_m, 1),
        "start_elevation_m": round(candidate.start_elevation_m, 1),
        "end_elevation_m": round(candidate.end_elevation_m, 1),
        "start_lon": round(first.samples[0].longitude, 6),
        "start_lat": round(first.samples[0].latitude, 6),
        "end_lon": round(last.samples[-1].longitude, 6),
        "end_lat": round(last.samples[-1].latitude, 6),
        "max_speed_km_h": round(candidate.max_speed_m_s * 3.6, 2),
        "mean_speed_km_h": round(candidate.mean_speed_m_s * 3.6, 2),
        "roads": " > ".join(names[:8]) + (" ..." if len(names) > 8 else ""),
        "edges_used": candidate.edges_used,
        "stop_reason": candidate.stop_reason,
        "termination": candidate.termination,
        "turn_limited": candidate.turn_limited,
        "bend_count": candidate.turn.bend_count,
        "tightest_radius_m": (
            round(candidate.turn.tightest_radius_m, 1)
            if candidate.turn.tightest_radius_m is not None
            else ""
        ),
        "critical_radius_m": (
            round(candidate.turn.critical_radius_m, 1)
            if candidate.turn.critical_radius_m is not None
            else ""
        ),
        "required_lateral_m_s2": (
            round(candidate.turn.required_lateral_m_s2, 2)
            if candidate.turn.required_lateral_m_s2 is not None
            else ""
        ),
        "lateral_limit_m_s2": round(candidate.turn.lateral_limit_m_s2, 2),
        "turn_margin_m_s2": (
            round(candidate.turn.margin_m_s2, 2) if candidate.turn.margin_m_s2 is not None else ""
        ),
        "surface_mix": ";".join(
            f"{name}={value / total:.0%}" for name, value in sorted(surface.items())
        ),
        "surface_assumed_share": round(candidate.surface_is_assumed_m / total, 3),
        "start_osm_way": first.osm_way_id,
        "end_osm_way": last.osm_way_id,
        "start_osm_url": f"https://www.openstreetmap.org/way/{first.osm_way_id}",
        "edge_ids": ";".join(candidate.edge_ids),
    }


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        write_text_lf(path, "")
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def route_map_svg(graph: RoutableGraph, candidates: list[RouteCandidate], title: str) -> str:
    points = [
        (sample.longitude, sample.latitude)
        for edge in graph.edges.values()
        for sample in edge.samples
    ]
    min_lon = min(p[0] for p in points)
    max_lon = max(p[0] for p in points)
    min_lat = min(p[1] for p in points)
    max_lat = max(p[1] for p in points)
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
                + '" fill="none" stroke="#d9d9d9" stroke-width="0.8"/>'
            )
    palette = ["#d73027", "#fc8d59", "#fee090", "#91bfdb", "#4575b4"]
    for index, candidate in enumerate(candidates):
        pixels = []
        for edge_id in candidate.edge_ids:
            for sample in graph.edges[edge_id].samples:
                pixels.append(place(sample.longitude, sample.latitude))
        if len(pixels) >= 2:
            lines.append(
                '<polyline points="'
                + " ".join(f"{x:.1f},{y:.1f}" for x, y in pixels)
                + f'" fill="none" stroke="{palette[index % len(palette)]}" stroke-width="2.6"/>'
            )
            start = pixels[0]
            lines.append(
                f'<circle cx="{start[0]:.1f}" cy="{start[1]:.1f}" r="4" '
                f'fill="{palette[index % len(palette)]}"/>'
            )
            lines.append(
                f'<text x="{start[0] + 6:.1f}" y="{start[1] - 6:.1f}" '
                f'font-family="sans-serif" font-size="11">{index + 1}</text>'
            )
    lines.append(f'<text x="24" y="26" font-family="sans-serif" font-size="15">{title}</text>')
    lines.append(
        '<text x="24" y="46" font-family="sans-serif" font-size="11">'
        "Experimental regional prototype — not a national claim</text>"
    )
    lines.append("</svg>")
    return "\n".join(lines)


def profile_svg(
    graph: RoutableGraph, profiles: dict[str, EdgeProfile], candidate: RouteCandidate, title: str
) -> str:
    distance = 0.0
    xs: list[float] = [0.0]
    ys: list[float] = []
    elevation = profiles[candidate.edge_ids[0]].start_elevation_m
    ys.append(elevation)
    for edge_id in candidate.edge_ids:
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
                f'<text x="{width - 90}" y="{height - 18}" font-family="sans-serif" '
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--overpass-cache", default=".cache/phase1b-live/oisans-overpass.json")
    parser.add_argument("--elevations", default=".cache/phase2/elevations.json")
    parser.add_argument("--output", default="outputs/phase2")
    parser.add_argument("--method", default=PRODUCTION_METHOD)
    arguments = parser.parse_args()

    started = time.monotonic()
    output = Path(arguments.output)
    (output / "profiles").mkdir(parents=True, exist_ok=True)
    (output / "maps").mkdir(parents=True, exist_ok=True)
    osm = json.loads(Path(arguments.overpass_cache).read_bytes())
    store = load_store(arguments.elevations)

    summaries: dict[str, object] = {}
    all_candidates: list[dict[str, object]] = []
    tops: dict[str, list[RouteCandidate]] = {}
    graphs: dict[str, RoutableGraph] = {}
    profile_sets: dict[str, dict[str, EdgeProfile]] = {}
    search_stats: dict[str, dict[str, int]] = {}

    for scenario in SCENARIOS:
        graph = build_graph(osm, scenario)
        profiles = build_profiles(graph, store, arguments.method)
        graphs[scenario] = graph
        profile_sets[scenario] = profiles
        print(f"[{scenario}] {len(graph.edges)} edges, {len(profiles)} profiled")
        candidates, stats = run_search(graph, profiles)
        search_stats[scenario] = stats
        print(
            f"[{scenario}] {stats['seeds']} seeds, {stats['expansions']} expansions, "
            f"{len(candidates)} routes, {stats['seeds_with_exhausted_budget']} budget-limited"
        )
        top = distinct_best(candidates, TOP_N)
        tops[scenario] = top
        for rank, candidate in enumerate(top, start=1):
            row = route_row(graph, candidate, rank)
            row["scenario"] = scenario
            all_candidates.append(row)

        unsimulable = Counter(
            profile.reason.split(";")[0] for profile in profiles.values() if not profile.simulable
        )
        summaries[scenario] = {
            **graph_summary(graph),
            "profiled_edges": len(profiles),
            "simulable_edges": sum(1 for profile in profiles.values() if profile.simulable),
            "unsimulable_reasons": dict(unsimulable.most_common(5)),
            "search": stats,
            "routes_found": len(candidates),
            "distinct_ranked": len(top),
        }

    # --- outputs -------------------------------------------------------------
    write_csv(output / "candidate_routes.csv", all_candidates)
    for scenario, filename in (
        ("paved_reference", "top20_paved.csv"),
        ("reference_vtc", "top20_vtc.csv"),
    ):
        write_csv(
            output / filename,
            [row for row in all_candidates if row["scenario"] == scenario],
        )

    # Turn-constraint audit over every ranked route in both scenarios.
    turn_rows = []
    for scenario, top in tops.items():
        for rank, candidate in enumerate(top, start=1):
            for name, limit in sorted(LATERAL_LIMIT_SCENARIOS_M_S2.items(), key=lambda kv: kv[1]):
                recomputed = evaluate_route(
                    graphs[scenario],
                    profile_sets[scenario],
                    candidate.edge_ids,
                    seed_edge_id=candidate.seed_edge_id,
                    lateral_scenario=name,
                )
                turn_rows.append(
                    {
                        "scenario": scenario,
                        "rank": rank,
                        "lateral_scenario": name,
                        "lateral_limit_m_s2": round(limit, 2),
                        "bend_count": recomputed.turn.bend_count,
                        "tightest_radius_m": (
                            round(recomputed.turn.tightest_radius_m, 1)
                            if recomputed.turn.tightest_radius_m is not None
                            else ""
                        ),
                        "critical_radius_m": (
                            round(recomputed.turn.critical_radius_m, 1)
                            if recomputed.turn.critical_radius_m is not None
                            else ""
                        ),
                        "speed_at_critical_km_h": (
                            round(recomputed.turn.speed_at_critical_m_s * 3.6, 1)
                            if recomputed.turn.speed_at_critical_m_s is not None
                            else ""
                        ),
                        "required_lateral_m_s2": (
                            round(recomputed.turn.required_lateral_m_s2, 2)
                            if recomputed.turn.required_lateral_m_s2 is not None
                            else ""
                        ),
                        "permitted_speed_km_h": (
                            round(recomputed.turn.permitted_speed_m_s * 3.6, 1)
                            if recomputed.turn.permitted_speed_m_s is not None
                            else ""
                        ),
                        "margin_m_s2": (
                            round(recomputed.turn.margin_m_s2, 2)
                            if recomputed.turn.margin_m_s2 is not None
                            else ""
                        ),
                        "violated": recomputed.turn.violated,
                        "elapsed_time_s": round(recomputed.elapsed_time_s, 2),
                        "admissible_time_s": round(recomputed.admissible_time_s, 2),
                    }
                )
    write_csv(output / "turn_constraint_audit.csv", turn_rows)

    # --- routing validation --------------------------------------------------
    validation_rows = []
    graph = graphs["paved_reference"]
    profiles = profile_sets["paved_reference"]
    simulable = sorted(edge_id for edge_id, item in profiles.items() if item.simulable)
    checked = 0
    for seed in simulable:
        if checked >= 40:
            break
        engine, budget = search_from_edge(
            graph, profiles, seed, budget=SearchBudget(max_expansions=200_000), keep_best=1
        )
        if budget.exhausted or not engine:
            continue
        reference = brute_force_routes(graph, profiles, seed)
        if not reference or len(reference) > 400:
            continue
        checked += 1
        best_reference = max(reference, key=lambda item: item.elapsed_time_s)
        validation_rows.append(
            {
                "seed_edge_id": seed,
                "engine_routes_kept": len(engine),
                "brute_force_routes": len(reference),
                "engine_best_time_s": round(engine[0].elapsed_time_s, 6),
                "brute_force_best_time_s": round(best_reference.elapsed_time_s, 6),
                "identical_time": abs(engine[0].elapsed_time_s - best_reference.elapsed_time_s)
                < 1e-9,
                "identical_path": engine[0].edge_ids == best_reference.edge_ids,
                "expansions": budget.expansions,
            }
        )
    write_csv(output / "routing_validation.csv", validation_rows)
    agreement = sum(1 for row in validation_rows if row["identical_path"])
    print(f"routing validation: {agreement}/{len(validation_rows)} subgraphs match brute force")

    # --- start-point approximation ------------------------------------------
    # Seeds sit at graph nodes, but the event allows a start anywhere on an edge.
    # The top routes are re-run from offsets inside their first edge to measure
    # how much that approximation costs.
    start_rows = []
    for scenario, top in tops.items():
        for rank, candidate in enumerate(top[:10], start=1):
            first = profile_sets[scenario][candidate.edge_ids[0]]
            best_gain = 0.0
            best_offset = 0.0
            cumulative = 0.0
            for index, length in enumerate(first.segment_horizontal_m):
                cumulative += length
                if cumulative < 25.0 or index >= len(first.segment_horizontal_m) - 1:
                    continue
                trimmed = EdgeProfile(
                    edge_id=first.edge_id,
                    segment_travelled_m=first.segment_travelled_m[index:],
                    segment_grade_ratio=first.segment_grade_ratio[index:],
                    segment_rolling_resistance=first.segment_rolling_resistance[index:],
                    segment_horizontal_m=first.segment_horizontal_m[index:],
                    horizontal_length_m=math.fsum(first.segment_horizontal_m[index:]),
                    net_dz_m=first.net_dz_m,
                    ascent_m=first.ascent_m,
                    descent_m=first.descent_m,
                    start_elevation_m=first.start_elevation_m,
                    end_elevation_m=first.end_elevation_m,
                    bends=first.bends,
                    surface_class=first.surface_class,
                    simulable=True,
                    reason="",
                )
                patched = dict(profile_sets[scenario])
                patched[first.edge_id] = trimmed
                shifted = evaluate_route(
                    graphs[scenario],
                    patched,
                    candidate.edge_ids,
                    seed_edge_id=candidate.seed_edge_id,
                    start_offset_m=cumulative,
                )
                gain = shifted.admissible_time_s - candidate.admissible_time_s
                if gain > best_gain:
                    best_gain = gain
                    best_offset = cumulative
            start_rows.append(
                {
                    "scenario": scenario,
                    "rank": rank,
                    "node_start_time_s": round(candidate.admissible_time_s, 2),
                    "best_interior_offset_m": round(best_offset, 1),
                    "best_interior_gain_s": round(best_gain, 2),
                    "relative_gain": round(best_gain / max(candidate.admissible_time_s, 1e-9), 4),
                }
            )
    write_csv(output / "start_point_sensitivity.csv", start_rows)

    # --- physical sensitivity ------------------------------------------------
    sensitivity_rows = []
    baseline_scenario = "paved_reference"
    baseline_top = tops[baseline_scenario]
    variants: list[tuple[str, str, dict]] = [
        ("baseline", "central Crr, CdA 0.55, rotating 1.5 kg, dt 0.05, raw_25m", {}),
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
        ("time_step_fine", "integrator step 0.01 s", {"time_step_s": 0.01}),
        ("time_step_coarse", "integrator step 0.20 s", {"time_step_s": 0.20}),
        ("method_raw_10m", "elevation method raw_10m", {"method": "raw_10m"}),
        ("method_net_dz", "elevation method net_dz_constrained", {"method": "net_dz_constrained"}),
        ("lateral_conservative", "lateral limit 0.20 g", {"lateral_scenario": "conservative"}),
        ("lateral_committed", "lateral limit 0.50 g", {"lateral_scenario": "committed"}),
    ]
    graph = graphs[baseline_scenario]
    for name, description, options in variants:
        method = options.get("method", arguments.method)
        crr_variant = options.get("crr_variant", "central")
        if method != arguments.method or crr_variant != "central":
            variant_profiles = build_profiles(graph, store, method, crr_variant=crr_variant)
        else:
            variant_profiles = profile_sets[baseline_scenario]
        times = []
        for candidate in baseline_top:
            if any(
                edge_id not in variant_profiles or not variant_profiles[edge_id].simulable
                for edge_id in candidate.edge_ids
            ):
                times.append(None)
                continue
            recomputed = evaluate_route(
                graph,
                variant_profiles,
                candidate.edge_ids,
                seed_edge_id=candidate.seed_edge_id,
                bicycle=options.get("bicycle"),
                time_step_s=options.get("time_step_s", 0.05),
                lateral_scenario=options.get("lateral_scenario", "nominal"),
            )
            times.append(recomputed.admissible_time_s)
        usable = [(index, value) for index, value in enumerate(times) if value is not None]
        reordered = [index for index, _ in sorted(usable, key=lambda item: -item[1])]
        original = [index for index, _ in usable]
        changed = sum(1 for a, b in zip(reordered, original) if a != b)
        baseline_times = [candidate.admissible_time_s for candidate in baseline_top]
        deltas = [
            (value - baseline_times[index]) / max(baseline_times[index], 1e-9)
            for index, value in usable
        ]
        sensitivity_rows.append(
            {
                "variant": name,
                "description": description,
                "routes_evaluated": len(usable),
                "top1_unchanged": bool(reordered and reordered[0] == 0),
                "positions_changed": changed,
                "kendall_like_stability": round(1.0 - changed / max(1, len(usable)), 3),
                "median_time_delta": round(statistics.median(deltas), 4) if deltas else "",
                "min_time_delta": round(min(deltas), 4) if deltas else "",
                "max_time_delta": round(max(deltas), 4) if deltas else "",
                "top1_time_s": round(max(value for _, value in usable), 1) if usable else "",
            }
        )
    write_csv(output / "sensitivity.csv", sensitivity_rows)

    # --- manual audit shortlist ---------------------------------------------
    audit_rows = []
    for scenario, top in tops.items():
        for rank, candidate in enumerate(top[:10], start=1):
            first = graphs[scenario].edges[candidate.edge_ids[0]]
            last = graphs[scenario].edges[candidate.edge_ids[-1]]
            surface = dict(candidate.surface_metres)
            total = sum(surface.values()) or 1.0
            flags = []
            if candidate.surface_is_assumed_m / total > 0.5:
                flags.append("majority of length has an assumed surface")
            if candidate.turn_limited:
                flags.append("braking required at a bend")
            if candidate.stationary_time_s > 0.5:
                flags.append("run includes stationary time")
            if candidate.mean_speed_m_s < 1.5:
                flags.append("mean speed below 5.4 km/h: near-equilibrium creep")
            if candidate.ascent_m > 0.5 * candidate.descent_m:
                flags.append("ascent is a large share of descent")
            if candidate.edges_used == 1:
                flags.append("single edge; no junction crossed")
            audit_rows.append(
                {
                    "scenario": scenario,
                    "rank": rank,
                    "admissible_time_s": round(candidate.admissible_time_s, 1),
                    "distance_m": round(candidate.distance_m, 0),
                    "mean_speed_km_h": round(candidate.mean_speed_m_s * 3.6, 1),
                    "max_speed_km_h": round(candidate.max_speed_m_s * 3.6, 1),
                    "start_osm_url": f"https://www.openstreetmap.org/way/{first.osm_way_id}",
                    "end_osm_url": f"https://www.openstreetmap.org/way/{last.osm_way_id}",
                    "start_coordinates": (
                        f"{first.samples[0].latitude:.6f},{first.samples[0].longitude:.6f}"
                    ),
                    "openstreetmap_view": (
                        f"https://www.openstreetmap.org/#map=16/"
                        f"{first.samples[0].latitude:.5f}/{first.samples[0].longitude:.5f}"
                    ),
                    "surface_mix": ";".join(
                        f"{name}={value / total:.0%}" for name, value in sorted(surface.items())
                    ),
                    "surface_assumed_share": round(candidate.surface_is_assumed_m / total, 2),
                    "data_quality_flags": "; ".join(flags) if flags else "none raised",
                }
            )
    write_csv(output / "manual_top10_audit.csv", audit_rows)

    # --- maps and profiles ---------------------------------------------------
    for scenario, top in tops.items():
        write_text_lf(
            output / "maps" / f"top_routes_{scenario}.svg",
            route_map_svg(
                graphs[scenario],
                top[:5],
                f"Oisans coasting candidates — {scenario} (top 5 of {len(top)})",
            ),
        )
        for rank, candidate in enumerate(top[:5], start=1):
            write_text_lf(
                output / "profiles" / f"{scenario}_rank{rank}.svg",
                profile_svg(
                    graphs[scenario],
                    profile_sets[scenario],
                    candidate,
                    f"{scenario} rank {rank}: {round(candidate.admissible_time_s)} s, "
                    f"{round(candidate.distance_m)} m, {round(candidate.net_dz_m)} m net",
                ),
            )

    elapsed = time.monotonic() - started
    summary = {
        "source": "offline reconstruction from the frozen Overpass extract and acquired RGE ALTI elevations",
        "production_elevation_method": arguments.method,
        "initial_speed_km_h": 15.0,
        "braking": "not permitted in the reference event",
        "cycle_rule": "each way piece at most once per route, in at most one direction",
        "scenarios": summaries,
        "rolling_resistance_scenarios": [
            {
                "surface_class": item.surface_class.value,
                "central": item.central,
                "low": item.low,
                "high": item.high,
                "basis": item.basis,
                "uncertainty": item.uncertainty,
            }
            for item in all_scenarios()
        ],
        "lateral_limits_m_s2": {
            name: round(value, 3) for name, value in LATERAL_LIMIT_SCENARIOS_M_S2.items()
        },
        "elevation_methods_compared": list(METHOD_NAMES),
        "runtime_s": round(elapsed, 1),
        "claim": "experimental regional prototype; no national or regional record is claimed",
    }
    (output / "regional_graph_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"wrote {output} in {elapsed:.0f}s")


if __name__ == "__main__":
    main()
