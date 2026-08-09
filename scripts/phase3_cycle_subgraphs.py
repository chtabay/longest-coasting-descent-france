"""What repeating a way is worth on real Oisans road, seed by seed.

Two questions, kept separate because they have different answers.

*Does allowing repetition change the distance at all?* Measured by running the
same seed twice, identical in every respect but the trip rule.

*Can the engine still be trusted once it does?* Measured against
``exhaustive_routes`` with repetition allowed, wherever the subgraph is small
enough for an unpruned enumeration to finish. Agreement there is the only thing
that makes the larger, unverifiable runs worth reading.

The combinatorial cost is the third output and not an afterthought. Lifting the
rule removes the only bound on path length that does not depend on physics, so
the walk's state count is what decides whether a regional run with repetition is
a computation or a fantasy. Seeds whose budget runs out are reported as such:
their distances are lower bounds, never answers.
"""

from __future__ import annotations

import argparse
import csv
import json
import time
from collections import Counter
from pathlib import Path

from coastdown.distance_search import (
    DistanceBudget,
    DistanceRoute,
    exhaustive_routes,
    search_distance_from_edge,
)
from coastdown.elevation_profile import build_profile
from coastdown.elevation_store import elevations_for, load_store
from coastdown.graph import RoutableGraph, build_graph
from coastdown.search import EdgeProfile, build_edge_profile
from coastdown.textio import write_text_lf

PRODUCTION_METHOD = "raw_25m"
ORACLE_PATH_CAP = 20_000


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


def repetition(route: DistanceRoute) -> tuple[int, int]:
    """Repeated traversals, and the most times any one edge is used."""
    counts = Counter(route.edge_ids)
    return len(route.edge_ids) - len(counts), counts.most_common(1)[0][1]


def compare_seed(
    graph: RoutableGraph,
    profiles: dict[str, EdgeProfile],
    seed: str,
    budget: int,
    *,
    check_oracle: bool,
) -> dict[str, object]:
    strict, strict_budget = search_distance_from_edge(
        graph, profiles, seed, budget=DistanceBudget(max_expansions=budget), keep_best=1
    )
    started = time.perf_counter()
    free, free_budget = search_distance_from_edge(
        graph,
        profiles,
        seed,
        budget=DistanceBudget(max_expansions=budget),
        keep_best=1,
        allow_cycles=True,
    )
    elapsed = time.perf_counter() - started
    if not strict or not free:
        return {}
    repeats, most_used = repetition(free[0])
    row: dict[str, object] = {
        "seed_edge_id": seed,
        "osm_way_id": graph.edges[seed].osm_way_id,
        "name": graph.edges[seed].name,
        "strict_distance_m": round(strict[0].distance_m, 2),
        "strict_expansions": strict_budget.expansions,
        "strict_exhausted": strict_budget.exhausted,
        "cycles_distance_m": round(free[0].distance_m, 2),
        "cycles_expansions": free_budget.expansions,
        "cycles_exhausted": free_budget.exhausted,
        "cycles_runtime_s": round(elapsed, 2),
        "gain_m": round(free[0].distance_m - strict[0].distance_m, 2),
        "relative_gain": round(free[0].distance_m / max(strict[0].distance_m, 1e-9) - 1.0, 4),
        "repeated_traversals": repeats,
        "max_traversals_of_one_edge": most_used,
        "identical_path": strict[0].edge_ids == free[0].edge_ids,
        "expansion_blowup": round(free_budget.expansions / max(strict_budget.expansions, 1), 2),
        "oracle_checked": False,
        "oracle_agrees": "",
        "oracle_routes": "",
    }
    if check_oracle and not free_budget.exhausted:
        try:
            reference = exhaustive_routes(
                graph, profiles, seed, max_paths=ORACLE_PATH_CAP, allow_cycles=True
            )
        except RuntimeError:
            return row
        if reference:
            best = max(reference, key=lambda item: item.distance_m)
            row["oracle_checked"] = True
            row["oracle_routes"] = len(reference)
            row["oracle_agrees"] = (
                abs(best.distance_m - free[0].distance_m) < 1e-9
                and best.edge_ids == free[0].edge_ids
            )
    return row


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", default="paved_reference")
    parser.add_argument("--budget", type=int, default=200_000)
    parser.add_argument("--stride", type=int, default=97)
    parser.add_argument("--overpass-cache", default=".cache/phase1b-live/oisans-overpass.json")
    parser.add_argument("--elevations", default=".cache/phase2/elevations.json")
    parser.add_argument("--candidates", default="outputs/phase3/candidate_routes.csv")
    parser.add_argument("--output", default="outputs/phase3")
    arguments = parser.parse_args()

    output = Path(arguments.output)
    output.mkdir(parents=True, exist_ok=True)
    osm = json.loads(Path(arguments.overpass_cache).read_bytes())
    store = load_store(arguments.elevations)
    graph = build_graph(osm, arguments.scenario)
    profiles = build_profiles(graph, store)
    simulable = sorted(edge_id for edge_id, item in profiles.items() if item.simulable)

    with Path(arguments.candidates).open(encoding="utf-8") as handle:
        candidates = [
            row for row in csv.DictReader(handle) if row["scenario"] == arguments.scenario
        ]
    corridor = list(dict.fromkeys(row["edge_ids"].split(";")[0] for row in candidates[:10]))
    sample = [seed for seed in simulable[:: arguments.stride] if seed not in corridor]

    rows: list[dict[str, object]] = []
    started = time.monotonic()
    for label, seeds in (("corridor", corridor), ("sample", sample)):
        print(f"--- {label}: {len(seeds)} seeds ---", flush=True)
        for seed in seeds:
            row = compare_seed(
                graph, profiles, seed, arguments.budget, check_oracle=(label == "sample")
            )
            if not row:
                continue
            row["group"] = label
            rows.append(row)
            limited_note = " BUDGET-LIMITED" if row["cycles_exhausted"] else ""
            oracle_note = f", oracle agrees={row['oracle_agrees']}" if row["oracle_checked"] else ""
            print(
                f"  {seed}: {row['strict_distance_m']} -> {row['cycles_distance_m']} m "
                f"({row['relative_gain']:+.2%}), repeats {row['repeated_traversals']}, "
                f"expansions x{row['expansion_blowup']}{limited_note}{oracle_note}",
                flush=True,
            )

    name = f"cycle_subgraphs_{arguments.scenario}"
    with (output / f"{name}.csv").open("w", encoding="utf-8", newline="\n") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    gains = [row for row in rows if row["gain_m"] > 1e-6]
    limited = [row for row in rows if row["cycles_exhausted"]]
    checked = [row for row in rows if row["oracle_checked"]]
    summary = {
        "scenario": arguments.scenario,
        "max_expansions_per_seed": arguments.budget,
        "seeds_compared": len(rows),
        "seeds_where_repetition_helps": len(gains),
        "largest_absolute_gain_m": max((row["gain_m"] for row in rows), default=0.0),
        "largest_relative_gain": max((row["relative_gain"] for row in rows), default=0.0),
        "max_traversals_of_one_edge": max(
            (row["max_traversals_of_one_edge"] for row in rows), default=0
        ),
        "seeds_budget_limited_with_cycles": len(limited),
        "seeds_budget_limited_without_cycles": sum(1 for row in rows if row["strict_exhausted"]),
        "median_expansion_blowup": sorted(row["expansion_blowup"] for row in rows)[len(rows) // 2]
        if rows
        else 0.0,
        "max_expansion_blowup": max((row["expansion_blowup"] for row in rows), default=0.0),
        "oracle_checked_seeds": len(checked),
        "oracle_disagreements": sum(1 for row in checked if row["oracle_agrees"] is not True),
        "runtime_s": round(time.monotonic() - started, 1),
        "caveat": (
            "a seed whose budget was exhausted yields a lower bound on its own answer with "
            "repetition allowed; gains measured on such seeds are lower bounds too"
        ),
    }
    write_text_lf(output / f"{name}.json", json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(json.dumps(summary, indent=2, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
