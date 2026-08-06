from __future__ import annotations

import math

from .models import BicycleSystem, Environment, RoadProfile, SimulationResult


def grade_percent_to_ratio(grade_percent: float) -> float:
    """Convert a signed road-grade percentage to a dimensionless rise/run ratio."""
    value = float(grade_percent)
    if not math.isfinite(value):
        raise ValueError("grade_percent must be finite.")
    return value / 100.0


def grade_ratio_to_angle_rad(grade_ratio: float) -> float:
    """Convert a signed dimensionless rise/run grade to an angle in radians."""
    value = float(grade_ratio)
    if not math.isfinite(value):
        raise ValueError("grade_ratio must be finite.")
    if abs(value) > 0.5:
        raise ValueError("grade_ratio must be within [-0.5, 0.5].")
    return math.atan(value)


def longitudinal_acceleration_m_s2(
    speed_m_s: float,
    grade_ratio: float,
    bicycle: BicycleSystem,
    environment: Environment,
) -> float:
    """Return forward acceleration; negative ``grade_ratio`` means downhill.

    Forces use real translational mass.  Their sum is divided by effective
    inertial mass, which additionally includes optional rotational equivalent mass.
    Positive wind is a tailwind in the direction of travel.
    """
    bicycle.validate()
    environment.validate()
    speed = float(speed_m_s)
    if not math.isfinite(speed):
        raise ValueError("speed_m_s must be finite.")
    if speed < 0:
        raise ValueError("speed_m_s cannot be negative.")
    theta_rad = grade_ratio_to_angle_rad(grade_ratio)
    real_mass_kg = bicycle.translational_mass_kg
    effective_mass_kg = bicycle.effective_inertial_mass_kg

    gravity_force_n = -real_mass_kg * environment.gravity_m_s2 * math.sin(theta_rad)
    rolling_force_n = (
        -bicycle.rolling_resistance_coefficient
        * real_mass_kg
        * environment.gravity_m_s2
        * math.cos(theta_rad)
    )
    relative_air_speed_m_s = speed - environment.along_route_wind_m_s
    aerodynamic_force_n = (
        -0.5
        * environment.air_density_kg_m3
        * bicycle.drag_area_m2
        * relative_air_speed_m_s
        * abs(relative_air_speed_m_s)
    )
    return (gravity_force_n + rolling_force_n + aerodynamic_force_n) / effective_mass_kg


def _time_to_distance(
    speed: float, acceleration: float, distance: float, limit: float
) -> float | None:
    """Time to ``distance`` under constant acceleration, if reached within limit."""
    if distance <= 1e-12:
        return 0.0
    if abs(acceleration) < 1e-15:
        candidate = distance / speed if speed > 0 else math.inf
    else:
        discriminant = speed * speed + 2.0 * acceleration * distance
        if discriminant < 0:
            return None
        root = math.sqrt(max(0.0, discriminant))
        # The rationalized physical root avoids catastrophic cancellation when
        # acceleration is tiny compared with speed.
        denominator = speed + root
        candidate = 2.0 * distance / denominator if denominator > 0 else math.inf
    return max(0.0, candidate) if candidate <= limit + 1e-12 else None


def _below_threshold_increment(
    v0: float, acceleration: float, duration: float, threshold: float
) -> float:
    v1 = max(0.0, v0 + acceleration * duration)
    if v0 <= threshold and v1 <= threshold:
        return duration
    if v0 > threshold and v1 < threshold:
        return duration - (threshold - v0) / acceleration
    if v0 < threshold and v1 > threshold:
        return (threshold - v0) / acceleration
    return 0.0


def _duration_for_below_increment(
    v0: float, acceleration: float, threshold: float, needed: float, limit: float
) -> float:
    """Invert below-threshold duration within a linear-speed substep."""
    if v0 <= threshold:
        return needed
    crossing = (threshold - v0) / acceleration
    return crossing + needed


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
    """Simulate passive motion with event-split, constant-acceleration substeps.

    Nominal time steps are split exactly at segment boundaries, route end, zero
    speed, the stop-dwell event and max time.  A speed at or below
    ``stop_speed_m_s`` accumulates dwell time; exceeding it resets the dwell.
    """
    bicycle.validate()
    environment.validate()
    controls = {
        "initial_speed_m_s": initial_speed_m_s,
        "time_step_s": time_step_s,
        "stop_speed_m_s": stop_speed_m_s,
        "stop_dwell_s": stop_dwell_s,
        "max_time_s": max_time_s,
    }
    for name, raw in controls.items():
        if not math.isfinite(float(raw)):
            raise ValueError(f"{name} must be finite.")
    if initial_speed_m_s <= 0:
        raise ValueError("initial_speed_m_s must be positive.")
    if time_step_s <= 0:
        raise ValueError("time_step_s must be positive.")
    if stop_speed_m_s < 0:
        raise ValueError("stop_speed_m_s cannot be negative.")
    if stop_dwell_s < 0:
        raise ValueError("stop_dwell_s cannot be negative.")
    if max_time_s <= 0:
        raise ValueError("max_time_s must be positive.")

    times = [0.0]
    distances = [0.0]
    speeds = [float(initial_speed_m_s)]
    below_s = 0.0
    epsilon = 1e-12

    if initial_speed_m_s <= stop_speed_m_s and stop_dwell_s == 0:
        return SimulationResult(
            tuple(times), tuple(distances), tuple(speeds), False, "speed_threshold"
        )

    while times[-1] < max_time_s - epsilon:
        nominal_remaining = min(time_step_s, max_time_s - times[-1])
        while nominal_remaining > epsilon:
            time = times[-1]
            distance = distances[-1]
            speed = speeds[-1]
            if distance >= profile.total_length_m - epsilon:
                distances[-1] = profile.total_length_m
                return SimulationResult(
                    tuple(times), tuple(distances), tuple(speeds), True, "route_end"
                )

            index = profile.segment_index_at_distance(distance)
            boundary = profile.segment_end_distances_m[index]
            acceleration = longitudinal_acceleration_m_s2(
                speed, profile.grade_ratios[index], bicycle, environment
            )
            # Rolling resistance may not reverse a stationary bicycle.  A genuine
            # positive net force (descent/tailwind) may start it again during dwell.
            if speed <= epsilon and acceleration < 0:
                acceleration = 0.0

            duration = nominal_remaining
            zero_time = -speed / acceleration if acceleration < 0 and speed > 0 else math.inf
            duration = min(duration, zero_time)
            boundary_time = _time_to_distance(speed, acceleration, boundary - distance, duration)
            hits_boundary = boundary_time is not None
            if hits_boundary:
                duration = boundary_time

            below_increment = _below_threshold_increment(
                speed, acceleration, duration, stop_speed_m_s
            )
            if below_increment > 0 and below_s + below_increment >= stop_dwell_s - epsilon:
                needed = max(0.0, stop_dwell_s - below_s)
                duration = _duration_for_below_increment(
                    speed, acceleration, stop_speed_m_s, needed, duration
                )
                new_speed = max(0.0, speed + acceleration * duration)
                new_distance = min(
                    profile.total_length_m,
                    distance + speed * duration + 0.5 * acceleration * duration * duration,
                )
                times.append(time + duration)
                distances.append(max(distance, new_distance))
                speeds.append(new_speed)
                return SimulationResult(
                    tuple(times), tuple(distances), tuple(speeds), False, "speed_threshold"
                )

            new_speed = max(0.0, speed + acceleration * duration)
            new_distance = distance + speed * duration + 0.5 * acceleration * duration * duration
            if hits_boundary:
                new_distance = boundary
            new_distance = min(profile.total_length_m, max(distance, new_distance))
            times.append(time + duration)
            distances.append(new_distance)
            speeds.append(new_speed)

            if speed <= stop_speed_m_s and new_speed <= stop_speed_m_s:
                below_s += duration
            elif speed > stop_speed_m_s and new_speed < stop_speed_m_s:
                below_s = _below_threshold_increment(speed, acceleration, duration, stop_speed_m_s)
            elif new_speed > stop_speed_m_s:
                below_s = 0.0

            nominal_remaining -= duration
            if duration <= epsilon:
                # Exact boundary: the index lookup selects the following segment.
                # If this is route end, the next loop returns immediately.
                if boundary >= profile.total_length_m - epsilon:
                    distances[-1] = profile.total_length_m
                    return SimulationResult(
                        tuple(times), tuple(distances), tuple(speeds), True, "route_end"
                    )
                distances[-1] = math.nextafter(boundary, math.inf)

        if times[-1] >= max_time_s - epsilon:
            break

    return SimulationResult(tuple(times), tuple(distances), tuple(speeds), False, "max_time")
