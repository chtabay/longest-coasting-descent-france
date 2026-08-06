"""Independent invariants added during the contradictory Phase 0 audit."""

import math

import pytest

from coastdown import BicycleSystem, Environment, RoadProfile, simulate_profile
from coastdown.physics import longitudinal_acceleration_m_s2


def nearly_lossless_bicycle() -> BicycleSystem:
    return BicycleSystem(
        rotating_equivalent_mass_kg=0.0,
        rolling_resistance_coefficient=0.0,
        drag_area_m2=1e-12,
    )


def test_frictionless_constant_slope_matches_energy_solution() -> None:
    """Check a physical invariant, rather than reproducing solver operations."""
    grade_ratio = -0.2
    distance_m = 1_000.0
    initial_speed_m_s = 4.0
    environment = Environment(air_density_kg_m3=1e-12)
    result = simulate_profile(
        RoadProfile([distance_m], [grade_ratio]),
        nearly_lossless_bicycle(),
        environment,
        initial_speed_m_s=initial_speed_m_s,
        time_step_s=2.0,
    )
    theta_rad = math.atan(grade_ratio)
    expected_speed_m_s = math.sqrt(
        initial_speed_m_s**2 - 2 * environment.gravity_m_s2 * math.sin(theta_rad) * distance_m
    )
    assert result.completed_route
    assert result.speed_m_s[-1] == pytest.approx(expected_speed_m_s, rel=1e-12)


def test_bicycle_stopping_exactly_at_boundary_can_restart_downhill() -> None:
    """Exercise the zero-speed/segment-boundary event collision."""
    bicycle = BicycleSystem(
        rotating_equivalent_mass_kg=0.0,
        rolling_resistance_coefficient=0.01,
        drag_area_m2=1e-12,
    )
    initial_speed_m_s = 5.0
    flat_acceleration = longitudinal_acceleration_m_s2(
        initial_speed_m_s, 0.0, bicycle, Environment()
    )
    stopping_distance_m = -(initial_speed_m_s**2) / (2 * flat_acceleration)
    profile = RoadProfile([stopping_distance_m, 100.0], [0.0, -0.1])
    result = simulate_profile(
        profile,
        bicycle,
        initial_speed_m_s=initial_speed_m_s,
        time_step_s=100.0,
        stop_speed_m_s=0.01,
        stop_dwell_s=2.0,
    )
    boundary_index = result.distance_m.index(stopping_distance_m)
    assert result.speed_m_s[boundary_index] == pytest.approx(0.0, abs=1e-10)
    assert result.completed_route
    assert result.speed_m_s[-1] > 0


def test_headwind_and_tailwind_have_opposite_effects() -> None:
    bicycle = BicycleSystem()
    still = longitudinal_acceleration_m_s2(5.0, 0.0, bicycle, Environment())
    headwind = longitudinal_acceleration_m_s2(
        5.0, 0.0, bicycle, Environment(along_route_wind_m_s=-3.0)
    )
    tailwind = longitudinal_acceleration_m_s2(
        5.0, 0.0, bicycle, Environment(along_route_wind_m_s=3.0)
    )
    assert headwind < still < tailwind


def test_max_time_is_an_exact_event_and_trace_time_is_strictly_increasing() -> None:
    result = simulate_profile(
        RoadProfile([100_000.0], [-0.02]),
        max_time_s=1.03,
        time_step_s=0.2,
    )
    assert result.stop_reason == "max_time"
    assert result.elapsed_time_s == pytest.approx(1.03)
    assert all(after > before for before, after in zip(result.time_s, result.time_s[1:]))


def test_route_end_wins_when_reached_before_threshold_dwell_expiry() -> None:
    result = simulate_profile(
        RoadProfile([0.01], [0.0]),
        initial_speed_m_s=0.1,
        stop_speed_m_s=0.3,
        stop_dwell_s=2.0,
        time_step_s=5.0,
    )
    assert result.completed_route
    assert result.stop_reason == "route_end"
    assert result.elapsed_time_s < 2.0
