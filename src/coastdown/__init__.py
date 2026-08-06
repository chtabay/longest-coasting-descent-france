"""Baseline tools for bicycle coast-down simulation."""

from .models import BicycleSystem, Environment, RoadProfile, SimulationResult
from .physics import grade_percent_to_ratio, grade_ratio_to_angle_rad, simulate_profile

__all__ = [
    "BicycleSystem",
    "AccessStatus",
    "DirectedRoadEdge",
    "ElevationSample",
    "Environment",
    "RoadProfile",
    "SimulationResult",
    "grade_percent_to_ratio",
    "grade_ratio_to_angle_rad",
    "simulate_profile",
]
