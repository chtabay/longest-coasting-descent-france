import math

import pytest

from coastdown import (
    BicycleSystem,
    Environment,
    RoadProfile,
    grade_percent_to_ratio,
    grade_ratio_to_angle_rad,
    simulate_profile,
)
from coastdown.physics import longitudinal_acceleration_m_s2


def acceleration(speed: float, grade_ratio: float, bicycle: BicycleSystem | None = None) -> float:
    return longitudinal_acceleration_m_s2(
        speed, grade_ratio, bicycle or BicycleSystem(), Environment()
    )


def test_grade_convention_and_conversions() -> None:
    assert acceleration(5.0, -0.05) > 0
    assert acceleration(5.0, 0.05) < 0
    assert grade_percent_to_ratio(-5.0) == -0.05
    assert grade_ratio_to_angle_rad(0.1) == pytest.approx(math.atan(0.1))


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_non_finite_major_parameter_families_are_rejected(bad: float) -> None:
    bicycle_fields = (
        "rider_mass_kg",
        "bicycle_mass_kg",
        "rotating_equivalent_mass_kg",
        "rolling_resistance_coefficient",
        "drag_area_m2",
    )
    for field in bicycle_fields:
        with pytest.raises(ValueError, match=field):
            BicycleSystem(**{field: bad}).validate()
    for field in ("gravity_m_s2", "air_density_kg_m3", "along_route_wind_m_s"):
        with pytest.raises(ValueError, match=field):
            Environment(**{field: bad}).validate()
    with pytest.raises(ValueError, match="grade_ratios"):
        RoadProfile([1.0], [bad])
    with pytest.raises(ValueError, match="segment_lengths_m"):
        RoadProfile([bad], [0.0])
    with pytest.raises(ValueError, match="speed_m_s"):
        acceleration(bad, 0.0)
    with pytest.raises(ValueError, match="grade_ratio"):
        acceleration(1.0, bad)
    for field in (
        "initial_speed_m_s",
        "time_step_s",
        "stop_speed_m_s",
        "stop_dwell_s",
        "max_time_s",
    ):
        with pytest.raises(ValueError, match=field):
            simulate_profile(RoadProfile([1.0], [0.0]), **{field: bad})


@pytest.mark.parametrize(
    ("factory", "message"),
    [
        (lambda: BicycleSystem(rider_mass_kg=0), "rider_mass_kg"),
        (lambda: BicycleSystem(bicycle_mass_kg=-1), "bicycle_mass_kg"),
        (lambda: BicycleSystem(rotating_equivalent_mass_kg=-1), "rotating"),
        (lambda: BicycleSystem(rolling_resistance_coefficient=0.1), "rolling"),
        (lambda: BicycleSystem(drag_area_m2=0), "drag_area"),
        (lambda: Environment(gravity_m_s2=0), "gravity"),
        (lambda: Environment(air_density_kg_m3=0), "density"),
    ],
)
def test_invalid_physical_parameters_are_rejected(factory, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        factory().validate()


def test_flat_road_decelerates_and_high_crr_shortens_coast() -> None:
    assert acceleration(5.0, 0.0) < 0
    profile = RoadProfile([10_000.0], [0.0])
    low = simulate_profile(
        profile, BicycleSystem(rolling_resistance_coefficient=0.003), time_step_s=0.05
    )
    high = simulate_profile(
        profile, BicycleSystem(rolling_resistance_coefficient=0.012), time_step_s=0.05
    )
    assert high.travelled_distance_m < low.travelled_distance_m


def test_constant_descent_converges_to_analytic_terminal_speed() -> None:
    bicycle = BicycleSystem()
    environment = Environment()
    grade = -0.04
    theta = math.atan(grade)
    driving = (
        bicycle.translational_mass_kg
        * environment.gravity_m_s2
        * (-math.sin(theta) - bicycle.rolling_resistance_coefficient * math.cos(theta))
    )
    expected = math.sqrt(2 * driving / (environment.air_density_kg_m3 * bicycle.drag_area_m2))
    result = simulate_profile(
        RoadProfile([30_000.0], [grade]), bicycle, environment, time_step_s=0.05
    )
    assert result.speed_m_s[-1] == pytest.approx(expected, rel=0.005)


def test_short_uphill_crossed_but_long_uphill_stops() -> None:
    crossed = simulate_profile(RoadProfile([300.0, 12.0, 300.0], [-0.05, 0.03, -0.02]))
    stopped = simulate_profile(RoadProfile([150.0, 2_000.0], [-0.04, 0.04]))
    assert crossed.completed_route
    assert stopped.stop_reason == "speed_threshold"
    assert not stopped.completed_route


def test_mass_drag_and_rotational_inertia_sensitivities() -> None:
    profile = RoadProfile([1_000.0], [-0.025])
    light = simulate_profile(profile, BicycleSystem(rider_mass_kg=50), time_step_s=0.05)
    heavy = simulate_profile(profile, BicycleSystem(rider_mass_kg=100), time_step_s=0.05)
    low_drag = simulate_profile(profile, BicycleSystem(drag_area_m2=0.35), time_step_s=0.05)
    high_drag = simulate_profile(profile, BicycleSystem(drag_area_m2=0.8), time_step_s=0.05)
    no_rotation = simulate_profile(
        profile, BicycleSystem(rotating_equivalent_mass_kg=0), time_step_s=0.05
    )
    rotation = simulate_profile(
        profile, BicycleSystem(rotating_equivalent_mass_kg=3), time_step_s=0.05
    )
    assert heavy.elapsed_time_s < light.elapsed_time_s  # less drag deceleration per real kg
    assert high_drag.elapsed_time_s > low_drag.elapsed_time_s
    assert rotation.elapsed_time_s != pytest.approx(no_rotation.elapsed_time_s, abs=1e-6)
    assert BicycleSystem(rotating_equivalent_mass_kg=0).effective_inertial_mass_kg == 90.0


def test_boundary_crossing_is_split_and_uses_new_grade() -> None:
    result = simulate_profile(
        RoadProfile([1.0, 100.0], [-0.2, 0.2]),
        initial_speed_m_s=10.0,
        time_step_s=1.0,
        stop_dwell_s=0.1,
    )
    boundary_index = result.distance_m.index(1.0)
    assert result.time_s[boundary_index] < 1.0
    assert result.speed_m_s[boundary_index + 1] < result.speed_m_s[boundary_index]


def test_multiple_short_segments_crossed_in_one_nominal_step() -> None:
    profile = RoadProfile([0.2] * 5 + [20.0], [-0.1, 0.1, -0.1, 0.1, -0.1, 0.0])
    result = simulate_profile(profile, initial_speed_m_s=10, time_step_s=1.0)
    for boundary in profile.segment_end_distances_m[:5]:
        assert any(distance == pytest.approx(boundary) for distance in result.distance_m)
    assert sum(time < 1.0 for time in result.time_s) >= 5


def test_route_end_time_is_interpolated() -> None:
    bicycle = BicycleSystem(
        rotating_equivalent_mass_kg=0,
        rolling_resistance_coefficient=0,
        drag_area_m2=1e-12,
    )
    result = simulate_profile(
        RoadProfile([5.0], [0.0]), bicycle, initial_speed_m_s=10.0, time_step_s=2.0
    )
    assert result.completed_route
    assert result.travelled_distance_m == 5.0
    assert result.elapsed_time_s == pytest.approx(0.5, abs=1e-10)


def test_threshold_stop_time_is_interpolated() -> None:
    bicycle = BicycleSystem(
        rotating_equivalent_mass_kg=0,
        rolling_resistance_coefficient=0.01,
        drag_area_m2=1e-12,
    )
    deceleration = -longitudinal_acceleration_m_s2(5.0, 0.0, bicycle, Environment())
    result = simulate_profile(
        RoadProfile([10_000.0], [0.0]),
        bicycle,
        initial_speed_m_s=5.0,
        stop_speed_m_s=1.0,
        stop_dwell_s=0.0,
        time_step_s=10.0,
    )
    assert result.elapsed_time_s == pytest.approx((5.0 - 1.0) / deceleration, rel=1e-9)
    assert result.speed_m_s[-1] == pytest.approx(1.0)


def test_outputs_are_finite_bounded_nonnegative_and_deterministic() -> None:
    profile = RoadProfile([50.0, 2.0, 70.0], [-0.03, 0.05, -0.01])
    first = simulate_profile(profile)
    second = simulate_profile(profile)
    assert first == second
    assert all(
        math.isfinite(value)
        for series in (first.time_s, first.distance_m, first.speed_m_s)
        for value in series
    )
    assert min(first.distance_m) >= 0
    assert max(first.distance_m) <= profile.total_length_m
    assert min(first.speed_m_s) >= 0
    assert all(after >= before for before, after in zip(first.distance_m, first.distance_m[1:]))


def test_time_step_refinement_is_stable() -> None:
    profile = RoadProfile([500.0, 20.0, 800.0], [-0.025, 0.015, -0.01])
    results = {
        step: simulate_profile(profile, time_step_s=step) for step in (0.2, 0.1, 0.05, 0.025)
    }
    assert all(result.completed_route for result in results.values())
    assert abs(results[0.05].elapsed_time_s - results[0.025].elapsed_time_s) < 0.15
    coarse_error = abs(results[0.2].elapsed_time_s - results[0.025].elapsed_time_s)
    fine_error = abs(results[0.05].elapsed_time_s - results[0.025].elapsed_time_s)
    assert fine_error < coarse_error
