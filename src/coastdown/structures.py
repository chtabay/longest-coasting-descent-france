"""Phase A2, case 1: give a short structure a roadway profile instead of deleting it.

The Phase 1B rule is not relaxed here and must not be:

    a bridge, tunnel, covered way or non-zero layer must not automatically
    receive terrain elevation.

A terrain model describes the ground — under the deck, above the bore — so
reading it on a structure invents a grade, and a maximum-distance search selects
for invented descents. What this module changes is the *other* half of the old
behaviour: that a way with no usable elevation produced no graph edge at all, so
the road it belonged to was severed. The rule protected the altimetry and
silently damaged the topology.

**No terrain sample is ever read for a structure here.** The roadway is
reconstructed from the two admitted edges it joins, whose elevations come from
the ordinary pipeline. That is a different claim from "the ground under the
bridge", and it is recorded as a reconstruction on every edge that carries one.

Why *short* structures, and where the threshold comes from
----------------------------------------------------------

Not from a round number. The production longitudinal profile is ``raw_25m``:
every ordinary stretch of road is already represented as straight segments of at
most 25 m between sampled elevations. A structure shorter than one such segment
is therefore modelled at exactly the granularity the rest of the network already
uses — interpolating across it adds no approximation that the pipeline does not
already make everywhere else.

Above that length the interpolation would be inventing detail the pipeline
declines to invent for ordinary road, and a viaduct's profile is a design
decision rather than a straight line between its ends. Those belong to case 2
(a source describing the deck) or case 3 (an explicit uncertainty), and until
such a source is verified a long structure stays in case 3 — it never falls back
to case 1.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum

from .geography import StructureStatus
from .graph import RoutableGraph

#: One production profile segment. See the module docstring for why this, and
#: not a round number, is the boundary of case 1.
PRODUCTION_SEGMENT_M = 25.0


class StructureCase(str, Enum):
    """Which of the three Phase A2 treatments a structure qualifies for."""

    SHORT_INTERPOLATED = "case1_short_interpolated"
    NEEDS_ROADWAY_SOURCE = "case2_needs_roadway_source"
    INDETERMINATE = "case3_indeterminate"


@dataclass(frozen=True)
class StructureAssessment:
    """What may be done with one structure way, and why."""

    osm_way_id: int
    trigger: str
    length_m: float
    case: StructureCase
    reason: str
    start_node: int
    end_node: int
    start_elevation_m: float | None = None
    end_elevation_m: float | None = None

    @property
    def reconstructable(self) -> bool:
        return self.case is StructureCase.SHORT_INTERPOLATED


def structure_trigger(tags: Mapping[str, str]) -> str | None:
    """Which tag makes this a structure, or ``None`` for ordinary road.

    Deliberately the same predicate as :func:`coastdown.live_oisans.structure_status`,
    only reported by name instead of by class. A second, subtly different rule
    would let a way count as a structure here and as ordinary road there — and
    ``bridge=no`` is the case that catches it, since it is an explicit statement
    that the way is *not* a bridge.
    """
    if tags.get("bridge") not in {None, "", "no"}:
        return "bridge"
    if tags.get("tunnel") not in {None, "", "no"}:
        return "tunnel"
    if tags.get("covered") == "yes":
        return "covered"
    if tags.get("layer", "0") not in {"0", "+0", "-0"}:
        return "layer"
    return None


def polyline_length_m(geometry: Sequence[Mapping[str, float]]) -> float:
    """Plan length of a raw OSM geometry, in metres."""
    total = 0.0
    for first, second in itertools.pairwise(geometry):
        northing = (second["lat"] - first["lat"]) * 111_320.0
        easting = (second["lon"] - first["lon"]) * 111_320.0 * math.cos(math.radians(first["lat"]))
        total += math.hypot(easting, northing)
    return total


def graph_elevations_by_node(
    graph: RoutableGraph, profiles: Mapping[str, object]
) -> dict[int, float]:
    """Roadway elevation at every node the admitted graph reaches.

    Taken from the profiled edges themselves, so it is the same elevation the
    simulator uses on the road either side of the structure. A node touched by
    several edges is averaged; disagreement there is a property of the elevation
    data, not something this module should silently pick a side on.
    """
    samples: dict[int, list[float]] = {}
    for edge_id, edge in graph.edges.items():
        profile = profiles.get(edge_id)
        if profile is None or not getattr(profile, "simulable", False):
            continue
        samples.setdefault(edge.from_node, []).append(profile.start_elevation_m)
        samples.setdefault(edge.to_node, []).append(profile.end_elevation_m)
    return {node: math.fsum(values) / len(values) for node, values in samples.items()}


def assess(
    way: Mapping[str, object],
    elevations_by_node: Mapping[int, float],
    *,
    max_span_m: float = PRODUCTION_SEGMENT_M,
) -> StructureAssessment | None:
    """Decide which case one raw OSM way falls into. ``None`` if not a structure."""
    tags = dict(way.get("tags") or {})
    trigger = structure_trigger(tags)
    if trigger is None:
        return None
    nodes = list(way.get("nodes") or ())
    geometry = list(way.get("geometry") or ())
    length = polyline_length_m(geometry) if len(geometry) > 1 else 0.0
    start_node = nodes[0] if nodes else -1
    end_node = nodes[-1] if nodes else -1
    start = elevations_by_node.get(start_node)
    end = elevations_by_node.get(end_node)

    if length > max_span_m:
        return StructureAssessment(
            osm_way_id=int(way["id"]),  # type: ignore[arg-type]
            trigger=trigger,
            length_m=length,
            case=StructureCase.NEEDS_ROADWAY_SOURCE,
            reason=(
                f"{length:.1f} m is longer than one {max_span_m:.0f} m production segment, so "
                "its profile is a design decision rather than a straight line between its "
                "ends; it needs a source describing the deck"
            ),
            start_node=start_node,
            end_node=end_node,
        )
    if start is None or end is None:
        missing = "both ends" if start is None and end is None else "one end"
        return StructureAssessment(
            osm_way_id=int(way["id"]),  # type: ignore[arg-type]
            trigger=trigger,
            length_m=length,
            case=StructureCase.INDETERMINATE,
            reason=(
                f"{missing} of the structure touches no admitted, simulable edge, so there is "
                "nothing to interpolate between"
            ),
            start_node=start_node,
            end_node=end_node,
            start_elevation_m=start,
            end_elevation_m=end,
        )

    grade = (end - start) / length if length > 0 else 0.0
    if abs(grade) > 0.5:
        return StructureAssessment(
            osm_way_id=int(way["id"]),  # type: ignore[arg-type]
            trigger=trigger,
            length_m=length,
            case=StructureCase.INDETERMINATE,
            reason=(
                f"the two ends imply a {grade * 100:.0f} % roadway, which no road carries; the "
                "endpoint elevations disagree too much to interpolate between"
            ),
            start_node=start_node,
            end_node=end_node,
            start_elevation_m=start,
            end_elevation_m=end,
        )
    return StructureAssessment(
        osm_way_id=int(way["id"]),  # type: ignore[arg-type]
        trigger=trigger,
        length_m=length,
        case=StructureCase.SHORT_INTERPOLATED,
        reason=(
            f"{length:.1f} m between two admitted edges, implying a {grade * 100:+.1f} % "
            "roadway; shorter than one production segment, so interpolating adds no "
            "approximation the pipeline does not already make"
        ),
        start_node=start_node,
        end_node=end_node,
        start_elevation_m=start,
        end_elevation_m=end,
    )


def assess_all(
    osm: Mapping[str, object],
    elevations_by_node: Mapping[int, float],
    *,
    max_span_m: float = PRODUCTION_SEGMENT_M,
) -> list[StructureAssessment]:
    """Every structure way in an extract, classified."""
    return [
        assessment
        for element in osm.get("elements", ())  # type: ignore[union-attr]
        if element.get("type") == "way" and (element.get("tags") or {}).get("highway")
        for assessment in (assess(element, elevations_by_node, max_span_m=max_span_m),)
        if assessment is not None
    ]


def interpolated_elevations(
    samples: Sequence[object], start_elevation_m: float, end_elevation_m: float
) -> list[float]:
    """A straight roadway between two known ends, sampled where the edge is.

    Interpolation is by chainage along the way, so an unevenly sampled geometry
    stays correct. No terrain value takes part.
    """
    if not samples:
        return []
    span = getattr(samples[-1], "chainage_m", 0.0)
    if span <= 0:
        return [start_elevation_m for _ in samples]
    rise = end_elevation_m - start_elevation_m
    return [
        start_elevation_m + rise * (getattr(sample, "chainage_m", 0.0) / span) for sample in samples
    ]


def admissible_structure_ways(
    assessments: Sequence[StructureAssessment],
) -> frozenset[int]:
    """The OSM way ids case 1 permits the graph to admit."""
    return frozenset(item.osm_way_id for item in assessments if item.reconstructable)


def summarise(assessments: Sequence[StructureAssessment]) -> dict[str, object]:
    """Counts and metres by case, for the report."""
    by_case: dict[str, dict[str, float]] = {}
    for item in assessments:
        bucket = by_case.setdefault(item.case.value, {"ways": 0.0, "metres": 0.0})
        bucket["ways"] += 1
        bucket["metres"] += item.length_m
    return {
        "structures": len(assessments),
        "total_metres": round(math.fsum(item.length_m for item in assessments), 1),
        "by_case": {
            case: {"ways": int(values["ways"]), "metres": round(values["metres"], 1)}
            for case, values in sorted(by_case.items())
        },
        "by_trigger": {
            trigger: sum(1 for item in assessments if item.trigger == trigger)
            for trigger in sorted({item.trigger for item in assessments})
        },
    }


def build_with_reconstructed_structures(
    osm: Mapping[str, object],
    scenario: str,
    store: Mapping[str, float],
    *,
    method: str = "raw_25m",
    max_span_m: float = PRODUCTION_SEGMENT_M,
):
    """Graph and profiles in which case-1 structures carry a roadway, not a hole.

    Two passes, and the order is forced by the problem rather than chosen: the
    elevation to interpolate between is the elevation of the admitted road on
    either side, which is not known until that road has been profiled.

    1. Build and profile the graph exactly as production does, structures
       excluded. Nothing about this pass changes.
    2. Classify every structure against the elevations that pass produced.
    3. Rebuild admitting the case-1 ways, and give each of them a roadway
       interpolated between its two end nodes.

    A structure edge never reads a terrain sample. If its ends are not both on
    the profiled graph after the rebuild — a way split differently, an end that
    only touched a structure — it is admitted for its topology but marked
    non-simulable with the reason, which keeps it out of any result rather than
    letting it carry an invented profile.
    """
    from .elevation_profile import build_profile
    from .elevation_store import elevations_for
    from .graph import build_graph
    from .search import build_edge_profile

    def terrain_profiles(graph: RoutableGraph, skip: frozenset[int]) -> dict:
        built = {}
        for edge_id, edge in graph.edges.items():
            if edge.osm_way_id in skip:
                continue
            base = elevations_for(store, edge.samples)
            if base is None:
                continue
            try:
                shaped = build_profile(method, edge.samples, base)
            except ValueError:
                continue
            built[edge_id] = build_edge_profile(
                edge, shaped.samples, shaped.elevations_m, geometry_samples=edge.samples
            )
        return built

    first = build_graph(osm, scenario)
    assessments = assess_all(
        osm,
        graph_elevations_by_node(first, terrain_profiles(first, frozenset())),
        max_span_m=max_span_m,
    )
    permitted = admissible_structure_ways(assessments)

    graph = build_graph(osm, scenario, reconstructable_structures=permitted)
    profiles = terrain_profiles(graph, permitted)
    node_elevations = graph_elevations_by_node(graph, profiles)

    reconstructed: list[str] = []
    for edge_id, edge in graph.edges.items():
        if edge.osm_way_id not in permitted:
            continue
        start = node_elevations.get(edge.from_node)
        end = node_elevations.get(edge.to_node)
        if start is None or end is None:
            continue
        profiles[edge_id] = build_edge_profile(
            edge,
            edge.samples,
            interpolated_elevations(edge.samples, start, end),
            geometry_samples=edge.samples,
        )
        reconstructed.append(edge_id)

    return graph, profiles, assessments, reconstructed


__all__ = [
    "PRODUCTION_SEGMENT_M",
    "StructureAssessment",
    "StructureCase",
    "StructureStatus",
    "admissible_structure_ways",
    "assess",
    "assess_all",
    "build_with_reconstructed_structures",
    "graph_elevations_by_node",
    "interpolated_elevations",
    "polyline_length_m",
    "structure_trigger",
    "summarise",
]
