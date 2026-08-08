"""What the once-per-way-piece rule is worth, on identical regional data.

The rule is a definition of what a trip is, not a physical claim:

    each physical way piece is traversed at most once, whichever direction.

Everything else here is held fixed -- same frozen Overpass extract, same
acquired RGE ALTI elevations, same ``raw_25m`` profile, same bends, same turn
restrictions, same physics, same engine. Only the definition changes. Any
difference in the answer is therefore attributable to the rule and to nothing
else, which is the only way to say what dropping it would cost.

Two things make the comparison delicate and are reported rather than hidden.

*The lapping search does not terminate cheaply.* Lifting the rule multiplies the
branching factor, so the per-seed budget binds where it never bound before. A
distance found under an exhausted budget is a lower bound on that seed's answer,
not the answer, and the count of such seeds is published beside the result.

*The invariant that makes lapping safe assumes no wind.* Over a closed cycle
gravity nets to zero while rolling resistance and drag only remove energy, so
repetition is self-limiting. Under an environment able to supply energy that
argument fails, and with it the guarantee that the lapping search stops at all.
This run uses the windless reference scenario.
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
from coastdown.textio import write_text_lf

PRODUCTION_METHOD = "raw_25m"
SCENARIO = "paved_reference"
TOP_N = 10
# Deliberately generous. The point of the run is to find out where the lapping
# search stops being answerable, so the cap must be high enough that hitting it
# is informative rather than an artefact of an arbitrarily small budget.
MAX_EXPANSIONS = 200_000


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


def rank(
    graph: RoutableGraph,
    profiles: dict[str, EdgeProfile],
    *,
    allow_cycles: bool,
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
        allow_cycles=allow_cycles,
    )
    return routes, {
        "allow_cycles": allow_cycles,
        "seeds": len(seeds),
        "expansions": expansions,
        "seeds_with_exhausted_budget": len(exhausted),
        "runtime_s": round(time.monotonic() - started, 1),
    }


def repetition(route: DistanceRoute) -> int:
    """How many more edge traversals than distinct edges the route uses."""
    return len(route.edge_ids) - len(set(route.edge_ids))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--overpass-cache", default=".cache/phase1b-live/oisans-overpass.json")
    parser.add_argument("--elevations", default=".cache/phase2/elevations.json")
    parser.add_argument("--output", default="outputs/phase3")
    arguments = parser.parse_args()

    output = Path(arguments.output)
    output.mkdir(parents=True, exist_ok=True)
    osm = json.loads(Path(arguments.overpass_cache).read_bytes())
    store = load_store(arguments.elevations)

    graph = build_graph(osm, SCENARIO)
    profiles = build_profiles(graph, store)

    rows: list[dict[str, object]] = []
    summaries: list[dict[str, object]] = []
    tops: dict[bool, list[DistanceRoute]] = {}
    for allow_cycles in (False, True):
        routes, stats = rank(graph, profiles, allow_cycles=allow_cycles)
        tops[allow_cycles] = routes
        summaries.append(stats)
        label = "cycles_allowed" if allow_cycles else "once_per_way_piece"
        print(
            f"[{label}] {stats['seeds']} seeds, {stats['expansions']} expansions, "
            f"{stats['seeds_with_exhausted_budget']} budget-limited, "
            f"best {routes[0].distance_m:.0f} m, {stats['runtime_s']}s"
        )
        for position, route in enumerate(routes, start=1):
            rows.append(
                {
                    "trip_definition": label,
                    "rank": position,
                    "distance_m": round(route.distance_m, 1),
                    "edges_used": route.edges_used,
                    "distinct_edges": len(set(route.edge_ids)),
                    "repeated_traversals": repetition(route),
                    "net_dz_m": round(route.net_dz_m, 1),
                    "elapsed_time_s": round(route.elapsed_time_s, 1),
                    "max_speed_km_h": round(route.max_speed_m_s * 3.6, 2),
                    "restart_count": route.restart_count,
                    "stop_reason": route.stop_reason,
                    "termination": route.termination,
                    "edge_ids": ";".join(route.edge_ids),
                }
            )

    with (output / "cycle_rule_comparison.csv").open("w", encoding="utf-8", newline="\n") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    strict, free = tops[False][0], tops[True][0]
    verdict = {
        "scenario": SCENARIO,
        "elevation_method": PRODUCTION_METHOD,
        "wind": "none (reference environment)",
        "max_expansions_per_seed": MAX_EXPANSIONS,
        "runs": summaries,
        "best_once_per_way_piece_m": round(strict.distance_m, 1),
        "best_cycles_allowed_m": round(free.distance_m, 1),
        "relative_change": round(free.distance_m / strict.distance_m - 1.0, 4),
        "best_cycles_allowed_repeats_an_edge": repetition(free) > 0,
        "same_route": strict.edge_ids == free.edge_ids,
        "caveat": (
            "a seed whose budget was exhausted yields a lower bound on its own answer, "
            "not its answer; the lapping run's figure is therefore a lower bound whenever "
            "seeds_with_exhausted_budget is non-zero"
        ),
    }
    write_text_lf(
        output / "cycle_rule_comparison.json", json.dumps(verdict, indent=2, sort_keys=True) + "\n"
    )
    print(
        f"\nonce per way piece: {strict.distance_m:.0f} m | "
        f"cycles allowed: {free.distance_m:.0f} m "
        f"({verdict['relative_change']:+.1%}), repeats an edge: "
        f"{verdict['best_cycles_allowed_repeats_an_edge']}"
    )


if __name__ == "__main__":
    main()
