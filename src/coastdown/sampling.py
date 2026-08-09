"""Arc-length sampling of a road polyline.

Phase 1B densified by subdividing each source chord, which preserved every OSM
vertex but meant the requested spacing was only an upper bound: asking for 25 m
on a finely mapped path realised 3.3 m.  Comparing sampling strategies needs the
opposite guarantee, so production sampling walks the polyline and places points
at exact multiples of the requested spacing.

Two properties matter and both are kept:

* horizontal length is preserved, because every sample lies *on* the polyline;
* a sharp bend is never cut, because source vertices whose turn angle exceeds a
  declared threshold are retained even when they fall between grid points.

The second rule is what makes a hairpin survive coarse sampling. Without it, a
25 m grid across a 12 m hairpin apex replaces the bend with a chord and both the
geometry and the curvature of the turn disappear.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Sequence
from dataclasses import dataclass

from .geography import lonlat_to_lambert93


@dataclass(frozen=True)
class SamplePoint:
    longitude: float
    latitude: float
    x_m: float
    y_m: float
    chainage_m: float
    on_uniform_grid: bool
    is_source_vertex: bool


def project(lonlat: Sequence[tuple[float, float]]) -> tuple[tuple[float, float], ...]:
    return tuple(lonlat_to_lambert93(longitude, latitude) for longitude, latitude in lonlat)


def polyline_length_m(lonlat: Sequence[tuple[float, float]]) -> float:
    projected = project(lonlat)
    return math.fsum(
        math.hypot(end[0] - start[0], end[1] - start[1])
        for start, end in itertools.pairwise(projected)
    )


def turn_angles_deg(projected: Sequence[tuple[float, float]]) -> tuple[float, ...]:
    """Absolute direction change at each interior vertex, in degrees."""
    angles: list[float] = []
    for before, here, after in zip(projected, projected[1:], projected[2:]):
        incoming = math.atan2(here[1] - before[1], here[0] - before[0])
        outgoing = math.atan2(after[1] - here[1], after[0] - here[0])
        change = math.degrees(outgoing - incoming)
        angles.append(abs((change + 180.0) % 360.0 - 180.0))
    return tuple(angles)


def sample_polyline(
    lonlat: Sequence[tuple[float, float]],
    spacing_m: float,
    *,
    keep_vertex_above_deg: float = 15.0,
) -> tuple[SamplePoint, ...]:
    """Place samples at exact multiples of ``spacing_m`` along the polyline.

    Source vertices turning by more than ``keep_vertex_above_deg`` are inserted
    as extra samples so that bends survive coarse spacings.  Set the threshold
    to 180 to obtain a strictly uniform grid.
    """
    if not math.isfinite(spacing_m) or spacing_m <= 0:
        raise ValueError("spacing_m must be finite and positive.")
    points = tuple(lonlat)
    if len(points) < 2:
        raise ValueError("At least two geometry points are required.")
    projected = project(points)

    # Cumulative chainage of every source vertex, dropping duplicates.
    kept: list[int] = [0]
    chainage: list[float] = [0.0]
    for index in range(1, len(points)):
        step = math.hypot(
            projected[index][0] - projected[kept[-1]][0],
            projected[index][1] - projected[kept[-1]][1],
        )
        if step <= 1e-9:
            continue
        kept.append(index)
        chainage.append(chainage[-1] + step)
    if len(kept) < 2:
        raise ValueError("The polyline collapses to a single point.")
    total = chainage[-1]

    vertex_projected = [projected[index] for index in kept]
    vertex_lonlat = [points[index] for index in kept]
    angles = turn_angles_deg(vertex_projected)
    sharp = {
        position + 1 for position, angle in enumerate(angles) if angle >= keep_vertex_above_deg
    }

    def interpolate(target: float) -> tuple[float, float, float, float]:
        """lon, lat, x, y at a chainage measured along the polyline."""
        low, high = 0, len(chainage) - 1
        while low < high - 1:
            middle = (low + high) // 2
            if chainage[middle] <= target:
                low = middle
            else:
                high = middle
        span = chainage[high] - chainage[low]
        fraction = 0.0 if span <= 0 else (target - chainage[low]) / span
        start_lonlat, end_lonlat = vertex_lonlat[low], vertex_lonlat[high]
        start_xy, end_xy = vertex_projected[low], vertex_projected[high]
        return (
            start_lonlat[0] + fraction * (end_lonlat[0] - start_lonlat[0]),
            start_lonlat[1] + fraction * (end_lonlat[1] - start_lonlat[1]),
            start_xy[0] + fraction * (end_xy[0] - start_xy[0]),
            start_xy[1] + fraction * (end_xy[1] - start_xy[1]),
        )

    grid: list[tuple[float, bool, bool]] = []
    steps = math.floor(total / spacing_m)
    for step_index in range(steps + 1):
        grid.append((step_index * spacing_m, True, False))
    if total - steps * spacing_m > 1e-9:
        grid.append((total, True, True))
    for vertex_index in sorted(sharp):
        grid.append((chainage[vertex_index], False, True))
    grid.sort(key=lambda item: item[0])

    samples: list[SamplePoint] = []
    for position, uniform, vertex in grid:
        if samples and position - samples[-1].chainage_m <= 1e-6:
            # Keep the richer flag when a bend coincides with a grid point.
            previous = samples[-1]
            samples[-1] = SamplePoint(
                previous.longitude,
                previous.latitude,
                previous.x_m,
                previous.y_m,
                previous.chainage_m,
                previous.on_uniform_grid or uniform,
                previous.is_source_vertex or vertex,
            )
            continue
        longitude, latitude, x_m, y_m = interpolate(position)
        samples.append(SamplePoint(longitude, latitude, x_m, y_m, position, uniform, vertex))
    if len(samples) < 2:
        raise ValueError("Sampling produced fewer than two points.")
    return tuple(samples)


def reverse_samples(samples: Sequence[SamplePoint]) -> tuple[SamplePoint, ...]:
    """Mirror a sample sequence for the opposite direction of travel.

    Sampling the reversed geometry would place the grid from the other end and
    produce different ground points, so the two directions of one road would be
    measured at different places and need two sets of elevations.  Mirroring
    keeps both directions on exactly the same points, which is also what the
    geometry contract requires: reversing an edge reverses the sample order and
    the grade signs while preserving the multiset of lengths.
    """
    if len(samples) < 2:
        raise ValueError("At least two samples are required.")
    total = samples[-1].chainage_m
    return tuple(
        SamplePoint(
            sample.longitude,
            sample.latitude,
            sample.x_m,
            sample.y_m,
            total - sample.chainage_m,
            sample.on_uniform_grid,
            sample.is_source_vertex,
        )
        for sample in reversed(samples)
    )


def subsample_uniform(
    samples: Sequence[SamplePoint], base_spacing_m: float, target_spacing_m: float
) -> tuple[SamplePoint, ...]:
    """Take every n-th uniform-grid point, reproducing a coarser grid.

    Selection is by **position in the grid sequence**, never by testing whether a
    chainage is a multiple of the target.  Reversing an edge renumbers chainage
    as ``total - chainage``, and a total that is not itself a multiple of the
    target leaves no sample satisfying such a test: the profile then collapses to
    its two endpoints, a single averaged grade with no terrain in between.  That
    is exactly what happened to every reverse edge — 1450 of 2400 — before this
    was fixed, and those edges dominated the ranking precisely because a
    featureless profile never stops a bicycle.
    """
    ratio = target_spacing_m / base_spacing_m
    factor = round(ratio)
    if factor < 1 or abs(ratio - factor) > 1e-9:
        raise ValueError("target_spacing_m must be an integer multiple of base_spacing_m.")
    grid = [sample for sample in samples if sample.on_uniform_grid]
    if len(grid) < 2:
        raise ValueError("The base sampling carries no uniform grid to subsample.")
    chosen = list(grid[::factor])
    if chosen[-1].chainage_m < grid[-1].chainage_m - 1e-6:
        chosen.append(grid[-1])
    tail = samples[-1]
    if chosen[-1].chainage_m < tail.chainage_m - 1e-6:
        chosen.append(tail)
    if len(chosen) < 2:
        raise ValueError("Subsampling produced fewer than two points.")
    return tuple(chosen)


def adaptive_subsample(
    samples: Sequence[SamplePoint],
    *,
    straight_spacing_m: float = 25.0,
    bend_spacing_m: float = 5.0,
    bend_influence_m: float = 30.0,
) -> tuple[SamplePoint, ...]:
    """Coarse where the road runs straight, fine near bends.

    Density follows the geometry rather than a single global constant, which is
    the compromise the sampling study is meant to test: coarse sampling is what
    suppresses terrain-model noise, but a bend needs points to exist at all.
    """
    projected = [(sample.x_m, sample.y_m) for sample in samples]
    angles = turn_angles_deg(projected)
    bend_positions = [
        samples[index + 1].chainage_m for index, angle in enumerate(angles) if angle >= 8.0
    ]
    chosen: list[SamplePoint] = [samples[0]]
    for sample in samples[1:-1]:
        near_bend = any(
            abs(sample.chainage_m - position) <= bend_influence_m for position in bend_positions
        )
        needed = bend_spacing_m if near_bend else straight_spacing_m
        if sample.chainage_m - chosen[-1].chainage_m >= needed - 1e-9 or sample.is_source_vertex:
            chosen.append(sample)
    chosen.append(samples[-1])
    if len(chosen) < 2:
        raise ValueError("Adaptive subsampling produced fewer than two points.")
    return tuple(chosen)
