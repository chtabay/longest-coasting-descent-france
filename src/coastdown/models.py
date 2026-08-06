from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class BicycleSystem:
    """Physical parameters for rider, bicycle and passive resistance.

    All values use SI units.
    """

    rider_mass_kg: float = 75.0
    bicycle_mass_kg: float = 15.0
    rolling_resistance_coefficient: float = 0.006
    drag_area_m2: float = 0.55

    @property
    def total_mass_kg(self) -> float:
        return self.rider_mass_kg + self.bicycle_mass_kg

    def validate(self) -> None:
        if self.rider_mass_kg <= 0 or self.bicycle_mass_kg <= 0:
            raise ValueError("Masses must be positive.")
        if not 0 <= self.rolling_resistance_coefficient < 0.1:
            raise ValueError("Rolling resistance coefficient is outside a plausible range.")
        if self.drag_area_m2 <= 0:
            raise ValueError("Drag area must be positive.")


@dataclass(frozen=True)
class Environment:
    gravity_m_s2: float = 9.80665
    air_density_kg_m3: float = 1.225
    along_route_wind_m_s: float = 0.0

    def validate(self) -> None:
        if self.gravity_m_s2 <= 0:
            raise ValueError("Gravity must be positive.")
        if self.air_density_kg_m3 <= 0:
            raise ValueError("Air density must be positive.")


@dataclass(frozen=True)
class RoadProfile:
    """Piecewise-constant grade profile.

    `segment_lengths_m[i]` and `grades[i]` describe one segment.
    Grade is rise/run in the direction of travel, with downhill NEGATIVE.
    Example: -0.05 means a 5% descent.
    """

    segment_lengths_m: np.ndarray
    grades: np.ndarray

    def __post_init__(self) -> None:
        lengths = np.asarray(self.segment_lengths_m, dtype=float)
        grades = np.asarray(self.grades, dtype=float)
        object.__setattr__(self, "segment_lengths_m", lengths)
        object.__setattr__(self, "grades", grades)
        if lengths.ndim != 1 or grades.ndim != 1:
            raise ValueError("Profile arrays must be one-dimensional.")
        if len(lengths) == 0 or len(lengths) != len(grades):
            raise ValueError("Lengths and grades must have equal non-zero length.")
        if np.any(~np.isfinite(lengths)) or np.any(~np.isfinite(grades)):
            raise ValueError("Profile contains non-finite values.")
        if np.any(lengths <= 0):
            raise ValueError("Every segment length must be positive.")
        if np.any(np.abs(grades) > 0.5):
            raise ValueError("A grade magnitude above 50% likely indicates bad input units.")

    @property
    def total_length_m(self) -> float:
        return float(self.segment_lengths_m.sum())

    @property
    def segment_end_distances_m(self) -> np.ndarray:
        return np.cumsum(self.segment_lengths_m)

    def grade_at_distance(self, distance_m: float) -> float:
        idx = int(np.searchsorted(self.segment_end_distances_m, distance_m, side="right"))
        idx = min(idx, len(self.grades) - 1)
        return float(self.grades[idx])


@dataclass(frozen=True)
class SimulationResult:
    time_s: np.ndarray
    distance_m: np.ndarray
    speed_m_s: np.ndarray
    completed_route: bool
    stop_reason: str

    @property
    def elapsed_time_s(self) -> float:
        return float(self.time_s[-1])

    @property
    def travelled_distance_m(self) -> float:
        return float(self.distance_m[-1])
