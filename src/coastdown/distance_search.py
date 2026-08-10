"""Route search under the definitive objective: maximum distance.

The Phase 2 engine in :mod:`coastdown.search` maximised elapsed time and is kept
unchanged, because the two rankings have to be shown side by side.  This module
is the engine for the question the study now asks:

    the greatest distance a 75 kg rider on a standard hybrid bicycle can cover
    from 15 km/h, never pedalling, until the definitive physical stop.

No condition is imposed on mean grade, minimum descent, mean speed, descent
share or duration.  A nearly level route may win if it genuinely rolls further.

Three properties make distance a better-behaved objective than time here.

*Distance is monotone along a path.*  Extending a route never shortens it, so a
prefix that has already stopped can be abandoned outright.  What distance is
*not* is separable edge by edge: the bend envelope is measured across the joined
geometry, so a turn spanning a junction couples the edges on either side of it.
An accumulator summed from per-edge runs is therefore not the objective, and the
search does not use one — every expansion re-simulates the whole path.  That is
quadratic in path length and much slower than accumulating, and it is the price
of pruning on the published quantity rather than on an approximation of it.

*The run ends where physics ends it.*  There is no 0.30 m/s threshold to sit
just above, so the near-equilibrium creep that dominated the time ranking earns
nothing: crawling adds seconds, not metres.

*Braking is not a choice.*  The optimiser never selects an amount; it only ever
respects a speed envelope built from the geometry.

The cycle rule from Phase 2 is retained unchanged and is part of the definition
of a trip: each physical way piece is traversed at most once, whichever
direction.  It forbids repeated roundabout laps, out-and-back on one road,
shuttling in a dip, and any cycle whose only purpose is to accumulate distance.
Genuinely distinct crossings of a sector by different physical ways remain
available.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace

from .coasting import (
    DEFAULT_BRAKE_DECELERATION_M_S2,
    DEFAULT_ZERO_SPEED_EPSILON_M_S,
    CoastingRun,
    simulate_coasting,
)
from .curvature import (
    DEFAULT_LATERAL_SCENARIO,
    LATERAL_LIMIT_SCENARIOS_M_S2,
    bend_radii,
    permitted_speed_m_s,
)
from .graph import RoutableGraph
from .models import BicycleSystem, Environment, RoadProfile
from .search import INITIAL_SPEED_M_S, EdgeProfile

MAX_BEND_SPEED_M_S = 200.0


def edge_bend_limits(
    profile: EdgeProfile, lateral_scenario: str = DEFAULT_LATERAL_SCENARIO
) -> tuple[tuple[float, float], ...]:
    """Bend speed limits of one edge, keyed by travelled distance inside it.

    Bend chainage is horizontal and the simulator works in travelled distance,
    so the two are related by the running ratio of 3D to plan length rather than
    assumed equal. On a 15 % grade the difference is about 1 %, which is small
    but free to get right.
    """
    limit = LATERAL_LIMIT_SCENARIOS_M_S2[lateral_scenario]
    if not profile.bends or not profile.segment_horizontal_m:
        return ()
    # Bend chainage is measured on the 5 m geometry; the simulator works in the
    # travelled distance of the 25 m profile, which is a shorter polyline. The
    # two are related by a fraction of the edge, never by equating absolute
    # chainages, which would drift along the edge.
    base_plan = max(1e-9, profile.bends[-1].chainage_m)
    for bend in profile.bends:
        base_plan = max(base_plan, bend.chainage_m)
    plan_total = max(base_plan, math.fsum(profile.segment_horizontal_m))
    travelled_total = math.fsum(profile.segment_travelled_m)

    def to_travelled(position: float) -> float:
        fraction = min(1.0, max(0.0, position / plan_total))
        return fraction * travelled_total

    return tuple(
        (
            to_travelled(bend.chainage_m),
            min(permitted_speed_m_s(bend.radius_m, limit), MAX_BEND_SPEED_M_S),
        )
        for bend in profile.bends
    )


def trim_edge_profile(profile: EdgeProfile, from_travelled_m: float) -> EdgeProfile:
    """Drop the leading part of an edge so a run can start inside it.

    Whole segments only. The production profile carries at most 25 m per
    segment, so that is the granularity at which a start point can be placed
    without rebuilding the elevation sampling.
    """
    if from_travelled_m <= 0:
        return profile
    # Remove every whole segment that fits inside the requested offset. The
    # comparison must be inclusive: an offset produced by start_offsets is a
    # cumulative segment sum, so `consumed + length` equals it to within
    # rounding, and an exclusive test removed one segment too few — a requested
    # 25 m offset moved the start by 0.00 m while the caller went on reporting a
    # gain from it.
    kept = 0
    consumed = 0.0
    for length in profile.segment_travelled_m:
        if consumed + length > from_travelled_m + 1e-6:
            break
        consumed += length
        kept += 1
    if kept >= len(profile.segment_travelled_m):
        raise ValueError("The start offset consumes the whole edge.")
    changes = [
        grade * plan
        for grade, plan in zip(
            profile.segment_grade_ratio[kept:], profile.segment_horizontal_m[kept:]
        )
    ]
    # Bends are keyed by PLAN chainage on the 5 m geometry, so they must be
    # rebased by the plan length removed, not by the travelled length. Leaving
    # them on the untrimmed frame displaced the whole speed envelope of every
    # in-edge start by the size of the trim.
    consumed_plan = math.fsum(profile.segment_horizontal_m[:kept])
    bends = tuple(
        replace(bend, chainage_m=bend.chainage_m - consumed_plan)
        for bend in profile.bends
        if bend.chainage_m >= consumed_plan
    )
    return EdgeProfile(
        edge_id=profile.edge_id,
        segment_travelled_m=profile.segment_travelled_m[kept:],
        segment_grade_ratio=profile.segment_grade_ratio[kept:],
        segment_rolling_resistance=profile.segment_rolling_resistance[kept:],
        segment_horizontal_m=profile.segment_horizontal_m[kept:],
        horizontal_length_m=math.fsum(profile.segment_horizontal_m[kept:]),
        net_dz_m=math.fsum(changes),
        ascent_m=math.fsum(value for value in changes if value > 0),
        descent_m=-math.fsum(value for value in changes if value < 0),
        start_elevation_m=profile.start_elevation_m
        + math.fsum(
            grade * plan
            for grade, plan in zip(
                profile.segment_grade_ratio[:kept], profile.segment_horizontal_m[:kept]
            )
        ),
        end_elevation_m=profile.end_elevation_m,
        bends=bends,
        surface_class=profile.surface_class,
        simulable=profile.simulable,
        reason=profile.reason,
    )


def route_bend_limits(
    graph: RoutableGraph,
    edge_ids: Sequence[str],
    chain: Sequence[EdgeProfile],
    lateral_scenario: str,
    start_offset_m: float = 0.0,
) -> tuple[tuple[float, float], ...]:
    """Bend speed limits measured across the whole route, not edge by edge.

    ``bend_radii`` needs a chord of geometry on both sides of a point, so it
    emits nothing within 15 m of an edge end. Ways are cut at every shared
    interior node — 974 of them on 502 admitted ways — so evaluating each edge
    in isolation leaves a blind band around every junction, exactly where a
    bicycle actually turns. Joining the 5 m geometry of the whole route first
    removes the blind band everywhere except its two outer ends.
    """
    limit = LATERAL_LIMIT_SCENARIOS_M_S2[lateral_scenario]
    horizontal: list[float] = []
    xs: list[float] = []
    ys: list[float] = []
    lons: list[float] = []
    lats: list[float] = []
    plan_offset = 0.0
    for position, edge_id in enumerate(edge_ids):
        samples = graph.edges[edge_id].samples
        skip = start_offset_m if position == 0 else 0.0
        first = True
        for sample in samples:
            if sample.chainage_m < skip - 1e-9:
                continue
            place = plan_offset + (sample.chainage_m - skip)
            # Consecutive edges share a node, so drop the duplicate point.
            if horizontal and place <= horizontal[-1] + 1e-9:
                continue
            horizontal.append(place)
            xs.append(sample.x_m)
            ys.append(sample.y_m)
            lons.append(sample.longitude)
            lats.append(sample.latitude)
            first = False
        if first:
            continue
        plan_offset = horizontal[-1]
    if len(horizontal) < 3:
        return ()

    # Two plan-length scales are in play and they are NOT interchangeable. The
    # joined chainage above is measured on the 5 m geometry; the simulator works
    # in the travelled distance of the 25 m production profile, whose polyline
    # cuts every corner and is therefore shorter. Mapping one onto the other by
    # absolute chainage lets the error accumulate — about 25 m, a whole segment,
    # by the end of a 4 km route — which silently shifts the entire speed
    # envelope downstream of the first junction. Each edge is therefore mapped
    # by its own fraction of its own length, so the drift cannot accumulate.
    edge_spans: list[tuple[float, float, float, float]] = []
    plan_cursor = 0.0
    travelled_cursor = 0.0
    for position, edge_id in enumerate(edge_ids):
        samples = graph.edges[edge_id].samples
        skip = start_offset_m if position == 0 else 0.0
        base_plan = max(1e-9, samples[-1].chainage_m - skip)
        item = chain[position]
        travelled = math.fsum(item.segment_travelled_m)
        edge_spans.append((plan_cursor, plan_cursor + base_plan, travelled_cursor, travelled))
        plan_cursor += base_plan
        travelled_cursor += travelled

    def to_travelled(position: float) -> float:
        for plan_start, plan_end, travelled_start, travelled_span in edge_spans:
            if position <= plan_end or plan_end == edge_spans[-1][1]:
                fraction = (position - plan_start) / max(1e-9, plan_end - plan_start)
                fraction = min(1.0, max(0.0, fraction))
                return travelled_start + fraction * travelled_span
        return travelled_cursor

    return tuple(
        (
            to_travelled(bend.chainage_m),
            min(permitted_speed_m_s(bend.radius_m, limit), MAX_BEND_SPEED_M_S),
        )
        for bend in bend_radii(horizontal, xs, ys, lons, lats)
    )


def concatenate_route(
    chain: Sequence[EdgeProfile], lateral_scenario: str
) -> tuple[RoadProfile, tuple[tuple[float, float], ...]]:
    lengths: list[float] = []
    grades: list[float] = []
    resistance: list[float] = []
    limits: list[tuple[float, float]] = []
    offset = 0.0
    for item in chain:
        for position, speed in edge_bend_limits(item, lateral_scenario):
            limits.append((offset + position, speed))
        lengths.extend(item.segment_travelled_m)
        grades.extend(item.segment_grade_ratio)
        resistance.extend(item.segment_rolling_resistance)
        offset += math.fsum(item.segment_travelled_m)
    return RoadProfile(lengths, grades, resistance), tuple(limits)


@dataclass(frozen=True)
class DistanceRoute:
    seed_edge_id: str
    edge_ids: tuple[str, ...]
    start_offset_m: float
    distance_m: float
    elapsed_time_s: float
    moving_time_s: float
    start_elevation_m: float
    end_elevation_m: float
    net_dz_m: float
    ascent_m: float
    descent_m: float
    mean_speed_m_s: float
    max_speed_m_s: float
    max_free_speed_m_s: float
    minimum_speed_before_stop_m_s: float
    braking_energy_j: float
    braking_distance_m: float
    active_constraints: int
    braking_substeps: int
    restart_count: int
    stop_reason: str
    termination: str
    distance_to_5kmh_m: float | None
    distance_to_1kmh_m: float | None
    distance_to_030ms_m: float | None
    surface_metres: tuple[tuple[str, float], ...]
    surface_is_assumed_m: float
    edges_used: int
    lateral_scenario: str
    braking_model: str


def simulate_path(
    graph: RoutableGraph,
    profiles: dict[str, EdgeProfile],
    edge_ids: Sequence[str],
    *,
    start_offset_m: float = 0.0,
    bicycle: BicycleSystem | None = None,
    environment: Environment | None = None,
    initial_speed_m_s: float = INITIAL_SPEED_M_S,
    time_step_s: float = 0.05,
    lateral_scenario: str = DEFAULT_LATERAL_SCENARIO,
    braking: str = "ideal",
    brake_deceleration_m_s2: float = DEFAULT_BRAKE_DECELERATION_M_S2,
    zero_speed_epsilon_m_s: float = DEFAULT_ZERO_SPEED_EPSILON_M_S,
) -> tuple[list[EdgeProfile], CoastingRun]:
    """Run one whole path under the authoritative joined-geometry envelope.

    **This is the single definition of what a path does.**  The search, the
    exhaustive oracle and the published evaluation all call it, so no decision
    can be taken on a quantity that differs from the one reported.

    That was not true before.  The walk chained per-edge simulations under
    ``edge_bend_limits``, which is blind within one chord of every junction,
    while the ranking published a run under ``route_bend_limits`` measured
    across the joined geometry.  The two disagree, so a branch could be dropped
    on a distance the study never publishes: on one seed the walk kept a route
    worth 159.3 m while a full enumeration found 1020.9 m.  Re-simulating the
    whole path at every expansion is quadratic in path length and much slower;
    correctness comes first, and a branch may be kept needlessly but must never
    be discarded wrongly.
    """
    chain = [profiles[edge_id] for edge_id in edge_ids]
    if start_offset_m > 0:
        chain[0] = trim_edge_profile(chain[0], start_offset_m)
    profile, _ = concatenate_route(chain, lateral_scenario)
    limits = route_bend_limits(graph, edge_ids, chain, lateral_scenario, start_offset_m)
    run = simulate_coasting(
        profile,
        bicycle or BicycleSystem(),
        environment or Environment(),
        initial_speed_m_s=initial_speed_m_s,
        time_step_s=time_step_s,
        bend_limits=limits,
        braking=braking,
        brake_deceleration_m_s2=brake_deceleration_m_s2,
        zero_speed_epsilon_m_s=zero_speed_epsilon_m_s,
    )
    return chain, run


def evaluate_distance_route(
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
    braking: str = "ideal",
    brake_deceleration_m_s2: float = DEFAULT_BRAKE_DECELERATION_M_S2,
    zero_speed_epsilon_m_s: float = DEFAULT_ZERO_SPEED_EPSILON_M_S,
    termination: str = "definitive_stop",
) -> DistanceRoute:
    """Simulate a finished route once, end to end, for its authoritative metrics."""
    chain, run = simulate_path(
        graph,
        profiles,
        edge_ids,
        start_offset_m=start_offset_m,
        bicycle=bicycle,
        environment=environment,
        initial_speed_m_s=initial_speed_m_s,
        time_step_s=time_step_s,
        lateral_scenario=lateral_scenario,
        braking=braking,
        brake_deceleration_m_s2=brake_deceleration_m_s2,
        zero_speed_epsilon_m_s=zero_speed_epsilon_m_s,
    )
    return _to_route(
        graph,
        chain,
        edge_ids,
        run,
        seed_edge_id=seed_edge_id,
        start_offset_m=start_offset_m,
        termination=termination,
        lateral_scenario=lateral_scenario,
        braking=braking,
    )


def _to_route(
    graph: RoutableGraph,
    chain: Sequence[EdgeProfile],
    edge_ids: Sequence[str],
    run: CoastingRun,
    *,
    seed_edge_id: str,
    start_offset_m: float,
    termination: str,
    lateral_scenario: str,
    braking: str,
) -> DistanceRoute:
    surface: dict[str, float] = {}
    assumed = 0.0
    for edge_id, item in zip(edge_ids, chain):
        surface[item.surface_class.value] = (
            surface.get(item.surface_class.value, 0.0) + item.horizontal_length_m
        )
        if graph.edges[edge_id].surface_is_assumed:
            assumed += item.horizontal_length_m
    diagnostics = dict(run.diagnostic_distances_m)
    distance = run.travelled_distance_m
    return DistanceRoute(
        seed_edge_id=seed_edge_id,
        edge_ids=tuple(edge_ids),
        start_offset_m=start_offset_m,
        distance_m=distance,
        elapsed_time_s=run.elapsed_time_s,
        moving_time_s=run.moving_time_s,
        start_elevation_m=chain[0].start_elevation_m,
        end_elevation_m=chain[-1].end_elevation_m,
        net_dz_m=math.fsum(item.net_dz_m for item in chain),
        ascent_m=math.fsum(item.ascent_m for item in chain),
        descent_m=math.fsum(item.descent_m for item in chain),
        mean_speed_m_s=distance / run.elapsed_time_s if run.elapsed_time_s > 0 else 0.0,
        max_speed_m_s=run.max_speed_m_s,
        max_free_speed_m_s=run.max_free_speed_m_s,
        minimum_speed_before_stop_m_s=run.minimum_speed_before_stop_m_s,
        braking_energy_j=run.braking_energy_j,
        braking_distance_m=run.braking_distance_m,
        active_constraints=run.active_constraint_count,
        braking_substeps=run.braking_substeps,
        restart_count=run.restart_count,
        stop_reason=run.stop_reason,
        termination=termination,
        distance_to_5kmh_m=diagnostics.get("5kmh"),
        distance_to_1kmh_m=diagnostics.get("1kmh"),
        distance_to_030ms_m=diagnostics.get("030ms"),
        surface_metres=tuple(sorted(surface.items())),
        surface_is_assumed_m=assumed,
        edges_used=len(chain),
        lateral_scenario=lateral_scenario,
        braking_model=braking,
    )


@dataclass
class DistanceBudget:
    max_expansions: int = 20_000
    max_edges_per_route: int = 400
    exhausted: bool = False
    expansions: int = 0


def _piece(graph: RoutableGraph, edge_id: str) -> tuple[int, int]:
    edge = graph.edges[edge_id]
    return (edge.osm_way_id, edge.piece_index)


# The per-edge run that used to drive the walk is deliberately gone. It applied
# `edge_bend_limits`, which is blind within one chord of every junction, so a
# chain of them disagreed with the published route evaluation and pruned on a
# quantity the study never reports. `simulate_path` is the only way a path is
# ever run now, and leaving a per-edge shortcut in the module would invite the
# same defect back.


def finished_paths(
    graph: RoutableGraph,
    profiles: dict[str, EdgeProfile],
    seed_edge_id: str,
    *,
    bicycle: BicycleSystem | None = None,
    environment: Environment | None = None,
    initial_speed_m_s: float = INITIAL_SPEED_M_S,
    lateral_scenario: str = DEFAULT_LATERAL_SCENARIO,
    braking: str = "ideal",
    zero_speed_epsilon_m_s: float = DEFAULT_ZERO_SPEED_EPSILON_M_S,
    start_offset_m: float = 0.0,
    budget: DistanceBudget | None = None,
    min_distance_m: float = 0.0,
    allow_cycles: bool = False,
) -> tuple[list[tuple[float, str, list[str]]], DistanceBudget]:
    """Every route the walk finishes, as (distance, termination, path).

    Depth-first under the cycle rule. Every expansion re-simulates the whole
    path through :func:`simulate_path`, so a branch is judged on exactly the
    distance that would be published for it. Nothing is pruned on an
    approximation of the objective, and nothing is pruned on an envelope other
    than the authoritative one.

    An edge that ends exactly at rest is not the end of the search: the next
    edge may be steep enough to restart the bicycle, and only the restart test
    at that boundary can say. Continuations are therefore explored from zero
    speed as well.

    Routes come back as bare tuples rather than :class:`DistanceRoute` records
    because the walk already knows each one's authoritative distance — it is the
    value it pruned on — and that is all a ranking needs. Building the full
    record re-simulates the path a second time, which is wasted on every route
    a caller is about to discard.

    ``min_distance_m`` drops finished routes below a caller-supplied floor. It
    acts on finished routes only and never prunes the walk, so it changes what
    is *reported*, never what is *explored*.

    ``allow_cycles`` changes the *problem*, not the engine's accuracy on it. The
    default is the Phase 2 trip definition: each physical way piece at most once,
    whichever direction. Setting it lifts that rule, so a route may lap a
    roundabout, run a road out and back, or shuttle in a dip. Termination is then
    left entirely to physics — over any closed cycle gravity nets to zero while
    rolling resistance and drag only remove energy, so repetition is
    self-limiting and a lapping route eventually stops. That argument assumes the
    windless reference environment; under a wind able to supply energy it does
    not hold and this mode has no termination guarantee.

    What is lost with the rule is the search's small branching factor. The tree
    grows fast enough that ``max_expansions`` will usually bind, and a result
    from an exhausted budget is a lower bound on the answer, not the answer.
    """
    machine = bicycle or BicycleSystem()
    air = environment or Environment()
    limits = budget or DistanceBudget()
    seed = profiles.get(seed_edge_id)
    if seed is None or not seed.simulable:
        return [], limits

    if start_offset_m > 0:
        # Fail early rather than silently walking an untrimmed seed.
        trim_edge_profile(seed, start_offset_m)

    finished: list[tuple[float, str, list[str]]] = []
    stack: list[tuple[list[str], frozenset[tuple[int, int]]]] = [
        ([seed_edge_id], frozenset({_piece(graph, seed_edge_id)}))
    ]

    def finish(path: list[str], distance: float, termination: str) -> None:
        # The floor is the only thing that discards a finished route here.
        # Truncating to a best-of-N would make the walk's output depend on the
        # order branches happen to be popped, which a caller assembling a global
        # ranking must not have to reason about.
        if distance < min_distance_m:
            return
        finished.append((distance, termination, path))

    while stack:
        if limits.expansions >= limits.max_expansions:
            limits.exhausted = True
            break
        path, used = stack.pop()
        limits.expansions += 1
        # The whole path is re-simulated under the authoritative envelope, so
        # the distance this branch is judged on is exactly the distance that
        # would be published for it.
        _, run = simulate_path(
            graph,
            profiles,
            path,
            start_offset_m=start_offset_m,
            bicycle=machine,
            environment=air,
            initial_speed_m_s=initial_speed_m_s,
            lateral_scenario=lateral_scenario,
            braking=braking,
            zero_speed_epsilon_m_s=zero_speed_epsilon_m_s,
        )
        total = run.travelled_distance_m
        if run.stop_reason != "route_end":
            finish(path, total, run.stop_reason)
            continue
        if len(path) >= limits.max_edges_per_route:
            finish(path, total, "route_length_cap")
            continue
        continuations = [
            candidate
            for candidate in graph.continuations(path[-1])
            if (allow_cycles or _piece(graph, candidate) not in used)
            and profiles.get(candidate) is not None
            and profiles[candidate].simulable
        ]
        if not continuations:
            blocked = graph.continuations(path[-1])
            finish(path, total, "no_admissible_continuation" if blocked else "network_end")
            continue
        for candidate in continuations:
            stack.append(([*path, candidate], used | {_piece(graph, candidate)}))

    finished.sort(key=lambda item: -item[0])
    return finished, limits


def search_distance_from_edge(
    graph: RoutableGraph,
    profiles: dict[str, EdgeProfile],
    seed_edge_id: str,
    *,
    bicycle: BicycleSystem | None = None,
    environment: Environment | None = None,
    initial_speed_m_s: float = INITIAL_SPEED_M_S,
    lateral_scenario: str = DEFAULT_LATERAL_SCENARIO,
    braking: str = "ideal",
    zero_speed_epsilon_m_s: float = DEFAULT_ZERO_SPEED_EPSILON_M_S,
    start_offset_m: float = 0.0,
    budget: DistanceBudget | None = None,
    keep_best: int | None = 2,
    min_distance_m: float = 0.0,
    allow_cycles: bool = False,
) -> tuple[list[DistanceRoute], DistanceBudget]:
    """:func:`finished_paths`, with the kept routes materialised in full."""
    machine = bicycle or BicycleSystem()
    air = environment or Environment()
    finished, limits = finished_paths(
        graph,
        profiles,
        seed_edge_id,
        bicycle=machine,
        environment=air,
        initial_speed_m_s=initial_speed_m_s,
        lateral_scenario=lateral_scenario,
        braking=braking,
        zero_speed_epsilon_m_s=zero_speed_epsilon_m_s,
        start_offset_m=start_offset_m,
        budget=budget,
        min_distance_m=min_distance_m,
        allow_cycles=allow_cycles,
    )
    best = [
        evaluate_distance_route(
            graph,
            profiles,
            path,
            seed_edge_id=seed_edge_id,
            start_offset_m=start_offset_m,
            bicycle=machine,
            environment=air,
            initial_speed_m_s=initial_speed_m_s,
            lateral_scenario=lateral_scenario,
            braking=braking,
            zero_speed_epsilon_m_s=zero_speed_epsilon_m_s,
            termination=termination,
        )
        for _, termination, path in (finished if keep_best is None else finished[:keep_best])
    ]
    best.sort(key=lambda item: -item.distance_m)
    return best, limits


def exhaustive_routes(
    graph: RoutableGraph,
    profiles: dict[str, EdgeProfile],
    seed_edge_id: str,
    *,
    initial_speed_m_s: float = INITIAL_SPEED_M_S,
    lateral_scenario: str = DEFAULT_LATERAL_SCENARIO,
    braking: str = "ideal",
    max_paths: int | None = None,
    allow_cycles: bool = False,
) -> list[DistanceRoute]:
    """Every admissible route from a seed, enumerated with no pruning at all.

    The oracle the optimised engine is checked against.  It applies **no**
    budget, **no** keep-best truncation, **no** dominance and **no** ordering
    heuristic: it extends a path for as long as the graph admits a continuation
    and the bicycle physically reaches the end of what it has, and it evaluates
    every path it produces.

    It shares the *evaluation* with the engine, which is unavoidable and
    intended — that evaluation is the definition of the objective — but it
    shares no pruning key, because it prunes nothing.  Agreement between the two
    is therefore evidence about the engine's search, not a tautology.

    ``max_paths`` is a safety stop for accidental use on a large subgraph. It
    raises rather than truncating: a silently truncated oracle would be worse
    than no oracle.
    """
    seed = profiles.get(seed_edge_id)
    if seed is None or not seed.simulable:
        return []
    machine = BicycleSystem()
    air = Environment()
    results: list[DistanceRoute] = []

    def evaluate(path: list[str], termination: str) -> None:
        if max_paths is not None and len(results) >= max_paths:
            raise RuntimeError(
                f"exhaustive_routes exceeded {max_paths} paths from {seed_edge_id}; "
                "the subgraph is too large for an unpruned oracle"
            )
        results.append(
            evaluate_distance_route(
                graph,
                profiles,
                path,
                seed_edge_id=seed_edge_id,
                bicycle=machine,
                environment=air,
                initial_speed_m_s=initial_speed_m_s,
                lateral_scenario=lateral_scenario,
                braking=braking,
                termination=termination,
            )
        )

    def walk(path: list[str], used: frozenset[tuple[int, int]]) -> None:
        _, run = simulate_path(
            graph,
            profiles,
            path,
            bicycle=machine,
            environment=air,
            initial_speed_m_s=initial_speed_m_s,
            lateral_scenario=lateral_scenario,
            braking=braking,
        )
        if run.stop_reason != "route_end":
            evaluate(path, run.stop_reason)
            return
        nexts = [
            candidate
            for candidate in graph.continuations(path[-1])
            if (allow_cycles or _piece(graph, candidate) not in used)
            and profiles.get(candidate) is not None
            and profiles[candidate].simulable
        ]
        if not nexts:
            blocked = graph.continuations(path[-1])
            evaluate(path, "no_admissible_continuation" if blocked else "network_end")
            return
        # A path that can continue is still a route in its own right: the rider
        # may simply have reached the end of the road they were on. Recording it
        # as well as its extensions is what makes the enumeration complete.
        evaluate(path, "prefix")
        for candidate in nexts:
            walk([*path, candidate], used | {_piece(graph, candidate)})

    walk([seed_edge_id], frozenset({_piece(graph, seed_edge_id)}))
    return results


def brute_force_distance_routes(
    graph: RoutableGraph,
    profiles: dict[str, EdgeProfile],
    seed_edge_id: str,
    *,
    initial_speed_m_s: float = INITIAL_SPEED_M_S,
    lateral_scenario: str = DEFAULT_LATERAL_SCENARIO,
    braking: str = "ideal",
) -> list[DistanceRoute]:
    """Backwards-compatible name for :func:`exhaustive_routes`."""
    return exhaustive_routes(
        graph,
        profiles,
        seed_edge_id,
        initial_speed_m_s=initial_speed_m_s,
        lateral_scenario=lateral_scenario,
        braking=braking,
    )


def distinct_longest(routes: Sequence[DistanceRoute], limit: int) -> list[DistanceRoute]:
    """Longest routes that are not sub-paths of an already-kept one."""
    ordered = sorted(routes, key=lambda item: -item.distance_m)
    kept: list[DistanceRoute] = []
    covered: list[set[str]] = []
    for route in ordered:
        edges = set(route.edge_ids)
        if any(edges <= seen or seen <= edges for seen in covered):
            continue
        kept.append(route)
        covered.append(edges)
        if len(kept) >= limit:
            break
    return kept


# --- one worker process holds the graph, and the seeds come to it ------------
#
# The walk is embarrassingly parallel: `finished_paths` is a pure function of
# (graph, profiles, seed), and no seed can observe another. What is not free is
# shipping the graph — so it is sent once per worker as an initialiser argument
# (15.5 MB, 0.22 s to load for the Oisans) rather than once per task.

_WORKER: dict[str, object] = {}


def _load_worker(graph: RoutableGraph, profiles: dict[str, EdgeProfile]) -> None:
    _WORKER["graph"] = graph
    _WORKER["profiles"] = profiles


def _walk_one(task: tuple[str, float, int, int, dict]) -> tuple[list, int, bool]:
    seed, floor, max_expansions, max_edges, kwargs = task
    finished, budget = finished_paths(
        _WORKER["graph"],  # type: ignore[arg-type]
        _WORKER["profiles"],  # type: ignore[arg-type]
        seed,
        budget=DistanceBudget(max_expansions=max_expansions, max_edges_per_route=max_edges),
        min_distance_m=floor,
        **kwargs,
    )
    return finished, budget.expansions, budget.exhausted


def _ranked_candidates(
    candidates: Sequence[tuple[float, str, str, list[str]]],
    limit: int,
) -> list[tuple[float, str, str, list[str]]]:
    """:func:`distinct_longest` on bare (distance, seed, termination, path)."""
    ordered = sorted(candidates, key=lambda item: -item[0])
    kept: list[tuple[float, str, str, list[str]]] = []
    covered: list[set[str]] = []
    for candidate in ordered:
        edges = set(candidate[3])
        if any(edges <= seen or seen <= edges for seen in covered):
            continue
        kept.append(candidate)
        covered.append(edges)
        if len(kept) >= limit:
            break
    return kept


def global_longest(
    graph: RoutableGraph,
    profiles: dict[str, EdgeProfile],
    seeds: Sequence[str],
    limit: int,
    *,
    budget_factory: Callable[[], DistanceBudget] | None = None,
    on_seed: Callable[[str, DistanceBudget], None] | None = None,
    workers: int = 1,
    chunk_size: int = 8,
    **search_kwargs,
) -> list[DistanceRoute]:
    """The exact global ranking, without holding every route of every seed.

    Keeping the *n* best routes of each seed and ranking the union does not give
    the global top *n*: one seed can legitimately own several of the leading
    places, and a per-seed cap silently drops the rest. Keeping everything is
    exact but unbounded.

    This keeps a running floor instead. Seeds are searched in turn; after each,
    the current ranking is recomputed and its last distance becomes the floor
    for the seeds still to come. The floor only ever rises, and a route rejected
    against an earlier, lower floor was already shorter than a floor that has
    since grown — so it could not have entered the final ranking. Every route
    that survives is evaluated; the ones discarded never needed to be.

    The one thing the floor must not do is start above the answer, so it starts
    at whatever the caller asked for (zero by default) and is raised only by
    routes actually found.

    ``workers`` spreads the walk over processes. It changes the runtime and
    nothing else, and the reason it is safe is worth stating rather than
    trusting.

    Seeds are dispatched in chunks and their results collected **in submission
    order**, so the pool is assembled exactly as the sequential loop assembles
    it. That matters because :func:`_ranked_candidates` sorts by distance alone
    and Python's sort is stable: two routes of identical length are separated by
    their position in the pool, so a pool built in arrival order could rank ties
    differently from one built in seed order.

    The floor is then held fixed for the whole parallel run rather than rising
    seed by seed, which makes it *lower* than the sequential floor, never higher.
    A lower floor records more routes, never fewer, and the extra ones are all
    shorter than the final ranking's last entry — they can neither enter the
    ranking nor eliminate a member of it, since elimination only ever comes from
    a longer route. The ranking is therefore identical, and a test asserts it.
    """
    floor = float(search_kwargs.pop("min_distance_m", 0.0))
    pool: list[tuple[float, str, str, list[str]]] = []
    template = budget_factory() if budget_factory is not None else DistanceBudget()
    seeds = list(seeds)

    def absorb(seed: str, found: list, expansions: int, exhausted: bool) -> None:
        nonlocal floor, pool
        if on_seed is not None:
            on_seed(seed, DistanceBudget(expansions=expansions, exhausted=exhausted))
        if not found:
            return
        pool.extend((distance, seed, termination, path) for distance, termination, path in found)

    def tighten() -> None:
        nonlocal floor, pool
        ranking = _ranked_candidates(pool, limit)
        if len(ranking) >= limit:
            floor = max(floor, ranking[-1][0])
            # Anything under the new floor can no longer reach the ranking.
            pool = [candidate for candidate in pool if candidate[0] >= floor]

    if workers > 1 and len(seeds) > 1:
        import concurrent.futures

        with concurrent.futures.ProcessPoolExecutor(
            max_workers=workers,
            initializer=_load_worker,
            initargs=(graph, profiles),
        ) as pool_executor:
            # Every seed is submitted at once rather than batch by batch. A
            # batch boundary is a barrier, and the walk's cost per seed is wildly
            # uneven — a handful of seeds dominate an otherwise trivial region —
            # so every barrier idles most of the pool waiting for one straggler.
            #
            # The floor is therefore fixed for the whole run instead of rising
            # between batches. That records more routes, never fewer, and the
            # extra ones are shorter than the ranking's last entry: they can
            # neither enter it nor eliminate a member of it. The pool stays small
            # in practice — the entire paved region finishes 6 554 routes.
            tasks = [
                (
                    seed,
                    floor,
                    template.max_expansions,
                    template.max_edges_per_route,
                    search_kwargs,
                )
                for seed in seeds
            ]
            # `map` yields in submission order, which is what keeps the pool
            # identical to the one the sequential loop builds.
            for seed, (found, expansions, exhausted) in zip(
                seeds, pool_executor.map(_walk_one, tasks, chunksize=chunk_size)
            ):
                absorb(seed, found, expansions, exhausted)
    else:
        for seed in seeds:
            found, budget = finished_paths(
                graph,
                profiles,
                seed,
                budget=budget_factory() if budget_factory is not None else DistanceBudget(),
                min_distance_m=floor,
                **search_kwargs,
            )
            absorb(seed, found, budget.expansions, budget.exhausted)
            tighten()
    evaluation_kwargs = {
        key: value
        for key, value in search_kwargs.items()
        if key not in {"budget", "keep_best", "max_expansions", "allow_cycles"}
    }
    return [
        evaluate_distance_route(
            graph,
            profiles,
            path,
            seed_edge_id=seed,
            termination=termination,
            **evaluation_kwargs,
        )
        for _, seed, termination, path in _ranked_candidates(pool, limit)
    ]


class StartPointStudy:
    """Best in-edge start offset per seed, evaluating each search exactly once.

    The baseline is measured with the SAME procedure as the candidates, at
    offset zero. Comparing a candidate search against a ranked route's distance
    manufactured the whole gain once reported: a ranked route is a *distinct*
    route, while ``search_distance_from_edge(keep_best=1)`` returns the seed's
    own best route, which is a different and usually longer one. On the two
    seeds once published, the difference between those two numbers was exactly
    the "gain" reported (4494.85 - 4178.98 = 315.87 m).

    The arithmetic here is unchanged; only the number of times it is performed.
    The answer depends on the *seed*, not on the route, and ranked routes share
    seeds heavily — a whole regional top ten can start on one edge, in which
    case the naive version runs the identical study ten times. It also
    re-measured offset zero for every pass and re-evaluated at the fine step
    every offset it had already evaluated at the coarse one.

    Every result is memoised on ``(seed, offset)``, and both passes read the
    same cache. No offset is dropped and no comparison is approximated: each
    pass still scans its own full offset set, so the numbers are identical to
    the uncached study by construction rather than by hope.

    Zero gain is a *measurement*, never an assumption. Starting later means
    restarting at the initial speed from the new point, so discarding an
    unfavourable prefix — a rise, an early bend that costs speed — genuinely can
    extend the total. The optimiser is written so that it can say so.
    """

    def __init__(
        self,
        graph: RoutableGraph,
        profiles: dict[str, EdgeProfile],
        *,
        budget_factory: Callable[[], DistanceBudget] | None = None,
        **search_kwargs,
    ) -> None:
        self.graph = graph
        self.profiles = profiles
        self._budget_factory = budget_factory or DistanceBudget
        self._search_kwargs = search_kwargs
        self._distance: dict[tuple[str, float], float | None] = {}
        self._best: dict[tuple[str, float], tuple[float, float]] = {}
        self.searches = 0
        self.cache_hits = 0

    def distance_at(self, seed_id: str, offset: float) -> float | None:
        """Distance of the seed's best route when it starts ``offset`` into it.

        ``None`` means the offset yields no answer at all — it consumes the
        whole edge, or the walk ran out of budget. An unanswered offset is
        skipped, never treated as a zero.
        """
        key = (seed_id, offset)
        if key in self._distance:
            self.cache_hits += 1
            return self._distance[key]
        if offset > 0:
            try:
                trim_edge_profile(self.profiles[seed_id], offset)
            except ValueError:
                self._distance[key] = None
                return None
        found, budget = search_distance_from_edge(
            self.graph,
            self.profiles,
            seed_id,
            start_offset_m=offset,
            budget=self._budget_factory(),
            keep_best=1,
            **self._search_kwargs,
        )
        self.searches += 1
        value = None if (budget.exhausted or not found) else found[0].distance_m
        self._distance[key] = value
        return value

    def optimise(self, seed_id: str, step_m: float) -> tuple[float, float]:
        """Best offset for one seed at one step, and the distance it gains."""
        key = (seed_id, step_m)
        if key in self._best:
            return self._best[key]
        reference = self.distance_at(seed_id, 0.0)
        if reference is None:
            self._best[key] = (0.0, 0.0)
            return self._best[key]
        best_offset, best_distance = 0.0, reference
        for offset in start_offsets(self.profiles[seed_id], step_m):
            if offset <= 0:
                continue
            value = self.distance_at(seed_id, offset)
            if value is not None and value > best_distance:
                best_distance = value
                best_offset = offset
        self._best[key] = (best_offset, best_distance - reference)
        return self._best[key]

    def searches_without_caching(self, seeds: Sequence[str], steps: Sequence[float]) -> int:
        """What the uncached study would have cost, for the record."""
        return sum(
            1 + sum(1 for offset in start_offsets(self.profiles[seed_id], step_m) if offset > 0)
            for seed_id in seeds
            for step_m in steps
        )


def start_offsets(profile: EdgeProfile, step_m: float) -> tuple[float, ...]:
    """Candidate in-edge start offsets, on segment boundaries.

    Screening uses a coarse step and finalists a fine one, which is the shape a
    national run needs: the coarse pass bounds where the gain can be, the fine
    pass finds it.
    """
    offsets: list[float] = [0.0]
    running = 0.0
    for length in itertools.islice(
        profile.segment_travelled_m, 0, len(profile.segment_travelled_m) - 1
    ):
        running += length
        if running - offsets[-1] >= step_m - 1e-9:
            offsets.append(running)
    return tuple(offsets)
