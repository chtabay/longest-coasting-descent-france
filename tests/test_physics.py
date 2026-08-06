import numpy as np

from coastdown import BicycleSystem, RoadProfile, simulate_profile
from coastdown.physics import longitudinal_acceleration_m_s2


def test_flat_road_decelerates() -> None:
    bicycle = BicycleSystem()
    acceleration = longitudinal_acceleration_m_s2(5.0, 0.0, bicycle, environment=_environment())
    assert acceleration < 0


def test_downhill_can_accelerate() -> None:
    bicycle = BicycleSystem()
    acceleration = longitudinal_acceleration_m_s2(5.0, -0.05, bicycle, environment=_environment())
    assert acceleration > 0


def test_flat_profile_eventually_stops() -> None:
    profile = RoadProfile(np.array([10_000.0]), np.array([0.0]))
    result = simulate_profile(profile, time_step_s=0.1)
    assert result.stop_reason == "speed_threshold"
    assert not result.completed_route
    assert result.travelled_distance_m > 0
    assert np.all(np.diff(result.distance_m) >= 0)


def test_steep_descent_completes() -> None:
    profile = RoadProfile(np.array([1_000.0]), np.array([-0.08]))
    result = simulate_profile(profile, time_step_s=0.05)
    assert result.completed_route
    assert result.stop_reason == "route_end"
    assert result.travelled_distance_m == profile.total_length_m


def test_short_uphill_can_be_crossed_by_inertia() -> None:
    profile = RoadProfile(
        np.array([400.0, 15.0, 400.0]),
        np.array([-0.06, 0.02, -0.03]),
    )
    result = simulate_profile(profile, time_step_s=0.02)
    assert result.completed_route


def _environment():
    from coastdown import Environment

    return Environment()
