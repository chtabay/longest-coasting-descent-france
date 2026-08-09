"""Why a route ended, and why that decides how its distance may be printed.

The distinction these tests defend is not cosmetic. A route that stopped
because the bicycle ran out of energy has measured the coasting distance; a
route that stopped because the model ran out of road has measured a lower bound
on it. Printing both as "4 494.8 m" invites a reader to treat a truncation as a
record, which is the specific error that made a 6 291.2 m figure look like a
regional maximum when the road simply continued through an 8.3 m underpass the
pipeline had dropped.
"""

from __future__ import annotations

import pytest
from test_phase2_graph_and_search import ASPHALT, forward_edge, osm, straight, way

from coastdown.graph import build_graph
from coastdown.termination import (
    BUDGET_LIMIT,
    MODEL_GAP,
    NETWORK_BOUNDARY,
    PHYSICAL_STOP,
    Termination,
    classify,
    node_way_index,
)


def dead_end_graph():
    """One admitted way, with nothing at all beyond its far end."""
    edge = way(1, straight(0, 400), ASPHALT)
    document = osm(edge)
    return build_graph(document, "paved_reference"), document


def severed_graph():
    """An admitted way whose continuation exists in OSM but is a structure.

    ``layer=-1`` is what the D 211 underpass carries, and the preserved rule
    gives no terrain elevation to a structure, so the pipeline admits no edge
    for it. The road continues; the graph does not.
    """
    trunk = way(1, straight(0, 400), ASPHALT, last_node=77)
    underpass = way(
        2,
        straight(400, 10),
        {**ASPHALT, "layer": "-1"},
        first_node=77,
    )
    underpass["geometry"][0] = trunk["geometry"][-1]
    document = osm(trunk, underpass)
    return build_graph(document, "paved_reference"), document


def test_a_definitive_stop_is_the_only_complete_answer() -> None:
    graph, _ = dead_end_graph()
    seed = forward_edge(graph, 1)
    result = classify(graph, [seed], "definitive_stop")
    assert result.status == PHYSICAL_STOP
    assert result.is_complete
    assert result.format_distance(4494.84) == "4494.8 m"
    assert ">=" not in result.format_distance(4494.84)


def test_a_road_that_continues_only_in_osm_is_a_model_gap() -> None:
    """The exact shape of the VTC leader, in miniature.

    The graph has no continuation, so from inside the search this looks like the
    end of the network. It is not: the extract still carries a way through that
    node, and the pipeline is what dropped it.
    """
    graph, document = severed_graph()
    seed = forward_edge(graph, 1)
    assert graph.continuations(seed) == (), "the structure must produce no admitted edge"
    result = classify(graph, [seed], "route_end", node_ways=node_way_index(document))
    assert result.status == MODEL_GAP
    assert not result.is_complete
    assert result.format_distance(6291.22) == ">= 6291.2 m"
    assert "2" in result.detail, "the detail must name the way that was dropped"


def test_a_true_dead_end_is_a_network_boundary_not_a_model_gap() -> None:
    """Nothing was dropped here, so nothing can be recovered by fixing the model."""
    graph, document = dead_end_graph()
    seed = forward_edge(graph, 1)
    result = classify(graph, [seed], "route_end", node_ways=node_way_index(document))
    assert result.status == NETWORK_BOUNDARY
    assert not result.is_complete


def test_without_the_extract_a_severed_road_cannot_be_told_from_a_dead_end() -> None:
    """The graph alone cannot make the distinction, and does not pretend to.

    Called without ``node_ways`` the classifier falls back to the conservative
    label rather than guessing, which is why every caller that has the extract
    is expected to pass it.
    """
    graph, _ = severed_graph()
    seed = forward_edge(graph, 1)
    assert classify(graph, [seed], "route_end").status == NETWORK_BOUNDARY


def test_a_continuation_refused_by_the_trip_rule_is_still_a_lower_bound() -> None:
    """A coast ended by a definition has not measured how far the bicycle rolls."""
    trunk = way(1, straight(0, 300), ASPHALT, last_node=21)
    branch = way(2, straight(300, 300), ASPHALT, first_node=21)
    branch["geometry"][0] = trunk["geometry"][-1]
    document = osm(trunk, branch)
    graph = build_graph(document, "paved_reference")
    seed = forward_edge(graph, 1)
    onward = graph.continuations(seed)
    assert onward, "the fixture needs a continuation for the rule to refuse"
    result = classify(
        graph,
        [seed, onward[0]],
        "route_end",
        node_ways=node_way_index(document),
        search_termination="no_admissible_continuation",
    )
    assert result.status in {MODEL_GAP, NETWORK_BOUNDARY}
    assert not result.is_complete


def test_an_exhausted_budget_outranks_every_other_reading() -> None:
    """A truncated search has described nothing about the road."""
    graph, document = dead_end_graph()
    seed = forward_edge(graph, 1)
    for stop_reason in ("definitive_stop", "route_end"):
        result = classify(
            graph,
            [seed],
            stop_reason,
            node_ways=node_way_index(document),
            budget_exhausted=True,
        )
        assert result.status == BUDGET_LIMIT
        assert not result.is_complete


def test_a_route_length_cap_is_a_cap_and_not_an_answer() -> None:
    graph, document = dead_end_graph()
    seed = forward_edge(graph, 1)
    result = classify(
        graph,
        [seed],
        "route_end",
        node_ways=node_way_index(document),
        search_termination="route_length_cap",
    )
    assert result.status == BUDGET_LIMIT


@pytest.mark.parametrize("status", [PHYSICAL_STOP, MODEL_GAP, NETWORK_BOUNDARY, BUDGET_LIMIT])
def test_only_a_physical_stop_prints_without_a_qualifier(status: str) -> None:
    """The formatting rule, pinned so it cannot be relaxed by accident."""
    rendered = Termination(status, "").format_distance(1234.56)
    assert rendered.startswith(">=") is (status != PHYSICAL_STOP)
