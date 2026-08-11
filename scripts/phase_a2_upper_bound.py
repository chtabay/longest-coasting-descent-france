"""How much distance the remaining 8.7 km of structure could still be hiding.

Case 1 reconstructs only structures shorter than one production profile segment.
Everything longer waits on case 2 — a source describing the deck — which is real
work with a real acquisition and verification cost. Before paying it, it is worth
knowing what it could buy.

This run answers that with a bound rather than a result. Every structure whose
two ends are known is given a **straight** deck, however long it is, and the
region is ranked again.

Why that is an upper bound and not a guess
-------------------------------------------

Between two fixed endpoints every possible deck has the same net elevation
change, so gravity gives the bicycle exactly the same energy whichever shape the
real deck has. What differs is what the shape *costs*: any departure from a
straight line adds a rise and a matching fall, which lengthens the path travelled
and charges rolling resistance and drag over the extra distance, and a rise can
stop the bicycle outright. A straight deck is therefore the cheapest deck a
structure can have, and no real one can do better.

**Nothing here is a result and none of it may be published as one.** The output
is the ceiling on what case 2 could deliver. If the ceiling is close to what the
study already reports, case 2 is not worth acquiring a source for; if it is far
above, it is the next thing to do.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from coastdown.distance_search import DistanceBudget, global_longest
from coastdown.elevation_store import load_store
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
MAX_EXPANSIONS = 50_000
#: Large enough that no structure in any French extract is excluded by length.
NO_LENGTH_LIMIT_M = 1e9


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--overpass-cache", default=".cache/phase1b-live/oisans-overpass.json")
    parser.add_argument("--elevations", default=".cache/phase2/elevations.json")
    parser.add_argument("--scenario", default="", help="one scenario, or all if empty")
    parser.add_argument("--output", default="outputs/phase_a2")
    parser.add_argument("--workers", type=int, default=8)
    arguments = parser.parse_args()

    output = Path(arguments.output)
    output.mkdir(parents=True, exist_ok=True)
    osm = json.loads(Path(arguments.overpass_cache).read_bytes())
    store = load_store(arguments.elevations)
    node_ways = node_way_index(osm)

    report: dict[str, object] = {
        "what_this_is": (
            "an upper bound on what case 2 could deliver, not a result; every structure "
            "with two known ends is given a straight deck, which is the cheapest deck any "
            "structure can have, so no real deck can beat these figures"
        ),
        "publishable_as_a_record": False,
        "max_expansions_per_seed": MAX_EXPANSIONS,
        "scenarios": {},
    }

    for scenario in [arguments.scenario] if arguments.scenario else SCENARIOS:
        started = time.monotonic()
        graph, profiles, assessments, reconstructed = build_with_reconstructed_structures(
            osm, scenario, store, method=PRODUCTION_METHOD, max_span_m=NO_LENGTH_LIMIT_M
        )
        seeds = [edge_id for edge_id, item in profiles.items() if item.simulable]
        exhausted: list[str] = []

        def account(seed: str, budget: DistanceBudget, sink: list[str] = exhausted) -> None:
            if budget.exhausted:
                sink.append(seed)

        routes = global_longest(
            graph,
            profiles,
            seeds,
            TOP_N,
            budget_factory=lambda: DistanceBudget(max_expansions=MAX_EXPANSIONS),
            on_seed=account,
            workers=arguments.workers,
        )
        statuses: dict[str, int] = {}
        for route in routes:
            status = classify(
                graph,
                route.edge_ids,
                route.stop_reason,
                node_ways=node_ways,
                search_termination=route.termination,
            )
            statuses[status.status] = statuses.get(status.status, 0) + 1
        leader = routes[0]
        report["scenarios"][scenario] = {  # type: ignore[index]
            "structures": summarise(assessments),
            "decked_ways": sum(
                1 for item in assessments if item.case is StructureCase.SHORT_INTERPOLATED
            ),
            "reconstructed_edges": len(reconstructed),
            "graph_edges": len(graph.edges),
            "seeds": len(seeds),
            "seeds_with_exhausted_budget": len(exhausted),
            "ceiling_distance_m": round(leader.distance_m, 1),
            "leader_edges": leader.edges_used,
            "leader_net_dz_m": round(leader.net_dz_m, 1),
            "termination_counts": statuses,
            "runtime_s": round(time.monotonic() - started, 1),
        }
        print(
            f"[{scenario}] ceiling {leader.distance_m:.1f} m over {leader.edges_used} edges, "
            f"{len(seeds)} seeds, {len(exhausted)} budget-limited, {statuses}",
            flush=True,
        )

        # Written after every scenario rather than at the end: this run takes
        # hours and a crash in the second scenario must not discard the first.
        target = output / "case2_upper_bound.json"
        merged = json.loads(target.read_text(encoding="utf-8")) if target.exists() else {}
        merged.update({key: value for key, value in report.items() if key != "scenarios"})
        merged.setdefault("scenarios", {}).update(report["scenarios"])
        write_text_lf(target, json.dumps(merged, indent=2, sort_keys=True) + "\n")

    print(f"\nwrote {output / 'case2_upper_bound.json'} — a ceiling, not a record", flush=True)


if __name__ == "__main__":
    main()
