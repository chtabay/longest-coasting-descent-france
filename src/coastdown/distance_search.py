"""Route search under the definitive objective: maximum distance.

The Phase 2 engine in :mod:`coastdown.search` maximised elapsed time and is kept
unchanged, because the two rankings have to be shown side by side.  This module
is the engine for the question the study now asks:

    the greatest distance a 75 kg rider on a standard hybrid bicycle can cover
    from 15 km/h, never pedalling, until the definitive physical stop.

No condition is imposed on mean grade, minimum descent, mean speed, descent
share or duration.  A nearly level route may win if it genuinely rolls further.

Three properties make distance a better-behaved objective than time here.

*Distance is exactly additive across edges.*  Elapsed time was not, because the
old stop rule carried dwell state across boundaries, so the depth-first
accumulator was an approximation that had to be re-checked at the end.  Summed
edge distances are the route distance, so the search prunes on the true value.

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
from collections.abc import Sequence
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
    chain = [profiles[edge_id] for edge_id in edge_ids]
    if start_offset_m > 0:
        chain[0] = trim_edge_profile(chain[0], start_offset_m)
    profile, _ = concatenate_route(chain, lateral_scenario)
    # The authoritative evaluation measures bends across the joined route, so a
    # turn spanning a junction is not lost between two edges.
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


def _run_edge(
    profile: EdgeProfile,
    entry_speed: float,
    machine: BicycleSystem,
    air: Environment,
    lateral_scenario: str,
    braking: str,
    zero_speed_epsilon_m_s: float,
) -> CoastingRun:
    road = RoadProfile(
        profile.segment_travelled_m,
        profile.segment_grade_ratio,
        profile.segment_rolling_resistance,
    )
    return simulate_coasting(
        road,
        machine,
        air,
        initial_speed_m_s=entry_speed,
        bend_limits=edge_bend_limits(profile, lateral_scenario),
        braking=braking,
        zero_speed_epsilon_m_s=zero_speed_epsilon_m_s,
    )


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
    keep_best: int = 2,
) -> tuple[list[DistanceRoute], DistanceBudget]:
    """Enumerate coasting routes from one seed and keep the longest.

    Depth-first under the cycle rule. Because distance adds exactly across
    edges, the accumulator carried down the search is the true objective, so a
    branch is never kept or dropped on an approximation.

    The walk applies the bend envelope edge by edge, which is blind within one
    chord of each junction; the kept routes are then re-evaluated with the
    envelope measured across the joined geometry. The walk is therefore mildly
    optimistic about bends near junctions, which is acceptable because braking
    barely moves distance at all — the two braking representations differ by
    nothing, and disabling the envelope entirely changes distance by well under
    a percent.

    An edge that ends exactly at rest is not the end of the search: the next
    edge may be steep enough to restart the bicycle, and only the restart test
    at that boundary can say. Continuations are therefore explored from zero
    speed as well.
    """
    machine = bicycle or BicycleSystem()
    air = environment or Environment()
    limits = budget or DistanceBudget()
    seed = profiles.get(seed_edge_id)
    if seed is None or not seed.simulable:
        return [], limits

    seed_profile = trim_edge_profile(seed, start_offset_m) if start_offset_m > 0 else seed
    local = dict(profiles)
    local[seed_edge_id] = seed_profile

    finished: list[tuple[float, str, list[str]]] = []
    stack: list[tuple[list[str], frozenset[tuple[int, int]], float, float]] = [
        ([seed_edge_id], frozenset({_piece(graph, seed_edge_id)}), initial_speed_m_s, 0.0)
    ]

    def finish(path: list[str], distance: float, termination: str) -> None:
        finished.append((distance, termination, path))
        if len(finished) > keep_best * 8:
            finished.sort(key=lambda item: -item[0])
            del finished[keep_best:]

    while stack:
        if limits.expansions >= limits.max_expansions:
            limits.exhausted = True
            break
        path, used, entry_speed, covered = stack.pop()
        limits.expansions += 1
        run = _run_edge(
            local[path[-1]],
            entry_speed,
            machine,
            air,
            lateral_scenario,
            braking,
            zero_speed_epsilon_m_s,
        )
        total = covered + run.travelled_distance_m
        if run.stop_reason != "route_end":
            finish(path, total, run.stop_reason)
            continue
        if len(path) >= limits.max_edges_per_route:
            finish(path, total, "route_length_cap")
            continue
        exit_speed = run.speed_m_s[-1]
        continuations = [
            candidate
            for candidate in graph.continuations(path[-1])
            if _piece(graph, candidate) not in used
            and local.get(candidate) is not None
            and local[candidate].simulable
        ]
        if not continuations:
            blocked = graph.continuations(path[-1])
            finish(path, total, "no_admissible_continuation" if blocked else "network_end")
            continue
        for candidate in continuations:
            stack.append(([*path, candidate], used | {_piece(graph, candidate)}, exit_speed, total))

    finished.sort(key=lambda item: -item[0])
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
        for _, termination, path in finished[:keep_best]
    ]
    best.sort(key=lambda item: -item.distance_m)
    return best, limits


def brute_force_distance_routes(
    graph: RoutableGraph,
    profiles: dict[str, EdgeProfile],
    seed_edge_id: str,
    *,
    initial_speed_m_s: float = INITIAL_SPEED_M_S,
    lateral_scenario: str = DEFAULT_LATERAL_SCENARIO,
    braking: str = "ideal",
) -> list[DistanceRoute]:
    """Every admissible route from a seed, with no budget and no pruning.

    Deliberately naive, and deliberately re-simulating the whole route at each
    leaf instead of accumulating: it shares none of the engine's shortcuts, so
    agreement between the two is evidence rather than tautology.
    """
    machine = BicycleSystem()
    air = Environment()
    results: list[DistanceRoute] = []

    def walk(path: list[str], used: frozenset[tuple[int, int]], entry_speed: float) -> None:
        run = _run_edge(
            profiles[path[-1]],
            entry_speed,
            machine,
            air,
            lateral_scenario,
            braking,
            DEFAULT_ZERO_SPEED_EPSILON_M_S,
        )
        if run.stop_reason != "route_end":
            results.append(
                evaluate_distance_route(
                    graph,
                    profiles,
                    path,
                    seed_edge_id=seed_edge_id,
                    lateral_scenario=lateral_scenario,
                    braking=braking,
                    termination=run.stop_reason,
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
                evaluate_distance_route(
                    graph,
                    profiles,
                    path,
                    seed_edge_id=seed_edge_id,
                    lateral_scenario=lateral_scenario,
                    braking=braking,
                    termination="no_admissible_continuation",
                )
            )
            return
        for candidate in nexts:
            walk([*path, candidate], used | {_piece(graph, candidate)}, run.speed_m_s[-1])

    seed = profiles.get(seed_edge_id)
    if seed is None or not seed.simulable:
        return []
    walk([seed_edge_id], frozenset({_piece(graph, seed_edge_id)}), initial_speed_m_s)
    return results


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
