from __future__ import annotations

import bisect
import math
from collections.abc import Iterable
from dataclasses import dataclass


def _finite(name: str, value: float) -> float:
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite, got {value!r}.")
    return value


@dataclass(frozen=True)
class BicycleSystem:
    """Rider/bicycle parameters in SI units.

    ``rotating_equivalent_mass_kg`` represents wheel/component rotational inertia
    as an equivalent mass.  It contributes only to effective inertia, not to
    gravity, rolling resistance, or aerodynamic force.  Set it to zero to disable
    the option.  The 1.5 kg default is provisional and must be sensitivity-tested.
    """

    rider_mass_kg: float = 75.0
    bicycle_mass_kg: float = 15.0
    rotating_equivalent_mass_kg: float = 1.5
    rolling_resistance_coefficient: float = 0.006
    drag_area_m2: float = 0.55

    @property
    def translational_mass_kg(self) -> float:
        return self.rider_mass_kg + self.bicycle_mass_kg

    @property
    def effective_inertial_mass_kg(self) -> float:
        return self.translational_mass_kg + self.rotating_equivalent_mass_kg

    @property
    def total_mass_kg(self) -> float:
        """Backward-compatible alias for real translational mass."""
        return self.translational_mass_kg

    def validate(self) -> None:
        rider = _finite("rider_mass_kg", self.rider_mass_kg)
        bicycle = _finite("bicycle_mass_kg", self.bicycle_mass_kg)
        rotating = _finite("rotating_equivalent_mass_kg", self.rotating_equivalent_mass_kg)
        crr = _finite("rolling_resistance_coefficient", self.rolling_resistance_coefficient)
        drag = _finite("drag_area_m2", self.drag_area_m2)
        if rider <= 0:
            raise ValueError("rider_mass_kg must be positive.")
        if bicycle <= 0:
            raise ValueError("bicycle_mass_kg must be positive.")
        if rotating < 0:
            raise ValueError("rotating_equivalent_mass_kg cannot be negative.")
        if not 0 <= crr < 0.1:
            raise ValueError("rolling_resistance_coefficient must be in [0, 0.1).")
        if drag <= 0:
            raise ValueError("drag_area_m2 must be positive.")


@dataclass(frozen=True)
class Environment:
    gravity_m_s2: float = 9.80665
    air_density_kg_m3: float = 1.225
    along_route_wind_m_s: float = 0.0

    def validate(self) -> None:
        gravity = _finite("gravity_m_s2", self.gravity_m_s2)
        density = _finite("air_density_kg_m3", self.air_density_kg_m3)
        _finite("along_route_wind_m_s", self.along_route_wind_m_s)
        if gravity <= 0:
            raise ValueError("gravity_m_s2 must be positive.")
        if density <= 0:
            raise ValueError("air_density_kg_m3 must be positive.")


@dataclass(frozen=True)
class RoadProfile:
    """Piecewise-constant road grades.

    ``grade_ratios[i]`` is rise/run in travel direction: negative is downhill,
    zero is flat and positive is uphill.  Thus -0.05 is a 5% descent.  The 50%
    magnitude limit is an input-error guard, not proof that the caller used ratios.
    """

    segment_lengths_m: tuple[float, ...]
    grade_ratios: tuple[float, ...]
    segment_rolling_resistance: tuple[float, ...] | None
    # Cumulative end distances, computed once. The simulator asks for them on
    # every integration substep, so rebuilding the tuple each time made the cost
    # of a run quadratic in the number of segments: a 600-segment profile took
    # 1.13 s against 0.01 s for 60. A regional route carries thousands.
    _end_distances_m: tuple[float, ...]

    def __init__(
        self,
        segment_lengths_m: Iterable[float],
        grade_ratios: Iterable[float],
        segment_rolling_resistance: Iterable[float] | None = None,
    ):
        lengths = tuple(_finite("segment_lengths_m item", value) for value in segment_lengths_m)
        grades = tuple(_finite("grade_ratios item", value) for value in grade_ratios)
        object.__setattr__(self, "segment_lengths_m", lengths)
        object.__setattr__(self, "grade_ratios", grades)
        if not lengths or len(lengths) != len(grades):
            raise ValueError("segment_lengths_m and grade_ratios must have equal non-zero length.")
        if any(length <= 0 for length in lengths):
            raise ValueError("Every segment_lengths_m item must be positive.")
        if any(abs(grade) > 0.5 for grade in grades):
            raise ValueError("Every grade_ratios item must be within [-0.5, 0.5].")
        ends: list[float] = []
        running = 0.0
        for length in lengths:
            running += length
            ends.append(running)
        object.__setattr__(self, "_end_distances_m", tuple(ends))
        if segment_rolling_resistance is None:
            object.__setattr__(self, "segment_rolling_resistance", None)
            return
        # A route crossing asphalt, gravel and dirt cannot share one coefficient:
        # rolling resistance dominates the end of a coast and varies by roughly an
        # order of magnitude across those surfaces.
        coefficients = tuple(
            _finite("segment_rolling_resistance item", value)
            for value in segment_rolling_resistance
        )
        if len(coefficients) != len(lengths):
            raise ValueError("segment_rolling_resistance must have one value per segment.")
        if any(not 0 <= value < 0.1 for value in coefficients):
            raise ValueError("Every segment_rolling_resistance item must be in [0, 0.1).")
        object.__setattr__(self, "segment_rolling_resistance", coefficients)

    @property
    def grades(self) -> tuple[float, ...]:
        """Deprecated-compatible alias; new code should use ``grade_ratios``."""
        return self.grade_ratios

    @property
    def total_length_m(self) -> float:
        return self._end_distances_m[-1]

    @property
    def segment_end_distances_m(self) -> tuple[float, ...]:
        return self._end_distances_m

    def segment_index_at_distance(self, distance_m: float) -> int:
        distance = _finite("distance_m", distance_m)
        if distance < 0 or distance > self._end_distances_m[-1]:
            raise ValueError("distance_m must lie within the road profile.")
        index = bisect.bisect_right(self._end_distances_m, distance)
        return min(index, len(self.grade_ratios) - 1)

    def grade_ratio_at_distance(self, distance_m: float) -> float:
        return self.grade_ratios[self.segment_index_at_distance(distance_m)]

    def grade_at_distance(self, distance_m: float) -> float:
        """Deprecated-compatible alias for ``grade_ratio_at_distance``."""
        return self.grade_ratio_at_distance(distance_m)


@dataclass(frozen=True)
class SimulationResult:
    time_s: tuple[float, ...]
    distance_m: tuple[float, ...]
    speed_m_s: tuple[float, ...]
    completed_route: bool
    stop_reason: str
    moving_time_s: float
    first_below_threshold_time_s: float | None
    first_zero_speed_time_s: float | None
    qualified_stop_time_s: float | None
    stationary_time_s: float

    @property
    def elapsed_time_s(self) -> float:
        return self.time_s[-1]

    @property
    def travelled_distance_m(self) -> float:
        return self.distance_m[-1]
