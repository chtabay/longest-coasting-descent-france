"""Choose the production elevation-profile method by measurement.

Phase 1B showed that no spacing is safe by default: 2 m sampling of a 1 m terrain
model is dominated by quantisation noise, 5 m is still contaminated, and a mean
filter along chainage can steepen a hairpin instead of relaxing it.  This study
therefore builds five candidate methods from the same acquired samples and scores
them on what a coasting simulation actually needs.

Scoring criteria, none of which is "looks smooth":

* **elevation conservation** — net elevation change against the unfiltered
  measurement, and how much cumulative ascent the method invents;
* **plausible grades** — segments beyond 25 %, which on a mapped French mountain
  road is far more likely to be a terrain artefact than a gradient;
* **temporal stability** — the coasting time computed at two integrator steps;
  a method whose answer moves with the step is not measuring the terrain;
* **stop sensitivity** — whether the run ends in the same way at both steps;
* **hairpin behaviour** — the worst grade the method produces near a real bend.
"""

from __future__ import annotations

import argparse
import csv
import itertools
import json
import math
import statistics
from pathlib import Path

from coastdown.curvature import bend_radii
from coastdown.elevation_profile import METHOD_NAMES, build_profile, score_profile
from coastdown.elevation_store import elevations_for, load_store
from coastdown.graph import build_graph
from coastdown.models import BicycleSystem, Environment, RoadProfile
from coastdown.physics import simulate_profile
from coastdown.surfaces import coefficient
from coastdown.textio import write_text_lf

INITIAL_SPEED_M_S = 15.0 / 3.6
FINE_STEP_S = 0.01
COARSE_STEP_S = 0.10
NOMINAL_STEP_S = 0.05


def simulate(profile_samples, elevations, crr, time_step_s):
    lengths: list[float] = []
    grades: list[float] = []
    for (start, start_z), (end, end_z) in zip(
        zip(profile_samples, elevations), zip(profile_samples[1:], elevations[1:])
    ):
        dx = math.hypot(end.x_m - start.x_m, end.y_m - start.y_m)
        if dx <= 1e-9:
            continue
        dz = end_z - start_z
        grade = dz / dx
        if abs(grade) > 0.5:
            return None
        lengths.append(math.hypot(dx, dz))
        grades.append(grade)
    if not lengths:
        return None
    return simulate_profile(
        RoadProfile(lengths, grades, [crr] * len(lengths)),
        BicycleSystem(),
        Environment(),
        initial_speed_m_s=INITIAL_SPEED_M_S,
        time_step_s=time_step_s,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--overpass-cache", default=".cache/phase1b-live/oisans-overpass.json")
    parser.add_argument("--elevations", default=".cache/phase2/elevations.json")
    parser.add_argument("--output", default="outputs/phase2")
    parser.add_argument("--scenario", default="reference_vtc")
    parser.add_argument("--max-edges", type=int, default=400)
    arguments = parser.parse_args()

    output = Path(arguments.output)
    output.mkdir(parents=True, exist_ok=True)
    store = load_store(arguments.elevations)
    osm = json.loads(Path(arguments.overpass_cache).read_bytes())
    graph = build_graph(osm, arguments.scenario)

    # Longest edges first: a 40 m stub cannot discriminate between methods.
    candidates = sorted(
        (edge for edge in graph.edges.values() if edge.direction == "forward"),
        key=lambda edge: -edge.horizontal_length_m,
    )

    rows: list[dict[str, object]] = []
    studied = 0
    for edge in candidates:
        if studied >= arguments.max_edges:
            break
        base = elevations_for(store, edge.samples)
        if base is None or len(base) < 8:
            continue
        studied += 1
        crr = coefficient(edge.surface_class, "central")
        reference_net = base[-1] - base[0]
        reference_ascent = math.fsum(
            max(0.0, after - before) for before, after in itertools.pairwise(base)
        )
        bends = bend_radii(
            [sample.chainage_m for sample in edge.samples],
            [sample.x_m for sample in edge.samples],
            [sample.y_m for sample in edge.samples],
            [sample.longitude for sample in edge.samples],
            [sample.latitude for sample in edge.samples],
        )
        hairpins = tuple(bend.chainage_m for bend in bends if bend.radius_m <= 40.0)

        for method in METHOD_NAMES:
            try:
                built = build_profile(method, edge.samples, base)
            except ValueError:
                continue
            score = score_profile(
                built,
                reference_net_dz_m=reference_net,
                reference_ascent_m=reference_ascent,
                hairpin_chainages_m=hairpins,
            )
            nominal = simulate(built.samples, built.elevations_m, crr, NOMINAL_STEP_S)
            fine = simulate(built.samples, built.elevations_m, crr, FINE_STEP_S)
            coarse = simulate(built.samples, built.elevations_m, crr, COARSE_STEP_S)
            simulable = nominal is not None and fine is not None and coarse is not None
            rows.append(
                {
                    "osm_way_id": edge.osm_way_id,
                    "edge_id": edge.edge_id,
                    "name": edge.name,
                    "horizontal_length_m": round(edge.horizontal_length_m, 1),
                    "hairpin_count": len(hairpins),
                    "method": method,
                    "segment_count": score.segment_count,
                    "mean_spacing_m": round(
                        score.horizontal_length_m / max(1, score.segment_count), 2
                    ),
                    "net_dz_m": round(score.net_dz_m, 3),
                    "net_dz_error_m": round(score.net_dz_error_m, 4),
                    "ascent_m": round(score.ascent_m, 3),
                    "ascent_inflation_ratio": round(score.ascent_inflation_ratio, 4),
                    "travelled_length_m": round(score.travelled_length_m, 2),
                    "max_abs_grade_ratio": round(score.max_abs_grade_ratio, 4),
                    "implausible_segment_count": score.implausible_segment_count,
                    "hairpin_max_abs_grade_ratio": (
                        round(score.hairpin_max_abs_grade_ratio, 4)
                        if score.hairpin_max_abs_grade_ratio is not None
                        else ""
                    ),
                    "simulable": simulable,
                    "elapsed_time_s": round(nominal.elapsed_time_s, 4) if nominal else "",
                    "elapsed_time_fine_s": round(fine.elapsed_time_s, 4) if fine else "",
                    "elapsed_time_coarse_s": round(coarse.elapsed_time_s, 4) if coarse else "",
                    "time_step_spread_s": (
                        round(abs(coarse.elapsed_time_s - fine.elapsed_time_s), 4)
                        if simulable
                        else ""
                    ),
                    "time_step_spread_ratio": (
                        round(
                            abs(coarse.elapsed_time_s - fine.elapsed_time_s)
                            / max(fine.elapsed_time_s, 1e-9),
                            6,
                        )
                        if simulable
                        else ""
                    ),
                    "stop_reason": nominal.stop_reason if nominal else "",
                    "stop_reason_stable": (
                        coarse.stop_reason == fine.stop_reason if simulable else ""
                    ),
                }
            )

    with (output / "elevation_method_comparison.csv").open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    # --- aggregate and decide ------------------------------------------------
    summary: dict[str, dict[str, float]] = {}
    for method in METHOD_NAMES:
        subset = [row for row in rows if row["method"] == method]
        simulable = [row for row in subset if row["simulable"]]
        with_hairpin = [row for row in subset if row["hairpin_max_abs_grade_ratio"] != ""]
        summary[method] = {
            "edges": len(subset),
            "simulable_share": round(len(simulable) / max(1, len(subset)), 4),
            "median_segments": statistics.median([row["segment_count"] for row in subset]),
            "median_abs_net_dz_error_m": round(
                statistics.median([abs(row["net_dz_error_m"]) for row in subset]), 4
            ),
            "max_abs_net_dz_error_m": round(max(abs(row["net_dz_error_m"]) for row in subset), 3),
            "median_ascent_inflation": round(
                statistics.median([row["ascent_inflation_ratio"] for row in subset]), 4
            ),
            "median_max_grade": round(
                statistics.median([row["max_abs_grade_ratio"] for row in subset]), 4
            ),
            "implausible_segments_total": sum(row["implausible_segment_count"] for row in subset),
            "median_hairpin_max_grade": (
                round(
                    statistics.median([row["hairpin_max_abs_grade_ratio"] for row in with_hairpin]),
                    4,
                )
                if with_hairpin
                else None
            ),
            "median_time_step_spread_ratio": (
                round(statistics.median([row["time_step_spread_ratio"] for row in simulable]), 6)
                if simulable
                else None
            ),
            "max_time_step_spread_ratio": (
                round(max(row["time_step_spread_ratio"] for row in simulable), 6)
                if simulable
                else None
            ),
            "stop_reason_unstable": sum(
                1 for row in simulable if row["stop_reason_stable"] is False
            ),
        }

    (output / "elevation_method_summary.json").write_text(
        json.dumps(
            {
                "scenario": arguments.scenario,
                "edges_studied": studied,
                "criteria": {
                    "elevation_conservation": "median and maximum |net dz error| against the 5 m measurement",
                    "plausible_grades": "segments beyond 25 % and the median worst grade",
                    "temporal_stability": "relative spread of elapsed time between 0.01 s and 0.10 s steps",
                    "stop_sensitivity": "runs whose stop reason changes with the step",
                    "hairpin_behaviour": "median worst grade within 25 m of a bend under 40 m radius",
                },
                "methods": summary,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )

    lines = [
        "method                | edges | sim% | segs | dz err | ascent | maxg | >25% | hairpin | dt spread | unstable"
    ]
    for method, values in summary.items():
        lines.append(
            f"{method:<21} | {values['edges']:>5} | {values['simulable_share'] * 100:>3.0f}% | "
            f"{values['median_segments']:>4.0f} | {values['median_abs_net_dz_error_m']:>6.3f} | "
            f"{values['median_ascent_inflation']:>6.3f} | {values['median_max_grade']:>4.2f} | "
            f"{values['implausible_segments_total']:>4} | "
            f"{values['median_hairpin_max_grade'] if values['median_hairpin_max_grade'] is not None else '-':>7} | "
            f"{values['median_time_step_spread_ratio']:>9} | {values['stop_reason_unstable']:>8}"
        )
    write_text_lf(output / "elevation_method_summary.txt", "\n".join(lines) + "\n")
    print("\n".join(lines))
    print(f"\nstudied {studied} edges; wrote {output / 'elevation_method_comparison.csv'}")


if __name__ == "__main__":
    main()
