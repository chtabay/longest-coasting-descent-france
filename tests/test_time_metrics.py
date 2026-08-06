import pytest

from coastdown import BicycleSystem, RoadProfile, simulate_profile
from coastdown.physics import longitudinal_acceleration_m_s2
from coastdown import Environment


def low_loss_bicycle(crr: float = 0.01) -> BicycleSystem:
    return BicycleSystem(
        rotating_equivalent_mass_kg=0,
        rolling_resistance_coefficient=crr,
        drag_area_m2=1e-12,
    )


def test_below_threshold_without_physical_stop() -> None:
    result = simulate_profile(
        RoadProfile([1.0], [-0.01]),
        initial_speed_m_s=0.2,
        stop_speed_m_s=0.3,
        stop_dwell_s=20,
    )
    assert result.completed_route
    assert result.first_below_threshold_time_s == 0
    assert result.first_zero_speed_time_s is None
    assert result.qualified_stop_time_s is None
    assert result.stationary_time_s == 0
    assert result.moving_time_s == pytest.approx(result.elapsed_time_s)


def test_physical_stop_at_boundary_followed_by_restart() -> None:
    bicycle = low_loss_bicycle()
    initial_speed = 5.0
    deceleration = longitudinal_acceleration_m_s2(initial_speed, 0, bicycle, Environment())
    stopping_distance = -(initial_speed**2) / (2 * deceleration)
    result = simulate_profile(
        RoadProfile([stopping_distance, 100], [0, -0.1]),
        bicycle,
        initial_speed_m_s=initial_speed,
        stop_speed_m_s=0.01,
        stop_dwell_s=2,
        time_step_s=100,
    )
    assert result.completed_route
    assert result.first_zero_speed_time_s is not None
    assert result.qualified_stop_time_s is None
    assert result.stationary_time_s == 0  # restart is immediate in this time-invariant model
    assert result.moving_time_s == pytest.approx(result.elapsed_time_s)


def test_multiple_zero_speed_events_are_preserved() -> None:
    bicycle = low_loss_bicycle(crr=0)
    initial_speed = 2.0
    uphill_grade = 0.1
    acceleration_up = longitudinal_acceleration_m_s2(
        initial_speed, uphill_grade, bicycle, Environment()
    )
    first_uphill = -(initial_speed**2) / (2 * acceleration_up)
    # A downhill of identical angle and length restores the initial kinetic energy.
    profile = RoadProfile(
        [first_uphill, first_uphill, first_uphill, 20],
        [uphill_grade, -uphill_grade, uphill_grade, -uphill_grade],
    )
    result = simulate_profile(
        profile,
        bicycle,
        initial_speed_m_s=initial_speed,
        stop_speed_m_s=0.001,
        stop_dwell_s=10,
        time_step_s=100,
    )
    assert result.completed_route
    assert sum(speed <= 1e-12 for speed in result.speed_m_s) >= 2
    assert result.first_zero_speed_time_s is not None
    assert result.qualified_stop_time_s is None


def test_qualified_stop_reports_stationary_dwell() -> None:
    result = simulate_profile(
        RoadProfile([10_000], [0]), stop_speed_m_s=0, stop_dwell_s=2, time_step_s=0.05
    )
    assert result.stop_reason == "speed_threshold"
    assert result.first_below_threshold_time_s is not None
    assert result.first_zero_speed_time_s is not None
    assert result.qualified_stop_time_s == result.elapsed_time_s
    assert result.stationary_time_s > 0
    assert result.moving_time_s + result.stationary_time_s == pytest.approx(result.elapsed_time_s)


@pytest.mark.parametrize("reason", ["route_end", "max_time"])
def test_non_stop_termination_has_no_qualified_stop(reason: str) -> None:
    kwargs = {"max_time_s": 0.1} if reason == "max_time" else {}
    length = 10_000 if reason == "max_time" else 1
    result = simulate_profile(RoadProfile([length], [-0.02]), **kwargs)
    assert result.stop_reason == reason
    assert result.qualified_stop_time_s is None
    assert result.moving_time_s == pytest.approx(result.elapsed_time_s)
