"""Why a route ended, in terms that decide whether its distance is the answer.

A distance means nothing without this. A run that stopped because the bicycle
ran out of energy has measured something; a run that stopped because the model
ran out of road has measured a *lower bound* on the same thing, and printing the
two the same way invites the reader to treat a truncation as a record.

Four statuses, exhaustive and mutually exclusive:

``physical_stop``
    Speed reached zero and nothing can restart the bicycle. The distance is the
    coasting distance of that route. This is the only status that is an answer.

``model_gap``
    The road continues and the model does not follow it. Either the pipeline
    admitted no edge for the continuation — a structure with no roadway
    elevation, an unusable surface, a missing profile — or every continuation
    was refused by the trip rule. The bicycle was still moving. The distance is
    a lower bound.

``network_boundary``
    Neither the graph nor the source data has anything beyond that point: a true
    dead end, or the edge of the extract. The bicycle was still moving. The
    distance is a lower bound, and only a larger extract can improve it.

``budget_limit``
    The search ran out of allowance rather than out of graph. Nothing about the
    road is being reported at all; the number is a lower bound on what that seed
    can reach. A published ranking should contain none of these.

The distinction between ``model_gap`` and ``network_boundary`` cannot be drawn
from the graph, because the graph is exactly what dropped the continuation. It
is drawn by going back to the raw extract and asking whether a highway way still
runs through the node where the route stopped.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from .graph import RoutableGraph

PHYSICAL_STOP = "physical_stop"
MODEL_GAP = "model_gap"
NETWORK_BOUNDARY = "network_boundary"
BUDGET_LIMIT = "budget_limit"

#: Statuses whose distance is a lower bound rather than a coasting distance.
LOWER_BOUND_STATUSES = frozenset({MODEL_GAP, NETWORK_BOUNDARY, BUDGET_LIMIT})


@dataclass(frozen=True)
class Termination:
    """What ended a route, and the one-line reason a reader needs."""

    status: str
    detail: str

    @property
    def is_complete(self) -> bool:
        """True only when the distance is the coasting distance."""
        return self.status == PHYSICAL_STOP

    def format_distance(self, distance_m: float) -> str:
        """The distance with the qualifier it must never be printed without."""
        if self.is_complete:
            return f"{distance_m:.1f} m"
        return f">= {distance_m:.1f} m"


def node_way_index(osm: Mapping[str, object]) -> dict[int, list[dict]]:
    """Every highway way of the raw extract, indexed by the nodes it passes."""
    index: dict[int, list[dict]] = {}
    for element in osm.get("elements", ()):  # type: ignore[union-attr]
        if element.get("type") != "way" or "highway" not in element.get("tags", {}):
            continue
        for node_id in element.get("nodes", ()):
            index.setdefault(node_id, []).append(element)
    return index


def classify(
    graph: RoutableGraph,
    edge_ids: Sequence[str],
    stop_reason: str,
    *,
    node_ways: Mapping[int, Iterable[dict]] | None = None,
    budget_exhausted: bool = False,
    search_termination: str = "",
) -> Termination:
    """Classify one finished route.

    ``budget_exhausted`` wins over everything: a truncated search has not
    described the road at all, so no conclusion about the road may be drawn from
    it.
    """
    if budget_exhausted:
        return Termination(
            BUDGET_LIMIT,
            "the search ran out of expansion allowance, not out of graph",
        )
    if stop_reason == "definitive_stop":
        return Termination(
            PHYSICAL_STOP,
            "speed reached zero and no segment could restart the bicycle",
        )
    if search_termination == "route_length_cap":
        return Termination(
            BUDGET_LIMIT,
            "the route hit the maximum edge count, which is a cap and not an answer",
        )

    last = graph.edges[edge_ids[-1]]
    terminal_node = last.to_node

    if graph.continuations(edge_ids[-1]):
        used = {
            (graph.edges[edge_id].osm_way_id, graph.edges[edge_id].piece_index)
            for edge_id in edge_ids
        }
        blocked = [
            candidate
            for candidate in graph.continuations(edge_ids[-1])
            if (graph.edges[candidate].osm_way_id, graph.edges[candidate].piece_index) not in used
        ]
        if blocked:
            return Termination(
                MODEL_GAP,
                f"road continues at node {terminal_node} but no admitted edge is "
                f"simulable there ({len(blocked)} candidate(s) carry no usable profile)",
            )
        return Termination(
            MODEL_GAP,
            f"road continues at node {terminal_node}; every continuation was refused "
            "by the trip rule, so the coast was ended by a definition and not by physics",
        )

    if node_ways is not None:
        others = [
            way
            for way in node_ways.get(terminal_node, ())
            if way["id"] != last.osm_way_id and terminal_node in way.get("nodes", ())
        ]
        if others:
            names = sorted({str(way["id"]) for way in others})[:4]
            return Termination(
                MODEL_GAP,
                f"OSM way(s) {', '.join(names)} still run through node {terminal_node}; "
                "the pipeline admitted no edge for them",
            )

    return Termination(
        NETWORK_BOUNDARY,
        f"nothing in the extract continues past node {terminal_node}: a dead end, "
        "or the edge of the download",
    )
