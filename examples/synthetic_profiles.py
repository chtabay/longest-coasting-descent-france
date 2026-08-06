"""Reproducible Phase 0 benchmark; uses only Python's standard library."""

from __future__ import annotations

import csv
import html
from dataclasses import dataclass
from pathlib import Path

from coastdown import BicycleSystem, RoadProfile, SimulationResult, simulate_profile


@dataclass(frozen=True)
class Run:
    scenario: str
    variant: str
    profile: RoadProfile
    result: SimulationResult
    time_step_s: float
    rotating_mass_kg: float


def _run(
    scenario: str,
    variant: str,
    profile: RoadProfile,
    *,
    time_step_s: float = 0.05,
    rotating_mass_kg: float = 1.5,
) -> Run:
    result = simulate_profile(
        profile,
        BicycleSystem(rotating_equivalent_mass_kg=rotating_mass_kg),
        time_step_s=time_step_s,
    )
    return Run(scenario, variant, profile, result, time_step_s, rotating_mass_kg)


def benchmark_runs() -> list[Run]:
    flat = RoadProfile([10_000.0], [0.0])
    gentle = RoadProfile([12_000.0], [-0.012])
    steep = RoadProfile([2_000.0], [-0.08])
    rise_crossed = RoadProfile([500.0, 15.0, 800.0], [-0.04, 0.025, -0.012])
    rise_stopped = RoadProfile([180.0, 2_000.0], [-0.04, 0.045])
    short_segments = RoadProfile(
        [20.0] * 24 + [500.0],
        [(-0.025 if index % 3 else 0.012) for index in range(24)] + [-0.01],
    )
    runs = [
        _run("flat_to_stop", "central", flat),
        _run("gentle_long", "central", gentle),
        _run("steep_short", "central", steep),
        _run("descent_rise_crossed", "central", rise_crossed),
        _run("descent_rise_stopped", "central", rise_stopped),
        _run("many_short_segments", "central", short_segments, time_step_s=0.2),
        _run("rotational_inertia", "enabled_1.5kg", rise_crossed, rotating_mass_kg=1.5),
        _run("rotational_inertia", "disabled_0kg", rise_crossed, rotating_mass_kg=0.0),
    ]
    for step in (0.2, 0.1, 0.05, 0.025):
        runs.append(_run("time_step_comparison", f"dt_{step:g}s", rise_crossed, time_step_s=step))
    return runs


def _svg_chart(
    path: Path,
    title: str,
    x_label: str,
    y_label: str,
    series: list[tuple[str, tuple[float, ...], tuple[float, ...]]],
) -> None:
    # Bound artifact size without changing any tabular simulation result.
    compact_series = []
    for label, xs, ys in series:
        stride = max(1, len(xs) // 2_000)
        indices = list(range(0, len(xs), stride))
        if indices[-1] != len(xs) - 1:
            indices.append(len(xs) - 1)
        compact_series.append(
            (label, tuple(xs[index] for index in indices), tuple(ys[index] for index in indices))
        )
    series = compact_series
    width, height = 900, 520
    left, right, top, bottom = 80, 25, 55, 65
    all_x = [value for _, xs, _ in series for value in xs]
    all_y = [value for _, _, ys in series for value in ys]
    x_min, x_max = min(all_x), max(all_x)
    y_min, y_max = min(all_y), max(all_y)
    if x_max == x_min:
        x_max += 1
    if y_max == y_min:
        y_max += 1
    y_pad = 0.05 * (y_max - y_min)
    y_min, y_max = min(0.0, y_min - y_pad), y_max + y_pad
    plot_w, plot_h = width - left - right, height - top - bottom

    def point(x: float, y: float) -> tuple[float, float]:
        return (
            left + (x - x_min) / (x_max - x_min) * plot_w,
            top + (y_max - y) / (y_max - y_min) * plot_h,
        )

    colors = ("#146c94", "#d1495b", "#2a9d8f", "#e9c46a", "#6a4c93")
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="900" height="520" viewBox="0 0 900 520">',
        '<rect width="100%" height="100%" fill="white"/>',
        f'<text x="450" y="28" text-anchor="middle" font-family="sans-serif" font-size="20">{html.escape(title)}</text>',
        f'<line x1="{left}" y1="{top + plot_h}" x2="{left + plot_w}" y2="{top + plot_h}" stroke="#333"/>',
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top + plot_h}" stroke="#333"/>',
    ]
    for tick in range(6):
        fraction = tick / 5
        x_value = x_min + fraction * (x_max - x_min)
        y_value = y_min + fraction * (y_max - y_min)
        x_pixel, _ = point(x_value, y_min)
        _, y_pixel = point(x_min, y_value)
        parts.extend(
            [
                f'<text x="{x_pixel:.1f}" y="{top + plot_h + 22}" text-anchor="middle" font-family="sans-serif" font-size="12">{x_value:.2f}</text>',
                f'<text x="{left - 8}" y="{y_pixel + 4:.1f}" text-anchor="end" font-family="sans-serif" font-size="12">{y_value:.2f}</text>',
            ]
        )
    for index, (label, xs, ys) in enumerate(series):
        color = colors[index % len(colors)]
        coordinates = " ".join(
            f"{x:.2f},{y:.2f}" for x, y in map(lambda pair: point(*pair), zip(xs, ys))
        )
        parts.append(
            f'<polyline fill="none" stroke="{color}" stroke-width="2" points="{coordinates}"/>'
        )
        parts.append(
            f'<text x="{left + 12}" y="{top + 18 + 18 * index}" font-family="sans-serif" font-size="13" fill="{color}">{html.escape(label)}</text>'
        )
    parts.extend(
        [
            f'<text x="{left + plot_w / 2}" y="{height - 12}" text-anchor="middle" font-family="sans-serif" font-size="14">{html.escape(x_label)}</text>',
            f'<text x="18" y="{top + plot_h / 2}" text-anchor="middle" transform="rotate(-90 18 {top + plot_h / 2})" font-family="sans-serif" font-size="14">{html.escape(y_label)}</text>',
            "</svg>",
        ]
    )
    path.write_text("\n".join(parts), encoding="utf-8")


def _profile_points(profile: RoadProfile) -> tuple[tuple[float, ...], tuple[float, ...]]:
    distances = [0.0]
    elevations = [0.0]
    for length, grade in zip(profile.segment_lengths_m, profile.grade_ratios):
        distances.append(distances[-1] + length)
        elevations.append(elevations[-1] + length * grade)
    return tuple(value / 1000 for value in distances), tuple(elevations)


def main() -> None:
    output_dir = Path("outputs")
    output_dir.mkdir(exist_ok=True)
    runs = benchmark_runs()
    with (output_dir / "phase0_benchmark.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(
            [
                "scenario",
                "variant",
                "time_step_s",
                "rotating_equivalent_mass_kg",
                "elapsed_time_s",
                "distance_m",
                "final_speed_m_s",
                "completed_route",
                "stop_reason",
            ]
        )
        for run in runs:
            writer.writerow(
                [
                    run.scenario,
                    run.variant,
                    run.time_step_s,
                    run.rotating_mass_kg,
                    f"{run.result.elapsed_time_s:.9f}",
                    f"{run.result.travelled_distance_m:.9f}",
                    f"{run.result.speed_m_s[-1]:.9f}",
                    run.result.completed_route,
                    run.result.stop_reason,
                ]
            )

    grouped: dict[str, list[Run]] = {}
    for run in runs:
        grouped.setdefault(run.scenario, []).append(run)
    for scenario, scenario_runs in grouped.items():
        distance_series = [
            (
                run.variant,
                tuple(value / 1000 for value in run.result.distance_m),
                tuple(value * 3.6 for value in run.result.speed_m_s),
            )
            for run in scenario_runs
        ]
        time_series = [
            (run.variant, run.result.time_s, tuple(value * 3.6 for value in run.result.speed_m_s))
            for run in scenario_runs
        ]
        profile_series = []
        seen: set[RoadProfile] = set()
        for run in scenario_runs:
            if run.profile not in seen:
                x_values, y_values = _profile_points(run.profile)
                profile_series.append((run.variant, x_values, y_values))
                seen.add(run.profile)
        _svg_chart(
            output_dir / f"{scenario}_speed_distance.svg",
            f"{scenario}: speed vs distance",
            "Distance (km)",
            "Speed (km/h)",
            distance_series,
        )
        _svg_chart(
            output_dir / f"{scenario}_speed_time.svg",
            f"{scenario}: speed vs time",
            "Time (s)",
            "Speed (km/h)",
            time_series,
        )
        _svg_chart(
            output_dir / f"{scenario}_profile.svg",
            f"{scenario}: synthetic elevation",
            "Distance (km)",
            "Relative elevation (m)",
            profile_series,
        )

    fine = next(
        run for run in runs if run.scenario == "time_step_comparison" and run.time_step_s == 0.025
    )
    coarse = next(
        run for run in runs if run.scenario == "time_step_comparison" and run.time_step_s == 0.2
    )
    enabled = next(
        run for run in runs if run.scenario == "rotational_inertia" and run.rotating_mass_kg > 0
    )
    disabled = next(
        run for run in runs if run.scenario == "rotational_inertia" and run.rotating_mass_kg == 0
    )
    report = f"""# Phase 0 synthetic benchmark

Generated by `python examples/synthetic_profiles.py` using deterministic synthetic profiles only.

## Highlights

- The flat case ends on the configured speed-threshold dwell event.
- Both crossable and non-crossable rises are represented and produce distinct outcomes.
- Rotational inertia changes elapsed time by {enabled.result.elapsed_time_s - disabled.result.elapsed_time_s:+.6f} s on the comparison profile.
- The 0.2 s and 0.025 s step results differ by {coarse.result.elapsed_time_s - fine.result.elapsed_time_s:+.6f} s.
- Segment boundaries and route-end times are handled as events inside nominal time steps.

See `phase0_benchmark.csv` for full-precision values and the SVG files for speed-distance, speed-time and synthetic elevation charts. Values are model outputs, not measurements or claims about a real French route.
"""
    (output_dir / "phase0_benchmark.md").write_text(report, encoding="utf-8")

    for run in runs:
        print(
            f"{run.scenario:24s} {run.variant:16s} time={run.result.elapsed_time_s:9.3f}s distance={run.result.travelled_distance_m:9.3f}m reason={run.result.stop_reason}"
        )


if __name__ == "__main__":
    main()
