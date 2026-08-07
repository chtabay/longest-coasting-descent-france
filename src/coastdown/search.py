"""Coasting-route construction and the regional search.

A candidate is a sequence of directed edges the rider can enter legally, one
after another, without pedalling and without braking.  It ends at the first of:

* the qualified stop (speed at or below the threshold for the dwell time);
* no admissible continuation exists;
* a legal constraint blocks every continuation;
* a bend requires more lateral acceleration than the scenario allows, which a
  braking-free rider cannot obey.

**Cycle rule.** Each way piece may be traversed at most once per route, in at
most one direction.  Without it a rider could shuttle back and forth across a
dip and accumulate unbounded time, which would measure the search's patience
rather than the terrain.  The rule is deliberately stricter than "no repeated
directed edge", because traversing a piece in both directions is the same
shuttle.

**Exactness.** The search is a depth-first enumeration under that rule, so it is
exhaustive within an expansion budget.  The budget exists because a dense
village network can branch faster than it dies, and a truncated search that says
so is worth more than an unbounded one that never returns.  Every seed records
whether its budget was exhausted; the validation subgraphs are small enough that
it never is, which is where exactness against brute force is demonstrated.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from .curvature import (
    DEFAULT_LATERAL_SCENARIO,
    BendObservation,
    TurnConstraintResult,
    bend_radii,
    evaluate_turn_constraint,
)
from .graph import GraphEdge, RoutableGraph
from .models import BicycleSystem, Environment, RoadProfile, SimulationResult
from .physics import simulate_profile
from .sampling import SamplePoint
from .surfaces import SurfaceClass, coefficient

INITIAL_SPEED_M_S = 15.0 / 3.6
STOP_SPEED_M_S = 0.30
STOP_DWELL_S = 2.0
MAX_SIMULABLE_GRADE_RATIO = 0.5


@dataclass(frozen=True)
class EdgeProfile:
    """One graph edge reduced to what the simulator and the bend check need."""

    edge_id: str
    segment_travelled_m: tuple[float, ...]
    segment_grade_ratio: tuple[float, ...]
    segment_rolling_resistance: tuple[float, ...]
    segment_horizontal_m: tuple[float, ...]
    horizontal_length_m: float
    net_dz_m: float
    ascent_m: float
    descent_m: float
    start_elevation_m: float
    end_elevation_m: float
    bends: tuple[BendObservation, ...]
    surface_class: SurfaceClass
    simulable: bool
    reason: str


def build_edge_profile(
    edge: GraphEdge,
    samples: Sequence[SamplePoint],
    elevations: Sequence[float],
    *,
    crr_variant: str = "central",
    max_grade_ratio: float = MAX_SIMULABLE_GRADE_RATIO,
) -> EdgeProfile:
    """Turn geometry plus elevations into simulator input, or explain why not."""
    if edge.surface_class is SurfaceClass.UNSUITABLE:
        return _unusable(edge, "surface class carries no rolling-resistance scenario")
    if len(samples) != len(elevations) or len(samples) < 2:
        return _unusable(edge, "geometry and elevation samples do not line up")
    if any(not math.isfinite(value) for value in elevations):
        return _unusable(edge, "terrain model has no value at one or more sample points")

    crr = coefficient(edge.surface_class, crr_variant)
    travelled: list[float] = []
    grades: list[float] = []
    horizontal: list[float] = []
    changes: list[float] = []
    for (start, start_z), (end, end_z) in zip(
        zip(samples, elevations), zip(samples[1:], elevations[1:])
    ):
        dx = math.hypot(end.x_m - start.x_m, end.y_m - start.y_m)
        if dx <= 1e-9:
            continue
        dz = end_z - start_z
        grade = dz / dx
        if abs(grade) > max_grade_ratio:
            return _unusable(
                edge,
                f"segment grade {grade:+.3f} exceeds the simulator bound "
                f"{max_grade_ratio}; the terrain model does not describe this roadway",
            )
        travelled.append(math.hypot(dx, dz))
        grades.append(grade)
        horizontal.append(dx)
        changes.append(dz)
    if not travelled:
        return _unusable(edge, "the edge collapses to zero length")

    bends = bend_radii(
        [sample.chainage_m for sample in samples],
        [sample.x_m for sample in samples],
        [sample.y_m for sample in samples],
        [sample.longitude for sample in samples],
        [sample.latitude for sample in samples],
    )
    return EdgeProfile(
        edge_id=edge.edge_id,
        segment_travelled_m=tuple(travelled),
        segment_grade_ratio=tuple(grades),
        segment_rolling_resistance=tuple([crr] * len(travelled)),
        segment_horizontal_m=tuple(horizontal),
        horizontal_length_m=math.fsum(horizontal),
        net_dz_m=math.fsum(changes),
        ascent_m=math.fsum(value for value in changes if value > 0),
        descent_m=-math.fsum(value for value in changes if value < 0),
        start_elevation_m=float(elevations[0]),
        end_elevation_m=float(elevations[-1]),
        bends=bends,
        surface_class=edge.surface_class,
        simulable=True,
        reason="",
    )


def _unusable(edge: GraphEdge, reason: str) -> EdgeProfile:
    return EdgeProfile(
        edge_id=edge.edge_id,
        segment_travelled_m=(),
        segment_grade_ratio=(),
        segment_rolling_resistance=(),
        segment_horizontal_m=(),
        horizontal_length_m=0.0,
        net_dz_m=0.0,
        ascent_m=0.0,
        descent_m=0.0,
        start_elevation_m=math.nan,
        end_elevation_m=math.nan,
        bends=(),
        surface_class=edge.surface_class,
        simulable=False,
        reason=reason,
    )


def concatenate(profiles: Sequence[EdgeProfile]) -> RoadProfile:
    lengths: list[float] = []
    grades: list[float] = []
    resistance: list[float] = []
    for profile in profiles:
        lengths.extend(profile.segment_travelled_m)
        grades.extend(profile.segment_grade_ratio)
        resistance.extend(profile.segment_rolling_resistance)
    return RoadProfile(lengths, grades, resistance)


@dataclass(frozen=True)
class RouteCandidate:
    seed_edge_id: str
    edge_ids: tuple[str, ...]
    start_offset_m: float
    elapsed_time_s: float
    moving_time_s: float
    stationary_time_s: float
    distance_m: float
    horizontal_length_m: float
    net_dz_m: float
    descent_m: float
    ascent_m: float
    start_elevation_m: float
    end_elevation_m: float
    max_speed_m_s: float
    mean_speed_m_s: float
    stop_reason: str
    termination: str
    turn: TurnConstraintResult
    surface_metres: tuple[tuple[str, float], ...]
    surface_is_assumed_m: float
    edges_used: int


def _speed_lookup(result: SimulationResult):
    distances = result.distance_m
    speeds = result.speed_m_s

    def speed_at(distance: float) -> float | None:
        if distance < distances[0] or distance > distances[-1]:
            return None
        low, high = 0, len(distances) - 1
        while low < high - 1:
            middle = (low + high) // 2
            if distances[middle] <= distance:
                low = middle
            else:
                high = middle
        span = distances[high] - distances[low]
        if span <= 0:
            return speeds[low]
        fraction = (distance - distances[low]) / span
        return speeds[low] + fraction * (speeds[high] - speeds[low])

    return speed_at


def evaluate_route(
    graph: RoutableGraph,
    profiles: dict[str, EdgeProfile],
    edge_ids: Sequence[str],
    *,
    seed_edge_id: str,
    start_offset_m: float = 0.0,
    bicycle: BicycleSystem | None = None,
    environment: Environment | None = None,
    initial_speed_m_s: float = INITIAL_SPEED_M_S,
    time_step_s: float = 0.05,
    lateral_scenario: str = DEFAULT_LATERAL_SCENARIO,
    termination: str = "qualified_stop",
) -> RouteCandidate:
    """Simulate a finished route once, end to end, for its authoritative metrics."""
    chain = [profiles[edge_id] for edge_id in edge_ids]
    profile = concatenate(chain)
    result = simulate_profile(
        profile,
        bicycle or BicycleSystem(),
        environment or Environment(),
        initial_speed_m_s=initial_speed_m_s,
        time_step_s=time_step_s,
        stop_speed_m_s=STOP_SPEED_M_S,
        stop_dwell_s=STOP_DWELL_S,
    )

    # Bends are placed on the route's own chainage so the speed the simulation
    # predicts can be read at each one.
    speed_at = _speed_lookup(result)
    offset = 0.0
    travelled_offset = 0.0
    bends: list[BendObservation] = []
    for item in chain:
        for bend in item.bends:
            # Convert horizontal chainage inside the edge to travelled distance.
            fraction = bend.chainage_m / item.horizontal_length_m if item.horizontal_length_m else 0
            position = travelled_offset + fraction * math.fsum(item.segment_travelled_m)
            bends.append(BendObservation(position, bend.radius_m, bend.longitude, bend.latitude))
        offset += item.horizontal_length_m
        travelled_offset += math.fsum(item.segment_travelled_m)
    turn = evaluate_turn_constraint(bends, speed_at, scenario=lateral_scenario)

    surface: dict[str, float] = {}
    assumed = 0.0
    for edge_id, item in zip(edge_ids, chain):
        surface[item.surface_class.value] = (
            surface.get(item.surface_class.value, 0.0) + item.horizontal_length_m
        )
        if graph.edges[edge_id].surface_is_assumed:
            assumed += item.horizontal_length_m

    return RouteCandidate(
        seed_edge_id=seed_edge_id,
        edge_ids=tuple(edge_ids),
        start_offset_m=start_offset_m,
        elapsed_time_s=result.elapsed_time_s,
        moving_time_s=result.moving_time_s,
        stationary_time_s=result.stationary_time_s,
        distance_m=result.travelled_distance_m,
        horizontal_length_m=math.fsum(item.horizontal_length_m for item in chain),
        net_dz_m=math.fsum(item.net_dz_m for item in chain),
        descent_m=math.fsum(item.descent_m for item in chain),
        ascent_m=math.fsum(item.ascent_m for item in chain),
        start_elevation_m=chain[0].start_elevation_m,
        end_elevation_m=chain[-1].end_elevation_m,
        max_speed_m_s=max(result.speed_m_s),
        mean_speed_m_s=(
            result.travelled_distance_m / result.elapsed_time_s
            if result.elapsed_time_s > 0
            else 0.0
        ),
        stop_reason=result.stop_reason,
        termination=termination,
        turn=turn,
        surface_metres=tuple(sorted(surface.items())),
        surface_is_assumed_m=assumed,
        edges_used=len(chain),
    )


@dataclass
class SearchBudget:
    max_expansions: int = 20_000
    max_edges_per_route: int = 400
    exhausted: bool = False
    expansions: int = 0


def search_from_edge(
    graph: RoutableGraph,
    profiles: dict[str, EdgeProfile],
    seed_edge_id: str,
    *,
    bicycle: BicycleSystem | None = None,
    environment: Environment | None = None,
    initial_speed_m_s: float = INITIAL_SPEED_M_S,
    lateral_scenario: str = DEFAULT_LATERAL_SCENARIO,
    budget: SearchBudget | None = None,
    keep_best: int = 3,
) -> tuple[list[RouteCandidate], SearchBudget]:
    """Enumerate coasting routes that begin at the start of ``seed_edge_id``.

    Only the best few routes per seed are kept: the enumeration is exhaustive but
    a seed can produce thousands of prefixes of the same descent, and keeping
    them all would drown the ranking in near-duplicates.
    """
    machine = bicycle or BicycleSystem()
    air = environment or Environment()
    limits = budget or SearchBudget()
    seed = profiles.get(seed_edge_id)
    if seed is None or not seed.simulable:
        return [], limits

    # Terminated routes are kept as (approximate time, termination, path) and
    # only the survivors are simulated end to end. Re-simulating the whole route
    # at every termination made the regional search quadratic in route length
    # for results that were then discarded.
    finished: list[tuple[float, str, list[str]]] = []
    stack: list[tuple[list[str], frozenset[tuple[int, int]], float, float]] = [
        ([seed_edge_id], frozenset({_piece(graph, seed_edge_id)}), initial_speed_m_s, 0.0)
    ]

    def finish(path: list[str], elapsed: float, termination: str) -> None:
        finished.append((elapsed, termination, path))
        if len(finished) > keep_best * 8:
            finished.sort(key=lambda item: -item[0])
            del finished[keep_best:]

    while stack:
        if limits.expansions >= limits.max_expansions:
            limits.exhausted = True
            break
        path, used, entry_speed, elapsed = stack.pop()
        limits.expansions += 1
        current = profiles[path[-1]]

        outcome = simulate_profile(
            RoadProfile(
                current.segment_travelled_m,
                current.segment_grade_ratio,
                current.segment_rolling_resistance,
            ),
            machine,
            air,
            initial_speed_m_s=max(entry_speed, 1e-6),
            stop_speed_m_s=STOP_SPEED_M_S,
            stop_dwell_s=STOP_DWELL_S,
        )
        total = elapsed + outcome.elapsed_time_s
        if outcome.stop_reason != "route_end":
            finish(path, total, "qualified_stop")
            continue

        exit_speed = outcome.speed_m_s[-1]
        if exit_speed <= STOP_SPEED_M_S:
            finish(path, total, "qualified_stop")
            continue

        if len(path) >= limits.max_edges_per_route:
            finish(path, total, "route_length_cap")
            continue

        continuations = [
            candidate
            for candidate in graph.continuations(path[-1])
            if _piece(graph, candidate) not in used
            and profiles.get(candidate) is not None
            and profiles[candidate].simulable
        ]
        if not continuations:
            blocked = graph.continuations(path[-1])
            finish(path, total, "no_admissible_continuation" if blocked else "network_end")
            continue
        for candidate in continuations:
            stack.append(
                (
                    [*path, candidate],
                    used | {_piece(graph, candidate)},
                    exit_speed,
                    total,
                )
            )

    finished.sort(key=lambda item: -item[0])
    best = [
        evaluate_route(
            graph,
            profiles,
            path,
            seed_edge_id=seed_edge_id,
            bicycle=machine,
            environment=air,
            initial_speed_m_s=initial_speed_m_s,
            lateral_scenario=lateral_scenario,
            termination=termination,
        )
        for _, termination, path in finished[:keep_best]
    ]
    best.sort(key=lambda item: -item.elapsed_time_s)
    return best, limits


def _piece(graph: RoutableGraph, edge_id: str) -> tuple[int, int]:
    edge = graph.edges[edge_id]
    return (edge.osm_way_id, edge.piece_index)


def brute_force_routes(
    graph: RoutableGraph,
    profiles: dict[str, EdgeProfile],
    seed_edge_id: str,
    *,
    initial_speed_m_s: float = INITIAL_SPEED_M_S,
) -> list[RouteCandidate]:
    """Every admissible route from a seed, with no budget and no pruning.

    Deliberately naive.  It exists so the regional engine can be checked against
    an implementation that shares none of its shortcuts.
    """
    results: list[RouteCandidate] = []
    machine = BicycleSystem()
    air = Environment()

    def walk(path: list[str], used: set[tuple[int, int]], entry_speed: float) -> None:
        current = profiles[path[-1]]
        outcome = simulate_profile(
            RoadProfile(
                current.segment_travelled_m,
                current.segment_grade_ratio,
                current.segment_rolling_resistance,
            ),
            machine,
            air,
            initial_speed_m_s=max(entry_speed, 1e-6),
            stop_speed_m_s=STOP_SPEED_M_S,
            stop_dwell_s=STOP_DWELL_S,
        )
        if outcome.stop_reason != "route_end" or outcome.speed_m_s[-1] <= STOP_SPEED_M_S:
            results.append(
                evaluate_route(
                    graph, profiles, path, seed_edge_id=seed_edge_id, termination="qualified_stop"
                )
            )
            return
        nexts = [
            candidate
            for candidate in graph.continuations(path[-1])
            if _piece(graph, candidate) not in used
            and profiles.get(candidate) is not None
            and profiles[candidate].simulable
        ]
        if not nexts:
            results.append(
                evaluate_route(
                    graph,
                    profiles,
                    path,
                    seed_edge_id=seed_edge_id,
                    termination="no_admissible_continuation",
                )
            )
            return
        for candidate in nexts:
            walk([*path, candidate], used | {_piece(graph, candidate)}, outcome.speed_m_s[-1])

    seed = profiles.get(seed_edge_id)
    if seed is None or not seed.simulable:
        return []
    walk([seed_edge_id], {_piece(graph, seed_edge_id)}, initial_speed_m_s)
    return results
