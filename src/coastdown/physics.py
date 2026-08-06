from __future__ import annotations

import math

import numpy as np

from .models import BicycleSystem, Environment, RoadProfile, SimulationResult


def longitudinal_acceleration_m_s2(
    speed_m_s: float,
    grade: float,
    bicycle: BicycleSystem,
    environment: Environment,
) -> float:
    """Return acceleration along the route.

    Grade uses the road convention rise/run in travel direction: downhill is negative.
    Positive acceleration increases forward speed.
    """

    bicycle.validate()
    environment.validate()
    if speed_m_s < 0:
        raise ValueError("Forward speed cannot be negative.")

    theta_rad = math.atan(grade)
    mass_kg = bicycle.total_mass_kg

    # Downhill (negative theta) must create positive forward gravity acceleration.
    gravity_component = -environment.gravity_m_s2 * math.sin(theta_rad)

    # Rolling resistance opposes forward motion.
    rolling_component = (
        -bicycle.rolling_resistance_coefficient
        * environment.gravity_m_s2
        * math.cos(theta_rad)
    )

    relative_air_speed_m_s = speed_m_s - environment.along_route_wind_m_s
    aerodynamic_component = (
        -0.5
        * environment.air_density_kg_m3
        * bicycle.drag_area_m2
        * relative_air_speed_m_s
        * abs(relative_air_speed_m_s)
        / mass_kg
    )

    return gravity_component + rolling_component + aerodynamic_component


def simulate_profile(
    profile: RoadProfile,
    bicycle: BicycleSystem = BicycleSystem(),
    environment: Environment = Environment(),
    *,
    initial_speed_m_s: float = 15.0 / 3.6,
    time_step_s: float = 0.05,
    stop_speed_m_s: float = 0.30,
    stop_dwell_s: float = 2.0,
    max_time_s: float = 6 * 3600,
) -> SimulationResult:
    """Simulate passive bicycle motion over a piecewise-constant road profile.

    The baseline solver is intentionally explicit and inspectable. Codex Phase 0
    should audit and improve numerical behavior before geodata work begins.
    """

    bicycle.validate()
    environment.validate()
    if initial_speed_m_s <= 0:
        raise ValueError("Initial speed must be positive.")
    if time_step_s <= 0 or stop_speed_m_s < 0 or stop_dwell_s < 0 or max_time_s <= 0:
        raise ValueError("Simulation controls are invalid.")

    time_values = [0.0]
    distance_values = [0.0]
    speed_values = [float(initial_speed_m_s)]
    below_threshold_duration_s = 0.0

    while time_values[-1] < max_time_s:
        current_time_s = time_values[-1]
        current_distance_m = distance_values[-1]
        current_speed_m_s = speed_values[-1]

        if current_distance_m >= profile.total_length_m:
            return SimulationResult(
                np.asarray(time_values),
                np.asarray(distance_values),
                np.asarray(speed_values),
                True,
                "route_end",
            )

        grade = profile.grade_at_distance(current_distance_m)
        acceleration_m_s2 = longitudinal_acceleration_m_s2(
            current_speed_m_s, grade, bicycle, environment
        )

        next_speed_m_s = max(0.0, current_speed_m_s + acceleration_m_s2 * time_step_s)
        mean_speed_m_s = 0.5 * (current_speed_m_s + next_speed_m_s)
        next_distance_m = min(
            profile.total_length_m,
            current_distance_m + mean_speed_m_s * time_step_s,
        )
        next_time_s = current_time_s + time_step_s

        time_values.append(next_time_s)
        distance_values.append(next_distance_m)
        speed_values.append(next_speed_m_s)

        if next_speed_m_s <= stop_speed_m_s:
            below_threshold_duration_s += time_step_s
        else:
            below_threshold_duration_s = 0.0

        if below_threshold_duration_s >= stop_dwell_s:
            return SimulationResult(
                np.asarray(time_values),
                np.asarray(distance_values),
                np.asarray(speed_values),
                False,
                "speed_threshold",
            )

    return SimulationResult(
        np.asarray(time_values),
        np.asarray(distance_values),
        np.asarray(speed_values),
        False,
        "max_time",
    )
