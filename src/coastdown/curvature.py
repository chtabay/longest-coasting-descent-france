"""Local curvature and the lateral-acceleration limit of a braking-free descent.

The reference event forbids braking, so the longitudinal simulation is only
credible where the bicycle can physically hold the road at the speed it predicts.
A 20 m radius hairpin taken at 60 km/h needs about 1.4 g laterally, which no
bicycle tyre delivers: such a route is not a fast descent, it is a crash.

Curvature is estimated from the circle through three points separated by a
declared arc length rather than from consecutive vertices.  OSM geometry carries
metre-level digitising noise, and consecutive-vertex curvature turns that noise
into imaginary 5 m radii on a straight road.  Using a chord long enough to
dominate the noise, and reporting the radius only where the turn is real, keeps
the constraint honest in the direction that matters: it must not invent bends.

The limits below are scenario bounds on what a rider will actually accept, not
tyre-friction limits.  Dry asphalt can exceed 0.8 g in a controlled test, but a
loaded hybrid bicycle on an unknown mountain road, without braking and with a
rider who has no reason to trust the surface, is a different question.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

GRAVITY_M_S2 = 9.80665

# Scenario name -> sustained lateral acceleration a rider is assumed to accept.
LATERAL_LIMIT_SCENARIOS_M_S2: dict[str, float] = {
    # Cautious: an unfamiliar road, no braking available, comfort-led.
    "conservative": 0.20 * GRAVITY_M_S2,
    # Central assumption for the ranking.
    "nominal": 0.35 * GRAVITY_M_S2,
    # Committed riding on a surface known to be good.
    "committed": 0.50 * GRAVITY_M_S2,
}
DEFAULT_LATERAL_SCENARIO = "nominal"

# Below this radius a turn is treated as a real bend rather than digitising
# noise; above it, no practical speed is constrained anyway.
MAX_CONSTRAINING_RADIUS_M = 400.0


@dataclass(frozen=True)
class BendObservation:
    chainage_m: float
    radius_m: float
    longitude: float
    latitude: float


@dataclass(frozen=True)
class TurnConstraintResult:
    scenario: str
    lateral_limit_m_s2: float
    critical_chainage_m: float | None
    critical_radius_m: float | None
    speed_at_critical_m_s: float | None
    required_lateral_m_s2: float | None
    permitted_speed_m_s: float | None
    margin_m_s2: float | None
    violated: bool
    bend_count: int
    tightest_radius_m: float | None
    # Distance along the route at which the rider would first have to brake.
    # A braking-free run ends there, so this is what bounds the admissible time.
    first_violation_distance_m: float | None = None
    first_violation_radius_m: float | None = None


def circumradius_m(
    first: tuple[float, float], second: tuple[float, float], third: tuple[float, float]
) -> float:
    """Radius of the circle through three planar points; ``inf`` when collinear."""
    ax, ay = first
    bx, by = second
    cx, cy = third
    side_a = math.hypot(bx - cx, by - cy)
    side_b = math.hypot(ax - cx, ay - cy)
    side_c = math.hypot(ax - bx, ay - by)
    if min(side_a, side_b, side_c) <= 1e-9:
        return math.inf
    # Twice the signed triangle area.
    cross = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)
    if abs(cross) <= 1e-12:
        return math.inf
    return (side_a * side_b * side_c) / (2.0 * abs(cross))


def bend_radii(
    chainage_m: Sequence[float],
    x_m: Sequence[float],
    y_m: Sequence[float],
    longitude: Sequence[float],
    latitude: Sequence[float],
    *,
    chord_m: float = 15.0,
) -> tuple[BendObservation, ...]:
    """Radius of curvature at every point that carries a real bend.

    The three points are taken at least ``chord_m`` apart along the roadway, so
    the estimate reflects the road's geometry rather than the spacing of its
    digitised vertices.
    """
    if chord_m <= 0:
        raise ValueError("chord_m must be positive.")
    count = len(chainage_m)
    if count < 3:
        return ()
    observations: list[BendObservation] = []
    for index in range(count):
        back = index
        while back > 0 and chainage_m[index] - chainage_m[back] < chord_m:
            back -= 1
        forward = index
        while forward < count - 1 and chainage_m[forward] - chainage_m[index] < chord_m:
            forward += 1
        if back == index or forward == index:
            continue
        if chainage_m[index] - chainage_m[back] < chord_m * 0.5:
            continue
        if chainage_m[forward] - chainage_m[index] < chord_m * 0.5:
            continue
        radius = circumradius_m(
            (x_m[back], y_m[back]), (x_m[index], y_m[index]), (x_m[forward], y_m[forward])
        )
        if not math.isfinite(radius) or radius > MAX_CONSTRAINING_RADIUS_M:
            continue
        observations.append(
            BendObservation(chainage_m[index], radius, longitude[index], latitude[index])
        )
    return tuple(observations)


def permitted_speed_m_s(radius_m: float, lateral_limit_m_s2: float) -> float:
    """Speed at which ``v^2 / R`` reaches the accepted lateral acceleration."""
    if radius_m <= 0:
        raise ValueError("radius_m must be positive.")
    return math.sqrt(lateral_limit_m_s2 * radius_m)


def evaluate_turn_constraint(
    bends: Sequence[BendObservation],
    speed_at_chainage,
    *,
    scenario: str = DEFAULT_LATERAL_SCENARIO,
) -> TurnConstraintResult:
    """Find the bend that most exceeds the accepted lateral acceleration.

    ``speed_at_chainage`` maps a chainage to the longitudinal speed the
    simulation predicts there.  The critical bend is the one with the largest
    required-minus-permitted lateral acceleration, which is the bend that would
    force the rider to brake.
    """
    limit = LATERAL_LIMIT_SCENARIOS_M_S2[scenario]
    if not bends:
        return TurnConstraintResult(
            scenario, limit, None, None, None, None, None, None, False, 0, None
        )
    worst = None
    worst_excess = -math.inf
    for bend in bends:
        speed = speed_at_chainage(bend.chainage_m)
        if speed is None:
            continue
        required = speed * speed / bend.radius_m
        excess = required - limit
        if excess > worst_excess:
            worst_excess = excess
            worst = (bend, speed, required)
    tightest = min(bend.radius_m for bend in bends)
    first_violation: BendObservation | None = None
    for bend in sorted(bends, key=lambda item: item.chainage_m):
        speed = speed_at_chainage(bend.chainage_m)
        if speed is not None and speed * speed / bend.radius_m > limit:
            first_violation = bend
            break
    if worst is None:
        return TurnConstraintResult(
            scenario, limit, None, None, None, None, None, None, False, len(bends), tightest
        )
    bend, speed, required = worst
    return TurnConstraintResult(
        scenario=scenario,
        lateral_limit_m_s2=limit,
        critical_chainage_m=bend.chainage_m,
        critical_radius_m=bend.radius_m,
        speed_at_critical_m_s=speed,
        required_lateral_m_s2=required,
        permitted_speed_m_s=permitted_speed_m_s(bend.radius_m, limit),
        margin_m_s2=limit - required,
        violated=required > limit,
        bend_count=len(bends),
        tightest_radius_m=tightest,
        first_violation_distance_m=(
            first_violation.chainage_m if first_violation is not None else None
        ),
        first_violation_radius_m=(
            first_violation.radius_m if first_violation is not None else None
        ),
    )
