"""The routable regional graph.

An OSM way is not a graph edge.  Ways are split at junctions most of the time,
but not always: in the Oisans extract 502 admitted ways carry 974 interior nodes
that another admitted way also touches.  Routing on unsplit ways would make
those junctions invisible, so every way is cut at each shared node first and the
directed edges are built from the pieces.

Everything the search needs travels on the edge: geometry, elevations, usability,
surface class and its rolling-resistance scenario, structure status, the OSM tags
that produced each decision, and the identifiers needed to look the edge up
again.  Nothing is recomputed from tags later, so a decision cannot silently
change between the graph and the ranking.

Turn restrictions are applied as relations between *edges*, not ways, which is
the only form the search can enforce.  ``no_*`` removes one continuation;
``only_*`` removes every continuation except one, which is the stronger and more
easily mishandled case.  ``except=bicycle`` disables a restriction entirely,
because a motor-vehicle turn ban does not apply to this study's rider.
"""

from __future__ import annotations

import itertools
import math
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

from .geography import StructureStatus
from .live_oisans import (
    OSMDirectedGeometry,
    TurnRestriction,
    bicycle_directions,
    parse_osm_directed_edges,
    parse_turn_restrictions,
)
from .sampling import SamplePoint, reverse_samples, sample_polyline
from .surfaces import SurfaceClass
from .usability import SCENARIO_ADMITS, UsabilityClass, assess_usability

BASE_SPACING_M = 5.0
KEEP_VERTEX_ABOVE_DEG = 15.0

NO_RESTRICTIONS = frozenset(
    {
        "no_left_turn",
        "no_right_turn",
        "no_straight_on",
        "no_u_turn",
        "no_entry",
        "no_exit",
    }
)
ONLY_RESTRICTIONS = frozenset({"only_left_turn", "only_right_turn", "only_straight_on"})


@dataclass(frozen=True)
class GraphEdge:
    edge_id: str
    osm_way_id: int
    piece_index: int
    direction: str
    from_node: int
    to_node: int
    samples: tuple[SamplePoint, ...]
    usability: UsabilityClass
    surface_class: SurfaceClass
    surface_is_assumed: bool
    usability_reason: str
    structure_status: StructureStatus
    tags: tuple[tuple[str, str], ...]

    @property
    def horizontal_length_m(self) -> float:
        return self.samples[-1].chainage_m

    @property
    def name(self) -> str:
        tags = dict(self.tags)
        return tags.get("ref") or tags.get("name") or tags.get("highway", "")


@dataclass(frozen=True)
class RoutableGraph:
    edges: dict[str, GraphEdge]
    outgoing: dict[int, tuple[str, ...]]
    banned_turns: frozenset[tuple[str, str]]
    forced_turns: dict[str, frozenset[str]]
    restriction_notes: tuple[str, ...]

    def continuations(self, edge_id: str) -> tuple[str, ...]:
        """Edges a rider may legally enter after traversing ``edge_id``."""
        edge = self.edges[edge_id]
        candidates = self.outgoing.get(edge.to_node, ())
        forced = self.forced_turns.get(edge_id)
        allowed = []
        for candidate in candidates:
            if (edge_id, candidate) in self.banned_turns:
                continue
            if forced is not None and candidate not in forced:
                continue
            other = self.edges[candidate]
            # A u-turn on the same way piece is not a continuation of a coast.
            if other.osm_way_id == edge.osm_way_id and other.piece_index == edge.piece_index:
                continue
            allowed.append(candidate)
        return tuple(allowed)


def junction_node_ids(forward_edges: Sequence[OSMDirectedGeometry]) -> frozenset[int]:
    """Nodes touched by more than one admitted way, plus every way endpoint."""
    counts: Counter[int] = Counter()
    endpoints: set[int] = set()
    for edge in forward_edges:
        for node in edge.node_ids:
            counts[node] += 1
        if edge.node_ids:
            endpoints.add(edge.node_ids[0])
            endpoints.add(edge.node_ids[-1])
    return frozenset({node for node, count in counts.items() if count > 1} | endpoints)


def split_positions(node_ids: Sequence[int], junctions: frozenset[int]) -> tuple[int, ...]:
    """Indices at which a way must be cut, always including both ends."""
    if len(node_ids) < 2:
        return ()
    inner = [index for index in range(1, len(node_ids) - 1) if node_ids[index] in junctions]
    return (0, *inner, len(node_ids) - 1)


def way_pieces(
    edge: OSMDirectedGeometry, junctions: frozenset[int]
) -> tuple[tuple[int, tuple[tuple[float, float], ...], int, int], ...]:
    """Cut one forward way into (piece index, geometry, from node, to node)."""
    if len(edge.node_ids) != len(edge.lonlat):
        # Overpass emits one geometry point per node; a mismatch means the
        # extract was trimmed and the way cannot be split reliably.
        return ((0, edge.lonlat, edge.node_ids[0], edge.node_ids[-1]),) if edge.node_ids else ()
    cuts = split_positions(edge.node_ids, junctions)
    pieces = []
    for piece_index, (start, end) in enumerate(itertools.pairwise(cuts)):
        geometry = edge.lonlat[start : end + 1]
        if len(geometry) < 2:
            continue
        pieces.append((piece_index, geometry, edge.node_ids[start], edge.node_ids[end]))
    return tuple(pieces)


def piece_sample_points(geometry: Sequence[tuple[float, float]]) -> tuple[SamplePoint, ...]:
    """Sampling used for both elevation acquisition and graph construction."""
    return sample_polyline(geometry, BASE_SPACING_M, keep_vertex_above_deg=KEEP_VERTEX_ABOVE_DEG)


def admitted_forward_edges(osm: dict, scenario: str) -> tuple[OSMDirectedGeometry, ...]:
    """Forward ways that the scenario admits and whose elevation is knowable."""
    admitted = SCENARIO_ADMITS[scenario]
    return tuple(
        edge
        for edge in parse_osm_directed_edges(osm)
        if edge.direction == "forward"
        and edge.structure_status is StructureStatus.NORMAL
        and assess_usability(dict(edge.tags)).usability in admitted
    )


def _restriction_edges(
    restriction: TurnRestriction,
    by_way_to_node: dict[tuple[int, int], list[str]],
    by_way_from_node: dict[tuple[int, int], list[str]],
) -> tuple[list[str], list[str]]:
    from_ids: list[str] = []
    to_ids: list[str] = []
    for via in restriction.via_node_ids:
        for way in restriction.from_way_ids:
            from_ids.extend(by_way_to_node.get((way, via), ()))
        for way in restriction.to_way_ids:
            to_ids.extend(by_way_from_node.get((way, via), ()))
    return from_ids, to_ids


# Junctions, and therefore the geometry of every graph piece, are derived from
# the widest scenario and never from the one being routed. A narrower scenario
# admits fewer ways, which would move the junction set, which would move the
# sample points, which would leave the acquired elevations addressing geometry
# that no longer exists. Splitting once keeps every scenario on the same pieces.
SPLITTING_SCENARIO = "extended_vtc"


def build_graph(
    osm: dict, scenario: str, *, splitting_scenario: str = SPLITTING_SCENARIO
) -> RoutableGraph:
    """Assemble the directed, restriction-aware graph for one usability scenario."""
    junctions = junction_node_ids(admitted_forward_edges(osm, splitting_scenario))
    forward = admitted_forward_edges(osm, scenario)

    edges: dict[str, GraphEdge] = {}
    outgoing: dict[int, list[str]] = defaultdict(list)
    by_way_to_node: dict[tuple[int, int], list[str]] = defaultdict(list)
    by_way_from_node: dict[tuple[int, int], list[str]] = defaultdict(list)

    for edge in forward:
        assessment = assess_usability(dict(edge.tags))
        directions = bicycle_directions(dict(edge.tags))
        for piece_index, geometry, start_node, end_node in way_pieces(edge, junctions):
            try:
                forward_samples = piece_sample_points(geometry)
            except ValueError:
                continue
            for direction in directions:
                oriented_samples = (
                    forward_samples if direction == "forward" else reverse_samples(forward_samples)
                )
                head, tail = (
                    (start_node, end_node) if direction == "forward" else (end_node, start_node)
                )
                edge_id = f"osm-{edge.osm_way_id}-{piece_index}-{direction}"
                edges[edge_id] = GraphEdge(
                    edge_id=edge_id,
                    osm_way_id=edge.osm_way_id,
                    piece_index=piece_index,
                    direction=direction,
                    from_node=head,
                    to_node=tail,
                    samples=oriented_samples,
                    usability=assessment.usability,
                    surface_class=assessment.surface_class,
                    surface_is_assumed=assessment.surface_is_assumed,
                    usability_reason=assessment.reason,
                    structure_status=edge.structure_status,
                    tags=edge.tags,
                )
                outgoing[head].append(edge_id)
                by_way_to_node[(edge.osm_way_id, tail)].append(edge_id)
                by_way_from_node[(edge.osm_way_id, head)].append(edge_id)

    banned: set[tuple[str, str]] = set()
    forced: dict[str, set[str]] = defaultdict(set)
    notes: list[str] = []
    for restriction in parse_turn_restrictions(osm):
        if not restriction.applies_to_bicycles:
            notes.append(
                f"relation {restriction.relation_id} {restriction.restriction} excepts "
                f"{'/'.join(restriction.except_values)}; not enforced for a bicycle"
            )
            continue
        from_ids, to_ids = _restriction_edges(restriction, by_way_to_node, by_way_from_node)
        if not from_ids or not to_ids:
            notes.append(
                f"relation {restriction.relation_id} "
                f"({restriction.restriction}) touches no admitted edge"
            )
            continue
        if restriction.restriction in NO_RESTRICTIONS:
            for from_id in from_ids:
                for to_id in to_ids:
                    banned.add((from_id, to_id))
            notes.append(
                f"relation {restriction.relation_id} {restriction.restriction}: "
                f"{len(from_ids)}x{len(to_ids)} turn(s) banned"
            )
        elif restriction.restriction in ONLY_RESTRICTIONS:
            for from_id in from_ids:
                forced[from_id].update(to_ids)
            notes.append(
                f"relation {restriction.relation_id} {restriction.restriction}: "
                f"{len(from_ids)} edge(s) restricted to {len(to_ids)} continuation(s)"
            )
        else:
            notes.append(
                f"relation {restriction.relation_id} carries unhandled restriction "
                f"{restriction.restriction!r}; left unenforced and reported"
            )

    return RoutableGraph(
        edges=edges,
        outgoing={node: tuple(ids) for node, ids in outgoing.items()},
        banned_turns=frozenset(banned),
        forced_turns={key: frozenset(value) for key, value in forced.items()},
        restriction_notes=tuple(notes),
    )


def graph_summary(graph: RoutableGraph) -> dict[str, object]:
    lengths = [edge.horizontal_length_m for edge in graph.edges.values()]
    usability = Counter(edge.usability.value for edge in graph.edges.values())
    surfaces = Counter(edge.surface_class.value for edge in graph.edges.values())
    degrees = Counter(len(ids) for ids in graph.outgoing.values())
    return {
        "directed_edges": len(graph.edges),
        "nodes_with_outgoing_edges": len(graph.outgoing),
        "total_directed_length_km": round(math.fsum(lengths) / 1000.0, 3),
        "median_edge_length_m": round(sorted(lengths)[len(lengths) // 2], 2) if lengths else 0.0,
        "usability_counts": dict(sorted(usability.items())),
        "surface_counts": dict(sorted(surfaces.items())),
        "out_degree_histogram": dict(sorted(degrees.items())),
        "banned_turns": len(graph.banned_turns),
        "forced_turn_edges": len(graph.forced_turns),
        "restriction_notes": list(graph.restriction_notes),
    }
