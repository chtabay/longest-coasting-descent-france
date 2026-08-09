"""One synthesis file for the four regional variants, and the site data built from it.

Four questions are being answered at once — paved or hybrid, trip rule kept or
lifted — and they have different answers. Presenting them from four separate
CSVs invites the reader to compare numbers that were produced under different
definitions, so they are collected here once, with the definition attached to
each.

Every figure is recomputed from the route's edge ids by the same evaluation the
search publishes. Nothing is copied from a rendered table, and nothing in the
generated page is written by hand: the page is a consumer of this file, so there
is exactly one place where a number can be wrong.

The termination status travels with every distance. A route that ended because
the model ran out of road is a lower bound and is written ``>= x m``; only a
definitive physical stop is written plainly.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import subprocess
import sys
from pathlib import Path

from coastdown.distance_search import evaluate_distance_route, simulate_path
from coastdown.elevation_profile import build_profile
from coastdown.elevation_store import elevations_for, load_store
from coastdown.graph import RoutableGraph, build_graph
from coastdown.models import BicycleSystem, Environment
from coastdown.search import EdgeProfile, build_edge_profile
from coastdown.termination import classify, node_way_index
from coastdown.textio import write_text_lf

PRODUCTION_METHOD = "raw_25m"

VARIANTS = (
    ("paved_reference", False, "outputs/phase3/candidate_routes.csv"),
    ("paved_reference", True, "outputs/phase3/cycle_rule_comparison_paved_reference.csv"),
    ("reference_vtc", False, "outputs/phase3/candidate_routes.csv"),
    ("reference_vtc", True, "outputs/phase3/cycle_rule_comparison_reference_vtc.csv"),
)


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


def read_ranking(path: Path, scenario: str, allow_cycles: bool) -> list[list[str]]:
    """Ordered edge-id lists for one variant, straight from the run that made it."""
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if "scenario" in (rows[0] if rows else {}):
        rows = [row for row in rows if row["scenario"] == scenario]
    if "trip_definition" in (rows[0] if rows else {}):
        wanted = "cycles_allowed" if allow_cycles else "once_per_way_piece"
        rows = [row for row in rows if row["trip_definition"] == wanted]
    rows.sort(key=lambda row: int(row["rank"]))
    return [row["edge_ids"].split(";") for row in rows]


def describe(
    graph: RoutableGraph,
    profiles: dict[str, EdgeProfile],
    edge_ids: list[str],
    node_ways,
) -> dict[str, object]:
    """Everything a reader needs about one route, recomputed from its edges."""
    route = evaluate_distance_route(graph, profiles, edge_ids, seed_edge_id=edge_ids[0])
    _, run = simulate_path(
        graph, profiles, edge_ids, bicycle=BicycleSystem(), environment=Environment()
    )
    status = classify(
        graph,
        edge_ids,
        run.stop_reason,
        node_ways=node_ways,
        search_termination=route.termination,
    )
    surface = dict(route.surface_metres)
    total = sum(surface.values()) or 1.0
    first = graph.edges[edge_ids[0]]
    last = graph.edges[edge_ids[-1]]
    counts: dict[str, int] = {}
    for edge_id in edge_ids:
        counts[edge_id] = counts.get(edge_id, 0) + 1
    names: list[str] = []
    for edge_id in edge_ids:
        name = graph.edges[edge_id].name
        if name and (not names or names[-1] != name):
            names.append(name)
    return {
        "distance_m": round(route.distance_m, 1),
        "termination_status": status.status,
        "termination_detail": status.detail,
        "is_complete": status.is_complete,
        "distance_label": status.format_distance(route.distance_m),
        "elapsed_time_s": round(route.elapsed_time_s, 1),
        "mean_speed_km_h": round(route.mean_speed_m_s * 3.6, 1),
        "max_speed_km_h": round(route.max_speed_m_s * 3.6, 1),
        "final_speed_km_h": round(run.speed_m_s[-1] * 3.6, 1),
        "start_elevation_m": round(route.start_elevation_m, 1),
        "end_elevation_m": round(route.end_elevation_m, 1),
        "net_dz_m": round(route.net_dz_m, 1),
        "descent_m": round(route.descent_m, 1),
        "ascent_m": round(route.ascent_m, 1),
        "braking_energy_kj": round(route.braking_energy_j / 1000.0, 1),
        "binding_bends": route.active_constraints,
        "edges_used": len(edge_ids),
        "distinct_edges": len(set(edge_ids)),
        "repeated_traversals": len(edge_ids) - len(set(edge_ids)),
        "distinct_osm_ways": len({graph.edges[edge_id].osm_way_id for edge_id in edge_ids}),
        "surface_tagged_share": round(1.0 - route.surface_is_assumed_m / total, 3),
        "surface_inferred_share": round(route.surface_is_assumed_m / total, 3),
        "surface_metres_by_class": {key: round(value, 1) for key, value in surface.items()},
        "restart_count": route.restart_count,
        "start_lat": round(first.samples[0].latitude, 6),
        "start_lon": round(first.samples[0].longitude, 6),
        "end_lat": round(last.samples[-1].latitude, 6),
        "end_lon": round(last.samples[-1].longitude, 6),
        "roads": names[:12],
        "repeated_edges": [
            {
                "edge_id": edge_id,
                "osm_way_id": graph.edges[edge_id].osm_way_id,
                "name": graph.edges[edge_id].name,
                "traversals": count,
            }
            for edge_id, count in counts.items()
            if count > 1
        ],
        "edge_ids": edge_ids,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--overpass-cache", default=".cache/phase1b-live/oisans-overpass.json")
    parser.add_argument("--elevations", default=".cache/phase2/elevations.json")
    parser.add_argument("--output", default="outputs/phase3")
    parser.add_argument("--site", default="site/data")
    parser.add_argument("--audit", action="store_true", help="also render leader profiles")
    arguments = parser.parse_args()

    output = Path(arguments.output)
    output.mkdir(parents=True, exist_ok=True)
    osm = json.loads(Path(arguments.overpass_cache).read_bytes())
    store = load_store(arguments.elevations)
    node_ways = node_way_index(osm)

    graphs: dict[str, RoutableGraph] = {}
    profile_sets: dict[str, dict[str, EdgeProfile]] = {}
    for scenario in ("paved_reference", "reference_vtc"):
        graphs[scenario] = build_graph(osm, scenario)
        profile_sets[scenario] = build_profiles(graphs[scenario], store)

    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=False
    ).stdout.strip()

    variants: list[dict[str, object]] = []
    for scenario, allow_cycles, source in VARIANTS:
        ranking = read_ranking(Path(source), scenario, allow_cycles)
        if not ranking:
            print(f"skipping {scenario} cycles={allow_cycles}: {source} has no rows", flush=True)
            continue
        graph = graphs[scenario]
        profiles = profile_sets[scenario]
        described = [describe(graph, profiles, edge_ids, node_ways) for edge_ids in ranking]
        key = f"{scenario}__{'cycles' if allow_cycles else 'no_cycles'}"
        # Asset paths are generated too: the page must not know how `outputs/`
        # is laid out, or that layout becomes a second source of truth.
        #
        # The files are copied into the site rather than linked with `../`,
        # which matters for deployment and not for tidiness. GitHub Pages
        # publishes one subtree — the repo root, `docs/`, or whatever an action
        # uploads — and a `../outputs/...` reference resolves outside any subtree
        # that does not contain both. Copying keeps the page correct under every
        # publish root. `outputs/` stays the source; the copy is generated.
        wanted = {
            "elevation_svg": output / "audit" / f"{key}_elevation.svg",
            "speed_svg": output / "audit" / f"{key}_speed.svg",
            "kinetic_energy_svg": output / "audit" / f"{key}_kinetic_energy.svg",
        }
        if not allow_cycles:
            wanted["map_svg"] = output / "maps" / f"top_routes_{scenario}.svg"
        assets = {}
        for name, source_path in wanted.items():
            if not source_path.exists():
                continue
            destination = Path(arguments.site).parent / "assets" / source_path.name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(source_path.read_bytes())
            assets[name] = f"assets/{source_path.name}"
        variants.append(
            {
                "key": key,
                "assets": assets,
                "scenario": scenario,
                "allow_cycles": allow_cycles,
                "trip_rule": (
                    "repetition allowed"
                    if allow_cycles
                    else "each way piece at most once, whichever direction"
                ),
                "source": source,
                "ranking_depth": len(described),
                "leader": described[0],
                "ranking": described,
                "termination_counts": {
                    status: sum(1 for item in described if item["termination_status"] == status)
                    for status in sorted({str(item["termination_status"]) for item in described})
                },
            }
        )
        leader = described[0]
        print(
            f"{key}: {leader['distance_label']} - {str(leader['termination_status']).upper()}, "
            f"{leader['edges_used']} edges, top {len(described)}",
            flush=True,
        )
        if arguments.audit:
            subprocess.run(
                [
                    sys.executable,
                    "scripts/phase3_audit_leader.py",
                    "--scenario",
                    scenario,
                    "--edge-ids",
                    ";".join(leader["edge_ids"]),  # type: ignore[arg-type]
                    "--label",
                    key,
                ],
                check=True,
            )

    payload = {
        "question": (
            "Quel est, en France, le trajet de plus grande distance qu'un cycliste de 75 kg "
            "sur un VTC standard peut parcourir en partant a 15 km/h, sans jamais pedaler, "
            "jusqu'a son arret physique definitif ?"
        ),
        "phase": "Phase A - validation regionale Oisans",
        "scope": "Oisans extract only. No national claim; the national search has not started.",
        "commit": commit,
        "initial_speed_km_h": 15.0,
        "elevation_method": PRODUCTION_METHOD,
        "termination_statuses": {
            "physical_stop": "speed reached zero and nothing could restart the bicycle; "
            "the distance is the coasting distance",
            "model_gap": "the road continues and the model does not follow it; "
            "the distance is a lower bound",
            "network_boundary": "nothing in the extract continues past that point; "
            "the distance is a lower bound",
            "budget_limit": "the search ran out of allowance, not of graph; "
            "the distance is a lower bound",
        },
        "variants": variants,
    }
    write_text_lf(output / "variants.json", json.dumps(payload, indent=2, sort_keys=True) + "\n")

    site = Path(arguments.site)
    site.mkdir(parents=True, exist_ok=True)
    serialised = json.dumps(payload, indent=2, sort_keys=True)
    write_text_lf(site / "phase3.json", serialised + "\n")
    # A page opened straight from disk cannot fetch() a sibling JSON file, so the
    # same object is also emitted as a script. Both come from one dict: there is
    # no second place for a number to drift.
    write_text_lf(
        site / "phase3.js",
        "// Generated by scripts/phase3_variants.py. Do not edit.\n"
        f"window.PHASE3 = {serialised};\n",
    )
    print(f"wrote {output / 'variants.json'} and {site / 'phase3.js'}", flush=True)
    if not math.isclose(len(variants), len(VARIANTS)):
        print(
            f"WARNING: {len(VARIANTS) - len(variants)} variant(s) missing; "
            "the page will show only what exists",
            flush=True,
        )


if __name__ == "__main__":
    main()
