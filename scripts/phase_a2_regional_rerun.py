"""Phase A2 deliverable 5: the regional ranking before and after structure continuity.

The same region, the same physics, the same engine, run twice. The only
difference is whether a short structure with two reliable approaches gets a
reconstructed roadway or gets deleted.

Publishing the pair rather than the improved figure alone is the point. A larger
number on its own would be indistinguishable from a looser model; side by side
with the termination status it shows what actually changed — routes moving from
``model_gap``, where the model ran out of road, to ``physical_stop``, where the
bicycle ran out of energy.

Nothing here relaxes the Phase 1B rule. No terrain sample is read on any
structure in either run; the "after" graph reconstructs a roadway from the
admitted road either side, and only where the structure is shorter than one
production profile segment.
"""

from __future__ import annotations

import argparse
import csv
import json
import time
from pathlib import Path

from coastdown.distance_search import DistanceBudget, DistanceRoute, global_longest
from coastdown.elevation_profile import build_profile
from coastdown.elevation_store import elevations_for, load_store
from coastdown.graph import RoutableGraph, build_graph
from coastdown.search import EdgeProfile, build_edge_profile
from coastdown.structures import (
    StructureCase,
    build_with_reconstructed_structures,
    summarise,
)
from coastdown.termination import classify, node_way_index
from coastdown.textio import write_text_lf

PRODUCTION_METHOD = "raw_25m"
SCENARIOS = ("paved_reference", "reference_vtc")
TOP_N = 20
# Generous: the reconstructed graph is better connected, so routes are longer
# and a cap tuned to the severed graph would bind here and be reported as a
# regression that is really an artefact of the budget.
MAX_EXPANSIONS = 50_000


def baseline_profiles(graph: RoutableGraph, store: dict[str, float]) -> dict[str, EdgeProfile]:
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


def rank(
    graph: RoutableGraph,
    profiles: dict[str, EdgeProfile],
    workers: int,
) -> tuple[list[DistanceRoute], dict[str, object]]:
    seeds = [edge_id for edge_id, item in profiles.items() if item.simulable]
    expansions = 0
    exhausted: list[str] = []

    def account(seed: str, budget: DistanceBudget) -> None:
        nonlocal expansions
        expansions += budget.expansions
        if budget.exhausted:
            exhausted.append(seed)

    started = time.monotonic()
    routes = global_longest(
        graph,
        profiles,
        seeds,
        TOP_N,
        budget_factory=lambda: DistanceBudget(max_expansions=MAX_EXPANSIONS),
        on_seed=account,
        workers=workers,
    )
    return routes, {
        "seeds": len(seeds),
        "simulable_edges": len(seeds),
        "graph_edges": len(graph.edges),
        "expansions": expansions,
        "seeds_with_exhausted_budget": len(exhausted),
        "runtime_s": round(time.monotonic() - started, 1),
    }


def describe(graph: RoutableGraph, route: DistanceRoute, node_ways) -> dict[str, object]:
    status = classify(
        graph,
        route.edge_ids,
        route.stop_reason,
        node_ways=node_ways,
        search_termination=route.termination,
    )
    return {
        "distance_m": round(route.distance_m, 1),
        "distance_label": status.format_distance(route.distance_m),
        "termination_status": status.status,
        "termination_detail": status.detail,
        "edges_used": route.edges_used,
        "net_dz_m": round(route.net_dz_m, 1),
        "elapsed_time_s": round(route.elapsed_time_s, 1),
        "max_speed_km_h": round(route.max_speed_m_s * 3.6, 1),
        "edge_ids": ";".join(route.edge_ids),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--overpass-cache", default=".cache/phase1b-live/oisans-overpass.json")
    parser.add_argument("--elevations", default=".cache/phase2/elevations.json")
    parser.add_argument("--output", default="outputs/phase_a2")
    parser.add_argument("--workers", type=int, default=8)
    arguments = parser.parse_args()

    output = Path(arguments.output)
    output.mkdir(parents=True, exist_ok=True)
    osm = json.loads(Path(arguments.overpass_cache).read_bytes())
    store = load_store(arguments.elevations)
    node_ways = node_way_index(osm)

    rows: list[dict[str, object]] = []
    report: dict[str, object] = {
        "phase": "A2 - structure continuity, case 1 only",
        "rule": (
            "no terrain sample is read on any structure in either run; the reconstructed "
            "run interpolates a roadway between two admitted edges, and only for structures "
            "shorter than one production profile segment"
        ),
        "max_expansions_per_seed": MAX_EXPANSIONS,
        "scenarios": {},
    }

    for scenario in SCENARIOS:
        before_graph = build_graph(osm, scenario)
        before_profiles = baseline_profiles(before_graph, store)
        before, before_stats = rank(before_graph, before_profiles, arguments.workers)
        print(
            f"[{scenario}] before: {before_stats['seeds']} seeds, "
            f"{before_stats['seeds_with_exhausted_budget']} budget-limited, "
            f"best {before[0].distance_m:.1f} m, {before_stats['runtime_s']}s",
            flush=True,
        )

        after_graph, after_profiles, assessments, reconstructed = (
            build_with_reconstructed_structures(osm, scenario, store, method=PRODUCTION_METHOD)
        )
        after, after_stats = rank(after_graph, after_profiles, arguments.workers)
        print(
            f"[{scenario}] after:  {after_stats['seeds']} seeds, "
            f"{after_stats['seeds_with_exhausted_budget']} budget-limited, "
            f"best {after[0].distance_m:.1f} m, {after_stats['runtime_s']}s",
            flush=True,
        )

        before_rows = [describe(before_graph, route, node_ways) for route in before]
        after_rows = [describe(after_graph, route, node_ways) for route in after]
        for position in range(max(len(before_rows), len(after_rows))):
            rows.append(
                {
                    "scenario": scenario,
                    "rank": position + 1,
                    **{
                        f"before_{key}": value
                        for key, value in (
                            before_rows[position] if position < len(before_rows) else {}
                        ).items()
                    },
                    **{
                        f"after_{key}": value
                        for key, value in (
                            after_rows[position] if position < len(after_rows) else {}
                        ).items()
                    },
                }
            )

        def statuses(items: list[dict[str, object]]) -> dict[str, int]:
            return {
                status: sum(1 for item in items if item["termination_status"] == status)
                for status in sorted({str(item["termination_status"]) for item in items})
            }

        report["scenarios"][scenario] = {  # type: ignore[index]
            "structures": summarise(assessments),
            "reconstructed_edges": len(reconstructed),
            "reconstructable_ways": sum(
                1 for item in assessments if item.case is StructureCase.SHORT_INTERPOLATED
            ),
            "before": {
                **before_stats,
                "leader": before_rows[0],
                "termination_counts": statuses(before_rows),
                "physical_stops": statuses(before_rows).get("physical_stop", 0),
            },
            "after": {
                **after_stats,
                "leader": after_rows[0],
                "termination_counts": statuses(after_rows),
                "physical_stops": statuses(after_rows).get("physical_stop", 0),
            },
            "leader_change_m": round(after[0].distance_m - before[0].distance_m, 1),
            "leader_relative_change": round(
                after[0].distance_m / max(before[0].distance_m, 1e-9) - 1.0, 4
            ),
            "leader_became_complete": (
                before_rows[0]["termination_status"] != "physical_stop"
                and after_rows[0]["termination_status"] == "physical_stop"
            ),
        }

    with (output / "regional_before_after.csv").open("w", encoding="utf-8", newline="\n") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    write_text_lf(
        output / "regional_before_after.json", json.dumps(report, indent=2, sort_keys=True) + "\n"
    )

    print()
    for scenario, entry in report["scenarios"].items():  # type: ignore[union-attr]
        before_leader = entry["before"]["leader"]
        after_leader = entry["after"]["leader"]
        print(
            f"{scenario}: {before_leader['distance_label']} "
            f"({before_leader['termination_status']}) -> "
            f"{after_leader['distance_label']} ({after_leader['termination_status']}), "
            f"{entry['leader_change_m']:+.1f} m; "
            f"physical stops in the top {TOP_N}: "
            f"{entry['before']['physical_stops']} -> {entry['after']['physical_stops']}"
        )


if __name__ == "__main__":
    main()
