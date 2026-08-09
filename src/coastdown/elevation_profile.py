"""Candidate methods for turning terrain samples into a production profile.

Phase 1B established the problem rather than solving it: 2 m sampling of a 1 m
terrain model is dominated by quantisation noise, 5 m is still contaminated,
10 m and 25 m are stable, and a mean filter applied along chainage can *steepen*
a hairpin instead of relaxing it.

No spacing is therefore chosen by decree.  Five methods are built, all fed from
the same base samples so that they differ only in construction, and each is
scored on what actually matters for a coasting simulation:

* is the elevation budget conserved, or has smoothing eaten the descent;
* are the grades physically plausible for a road;
* is the simulated time stable when the integrator step changes;
* does the run stop and restart in the same places;
* does the method survive a hairpin.

A visually smooth curve is not the objective and is not scored.

The filters here window along **chainage**, never in the plane.  Two points on
opposite legs of a hairpin can be ten metres apart on the ground and a hundred
metres apart along the roadway; a spatial window would average them together and
flatten precisely the feature the study cares about.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Sequence
from dataclasses import dataclass

from .sampling import SamplePoint, adaptive_subsample, subsample_uniform

BASE_SPACING_M = 5.0

METHOD_NAMES = (
    "raw_10m",
    "raw_25m",
    "adaptive_geometry",
    "robust_median_local",
    "net_dz_constrained",
)


@dataclass(frozen=True)
class BuiltProfile:
    method: str
    samples: tuple[SamplePoint, ...]
    elevations_m: tuple[float, ...]


def _pairs(
    samples: Sequence[SamplePoint], elevations: Sequence[float]
) -> tuple[tuple[SamplePoint, float], ...]:
    if len(samples) != len(elevations):
        raise ValueError("samples and elevations must have equal length.")
    return tuple(zip(samples, elevations))


def robust_median_filter(
    chainage_m: Sequence[float], elevations: Sequence[float], window_m: float
) -> tuple[float, ...]:
    """Median of the elevations within a centred chainage window.

    A median rather than a mean, because the artefact being removed is a spike:
    one cell-height jump drags a mean by half its size and leaves a median
    untouched.  The window is measured along the roadway, so a hairpin's two
    legs are never mixed.
    """
    if len(chainage_m) != len(elevations):
        raise ValueError("chainage_m and elevations must have equal length.")
    if window_m <= 0:
        return tuple(float(value) for value in elevations)
    half = window_m / 2.0
    count = len(elevations)
    smoothed: list[float] = []
    low = 0
    high = 0
    for index in range(count):
        while low < count and chainage_m[index] - chainage_m[low] > half:
            low += 1
        while high < count and chainage_m[high] - chainage_m[index] <= half:
            high += 1
        smoothed.append(statistics.median(elevations[low:high]))
    return tuple(smoothed)


def restore_net_elevation(
    chainage_m: Sequence[float], elevations: Sequence[float], target_net_dz_m: float
) -> tuple[float, ...]:
    """Add the linear ramp that restores an exact end-to-end elevation change.

    Filtering moves the endpoints, so the descent a route actually offers can be
    quietly reduced.  A linear correction along chainage restores the measured
    budget without reintroducing the local spikes the filter removed, and being
    linear it adds a constant grade offset rather than a new feature.
    """
    span = chainage_m[-1] - chainage_m[0]
    if span <= 0:
        raise ValueError("The profile has zero length.")
    current = elevations[-1] - elevations[0]
    correction = target_net_dz_m - current
    return tuple(
        value + correction * (position - chainage_m[0]) / span
        for position, value in zip(chainage_m, elevations)
    )


def build_profile(
    method: str,
    base_samples: Sequence[SamplePoint],
    base_elevations: Sequence[float],
    *,
    base_spacing_m: float = BASE_SPACING_M,
    filter_window_m: float = 20.0,
) -> BuiltProfile:
    """Construct one candidate production profile from the base samples."""
    pairs = _pairs(base_samples, base_elevations)
    lookup = {sample.chainage_m: elevation for sample, elevation in pairs}

    if method == "raw_10m":
        chosen = subsample_uniform(base_samples, base_spacing_m, 10.0)
        return BuiltProfile(method, chosen, tuple(lookup[s.chainage_m] for s in chosen))
    if method == "raw_25m":
        chosen = subsample_uniform(base_samples, base_spacing_m, 25.0)
        return BuiltProfile(method, chosen, tuple(lookup[s.chainage_m] for s in chosen))
    if method == "adaptive_geometry":
        chosen = adaptive_subsample(base_samples)
        return BuiltProfile(method, chosen, tuple(lookup[s.chainage_m] for s in chosen))

    chainage = [sample.chainage_m for sample in base_samples]
    filtered = robust_median_filter(chainage, list(base_elevations), filter_window_m)
    if method == "net_dz_constrained":
        filtered = restore_net_elevation(
            chainage, filtered, base_elevations[-1] - base_elevations[0]
        )
    elif method != "robust_median_local":
        raise ValueError(f"Unknown profile method {method!r}.")
    filtered_lookup = dict(zip(chainage, filtered))
    chosen = subsample_uniform(base_samples, base_spacing_m, 10.0)
    return BuiltProfile(method, chosen, tuple(filtered_lookup[s.chainage_m] for s in chosen))


@dataclass(frozen=True)
class MethodScore:
    method: str
    segment_count: int
    horizontal_length_m: float
    travelled_length_m: float
    net_dz_m: float
    net_dz_error_m: float
    ascent_m: float
    ascent_inflation_ratio: float
    max_abs_grade_ratio: float
    implausible_segment_count: int
    hairpin_max_abs_grade_ratio: float | None


def score_profile(
    profile: BuiltProfile,
    *,
    reference_net_dz_m: float,
    reference_ascent_m: float,
    plausible_grade_ratio: float = 0.25,
    hairpin_chainages_m: Sequence[float] = (),
    hairpin_window_m: float = 25.0,
) -> MethodScore:
    """Score one built profile against the unfiltered measurement.

    ``plausible_grade_ratio`` is a road-engineering bound, not the simulator's
    validity bound: French mountain roads are built below 15 %, and a 25 %
    segment on a mapped road is far more likely to be a terrain artefact than a
    gradient.
    """
    samples = profile.samples
    elevations = profile.elevations_m
    grades: list[float] = []
    changes: list[float] = []
    horizontal = 0.0
    travelled = 0.0
    positions: list[float] = []
    for (start, start_z), (end, end_z) in zip(
        zip(samples, elevations), zip(samples[1:], elevations[1:])
    ):
        dx = math.hypot(end.x_m - start.x_m, end.y_m - start.y_m)
        if dx <= 1e-9:
            continue
        dz = end_z - start_z
        grades.append(dz / dx)
        changes.append(dz)
        horizontal += dx
        travelled += math.hypot(dx, dz)
        positions.append(start.chainage_m)
    if not grades:
        raise ValueError("The profile produced no usable segment.")
    ascent = math.fsum(value for value in changes if value > 0)
    net = math.fsum(changes)

    hairpin_max: float | None = None
    if hairpin_chainages_m:
        local = [
            abs(grade)
            for grade, position in zip(grades, positions)
            if any(abs(position - bend) <= hairpin_window_m for bend in hairpin_chainages_m)
        ]
        hairpin_max = max(local) if local else None

    return MethodScore(
        method=profile.method,
        segment_count=len(grades),
        horizontal_length_m=horizontal,
        travelled_length_m=travelled,
        net_dz_m=net,
        net_dz_error_m=net - reference_net_dz_m,
        ascent_m=ascent,
        ascent_inflation_ratio=(ascent / reference_ascent_m) if reference_ascent_m > 0 else 1.0,
        max_abs_grade_ratio=max(abs(value) for value in grades),
        implausible_segment_count=sum(1 for value in grades if abs(value) > plausible_grade_ratio),
        hairpin_max_abs_grade_ratio=hairpin_max,
    )
