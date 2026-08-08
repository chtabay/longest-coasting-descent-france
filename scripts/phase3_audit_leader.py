"""Manual audit of one ranked route, edge by edge and joule by joule.

A ranking is a number. This asks whether the number describes a road a person
could ride: which OSM ways it uses in which order, where it starts and stops on
the ground, what surface each part actually has and how much of that was tagged
rather than inferred, which bends bind and where, and whether the energy books
balance.

The energy budget is reconstructed independently of the integrator, by summing
the work of each force over the run's own samples. It therefore does not merely
restate what the simulator recorded: if the reconstruction and the simulator
disagree, the residual says so, and the residual is published.

Nothing here adjusts the model to make a result read better. The audit reports
what the route is, including the parts that weaken the claim.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path

from coastdown.curvature import DEFAULT_LATERAL_SCENARIO
from coastdown.distance_search import (
    evaluate_distance_route,
    route_bend_limits,
    simulate_path,
)
from coastdown.elevation_profile import build_profile
from coastdown.elevation_store import elevations_for, load_store
from coastdown.graph import RoutableGraph, build_graph
from coastdown.models import BicycleSystem, Environment
from coastdown.search import EdgeProfile, build_edge_profile
from coastdown.textio import write_text_lf

PRODUCTION_METHOD = "raw_25m"
STRUCTURE_TAGS = ("bridge", "tunnel", "covered", "layer", "tracktype", "surface", "smoothness")


def build_profiles(graph: RoutableGraph, store: dict[str, float]) -> dict[str, EdgeProfile]:
    profiles: dict[str, EdgeProfile] = {}
    for edge_id, edge in graph.edges.items():
        base = elevations_for(store, edge.samples)
        if base is None:
            continue
        try:
            built = build_profile(PRODUCTION_METHOD, edge.samples, base)
        except ValueError:
            continue
        profiles[edge_id] = build_edge_profile(
            edge, built.samples, built.elevations_m, geometry_samples=edge.samples
        )
    return profiles


def segment_index_at(cumulative: list[float], distance: float) -> int:
    """Index of the joined-profile segment containing a travelled distance."""
    for index, end in enumerate(cumulative):
        if distance <= end + 1e-9:
            return index
    return len(cumulative) - 1


def energy_budget(
    chain: list[EdgeProfile],
    run,
    bicycle: BicycleSystem,
    environment: Environment,
) -> dict[str, float]:
    """Work done by each force along the run, summed over the run's samples.

    Rebuilt from the trajectory rather than read off the simulator, so the
    closing residual is a real check on both.
    """
    grades: list[float] = []
    resistances: list[float] = []
    lengths: list[float] = []
    for item in chain:
        grades.extend(item.segment_grade_ratio)
        resistances.extend(item.segment_rolling_resistance)
        lengths.extend(item.segment_travelled_m)
    cumulative: list[float] = []
    running = 0.0
    for length in lengths:
        running += length
        cumulative.append(running)

    mass = bicycle.translational_mass_kg
    gravity = environment.gravity_m_s2
    drag_coefficient = 0.5 * environment.air_density_kg_m3 * bicycle.drag_area_m2

    rolling = 0.0
    drag = 0.0
    gravity_release = 0.0
    for index in range(len(run.distance_m) - 1):
        step = run.distance_m[index + 1] - run.distance_m[index]
        if step <= 0:
            continue
        middle = 0.5 * (run.distance_m[index] + run.distance_m[index + 1])
        segment = segment_index_at(cumulative, middle)
        theta = math.atan(grades[segment])
        speed_squared = 0.5 * (run.speed_m_s[index] ** 2 + run.speed_m_s[index + 1] ** 2)
        rolling += resistances[segment] * mass * gravity * math.cos(theta) * step
        drag += drag_coefficient * speed_squared * step
        gravity_release += -mass * gravity * math.sin(theta) * step

    initial = 0.5 * bicycle.effective_inertial_mass_kg * run.speed_m_s[0] ** 2
    final = 0.5 * bicycle.effective_inertial_mass_kg * run.speed_m_s[-1] ** 2
    supplied = initial + gravity_release
    consumed = rolling + drag + run.braking_energy_j + final
    return {
        "initial_kinetic_j": initial,
        "gravity_released_j": gravity_release,
        "total_supplied_j": supplied,
        "rolling_dissipated_j": rolling,
        "drag_dissipated_j": drag,
        "braking_dissipated_j": run.braking_energy_j,
        "final_kinetic_j": final,
        "total_consumed_j": consumed,
        "residual_j": supplied - consumed,
        "residual_relative": (supplied - consumed) / supplied if supplied else 0.0,
    }


def svg_polyline(
    path: Path, xs: list[float], ys: list[float], title: str, x_label: str, y_label: str
) -> None:
    width, height, pad = 900.0, 320.0, 55.0
    span_x = (max(xs) - min(xs)) or 1.0
    span_y = (max(ys) - min(ys)) or 1.0
    points = " ".join(
        f"{pad + (x - min(xs)) / span_x * (width - 2 * pad):.2f},"
        f"{height - pad - (y - min(ys)) / span_y * (height - 2 * pad):.2f}"
        for x, y in zip(xs, ys)
    )
    write_text_lf(
        path,
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.0f}" height="{height:.0f}" '
        f'viewBox="0 0 {width:.0f} {height:.0f}">\n'
        f'  <rect width="{width:.0f}" height="{height:.0f}" fill="#ffffff"/>\n'
        f'  <text x="{pad:.0f}" y="26" font-family="sans-serif" font-size="15">{title}</text>\n'
        f'  <polyline fill="none" stroke="#2166ac" stroke-width="1.8" points="{points}"/>\n'
        f'  <text x="{pad:.0f}" y="{height - 14:.0f}" font-family="sans-serif" font-size="12">'
        f"{x_label}: {min(xs):.0f} to {max(xs):.0f}</text>\n"
        f'  <text x="{width - pad - 250:.0f}" y="{height - 14:.0f}" font-family="sans-serif" '
        f'font-size="12">{y_label}: {min(ys):.1f} to {max(ys):.1f}</text>\n'
        f"</svg>\n",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", default="reference_vtc")
    parser.add_argument("--rank", type=int, default=1)
    parser.add_argument("--overpass-cache", default=".cache/phase1b-live/oisans-overpass.json")
    parser.add_argument("--elevations", default=".cache/phase2/elevations.json")
    parser.add_argument("--candidates", default="outputs/phase3/candidate_routes.csv")
    parser.add_argument("--output", default="outputs/phase3/audit")
    arguments = parser.parse_args()

    output = Path(arguments.output)
    output.mkdir(parents=True, exist_ok=True)
    osm = json.loads(Path(arguments.overpass_cache).read_bytes())
    store = load_store(arguments.elevations)
    graph = build_graph(osm, arguments.scenario)
    profiles = build_profiles(graph, store)

    with Path(arguments.candidates).open(encoding="utf-8") as handle:
        rows = [
            row
            for row in csv.DictReader(handle)
            if row["scenario"] == arguments.scenario and int(row["rank"]) == arguments.rank
        ]
    if not rows:
        raise SystemExit(f"no rank {arguments.rank} row for {arguments.scenario}")
    edge_ids = rows[0]["edge_ids"].split(";")

    bicycle = BicycleSystem()
    environment = Environment()
    chain, run = simulate_path(graph, profiles, edge_ids, bicycle=bicycle, environment=environment)
    route = evaluate_distance_route(graph, profiles, edge_ids, seed_edge_id=edge_ids[0])

    # --- per-edge table ------------------------------------------------------
    edge_rows: list[dict[str, object]] = []
    offset = 0.0
    for position, (edge_id, profile) in enumerate(zip(edge_ids, chain), start=1):
        edge = graph.edges[edge_id]
        tags = dict(edge.tags)
        length = math.fsum(profile.segment_travelled_m)
        reached = run.distance_m[-1] >= offset + 1e-6
        edge_rows.append(
            {
                "position": position,
                "edge_id": edge_id,
                "osm_way_id": edge.osm_way_id,
                "osm_url": f"https://www.openstreetmap.org/way/{edge.osm_way_id}",
                "piece_index": edge.piece_index,
                "direction": edge.direction,
                "from_node": edge.from_node,
                "to_node": edge.to_node,
                "name": edge.name,
                "highway": tags.get("highway", ""),
                "travelled_m": round(length, 2),
                "route_start_m": round(offset, 2),
                "route_end_m": round(offset + length, 2),
                "entered": reached,
                "start_elevation_m": round(profile.start_elevation_m, 2),
                "end_elevation_m": round(profile.end_elevation_m, 2),
                "net_dz_m": round(profile.net_dz_m, 2),
                "descent_m": round(profile.descent_m, 2),
                "ascent_m": round(profile.ascent_m, 2),
                "mean_grade_ratio": round(
                    profile.net_dz_m / profile.horizontal_length_m
                    if profile.horizontal_length_m
                    else 0.0,
                    5,
                ),
                "surface_class": edge.surface_class.value,
                "surface_is_assumed": edge.surface_is_assumed,
                "usability": edge.usability.value,
                "usability_reason": edge.usability_reason,
                "structure_status": edge.structure_status.value,
                "start_lat": round(edge.samples[0].latitude, 6),
                "start_lon": round(edge.samples[0].longitude, 6),
                "end_lat": round(edge.samples[-1].latitude, 6),
                "end_lon": round(edge.samples[-1].longitude, 6),
                **{f"tag_{name}": tags.get(name, "") for name in STRUCTURE_TAGS},
            }
        )
        offset += length

    with (output / f"{arguments.scenario}_rank{arguments.rank}_edges.csv").open(
        "w", encoding="utf-8", newline="\n"
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(edge_rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(edge_rows)

    # --- binding bends, located on the ground --------------------------------
    lengths: list[float] = []
    for item in chain:
        lengths.extend(item.segment_travelled_m)
    cumulative: list[float] = []
    running = 0.0
    for length in lengths:
        running += length
        cumulative.append(running)

    def locate(distance: float) -> tuple[str, float, float]:
        travelled = 0.0
        for edge_id, profile in zip(edge_ids, chain):
            span = math.fsum(profile.segment_travelled_m)
            if distance <= travelled + span + 1e-9:
                edge = graph.edges[edge_id]
                fraction = (distance - travelled) / span if span else 0.0
                sample = edge.samples[
                    min(len(edge.samples) - 1, int(fraction * (len(edge.samples) - 1)))
                ]
                return edge_id, sample.latitude, sample.longitude
            travelled += span
        edge = graph.edges[edge_ids[-1]]
        return edge_ids[-1], edge.samples[-1].latitude, edge.samples[-1].longitude

    limits = dict(route_bend_limits(graph, edge_ids, chain, DEFAULT_LATERAL_SCENARIO))
    bend_rows = []
    for segment in sorted(run.binding_segments):
        start = cumulative[segment - 1] if segment else 0.0
        end = cumulative[segment]
        middle = 0.5 * (start + end)
        edge_id, latitude, longitude = locate(middle)
        nearest = min(limits, key=lambda position: abs(position - middle)) if limits else None
        bend_rows.append(
            {
                "profile_segment": segment,
                "route_distance_m": round(middle, 1),
                "edge_id": edge_id,
                "osm_way_id": graph.edges[edge_id].osm_way_id,
                "name": graph.edges[edge_id].name,
                "lat": round(latitude, 6),
                "lon": round(longitude, 6),
                "nearest_limit_km_h": round(limits[nearest] * 3.6, 1)
                if nearest is not None
                else "",
                "nearest_limit_offset_m": round(abs(nearest - middle), 1)
                if nearest is not None
                else "",
            }
        )
    with (output / f"{arguments.scenario}_rank{arguments.rank}_bends.csv").open(
        "w", encoding="utf-8", newline="\n"
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(bend_rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(bend_rows)

    # --- energy --------------------------------------------------------------
    budget = energy_budget(chain, run, bicycle, environment)

    # --- profiles ------------------------------------------------------------
    elevation_xs: list[float] = [0.0]
    elevation_ys: list[float] = [chain[0].start_elevation_m]
    travelled = 0.0
    elevation = chain[0].start_elevation_m
    for item in chain:
        for length, grade in zip(item.segment_travelled_m, item.segment_grade_ratio):
            travelled += length
            elevation += length * math.sin(math.atan(grade))
            elevation_xs.append(travelled)
            elevation_ys.append(elevation)
    stem = f"{arguments.scenario}_rank{arguments.rank}"
    svg_polyline(
        output / f"{stem}_elevation.svg",
        elevation_xs,
        elevation_ys,
        f"{stem} — elevation",
        "distance (m)",
        "elevation (m)",
    )
    svg_polyline(
        output / f"{stem}_speed.svg",
        list(run.distance_m),
        [value * 3.6 for value in run.speed_m_s],
        f"{stem} — speed",
        "distance (m)",
        "speed (km/h)",
    )
    kinetic = [
        0.5 * bicycle.effective_inertial_mass_kg * value**2 / 1000.0 for value in run.speed_m_s
    ]
    svg_polyline(
        output / f"{stem}_kinetic_energy.svg",
        list(run.distance_m),
        kinetic,
        f"{stem} — kinetic energy",
        "distance (m)",
        "kinetic energy (kJ)",
    )

    # --- surface and structure mix ------------------------------------------
    surface_metres: dict[str, float] = {}
    assumed_metres = 0.0
    structures: dict[str, float] = {}
    tagged_asphalt = 0.0
    for row, profile in zip(edge_rows, chain):
        metres = math.fsum(profile.segment_travelled_m)
        surface_metres[row["surface_class"]] = (
            surface_metres.get(row["surface_class"], 0.0) + metres
        )
        if row["surface_is_assumed"]:
            assumed_metres += metres
        elif str(row["tag_surface"]).startswith("asphalt") or row["tag_surface"] == "paved":
            tagged_asphalt += metres
        structures[row["structure_status"]] = structures.get(row["structure_status"], 0.0) + metres
    total = math.fsum(math.fsum(item.segment_travelled_m) for item in chain)

    audit = {
        "scenario": arguments.scenario,
        "rank": arguments.rank,
        "edge_ids": edge_ids,
        "osm_way_ids": sorted({graph.edges[edge].osm_way_id for edge in edge_ids}),
        "distinct_ways": len({graph.edges[edge].osm_way_id for edge in edge_ids}),
        "edges_used": len(edge_ids),
        "geometry": {
            "start_lat": edge_rows[0]["start_lat"],
            "start_lon": edge_rows[0]["start_lon"],
            "end_lat": edge_rows[-1]["end_lat"],
            "end_lon": edge_rows[-1]["end_lon"],
            "start_elevation_m": round(route.start_elevation_m, 2),
            "end_elevation_m": round(route.end_elevation_m, 2),
            "net_dz_m": round(route.net_dz_m, 2),
            "descent_m": round(route.descent_m, 2),
            "ascent_m": round(route.ascent_m, 2),
        },
        "kinematics": {
            "distance_m": round(route.distance_m, 2),
            "elapsed_time_s": round(route.elapsed_time_s, 1),
            "moving_time_s": round(route.moving_time_s, 1),
            "mean_speed_km_h": round(route.mean_speed_m_s * 3.6, 2),
            "max_speed_km_h": round(route.max_speed_m_s * 3.6, 2),
            "max_free_speed_km_h": round(route.max_free_speed_m_s * 3.6, 2),
            "final_speed_km_h": round(run.speed_m_s[-1] * 3.6, 2),
            "min_speed_before_stop_km_h": round(route.minimum_speed_before_stop_m_s * 3.6, 2),
            "restart_count": route.restart_count,
        },
        "energy_j": {key: round(value, 1) for key, value in budget.items()},
        "bends": {
            "binding_segments": len(bend_rows),
            "braking_distance_m": round(route.braking_distance_m, 1),
            "braking_substeps": route.braking_substeps,
        },
        "termination": {
            "stop_reason": run.stop_reason,
            "search_termination": route.termination,
            "energy_limited": run.stop_reason == "definitive_stop",
            "reading": (
                "the bicycle ran out of energy where the road still continued"
                if run.stop_reason == "definitive_stop"
                else "the admitted graph ran out while the bicycle was still moving; "
                "the distance is a lower bound on this corridor, not a measurement of where "
                "the bicycle stops"
            ),
        },
        "surface": {
            "metres_by_class": {key: round(value, 1) for key, value in surface_metres.items()},
            "share_by_class": {
                key: round(value / total, 4) for key, value in surface_metres.items()
            },
            "inferred_share": round(assumed_metres / total, 4),
            "explicitly_tagged_asphalt_share": round(tagged_asphalt / total, 4),
        },
        "structures": {
            "metres_by_status": {key: round(value, 1) for key, value in structures.items()},
            "bridges": [row["edge_id"] for row in edge_rows if row["tag_bridge"]],
            "tunnels": [row["edge_id"] for row in edge_rows if row["tag_tunnel"]],
            "covered": [row["edge_id"] for row in edge_rows if row["tag_covered"]],
            "non_zero_layer": [
                row["edge_id"] for row in edge_rows if row["tag_layer"] not in ("", "0")
            ],
            "tracks": [row["edge_id"] for row in edge_rows if row["highway"] == "track"],
            "unpaved": [
                row["edge_id"]
                for row in edge_rows
                if row["surface_class"] not in ("asphalt_good", "asphalt_degraded")
            ],
        },
    }
    write_text_lf(output / f"{stem}_audit.json", json.dumps(audit, indent=2, sort_keys=True) + "\n")

    print(f"{stem}: {audit['kinematics']['distance_m']} m over {len(edge_ids)} edges")
    print(f"  stop: {run.stop_reason} ({audit['termination']['reading']})")
    print(
        f"  energy: supplied {budget['total_supplied_j'] / 1000:.1f} kJ = "
        f"roll {budget['rolling_dissipated_j'] / 1000:.1f} + "
        f"drag {budget['drag_dissipated_j'] / 1000:.1f} + "
        f"brake {budget['braking_dissipated_j'] / 1000:.1f} + "
        f"final KE {budget['final_kinetic_j'] / 1000:.1f}, "
        f"residual {budget['residual_relative']:+.3%}"
    )
    print(
        f"  surface: inferred {audit['surface']['inferred_share']:.1%}, "
        f"tagged asphalt {audit['surface']['explicitly_tagged_asphalt_share']:.1%}"
    )
    print(f"  binding bends: {len(bend_rows)}")


if __name__ == "__main__":
    main()
