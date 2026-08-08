"""The maximum-distance objective: definitive stop, constrained braking, search.

Physics cases run on hand-built profiles where the answer is derivable, usually
as an energy bracket rather than a closed form: rolling resistance gives an
exact upper bound on distance and holding drag at its initial value gives an
exact lower bound, and a correct simulation must land strictly between them.

Search cases run on synthetic graphs built through the real OSM parsing path,
reusing the Phase 2 builders so tag handling, way splitting, direction rules and
turn restrictions stay exercised.

The recurring trap in a distance objective is that the *fastest* route and the
*furthest* route are different routes, and that a route which stops can
sometimes restart. Several cases exist only to catch an engine that conflates
them.
"""

from __future__ import annotations

import itertools
import math

import pytest
from test_phase2_graph_and_search import (
    ASPHALT,
    METRE_DEG,
    arc,
    forward_edge,
    osm,
    profiles_for,
    straight,
    way,
)

from coastdown.coasting import (
    braking_allowance,
    can_restart_from_rest,
    segment_speed_limits,
    simulate_coasting,
)
from coastdown.curvature import LATERAL_LIMIT_SCENARIOS_M_S2, permitted_speed_m_s
from coastdown.distance_search import (
    DistanceBudget,
    brute_force_distance_routes,
    distinct_longest,
    edge_bend_limits,
    evaluate_distance_route,
    search_distance_from_edge,
    trim_edge_profile,
)
from coastdown.graph import build_graph
from coastdown.models import BicycleSystem, RoadProfile

V0 = 15.0 / 3.6
CRR = 0.006
GRAVITY = 9.80665
TRANSLATIONAL_KG = 90.0
EFFECTIVE_KG = 91.5
DRAG_COEFFICIENT = 0.5 * 1.225 * 0.55


def energy_bracket_m(grade_ratio: float = 0.0, crr: float = CRR) -> tuple[float, float]:
    """Exact bounds on the distance a flat-or-rising run can cover.

    Upper bound: ignore drag entirely.  Lower bound: charge drag at the initial
    speed for the whole run, which it can never exceed while decelerating.
    """
    kinetic = 0.5 * EFFECTIVE_KG * V0 * V0
    theta = math.atan(grade_ratio)
    resistive = TRANSLATIONAL_KG * GRAVITY * (math.sin(theta) + crr * math.cos(theta))
    return kinetic / (resistive + DRAG_COEFFICIENT * V0 * V0), kinetic / resistive


# --------------------------------------------------------------------------
# definitive physical stop
# --------------------------------------------------------------------------


def test_restart_from_rest_follows_the_derived_threshold() -> None:
    # At rest the drag term vanishes, so a(0) > 0 reduces to -tan(theta) > Crr.
    assert can_restart_from_rest(-0.0061, CRR)
    assert not can_restart_from_rest(-0.0059, CRR)
    assert not can_restart_from_rest(-CRR, CRR), "exact balance does not restart"
    assert not can_restart_from_rest(0.0, CRR)
    assert not can_restart_from_rest(0.05, CRR)
    # A worse surface needs a steeper road to move at all.
    assert not can_restart_from_rest(-0.02, 0.045)
    assert can_restart_from_rest(-0.05, 0.045)


def test_a_flat_run_stops_on_resistance_alone_inside_its_energy_bracket() -> None:
    run = simulate_coasting(RoadProfile([5000.0], [0.0], [CRR]), initial_speed_m_s=V0)
    low, high = energy_bracket_m()
    assert run.stop_reason == "definitive_stop"
    assert low < run.travelled_distance_m < high
    assert run.speed_m_s[-1] == 0.0
    assert run.restart_count == 0
    assert len(run.zero_events) == 1 and not run.zero_events[0].restarted


def test_the_diagnostic_distances_are_ordered_and_bounded_by_the_stop() -> None:
    run = simulate_coasting(RoadProfile([5000.0], [0.0], [CRR]), initial_speed_m_s=V0)
    diagnostics = dict(run.diagnostic_distances_m)
    assert diagnostics["5kmh"] < diagnostics["1kmh"] <= run.travelled_distance_m
    assert diagnostics["030ms"] <= run.travelled_distance_m
    # 1 km/h is 0.278 m/s, below the old 0.30 m/s threshold, so it comes later.
    assert diagnostics["030ms"] <= diagnostics["1kmh"]


def test_a_rise_that_consumes_all_the_energy_stops_at_its_own_end() -> None:
    low, high = energy_bracket_m(0.05)
    probe = simulate_coasting(RoadProfile([500.0], [0.05], [CRR]), initial_speed_m_s=V0)
    assert low < probe.travelled_distance_m < high
    stopping = probe.travelled_distance_m
    # A rise exactly as long as the energy allows: the run ends at its end.
    exact = simulate_coasting(RoadProfile([stopping], [0.05], [CRR]), initial_speed_m_s=V0)
    assert exact.travelled_distance_m == pytest.approx(stopping, rel=1e-6)


def test_a_zero_at_a_boundary_restarts_when_the_next_grade_is_steep_enough() -> None:
    probe = simulate_coasting(RoadProfile([500.0], [0.05], [CRR]), initial_speed_m_s=V0)
    stopping = probe.travelled_distance_m
    # -3 % is well beyond the -0.6 % restart threshold.
    run = simulate_coasting(
        RoadProfile([stopping, 800.0], [0.05, -0.03], [CRR, CRR]), initial_speed_m_s=V0
    )
    assert run.restart_count == 1, "the bicycle must roll on into the descent"
    assert run.travelled_distance_m > stopping + 700
    event = run.zero_events[0]
    assert event.restarted and event.acceleration_at_rest_m_s2 > 0
    assert event.distance_m == pytest.approx(stopping, abs=1.0)


def test_the_same_zero_is_definitive_when_the_next_grade_is_too_gentle() -> None:
    probe = simulate_coasting(RoadProfile([500.0], [0.05], [CRR]), initial_speed_m_s=V0)
    stopping = probe.travelled_distance_m
    # -0.4 % is inside the -0.6 % threshold, so gravity cannot beat resistance.
    run = simulate_coasting(
        RoadProfile([stopping, 800.0], [0.05, -0.004], [CRR, CRR]), initial_speed_m_s=V0
    )
    assert run.stop_reason == "definitive_stop"
    assert run.restart_count == 0
    assert run.travelled_distance_m == pytest.approx(stopping, abs=1.0)


def test_a_mid_segment_zero_is_always_definitive() -> None:
    # The rise is far longer than the energy allows, so zero lands inside it.
    run = simulate_coasting(RoadProfile([2000.0], [0.05], [CRR]), initial_speed_m_s=V0)
    assert run.stop_reason == "definitive_stop"
    assert run.travelled_distance_m < 1000
    assert run.restart_count == 0


def test_a_run_may_start_from_rest_when_the_road_is_steep_enough() -> None:
    rolling = simulate_coasting(RoadProfile([600.0], [-0.03], [CRR]), initial_speed_m_s=0.0)
    assert rolling.travelled_distance_m == pytest.approx(600.0, abs=1e-6)
    assert rolling.stop_reason == "route_end"
    stuck = simulate_coasting(RoadProfile([600.0], [-0.004], [CRR]), initial_speed_m_s=0.0)
    assert stuck.stop_reason == "definitive_stop"
    assert stuck.travelled_distance_m == pytest.approx(0.0, abs=1e-6)


@pytest.mark.parametrize("epsilon", [1e-4, 1e-6, 1e-9, 1e-12])
def test_the_result_does_not_depend_on_the_zero_detection_threshold(epsilon: float) -> None:
    profile = RoadProfile([300.0, 400.0, 900.0], [-0.02, 0.03, -0.05], [CRR] * 3)
    run = simulate_coasting(profile, initial_speed_m_s=V0, zero_speed_epsilon_m_s=epsilon)
    reference = simulate_coasting(profile, initial_speed_m_s=V0, zero_speed_epsilon_m_s=1e-6)
    assert run.travelled_distance_m == pytest.approx(reference.travelled_distance_m, rel=1e-6)
    assert run.stop_reason == reference.stop_reason
    assert run.restart_count == reference.restart_count


def test_a_closed_cycle_always_returns_less_energy_than_it_received() -> None:
    """The invariant that makes route reuse safe to allow.

    On any closed cycle returning the bicycle to the same elevation, the
    mechanical energy available after the lap must be strictly less than before
    it: gravity nets to zero and both rolling resistance and drag are
    unconditionally dissipative. A cycle that returned *more* would let a search
    accumulate distance without bound, so this is what separates a physically
    real loop from a data or modelling error.

    Most loops are not lappable at all — a 300 m lap at 4 % stops the bicycle on
    its own climb — so the test asserts the invariant in both forms: strict
    energy loss when the lap completes, and a definitive stop when it does not.
    """
    for grade, length, speed in ((0.04, 300.0, 12.0), (0.02, 25.0, 14.0), (0.01, 100.0, 10.0)):
        loop = RoadProfile([length, length], [-grade, grade], [CRR, CRR])
        assert math.fsum(
            g * segment for g, segment in zip(loop.grade_ratios, loop.segment_lengths_m)
        ) == pytest.approx(0.0, abs=1e-9), "the lap must be closed"
        run = simulate_coasting(loop, initial_speed_m_s=speed)
        if run.stop_reason == "route_end":
            after = 0.5 * EFFECTIVE_KG * run.speed_m_s[-1] ** 2
            before = 0.5 * EFFECTIVE_KG * speed**2
            assert after < before, f"a closed lap at {grade:.0%} returned energy"
        else:
            assert run.stop_reason == "definitive_stop"


def test_repeated_laps_of_a_closed_cycle_decay_monotonically() -> None:
    """Energy falls lap after lap until the loop is no longer passable.

    This is the property a search may rely on once the once-per-piece rule is
    lifted: repeating a loop is self-limiting, so it cannot manufacture
    distance.
    """
    lap = ([25.0, 25.0], [-0.02, 0.02], [CRR, CRR])
    speed = 14.0
    energies = [0.5 * EFFECTIVE_KG * speed**2]
    laps = 0
    while laps < 20:
        run = simulate_coasting(RoadProfile(*lap), initial_speed_m_s=speed)
        if run.stop_reason != "route_end":
            break
        speed = run.speed_m_s[-1]
        energies.append(0.5 * EFFECTIVE_KG * speed**2)
        laps += 1
    assert laps >= 2, f"the 50 m lap must be passable at least twice from 14 m/s, got {laps}"
    assert all(later < earlier for earlier, later in itertools.pairwise(energies)), (
        "energy must decay on every lap"
    )
    assert energies[-1] < energies[0]


# --------------------------------------------------------------------------
# constrained braking
# --------------------------------------------------------------------------


def test_the_envelope_places_each_constraint_on_its_own_segment() -> None:
    profile = RoadProfile([25.0] * 4, [-0.05] * 4, [CRR] * 4)
    limits = segment_speed_limits(profile, [(10.0, 8.0), (60.0, 5.0), (62.0, 4.0)])
    assert limits[0] == 8.0
    assert math.isinf(limits[1])
    assert limits[2] == 4.0, "the tighter of two constraints in one segment wins"
    assert math.isinf(limits[3])


def test_anticipated_braking_pulls_the_limit_upstream() -> None:
    profile = RoadProfile([25.0] * 4, [0.0] * 4, [CRR] * 4)
    limits = (math.inf, math.inf, math.inf, 5.0)
    allowance = braking_allowance(profile, limits, 1.5)
    assert allowance[3] == 5.0
    # v^2 = 5^2 + 2 * 1.5 * 25 = 100 -> 10 m/s one segment upstream.
    assert allowance[2] == pytest.approx(10.0, rel=1e-9)
    assert allowance[1] == pytest.approx(math.sqrt(100.0 + 75.0), rel=1e-9)
    # The allowance rises going upstream: the further from the constraint, the
    # more speed there is room to shed before reaching it.
    assert allowance[0] > allowance[1] > allowance[2] > allowance[3]


def test_braking_removes_energy_only_where_the_envelope_binds() -> None:
    profile = RoadProfile([50.0] * 20, [-0.08] * 20, [CRR] * 20)
    free = simulate_coasting(profile, initial_speed_m_s=V0, braking="none")
    limited = simulate_coasting(
        profile, initial_speed_m_s=V0, bend_limits=[(600.0, 6.0)], braking="ideal"
    )
    assert free.braking_energy_j == 0.0
    assert limited.braking_energy_j > 0.0
    # Distinct segments the envelope actually bound, not integration substeps:
    # the substep count scales with the time step and says nothing about the road.
    assert limited.active_constraint_count > 0
    assert limited.braking_substeps >= limited.active_constraint_count
    assert limited.max_speed_m_s < free.max_speed_m_s
    # The free speed the dynamics would have reached is still reported.
    assert limited.max_free_speed_m_s > limited.max_speed_m_s


def test_a_bend_that_needs_braking_does_not_end_the_run() -> None:
    # Phase 2 terminated a route at the first unholdable bend. It now brakes and
    # keeps going, which is what a rider does.
    profile = RoadProfile([50.0] * 30, [-0.06] * 30, [CRR] * 30)
    limited = simulate_coasting(
        profile, initial_speed_m_s=V0, bend_limits=[(500.0, 5.0)], braking="ideal"
    )
    assert limited.stop_reason == "route_end"
    assert limited.travelled_distance_m == pytest.approx(1500.0, rel=1e-9)
    assert limited.braking_energy_j > 0


def test_the_braking_model_changes_dissipation_but_not_distance() -> None:
    """The two representations travel identically; only the bookkeeping differs.

    Both leave the last binding constraint at the same place and at the same
    speed, so the state governing everything downstream is identical and the
    distance cannot differ. That is structural, not a coincidence of these
    numbers.

    The braking energy does differ, and it is deliberately *not* treated as a
    discriminator: it only records how much speed had to be removed, and
    carrying more speed into a constraint means more to destroy. Here the
    anticipated model rides the descent slower, loses less to drag, and so
    arrives with more energy left for the brakes to take.
    """
    profile = RoadProfile([25.0] * 60 + [25.0] * 160, [-0.05] * 60 + [0.01] * 160, [CRR] * 220)
    bends = [(700.0, 6.0), (1200.0, 5.0)]
    ideal = simulate_coasting(profile, initial_speed_m_s=V0, bend_limits=bends, braking="ideal")
    anticipated = simulate_coasting(
        profile, initial_speed_m_s=V0, bend_limits=bends, braking="anticipated"
    )
    free = simulate_coasting(profile, initial_speed_m_s=V0, braking="none")

    assert ideal.stop_reason == anticipated.stop_reason == "definitive_stop"
    assert anticipated.travelled_distance_m == pytest.approx(ideal.travelled_distance_m, rel=1e-9)
    assert anticipated.braking_energy_j > ideal.braking_energy_j
    assert anticipated.braking_distance_m > ideal.braking_distance_m
    # Anticipation spreads the same job over more of the road.
    assert anticipated.active_constraint_count > ideal.active_constraint_count
    assert anticipated.elapsed_time_s > ideal.elapsed_time_s
    # Braking costs distance against an unconstrained run, but only a little.
    assert ideal.travelled_distance_m < free.travelled_distance_m
    assert ideal.travelled_distance_m > 0.99 * free.travelled_distance_m


# --------------------------------------------------------------------------
# search under the distance objective
# --------------------------------------------------------------------------


def longest(graph, profiles, seed, **kwargs):
    routes, budget = search_distance_from_edge(graph, profiles, seed, **kwargs)
    assert not budget.exhausted
    assert routes
    return routes[0]


def test_at_equal_drop_a_long_gentle_descent_travels_further_than_a_short_steep_one() -> None:
    """The comparison only means something at equal elevation drop.

    Compared at equal *length* the steeper road wins trivially, because it banks
    more potential energy. Given the same 48 m to spend, the gentle road turns
    it into 6 km of road ridden while the steep road turns it into 600 m plus a
    run-out, and the gentle road wins on distance while never exceeding 8 km/h.
    """
    gentle = simulate_coasting(
        RoadProfile([6000.0, 6000.0], [-0.008, 0.0], [CRR, CRR]), initial_speed_m_s=V0
    )
    steep = simulate_coasting(
        RoadProfile([600.0, 6000.0], [-0.08, 0.0], [CRR, CRR]), initial_speed_m_s=V0
    )
    assert gentle.travelled_distance_m > 6000
    assert steep.travelled_distance_m < 1200
    assert gentle.travelled_distance_m > 4 * steep.travelled_distance_m
    assert steep.max_speed_m_s > 3 * gentle.max_speed_m_s


def test_a_descent_then_a_long_flat_runs_out_on_the_flat() -> None:
    descent = way(1, straight(0, 500), ASPHALT, last_node=18)
    flat = way(2, straight(500, 4000), ASPHALT, first_node=18)
    flat["geometry"][0] = descent["geometry"][-1]
    graph = build_graph(osm(descent, flat), "paved_reference")
    profiles = profiles_for(graph, {1: -0.05, 2: 0.0})
    route = longest(graph, profiles, forward_edge(graph, 1))
    assert route.edges_used == 2
    assert route.stop_reason == "definitive_stop"
    # It must get well past the junction: the descent banked real energy, and
    # the run ends on the flat rather than at the end of the road.
    assert 700 < route.distance_m < 900
    assert route.distance_m > 520, "the run continues past the 500 m descent"
    assert route.net_dz_m == pytest.approx(-25.0, abs=1.0)


def test_inertia_clears_a_small_rise_and_the_run_continues_beyond_it() -> None:
    descent = way(1, straight(0, 600), ASPHALT, last_node=18)
    rise = way(2, straight(600, 40), ASPHALT, first_node=18, last_node=24)
    runout = way(3, straight(640, 1500), ASPHALT, first_node=24)
    rise["geometry"][0] = descent["geometry"][-1]
    runout["geometry"][0] = rise["geometry"][-1]
    graph = build_graph(osm(descent, rise, runout), "paved_reference")
    profiles = profiles_for(graph, {1: -0.06, 2: 0.02, 3: -0.02})
    route = longest(graph, profiles, forward_edge(graph, 1))
    assert [graph.edges[edge].osm_way_id for edge in route.edge_ids] == [1, 2, 3]
    assert route.ascent_m > 0


def test_a_geometrically_longer_branch_can_be_the_worse_choice() -> None:
    # Branch 2 is 1200 m but rises; branch 3 is 900 m and descends gently. The
    # engine must prefer total distance travelled, not the longer geometry.
    trunk = way(1, straight(0, 300), ASPHALT, last_node=18)
    uphill_long = way(2, straight(300, 1200), ASPHALT, first_node=18)
    gentle_short = way(3, straight(300, 900, lat=45.05 + 0.0006), ASPHALT, first_node=18)
    uphill_long["geometry"][0] = gentle_short["geometry"][0] = trunk["geometry"][-1]
    graph = build_graph(osm(trunk, uphill_long, gentle_short), "paved_reference")
    profiles = profiles_for(graph, {1: -0.03, 2: 0.03, 3: -0.004})
    route = longest(graph, profiles, forward_edge(graph, 1))
    chosen = [graph.edges[edge].osm_way_id for edge in route.edge_ids]
    assert chosen == [1, 3], "the longer branch stops sooner"


def test_the_furthest_fork_is_neither_the_steepest_nor_the_lowest() -> None:
    # Steep branch: 250 m at -12 %, then nothing. Middle branch: 2500 m at
    # -0.9 %, which is above the restart threshold and keeps rolling furthest.
    # Deep branch: 400 m at -20 % into a wall.
    trunk = way(1, straight(0, 200), ASPHALT, last_node=18)
    steep = way(2, straight(200, 250), ASPHALT, first_node=18)
    middle = way(3, straight(200, 2500, lat=45.05 + 0.0005), ASPHALT, first_node=18)
    deep = way(4, straight(200, 400, lat=45.05 - 0.0005), ASPHALT, first_node=18)
    for element in (steep, middle, deep):
        element["geometry"][0] = trunk["geometry"][-1]
    graph = build_graph(osm(trunk, steep, middle, deep), "paved_reference")
    profiles = profiles_for(graph, {1: -0.02, 2: -0.12, 3: -0.009, 4: -0.20})
    route = longest(graph, profiles, forward_edge(graph, 1))
    chosen = [graph.edges[edge].osm_way_id for edge in route.edge_ids]
    assert chosen == [1, 3]
    assert route.distance_m > 2000


def test_the_cycle_rule_refuses_the_second_traversal_of_a_loop() -> None:
    first = way(1, straight(0, 200), ASPHALT, first_node=10, last_node=20)
    second = way(
        2,
        [(200 * METRE_DEG, 45.05), (300 * METRE_DEG, 45.05 + 100 * METRE_DEG)],
        ASPHALT,
        first_node=20,
        last_node=30,
    )
    third = way(
        3,
        [(300 * METRE_DEG, 45.05 + 100 * METRE_DEG), (0.0, 45.05)],
        ASPHALT,
        first_node=30,
        last_node=10,
    )
    graph = build_graph(osm(first, second, third), "paved_reference")
    profiles = profiles_for(graph, {1: -0.03, 2: -0.03, 3: -0.03})
    routes, budget = search_distance_from_edge(graph, profiles, forward_edge(graph, 1))
    assert not budget.exhausted
    for route in routes:
        pieces = [
            (graph.edges[edge].osm_way_id, graph.edges[edge].piece_index) for edge in route.edge_ids
        ]
        assert len(pieces) == len(set(pieces)), "a piece may not be re-entered"


def test_a_tight_bend_costs_speed_but_the_route_carries_on() -> None:
    approach = way(1, straight(0, 900), ASPHALT, last_node=43)
    bend = way(2, arc(900, 15, 15.0, 90.0, 14), ASPHALT, first_node=43, last_node=90)
    exit_road = way(3, straight(920, 1200, lat=45.05 + 0.0004), ASPHALT, first_node=90)
    bend["geometry"][0] = approach["geometry"][-1]
    exit_road["geometry"][0] = bend["geometry"][-1]
    graph = build_graph(osm(approach, bend, exit_road), "paved_reference")
    profiles = profiles_for(graph, {1: -0.08, 2: -0.02, 3: -0.01})
    route = longest(graph, profiles, forward_edge(graph, 1))
    assert route.edges_used == 3, "braking must not truncate the route"
    assert route.braking_energy_j > 0
    assert route.active_constraints > 0
    # The same route with braking disabled dissipates nothing and is not slower.
    free = evaluate_distance_route(
        graph, profiles, route.edge_ids, seed_edge_id=route.seed_edge_id, braking="none"
    )
    assert free.braking_energy_j == 0.0
    assert free.max_speed_m_s >= route.max_speed_m_s


def test_a_forbidden_road_is_still_never_entered() -> None:
    trunk = way(1, straight(0, 300), ASPHALT, last_node=18)
    private = way(2, straight(300, 3000), {**ASPHALT, "bicycle": "no"}, first_node=18)
    private["geometry"][0] = trunk["geometry"][-1]
    graph = build_graph(osm(trunk, private), "paved_reference")
    assert not any(edge.osm_way_id == 2 for edge in graph.edges.values())
    route = longest(graph, profiles_for(graph, {1: -0.05}), forward_edge(graph, 1))
    assert route.edges_used == 1


# --------------------------------------------------------------------------
# the engine must equal brute force
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "grades",
    [
        {1: -0.03, 2: -0.12, 3: -0.009, 4: -0.02, 5: 0.01},
        {1: -0.05, 2: -0.01, 3: -0.05, 4: 0.03, 5: -0.03},
        {1: -0.02, 2: 0.0, 3: -0.008, 4: -0.01, 5: -0.02},
        {1: -0.01, 2: 0.02, 3: -0.007, 4: -0.004, 5: 0.0},
    ],
)
def test_the_distance_engine_matches_brute_force(grades) -> None:
    trunk = way(1, straight(0, 300), ASPHALT, last_node=21)
    left = way(2, straight(300, 400), ASPHALT, first_node=21, last_node=46)
    right = way(3, straight(300, 500, lat=45.05 + 0.0004), ASPHALT, first_node=21, last_node=80)
    left_tail = way(4, straight(700, 900), ASPHALT, first_node=46)
    right_tail = way(5, straight(800, 900, lat=45.05 + 0.0004), ASPHALT, first_node=80)
    left["geometry"][0] = right["geometry"][0] = trunk["geometry"][-1]
    left_tail["geometry"][0] = left["geometry"][-1]
    right_tail["geometry"][0] = right["geometry"][-1]
    graph = build_graph(osm(trunk, left, right, left_tail, right_tail), "paved_reference")
    profiles = profiles_for(graph, grades)
    seed = forward_edge(graph, 1)

    engine, budget = search_distance_from_edge(
        graph, profiles, seed, budget=DistanceBudget(max_expansions=10**6)
    )
    reference = brute_force_distance_routes(graph, profiles, seed)
    assert not budget.exhausted
    assert engine and reference
    best_reference = max(reference, key=lambda item: item.distance_m)
    assert engine[0].distance_m == pytest.approx(best_reference.distance_m, abs=1e-9)
    assert engine[0].edge_ids == best_reference.edge_ids


# --------------------------------------------------------------------------
# starting inside an edge
# --------------------------------------------------------------------------


def test_trimming_an_edge_moves_the_start_without_changing_what_follows() -> None:
    graph = build_graph(osm(way(1, straight(0, 500), ASPHALT)), "paved_reference")
    profiles = profiles_for(graph, {1: -0.03})
    edge_id = forward_edge(graph, 1)
    whole = profiles[edge_id]
    trimmed = trim_edge_profile(whole, 100.0)
    assert trimmed.horizontal_length_m < whole.horizontal_length_m
    assert trimmed.end_elevation_m == whole.end_elevation_m
    assert trimmed.start_elevation_m < whole.start_elevation_m
    with pytest.raises(ValueError, match="whole edge"):
        trim_edge_profile(whole, 10_000.0)


def test_trimming_removes_what_was_asked_and_rebases_the_bends() -> None:
    """An offset that moves the start by nothing is not an offset.

    The loop used to break one segment late, so the smallest offset that
    start_offsets can produce removed 0.00 m while the caller went on reporting
    a distance gain from it. And the bends kept the untrimmed edge's chainage
    frame, which displaced the whole speed envelope of every in-edge start by
    the size of the trim.
    """
    graph = build_graph(osm(way(1, arc(0, 60, 60.0, 150.0, 40), ASPHALT)), "paved_reference")
    profiles = profiles_for(graph, {1: -0.04})
    whole = profiles[forward_edge(graph, 1)]
    assert len(whole.segment_travelled_m) > 4
    assert whole.bends

    first = whole.segment_travelled_m[0]
    trimmed = trim_edge_profile(whole, first)
    removed = math.fsum(whole.segment_travelled_m) - math.fsum(trimmed.segment_travelled_m)
    assert removed == pytest.approx(first, abs=1e-6), "the first segment must actually go"
    assert len(trimmed.segment_travelled_m) == len(whole.segment_travelled_m) - 1

    # Bends are rebased into the trimmed frame, never left on the old one.
    assert trimmed.bends
    assert min(bend.chainage_m for bend in trimmed.bends) >= -1e-9
    assert max(bend.chainage_m for bend in trimmed.bends) <= trimmed.horizontal_length_m + 1e-6
    shift = max(bend.chainage_m for bend in whole.bends) - max(
        bend.chainage_m for bend in trimmed.bends
    )
    assert shift > 0, "the envelope must move with the start"


def test_starting_inside_an_edge_cannot_beat_starting_at_its_head_on_one_edge() -> None:
    # On a single descending edge, moving the start forward only removes road.
    graph = build_graph(osm(way(1, straight(0, 1200), ASPHALT)), "paved_reference")
    profiles = profiles_for(graph, {1: -0.02})
    seed = forward_edge(graph, 1)
    head = longest(graph, profiles, seed)
    inside = longest(graph, profiles, seed, start_offset_m=300.0)
    assert inside.distance_m < head.distance_m


def test_starting_inside_an_edge_can_help_when_the_head_wastes_energy() -> None:
    """Node seeding is an approximation, and this is where it costs the most.

    A 250 m rise at 1 % exhausts the starting energy after about 47 m, so a run
    seeded at the node never reaches the descent beyond it. Seeded 225 m in, the
    bicycle clears the last 25 m of rise and collects the whole descent. The
    ranking is therefore not invariant to where a run is allowed to begin.
    """
    climb = way(1, straight(0, 250), ASPHALT, last_node=18)
    descent = way(2, straight(250, 1500), ASPHALT, first_node=18)
    descent["geometry"][0] = climb["geometry"][-1]
    graph = build_graph(osm(climb, descent), "paved_reference")
    profiles = profiles_for(graph, {1: 0.01, 2: -0.03})
    seed = forward_edge(graph, 1)
    head = longest(graph, profiles, seed)
    inside = longest(graph, profiles, seed, start_offset_m=225.0)
    assert head.distance_m < 100, "the rise alone exhausts the initial energy"
    assert inside.distance_m > 1000, "starting past the rise reaches the descent"


def test_distinct_longest_drops_sub_paths_of_a_kept_route() -> None:
    graph = build_graph(osm(way(1, straight(0, 800), ASPHALT)), "paved_reference")
    profiles = profiles_for(graph, {1: -0.03})
    seed = forward_edge(graph, 1)
    whole = evaluate_distance_route(graph, profiles, [seed], seed_edge_id=seed)
    kept = distinct_longest([whole, whole], 5)
    assert len(kept) == 1


def test_bend_limits_are_reported_in_travelled_distance() -> None:
    graph = build_graph(osm(way(1, arc(0, 30, 30.0, 120.0, 24), ASPHALT)), "paved_reference")
    profiles = profiles_for(graph, {1: -0.05})
    profile = profiles[forward_edge(graph, 1)]
    limits = edge_bend_limits(profile, "nominal")
    assert limits
    travelled = math.fsum(profile.segment_travelled_m)
    assert all(0.0 <= position <= travelled + 1e-6 for position, _ in limits)
    tightest = min(speed for _, speed in limits)
    assert tightest == pytest.approx(
        permitted_speed_m_s(
            min(bend.radius_m for bend in profile.bends),
            LATERAL_LIMIT_SCENARIOS_M_S2["nominal"],
        ),
        rel=1e-9,
    )


def test_a_heavier_rider_does_not_change_the_restart_threshold() -> None:
    # Mass cancels from -tan(theta) > Crr, so the threshold is mass-independent.
    heavy = BicycleSystem(rider_mass_kg=110.0)
    assert can_restart_from_rest(-0.0061, CRR, heavy)
    assert not can_restart_from_rest(-0.0059, CRR, heavy)
