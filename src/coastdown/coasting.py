"""Coasting to the definitive physical stop, under a constrained-speed envelope.

Phase 2 maximised elapsed time and found a degenerate optimum: a 734 m route
dropping 1.8 m, winning because a nearly balanced bicycle creeps for a long
while.  The objective is now distance, and the run no longer ends at an
arbitrary 0.30 m/s threshold.  It ends where physics ends it.

**Definitive stop.**  The run ends when speed reaches zero and no spontaneous
forward acceleration can restart the bicycle from rest.  At rest the
aerodynamic term vanishes, so what remains is gravity against rolling
resistance::

    a(0) > 0   <=>   -sin(theta) > Crr * cos(theta)   <=>   grade < -Crr

Because ``a(v)`` decreases with speed — drag only ever opposes motion —
``a(0)`` is the largest acceleration available on a segment.  So if a segment
could restart the bicycle, the bicycle could never have stopped on it in the
first place: it would have decayed towards a terminal speed instead of reaching
zero.  **A mid-segment zero is therefore always definitive, and only a zero
landing on a segment boundary can be followed by a restart**, decided by the
segment about to be entered.  The bicycle never rolls backwards; a negative
``a(0)`` at rest means the run is over, not that it reverses.

The condition is evaluated by calling the acceleration function itself rather
than by testing ``grade < -Crr`` directly, so that a non-zero along-route wind —
which does exert a force at rest — is handled by the same rule.

**Braking.**  No braking is discretionary and the search never chooses an
amount.  A maximum-speed envelope comes from the bend radii of the fine
geometry, and the bicycle follows its natural dynamics wherever they respect it.
Where they would not, exactly enough energy is removed to respect it, under one
of two representations:

``ideal``
    energy is removed at the constraint itself, an instantaneous clamp.
``anticipated``
    the bicycle brakes ahead of the constraint at a fixed, declared
    deceleration, which is what a rider can actually do.  A backward pass gives
    the admissible speed at every point.

**The two are equivalent for distance, and the reason is structural.**  Both
leave the constraint at the same place and at the same speed, so the state that
determines everything downstream is identical and the rest of the run cannot
differ.  The braking *energy* differs between them, but that figure is
bookkeeping: it only records how much speed had to be removed, and carrying more
speed into a constraint simply means more to destroy.  It is not a discriminator
between the models and must not be read as one.

The single exception is a constraint the anticipated model never reaches,
because braking early on a rising approach can stop the bicycle short.  That is
a genuine difference in distance, and it is why both models are still computed
for the ranked routes rather than assumed equal.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field

from .models import BicycleSystem, Environment, RoadProfile
from .physics import DEFAULT_BICYCLE, DEFAULT_ENVIRONMENT, longitudinal_acceleration_m_s2

# Speeds at which a diagnostic distance is recorded, fastest first.
DIAGNOSTIC_SPEEDS_M_S: tuple[tuple[str, float], ...] = (
    ("5kmh", 5.0 / 3.6),
    ("1kmh", 1.0 / 3.6),
    ("030ms", 0.30),
)

# Speed below which the bicycle is treated as at rest. The restart test is then
# applied. It is a numerical device, not a physical threshold: the ranking must
# be shown to be insensitive to it, which tests/test_phase3_distance.py checks.
DEFAULT_ZERO_SPEED_EPSILON_M_S = 1.0e-6

# Deterministic deceleration for the anticipated-braking representation. A
# hybrid bicycle on dry asphalt can exceed this; a loaded rider on an unknown
# mountain road choosing to shed speed early cannot be assumed to use more.
DEFAULT_BRAKE_DECELERATION_M_S2 = 1.5

BRAKING_MODELS = ("none", "ideal", "anticipated")


@dataclass(frozen=True)
class ZeroSpeedEvent:
    distance_m: float
    time_s: float
    restarted: bool
    next_grade_ratio: float | None
    acceleration_at_rest_m_s2: float | None


@dataclass
class CoastingRun:
    time_s: list[float] = field(default_factory=list)
    distance_m: list[float] = field(default_factory=list)
    speed_m_s: list[float] = field(default_factory=list)
    stop_reason: str = ""
    completed_route: bool = False
    braking_energy_j: float = 0.0
    braking_distance_m: float = 0.0
    # Integration substeps during which the envelope bound the speed. It is a
    # measure of solver work, not of the road: it scales with the time step and
    # must never be published as "how many constraints were active".
    braking_substeps: int = 0
    # Distinct profile segments whose speed the envelope actually reduced. This
    # is the count of constraints that bound, and it is scale-free.
    binding_segments: frozenset[int] = frozenset()
    max_free_speed_m_s: float = 0.0
    zero_events: tuple[ZeroSpeedEvent, ...] = ()
    diagnostic_distances_m: tuple[tuple[str, float | None], ...] = ()
    moving_time_s: float = 0.0

    @property
    def travelled_distance_m(self) -> float:
        return self.distance_m[-1]

    @property
    def elapsed_time_s(self) -> float:
        return self.time_s[-1]

    @property
    def max_speed_m_s(self) -> float:
        return max(self.speed_m_s)

    @property
    def active_constraint_count(self) -> int:
        """Number of distinct segments whose speed the envelope reduced."""
        return len(self.binding_segments)

    @property
    def restart_count(self) -> int:
        return sum(1 for event in self.zero_events if event.restarted)

    @property
    def minimum_speed_before_stop_m_s(self) -> float:
        """Lowest speed reached strictly before the final point.

        Zero at the end is the stop itself and says nothing; what matters for
        reading a run is how close it came to stopping on the way.
        """
        interior = self.speed_m_s[:-1]
        return min(interior) if interior else self.speed_m_s[-1]


def segment_speed_limits(
    profile: RoadProfile,
    bend_limits: Sequence[tuple[float, float]],
) -> tuple[float, ...]:
    """Per-segment maximum speed from (travelled distance, speed limit) pairs.

    Constraints are resolved onto the segment that contains them, so the
    envelope has the same granularity as the production profile. Segments carry
    at most 25 m, which is finer than the distance over which a bend's own
    geometry varies.
    """
    ends = profile.segment_end_distances_m
    limits = [math.inf] * len(ends)
    for distance, speed in bend_limits:
        if not math.isfinite(speed) or speed < 0:
            raise ValueError("A bend speed limit must be finite and non-negative.")
        index = profile.segment_index_at_distance(min(max(distance, 0.0), profile.total_length_m))
        limits[index] = min(limits[index], speed)
    return tuple(limits)


def braking_allowance(
    profile: RoadProfile,
    segment_limits: Sequence[float],
    brake_deceleration_m_s2: float,
) -> tuple[float, ...]:
    """Admissible entry speed per segment under anticipated braking.

    Backward recurrence, in the squared speed so it stays linear::

        allow[n]   = segment_limits[n]
        allow[i]   = min(segment_limits[i], sqrt(allow[i+1]^2 + 2 a L_i))

    which is the fastest a rider may enter segment ``i`` while still being able
    to shed enough speed, at ``a``, to satisfy every constraint downstream.
    """
    if brake_deceleration_m_s2 <= 0:
        raise ValueError("brake_deceleration_m_s2 must be positive.")
    lengths = profile.segment_lengths_m
    count = len(lengths)
    allowance = [math.inf] * count
    downstream = math.inf
    for index in range(count - 1, -1, -1):
        reachable = (
            math.inf
            if math.isinf(downstream)
            else math.sqrt(downstream * downstream + 2.0 * brake_deceleration_m_s2 * lengths[index])
        )
        allowance[index] = min(segment_limits[index], reachable)
        downstream = allowance[index]
    return tuple(allowance)


def _allowed_speed(
    profile: RoadProfile,
    allowance: Sequence[float],
    segment_limits: Sequence[float],
    index: int,
    distance_m: float,
    brake_deceleration_m_s2: float,
) -> float:
    """Admissible speed at a point inside a segment, interpolated in v^2."""
    limit = segment_limits[index]
    ends = profile.segment_end_distances_m
    exit_allowance = allowance[index + 1] if index + 1 < len(allowance) else math.inf
    if math.isinf(exit_allowance):
        return limit
    remaining = max(0.0, ends[index] - distance_m)
    reachable = math.sqrt(
        exit_allowance * exit_allowance + 2.0 * brake_deceleration_m_s2 * remaining
    )
    return min(limit, reachable)


def simulate_coasting(
    profile: RoadProfile,
    bicycle: BicycleSystem = DEFAULT_BICYCLE,
    environment: Environment = DEFAULT_ENVIRONMENT,
    *,
    initial_speed_m_s: float,
    time_step_s: float = 0.05,
    bend_limits: Sequence[tuple[float, float]] = (),
    braking: str = "ideal",
    brake_deceleration_m_s2: float = DEFAULT_BRAKE_DECELERATION_M_S2,
    zero_speed_epsilon_m_s: float = DEFAULT_ZERO_SPEED_EPSILON_M_S,
    max_time_s: float = 12 * 3600,
) -> CoastingRun:
    """Roll until the route ends or the bicycle definitively stops.

    ``initial_speed_m_s`` may be zero: a route continued from an edge that ended
    at rest starts here, and the restart test decides whether it moves at all.
    """
    bicycle.validate()
    environment.validate()
    if braking not in BRAKING_MODELS:
        raise ValueError(f"braking must be one of {BRAKING_MODELS}.")
    if initial_speed_m_s < 0:
        raise ValueError("initial_speed_m_s cannot be negative.")
    if time_step_s <= 0:
        raise ValueError("time_step_s must be positive.")
    if zero_speed_epsilon_m_s <= 0:
        raise ValueError("zero_speed_epsilon_m_s must be positive.")

    limits = (
        segment_speed_limits(profile, bend_limits)
        if bend_limits and braking != "none"
        else tuple([math.inf] * len(profile.grade_ratios))
    )
    allowance = (
        braking_allowance(profile, limits, brake_deceleration_m_s2)
        if braking == "anticipated"
        else limits
    )

    run = CoastingRun()
    binding: set[int] = set()
    run.time_s.append(0.0)
    run.distance_m.append(0.0)
    run.speed_m_s.append(float(initial_speed_m_s))
    zero_events: list[ZeroSpeedEvent] = []
    diagnostics: dict[str, float | None] = {name: None for name, _ in DIAGNOSTIC_SPEEDS_M_S}
    epsilon = 1e-12
    free_speed = float(initial_speed_m_s)

    def note_diagnostics(before: float, after: float, start: float, end: float) -> None:
        """Record the distance at which the run first drops through a level."""
        for name, level in DIAGNOSTIC_SPEEDS_M_S:
            if diagnostics[name] is not None:
                continue
            if before > level >= after:
                span = before - after
                fraction = 0.0 if span <= 0 else (before - level) / span
                diagnostics[name] = start + fraction * (end - start)
            elif before <= level:
                diagnostics[name] = start

    def finish(reason: str, completed: bool) -> CoastingRun:
        run.binding_segments = frozenset(binding)
        run.stop_reason = reason
        run.completed_route = completed
        run.zero_events = tuple(zero_events)
        run.diagnostic_distances_m = tuple(
            (name, diagnostics[name]) for name, _ in DIAGNOSTIC_SPEEDS_M_S
        )
        run.max_free_speed_m_s = free_speed
        return run

    note_diagnostics(math.inf, float(initial_speed_m_s), 0.0, 0.0)

    while run.time_s[-1] < max_time_s - epsilon:
        distance = run.distance_m[-1]
        speed = run.speed_m_s[-1]
        if distance >= profile.total_length_m - epsilon:
            run.distance_m[-1] = profile.total_length_m
            return finish("route_end", True)

        index = profile.segment_index_at_distance(distance)
        grade = profile.grade_ratios[index]
        crr = (
            None
            if profile.segment_rolling_resistance is None
            else profile.segment_rolling_resistance[index]
        )
        acceleration = longitudinal_acceleration_m_s2(speed, grade, bicycle, environment, crr)

        # --- at rest: the definitive-stop test --------------------------------
        if speed <= zero_speed_epsilon_m_s:
            at_rest = longitudinal_acceleration_m_s2(0.0, grade, bicycle, environment, crr)
            restarted = at_rest > 0.0
            zero_events.append(ZeroSpeedEvent(distance, run.time_s[-1], restarted, grade, at_rest))
            if not restarted:
                run.speed_m_s[-1] = 0.0
                return finish("definitive_stop", False)
            speed = 0.0
            acceleration = at_rest

        boundary = profile.segment_end_distances_m[index]
        duration = time_step_s
        if acceleration < 0 and speed > 0:
            duration = min(duration, -speed / acceleration)
        boundary_time = _time_to_distance(speed, acceleration, boundary - distance, duration)
        hits_boundary = boundary_time is not None
        if hits_boundary:
            duration = boundary_time
        duration = min(duration, max_time_s - run.time_s[-1])
        if duration <= epsilon:
            # Sitting exactly on a boundary with no progress: step past it so the
            # next iteration reads the following segment.
            if boundary >= profile.total_length_m - epsilon:
                run.distance_m[-1] = profile.total_length_m
                return finish("route_end", True)
            run.distance_m[-1] = math.nextafter(boundary, math.inf)
            continue

        new_speed = max(0.0, speed + acceleration * duration)
        new_distance = distance + speed * duration + 0.5 * acceleration * duration * duration
        if hits_boundary:
            new_distance = boundary
        new_distance = min(profile.total_length_m, max(distance, new_distance))
        free_speed = max(free_speed, new_speed)

        # --- constrained braking ---------------------------------------------
        if braking != "none":
            ceiling = (
                _allowed_speed(
                    profile, allowance, limits, index, new_distance, brake_deceleration_m_s2
                )
                if braking == "anticipated"
                else limits[index]
            )
            if new_speed > ceiling:
                effective = bicycle.effective_inertial_mass_kg
                run.braking_energy_j += (
                    0.5 * effective * (new_speed * new_speed - ceiling * ceiling)
                )
                run.braking_distance_m += new_distance - distance
                run.braking_substeps += 1
                binding.add(index)
                new_speed = ceiling

        note_diagnostics(speed, new_speed, distance, new_distance)
        if new_speed > zero_speed_epsilon_m_s or speed > zero_speed_epsilon_m_s:
            run.moving_time_s += duration
        run.time_s.append(run.time_s[-1] + duration)
        run.distance_m.append(new_distance)
        run.speed_m_s.append(new_speed)

    return finish("max_time", False)


def _time_to_distance(
    speed: float, acceleration: float, distance: float, limit: float
) -> float | None:
    """Time to cover ``distance`` under constant acceleration, within ``limit``."""
    if distance <= 1e-12:
        return 0.0
    if abs(acceleration) < 1e-15:
        candidate = distance / speed if speed > 0 else math.inf
    else:
        discriminant = speed * speed + 2.0 * acceleration * distance
        if discriminant < 0:
            return None
        root = math.sqrt(max(0.0, discriminant))
        denominator = speed + root
        candidate = 2.0 * distance / denominator if denominator > 0 else math.inf
    return max(0.0, candidate) if candidate <= limit + 1e-12 else None


def can_restart_from_rest(
    grade_ratio: float,
    rolling_resistance_coefficient: float,
    bicycle: BicycleSystem = DEFAULT_BICYCLE,
    environment: Environment = DEFAULT_ENVIRONMENT,
) -> bool:
    """Whether a bicycle at rest on this grade rolls forward unaided."""
    return (
        longitudinal_acceleration_m_s2(
            0.0, grade_ratio, bicycle, environment, rolling_resistance_coefficient
        )
        > 0.0
    )
