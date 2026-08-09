"""Graph construction and search-engine validation on controlled networks.

Every graph here is built through the real OSM parsing path rather than by
constructing :class:`GraphEdge` directly, so tag handling, way splitting,
direction rules and turn restrictions are all exercised.  Elevations are
supplied analytically, which is what makes the expected answer knowable: the
question under test is whether the engine finds the optimum, not whether a
terrain model is accurate.

The adversarial cases exist because the obvious failure of a coasting search is
to behave like a steepest-descent walk.  The fork case is the one that matters:
the steeper branch is a dead end and the gentler branch wins, so an engine that
follows the gradient gets it wrong.
"""

from __future__ import annotations

import math

import pytest

from coastdown.graph import build_graph, graph_summary
from coastdown.search import (
    EdgeProfile,
    RouteCandidate,
    SearchBudget,
    brute_force_routes,
    build_edge_profile,
    search_from_edge,
)

LATITUDE = 45.05
# One metre of longitude at the study latitude.
METRE_DEG = 1.0 / (111_320.0 * math.cos(math.radians(LATITUDE)))

ASPHALT = {"highway": "tertiary", "surface": "asphalt"}


def straight(start_lon_m: float, length_m: float, *, step_m: float = 25.0, lat=LATITUDE):
    count = max(2, round(length_m / step_m) + 1)
    return [
        (
            (start_lon_m + index * (length_m / (count - 1))) * METRE_DEG,
            lat,
        )
        for index in range(count)
    ]


def arc(centre_lon_m: float, centre_lat_m: float, radius_m: float, turn_deg: float, points: int):
    """A circular arc, used to create a bend of a known radius."""
    return [
        (
            (centre_lon_m + radius_m * math.cos(math.radians(angle))) * METRE_DEG,
            LATITUDE + (centre_lat_m + radius_m * math.sin(math.radians(angle))) * METRE_DEG,
        )
        for angle in (-90.0 + turn_deg * index / (points - 1) for index in range(points))
    ]


def way(
    way_id: int,
    coordinates,
    tags: dict[str, str],
    *,
    first_node: int | None = None,
    last_node: int | None = None,
) -> dict:
    """One OSM way, with node identifiers derived from the geometry.

    Node ids are generated rather than written by hand so that they always match
    the geometry length: Overpass emits one node per geometry point, and a
    mismatch silently disables way splitting.  ``first_node``/``last_node`` wire
    a junction by making two ways share an endpoint identifier.
    """
    nodes = list(range(way_id * 1000, way_id * 1000 + len(coordinates)))
    if first_node is not None:
        nodes[0] = first_node
    if last_node is not None:
        nodes[-1] = last_node
    return {
        "type": "way",
        "id": way_id,
        "nodes": nodes,
        "geometry": [{"lon": lon, "lat": lat} for lon, lat in coordinates],
        "tags": dict(tags),
    }


def osm(*elements) -> dict:
    return {
        "version": 0.6,
        "osm3s": {"timestamp_osm_base": "2026-08-07T00:00:00Z"},
        "elements": list(elements),
    }


def profiles_for(graph, grades: dict[int, float], start_elevation: float = 1000.0):
    """Give each way a constant grade, so every expected time is computable."""
    built: dict[str, EdgeProfile] = {}
    for edge_id, edge in graph.edges.items():
        grade = grades[edge.osm_way_id]
        elevations = [start_elevation + grade * sample.chainage_m for sample in edge.samples]
        built[edge_id] = build_edge_profile(edge, edge.samples, elevations)
    return built


# --------------------------------------------------------------------------
# graph construction
# --------------------------------------------------------------------------


def test_ways_are_split_at_a_shared_interior_node() -> None:
    # Way 1 runs 400 m east; way 2 joins it at way 1's middle node, which is an
    # interior node of way 1 and would otherwise be invisible to routing.
    first = way(1, straight(0, 400, step_m=100), ASPHALT)
    junction = first["nodes"][2]
    second = way(
        2,
        straight(200, 200, step_m=100, lat=LATITUDE + 200 * METRE_DEG),
        ASPHALT,
        first_node=junction,
    )
    second["geometry"][0] = first["geometry"][2]
    graph = build_graph(osm(first, second), "paved_reference")
    pieces = sorted(
        (edge.osm_way_id, edge.piece_index)
        for edge in graph.edges.values()
        if edge.direction == "forward"
    )
    assert pieces == [(1, 0), (1, 1), (2, 0)]
    # The junction now carries three outgoing edges: the two halves of way 1
    # leaving in opposite directions, plus the branch.
    assert len(graph.outgoing[junction]) == 3


def test_direction_rules_and_usability_survive_into_the_graph() -> None:
    oneway = way(1, straight(0, 200), {**ASPHALT, "oneway": "yes"})
    contraflow = way(2, straight(200, 200), {**ASPHALT, "oneway": "yes", "oneway:bicycle": "no"})
    trail = way(3, straight(400, 200), {"highway": "path", "surface": "dirt", "mtb:scale": "2"})
    graph = build_graph(osm(oneway, contraflow, trail), "extended_vtc")
    directions = {(edge.osm_way_id, edge.direction) for edge in graph.edges.values()}
    assert (1, "forward") in directions and (1, "reverse") not in directions
    assert (2, "forward") in directions and (2, "reverse") in directions
    assert not any(edge.osm_way_id == 3 for edge in graph.edges.values())


def test_turn_restrictions_remove_and_force_continuations() -> None:
    trunk = way(1, straight(0, 200), ASPHALT, last_node=18)
    left = way(2, straight(200, 200), ASPHALT, first_node=18)
    right = way(3, straight(200, 200, lat=LATITUDE + 0.001), ASPHALT, first_node=18)
    left["geometry"][0] = right["geometry"][0] = trunk["geometry"][-1]

    def relation(relation_id: int, kind: str, to_way: int, extra=None) -> dict:
        return {
            "type": "relation",
            "id": relation_id,
            "tags": {"type": "restriction", "restriction": kind, **(extra or {})},
            "members": [
                {"type": "way", "ref": 1, "role": "from"},
                {"type": "node", "ref": 18, "role": "via"},
                {"type": "way", "ref": to_way, "role": "to"},
            ],
        }

    banned = build_graph(
        osm(trunk, left, right, relation(90, "no_left_turn", 2)), "paved_reference"
    )
    assert len(banned.banned_turns) == 1
    forward_trunk = next(
        edge_id
        for edge_id, edge in banned.edges.items()
        if edge.osm_way_id == 1 and edge.to_node == 18
    )
    reachable = {banned.edges[item].osm_way_id for item in banned.continuations(forward_trunk)}
    assert 2 not in reachable and 3 in reachable

    forced = build_graph(
        osm(trunk, left, right, relation(91, "only_straight_on", 3)), "paved_reference"
    )
    reachable = {forced.edges[item].osm_way_id for item in forced.continuations(forward_trunk)}
    assert reachable == {3}

    excepted = build_graph(
        osm(trunk, left, right, relation(92, "no_left_turn", 2, {"except": "bicycle"})),
        "paved_reference",
    )
    assert not excepted.banned_turns
    assert any("excepts" in note for note in excepted.restriction_notes)


def test_graph_summary_reports_what_it_built() -> None:
    graph = build_graph(osm(way(1, straight(0, 300), ASPHALT)), "paved_reference")
    summary = graph_summary(graph)
    assert summary["directed_edges"] == 2
    assert summary["usability_counts"] == {"paved_reference": 2}
    assert summary["surface_counts"] == {"asphalt_good": 2}


# --------------------------------------------------------------------------
# adversarial search cases
# --------------------------------------------------------------------------


def best_route(graph, profiles, seed: str) -> RouteCandidate:
    routes, budget = search_from_edge(graph, profiles, seed)
    assert not budget.exhausted
    assert routes
    return routes[0]


def forward_edge(graph, way_id: int) -> str:
    return next(
        edge_id
        for edge_id, edge in graph.edges.items()
        if edge.osm_way_id == way_id and edge.direction == "forward"
    )


def test_a_long_gentle_descent_outlasts_a_short_steep_one() -> None:
    gentle = build_graph(osm(way(1, straight(0, 3000), ASPHALT)), "paved_reference")
    steep = build_graph(osm(way(1, straight(0, 300), ASPHALT)), "paved_reference")
    slow = best_route(gentle, profiles_for(gentle, {1: -0.012}), forward_edge(gentle, 1))
    fast = best_route(steep, profiles_for(steep, {1: -0.08}), forward_edge(steep, 1))
    assert slow.elapsed_time_s > fast.elapsed_time_s
    assert fast.max_speed_m_s > slow.max_speed_m_s


def test_the_engine_prefers_the_gentler_branch_when_the_steeper_one_dead_ends() -> None:
    trunk = way(1, straight(0, 200), ASPHALT, last_node=18)
    steep_stub = way(2, straight(200, 150), ASPHALT, first_node=18)
    gentle_long = way(3, straight(200, 2500, lat=LATITUDE + 0.0005), ASPHALT, first_node=18)
    steep_stub["geometry"][0] = gentle_long["geometry"][0] = trunk["geometry"][-1]
    graph = build_graph(osm(trunk, steep_stub, gentle_long), "paved_reference")
    profiles = profiles_for(graph, {1: -0.03, 2: -0.12, 3: -0.010})
    winner = best_route(graph, profiles, forward_edge(graph, 1))
    chosen = [graph.edges[edge_id].osm_way_id for edge_id in winner.edge_ids]
    assert chosen == [1, 3], "a steepest-descent walk would have taken way 2"


def test_inertia_carries_the_rider_across_a_flat_and_over_a_small_rise() -> None:
    descent = way(1, straight(0, 600), ASPHALT, last_node=18)
    flat = way(2, straight(600, 100), ASPHALT, first_node=18, last_node=24)
    rise = way(3, straight(700, 40), ASPHALT, first_node=24, last_node=27)
    runout = way(4, straight(740, 800), ASPHALT, first_node=27)
    flat["geometry"][0] = descent["geometry"][-1]
    rise["geometry"][0] = flat["geometry"][-1]
    runout["geometry"][0] = rise["geometry"][-1]
    graph = build_graph(osm(descent, flat, rise, runout), "paved_reference")
    profiles = profiles_for(graph, {1: -0.06, 2: 0.0, 3: 0.02, 4: -0.02})
    winner = best_route(graph, profiles, forward_edge(graph, 1))
    assert [graph.edges[edge_id].osm_way_id for edge_id in winner.edge_ids] == [1, 2, 3, 4]
    assert winner.ascent_m > 0, "the small rise must appear in the elevation budget"


def test_a_rise_the_rider_cannot_clear_ends_the_route() -> None:
    descent = way(1, straight(0, 200), ASPHALT, last_node=18)
    wall = way(2, straight(200, 600), ASPHALT, first_node=18)
    wall["geometry"][0] = descent["geometry"][-1]
    graph = build_graph(osm(descent, wall), "paved_reference")
    profiles = profiles_for(graph, {1: -0.02, 2: 0.06})
    winner = best_route(graph, profiles, forward_edge(graph, 1))
    assert winner.stop_reason == "speed_threshold"
    assert winner.distance_m < 400


def test_the_cycle_rule_stops_a_loop_from_running_forever() -> None:
    # A closed triangle whose net elevation change is zero: without the rule the
    # rider could circulate until rolling resistance alone stopped them, and the
    # search would keep re-expanding the same three pieces.
    first = way(1, straight(0, 200), ASPHALT, first_node=10, last_node=20)
    second = way(
        2,
        [(200 * METRE_DEG, LATITUDE), (300 * METRE_DEG, LATITUDE + 100 * METRE_DEG)],
        ASPHALT,
        first_node=20,
        last_node=30,
    )
    third = way(
        3,
        [(300 * METRE_DEG, LATITUDE + 100 * METRE_DEG), (0.0, LATITUDE)],
        ASPHALT,
        first_node=30,
        last_node=10,
    )
    graph = build_graph(osm(first, second, third), "paved_reference")
    profiles = profiles_for(graph, {1: -0.02, 2: -0.02, 3: 0.02})
    routes, budget = search_from_edge(graph, profiles, forward_edge(graph, 1))
    assert not budget.exhausted
    for route in routes:
        pieces = [
            (graph.edges[edge_id].osm_way_id, graph.edges[edge_id].piece_index)
            for edge_id in route.edge_ids
        ]
        assert len(pieces) == len(set(pieces))


def test_a_tight_bend_taken_fast_is_reported_as_a_turn_violation() -> None:
    # A 12 m radius quarter-circle reached after a long steep descent.
    approach = way(1, straight(0, 800), ASPHALT, last_node=43)
    bend = way(2, arc(800, 12, 12.0, 90.0, 12), ASPHALT, first_node=43)
    bend["geometry"][0] = approach["geometry"][-1]
    graph = build_graph(osm(approach, bend), "paved_reference")
    profiles = profiles_for(graph, {1: -0.09, 2: -0.02})
    winner = best_route(graph, profiles, forward_edge(graph, 1))
    assert winner.turn.bend_count > 0
    assert winner.turn.critical_radius_m is not None
    assert winner.turn.critical_radius_m < 60
    assert winner.turn.violated, "a fast rider cannot hold a 12 m radius without braking"
    assert winner.turn.permitted_speed_m_s < winner.turn.speed_at_critical_m_s


def test_a_gentle_bend_at_moderate_speed_keeps_a_positive_margin() -> None:
    approach = way(1, straight(0, 200), ASPHALT, last_node=19)
    bend = way(2, arc(200, 150, 150.0, 45.0, 12), ASPHALT, first_node=19)
    bend["geometry"][0] = approach["geometry"][-1]
    graph = build_graph(osm(approach, bend), "paved_reference")
    profiles = profiles_for(graph, {1: -0.02, 2: -0.02})
    winner = best_route(graph, profiles, forward_edge(graph, 1))
    assert not winner.turn.violated
    assert winner.turn.margin_m_s2 is None or winner.turn.margin_m_s2 > 0


def test_a_forbidden_continuation_is_never_entered() -> None:
    trunk = way(1, straight(0, 200), ASPHALT, last_node=18)
    private = way(2, straight(200, 2000), {**ASPHALT, "bicycle": "no"}, first_node=18)
    private["geometry"][0] = trunk["geometry"][-1]
    graph = build_graph(osm(trunk, private), "paved_reference")
    assert not any(edge.osm_way_id == 2 for edge in graph.edges.values())
    profiles = profiles_for(graph, {1: -0.05})
    winner = best_route(graph, profiles, forward_edge(graph, 1))
    assert winner.edges_used == 1


def test_a_structure_without_roadway_elevation_is_not_routable() -> None:
    trunk = way(1, straight(0, 200), ASPHALT, last_node=18)
    viaduct = way(2, straight(200, 400), {**ASPHALT, "bridge": "yes"}, first_node=18)
    viaduct["geometry"][0] = trunk["geometry"][-1]
    graph = build_graph(osm(trunk, viaduct), "paved_reference")
    assert not any(edge.osm_way_id == 2 for edge in graph.edges.values())


def test_an_edge_whose_terrain_is_missing_is_marked_unsimulable() -> None:
    graph = build_graph(osm(way(1, straight(0, 300), ASPHALT)), "paved_reference")
    edge_id = forward_edge(graph, 1)
    edge = graph.edges[edge_id]
    elevations = [1000.0 - 0.02 * sample.chainage_m for sample in edge.samples]
    elevations[3] = math.nan
    profile = build_edge_profile(edge, edge.samples, elevations)
    assert not profile.simulable
    assert "no value" in profile.reason


# --------------------------------------------------------------------------
# the engine must agree with brute force
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("grades", "label"),
    [
        ({1: -0.03, 2: -0.12, 3: -0.010, 4: -0.02, 5: 0.01}, "misleading fork"),
        ({1: -0.05, 2: -0.01, 3: -0.05, 4: 0.03, 5: -0.03}, "mixed"),
        ({1: -0.02, 2: 0.0, 3: -0.04, 4: -0.01, 5: -0.02}, "flat branch"),
    ],
)
def test_the_engine_matches_brute_force_on_a_branching_subgraph(grades, label) -> None:
    trunk = way(1, straight(0, 300), ASPHALT, last_node=21)
    left = way(2, straight(300, 400), ASPHALT, first_node=21, last_node=46)
    right = way(3, straight(300, 500, lat=LATITUDE + 0.0004), ASPHALT, first_node=21, last_node=80)
    left_tail = way(4, straight(700, 600), ASPHALT, first_node=46)
    right_tail = way(5, straight(800, 600, lat=LATITUDE + 0.0004), ASPHALT, first_node=80)
    left["geometry"][0] = right["geometry"][0] = trunk["geometry"][-1]
    left_tail["geometry"][0] = left["geometry"][-1]
    right_tail["geometry"][0] = right["geometry"][-1]
    graph = build_graph(osm(trunk, left, right, left_tail, right_tail), "paved_reference")
    profiles = profiles_for(graph, grades)
    seed = forward_edge(graph, 1)

    engine, budget = search_from_edge(
        graph, profiles, seed, budget=SearchBudget(max_expansions=10**6)
    )
    reference = brute_force_routes(graph, profiles, seed)
    assert not budget.exhausted
    assert engine and reference
    best_engine = max(engine, key=lambda item: item.elapsed_time_s)
    best_reference = max(reference, key=lambda item: item.elapsed_time_s)
    assert best_engine.elapsed_time_s == pytest.approx(best_reference.elapsed_time_s, abs=1e-9)
    assert best_engine.edge_ids == best_reference.edge_ids, label
