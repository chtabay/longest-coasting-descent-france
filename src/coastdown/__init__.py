"""Baseline tools for bicycle coast-down simulation."""

from .models import BicycleSystem, Environment, RoadProfile, SimulationResult
from .geography import (
    AccessStatus,
    DirectedRoadEdge,
    ElevationSample,
    ProfileSegment,
    SourceProvenance,
    StructureStatus,
    build_profile_segments,
    edge_to_road_profile,
    lonlat_to_lambert93,
)
from .physics import grade_percent_to_ratio, grade_ratio_to_angle_rad, simulate_profile

__all__ = [
    "BicycleSystem",
    "AccessStatus",
    "DirectedRoadEdge",
    "ElevationSample",
    "Environment",
    "RoadProfile",
    "SimulationResult",
    "ProfileSegment",
    "SourceProvenance",
    "StructureStatus",
    "build_profile_segments",
    "edge_to_road_profile",
    "grade_percent_to_ratio",
    "grade_ratio_to_angle_rad",
    "lonlat_to_lambert93",
    "simulate_profile",
]
