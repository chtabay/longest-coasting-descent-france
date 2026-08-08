"""Close the regional baseline: find every seed whose budget bound, then finish it.

A seed that exhausts its expansion budget has not been answered. Its reported
distance is a lower bound on its own optimum, because the walk stopped choosing
branches rather than running out of them. A baseline containing such a seed is
not exhaustive, and calling it one would be false.

This does not re-run the region. It walks every seed once at the production
budget purely to find the incomplete ones, then re-runs only those, raising the
budget until the walk ends because it ran out of graph rather than out of
allowance. A seed that stays unfinished at the highest budget tried is reported
as unfinished, with its expansion count, never truncated silently.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from coastdown.distance_search import (
    DistanceBudget,
    evaluate_distance_route,
    finished_paths,
)
from coastdown.elevation_profile import build_profile
from coastdown.elevation_store import elevations_for, load_store
from coastdown.graph import RoutableGraph, build_graph
from coastdown.search import EdgeProfile, build_edge_profile
from coastdown.textio import write_text_lf

PRODUCTION_METHOD = "raw_25m"
PRODUCTION_BUDGET = 5_000
# Escalation rather than one huge budget: the point is to learn how much each
# seed actually needs, which a single generous cap would hide.
ESCALATION = (50_000, 500_000, 5_000_000, 50_000_000)


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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", default="reference_vtc")
    parser.add_argument("--overpass-cache", default=".cache/phase1b-live/oisans-overpass.json")
    parser.add_argument("--elevations", default=".cache/phase2/elevations.json")
    parser.add_argument("--output", default="outputs/phase3")
    arguments = parser.parse_args()

    output = Path(arguments.output)
    output.mkdir(parents=True, exist_ok=True)
    osm = json.loads(Path(arguments.overpass_cache).read_bytes())
    store = load_store(arguments.elevations)
    graph = build_graph(osm, arguments.scenario)
    profiles = build_profiles(graph, store)
    seeds = sorted(edge_id for edge_id, item in profiles.items() if item.simulable)
    print(f"{arguments.scenario}: {len(seeds)} simulable seeds", flush=True)

    started = time.monotonic()
    limited: list[str] = []
    for index, seed in enumerate(seeds):
        _, budget = finished_paths(
            graph, profiles, seed, budget=DistanceBudget(max_expansions=PRODUCTION_BUDGET)
        )
        if budget.exhausted:
            limited.append(seed)
            print(f"  budget-limited: {seed}", flush=True)
        if index % 500 == 0:
            print(f"  {index}/{len(seeds)} scanned, {time.monotonic() - started:.0f}s", flush=True)
    print(
        f"{len(limited)} budget-limited seeds found in {time.monotonic() - started:.0f}s\n",
        flush=True,
    )

    records = []
    for seed in limited:
        record: dict[str, object] = {"seed_edge_id": seed, "attempts": [], "resolved": False}
        for allowance in ESCALATION:
            attempt_started = time.monotonic()
            finished, budget = finished_paths(
                graph, profiles, seed, budget=DistanceBudget(max_expansions=allowance)
            )
            elapsed = time.monotonic() - attempt_started
            best = finished[0] if finished else None
            attempt = {
                "max_expansions": allowance,
                "expansions": budget.expansions,
                "exhausted": budget.exhausted,
                "routes": len(finished),
                "best_distance_m": round(best[0], 3) if best else None,
                "runtime_s": round(elapsed, 1),
            }
            record["attempts"].append(attempt)
            print(
                f"  {seed} @ {allowance}: {budget.expansions} expansions, "
                f"exhausted={budget.exhausted}, best={attempt['best_distance_m']} m, "
                f"{elapsed:.0f}s",
                flush=True,
            )
            if not budget.exhausted:
                record["resolved"] = True
                record["expansions_needed"] = budget.expansions
                route = evaluate_distance_route(
                    graph,
                    profiles,
                    best[2],
                    seed_edge_id=seed,
                    termination=best[1],
                )
                record["best_distance_m"] = round(route.distance_m, 3)
                record["edges_used"] = route.edges_used
                record["stop_reason"] = route.stop_reason
                record["net_dz_m"] = round(route.net_dz_m, 1)
                record["edge_ids"] = list(route.edge_ids)
                break
        if not record["resolved"]:
            record["note"] = (
                "not closed at the highest budget tried; its distance is a lower bound "
                "on its own optimum and the baseline carries it as an open reserve"
            )
        records.append(record)

    payload = {
        "scenario": arguments.scenario,
        "production_budget": PRODUCTION_BUDGET,
        "escalation": list(ESCALATION),
        "seeds": len(seeds),
        "budget_limited_seeds": len(limited),
        "resolved": sum(1 for item in records if item["resolved"]),
        "records": records,
        "total_runtime_s": round(time.monotonic() - started, 1),
    }
    write_text_lf(
        output / f"budget_limited_{arguments.scenario}.json",
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
    )
    print(f"\nresolved {payload['resolved']}/{len(limited)}", flush=True)
    for item in records:
        if item["resolved"]:
            print(
                f"  {item['seed_edge_id']}: {item['best_distance_m']} m "
                f"({item['expansions_needed']} expansions)",
                flush=True,
            )


if __name__ == "__main__":
    main()
