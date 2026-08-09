"""Non-regression tests over frozen, verbatim extracts of the real sources.

The fixtures are small subsets of actual Overpass and IGN Geoplateforme
responses, redistributed under ODbL 1.0 and Licence Ouverte 2.0 with the
attribution recorded inside each file.  They pin the behaviour that only real
data exposes: the no-data sentinel, contraflow tagging, implicit roundabout
direction, structures that must not receive terrain elevation, and the way a
bare-earth model behaves on a hairpin.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from coastdown import (
    AccessStatus,
    DirectedRoadEdge,
    ElevationSample,
    RoadProfile,
    SourceProvenance,
    StructureStatus,
    build_profile_segments,
    simulate_profile,
)
from coastdown.live_oisans import (
    bicycle_directions,
    box_filter_elevations,
    densify_lonlat,
    extract_elevations,
    hairpin_turns,
    parse_osm_directed_edges,
    parse_turn_restrictions,
    profile_metrics,
)

FIXTURES = Path(__file__).parent / "fixtures"
OSM_EXTRACT = json.loads((FIXTURES / "phase1b_osm_extract.json").read_text(encoding="utf-8"))
ALTIMETRY = json.loads((FIXTURES / "phase1b_altimetry_response.json").read_text(encoding="utf-8"))
PROFILE = json.loads((FIXTURES / "phase1b_profile_elevations.json").read_text(encoding="utf-8"))

TERRAIN = SourceProvenance(
    producer="IGN",
    dataset="RGE ALTI frozen extract",
    version="test",
    retrieval_date="2026-08-07",
    source_url=str(FIXTURES / "phase1b_profile_elevations.json"),
    original_crs="EPSG:2154",
    original_units="metre",
    elevation_model_kind="terrain",
)
GEOMETRY = SourceProvenance(
    producer="OpenStreetMap contributors",
    dataset="OSM frozen extract",
    version="test",
    retrieval_date="2026-08-07",
    source_url=str(FIXTURES / "phase1b_osm_extract.json"),
    original_crs="EPSG:4326",
    original_units="degree",
)


def way(way_id: int) -> dict:
    return next(item for item in OSM_EXTRACT["elements"] if item.get("id") == way_id)


def tags_of(way_id: int) -> dict[str, str]:
    return {str(key): str(value) for key, value in way(way_id)["tags"].items()}


def build_edge(points, elevations, structure=StructureStatus.NORMAL) -> DirectedRoadEdge:
    samples = tuple(
        ElevationSample(point[2], point[3], elevation, point[4], TERRAIN)
        for point, elevation in zip(points, elevations)
    )
    return DirectedRoadEdge(
        "frozen",
        samples,
        GEOMETRY,
        TERRAIN,
        "EPSG:2154",
        AccessStatus.ADMISSIBLE,
        structure,
    )


def test_the_suite_cannot_reach_the_network() -> None:
    """Prove the guarantee instead of trusting it.

    If this ever passes silently, a future test could start depending on
    Overpass or the Geoplateforme and the build would go red for reasons that
    have nothing to do with the code.
    """
    import urllib.request

    from conftest import NetworkAccessInTestError

    # The guard raises a plain RuntimeError subclass, which urllib does not wrap,
    # so the assertion fails if the guard is ever dropped even on an offline machine.
    with pytest.raises(NetworkAccessInTestError):
        urllib.request.urlopen("https://overpass-api.de/api/status", timeout=5)


def test_fixtures_carry_producer_licence_and_attribution() -> None:
    for document in (OSM_EXTRACT, ALTIMETRY, PROFILE):
        provenance = document["_provenance"]
        assert provenance["producer"]
        assert provenance["licence"]
        assert provenance["attribution"]
    assert OSM_EXTRACT["_provenance"]["licence"] == "ODbL 1.0"
    assert OSM_EXTRACT["osm3s"]["timestamp_osm_base"]


def test_frozen_extract_yields_stable_directed_edges() -> None:
    edges = parse_osm_directed_edges(OSM_EXTRACT)
    assert len(edges) == 31
    assert Counter(edge.access_status for edge in edges) == {
        AccessStatus.ADMISSIBLE: 17,
        AccessStatus.REVIEW: 10,
        AccessStatus.PROHIBITED: 4,
    }
    assert Counter(edge.structure_status for edge in edges) == {
        StructureStatus.NORMAL: 21,
        StructureStatus.TUNNEL: 6,
        StructureStatus.BRIDGE: 2,
        StructureStatus.STACKED: 2,
    }
    # Node identifiers survive orientation, reversed for the reverse direction.
    forward = next(edge for edge in edges if edge.edge_id == "osm-way-30483374-forward")
    reverse = next(edge for edge in edges if edge.edge_id == "osm-way-30483374-reverse")
    assert forward.node_ids == tuple(reversed(reverse.node_ids))
    assert forward.lonlat == tuple(reversed(reverse.lonlat))


def test_real_oneway_bicycle_contraflow_restores_both_directions() -> None:
    # Way 91229698 is tagged oneway=yes with oneway:bicycle=no, the contraflow
    # exemption: a bicycle may legally travel it in both directions.
    tags = tags_of(91229698)
    assert tags["oneway"] == "yes"
    assert tags["oneway:bicycle"] == "no"
    assert bicycle_directions(tags) == ("forward", "reverse")


def test_real_roundabout_implies_direction_without_a_oneway_tag() -> None:
    # Way 28417066 carries junction=roundabout and no oneway tag.
    tags = tags_of(28417066)
    assert "oneway" not in tags
    assert tags["junction"] == "roundabout"
    assert bicycle_directions(tags) == ("forward",)


def test_real_ways_classify_into_the_expected_structures() -> None:
    edges = {edge.osm_way_id: edge for edge in parse_osm_directed_edges(OSM_EXTRACT)}
    assert edges[30483374].structure_status is StructureStatus.BRIDGE
    assert edges[23258945].structure_status is StructureStatus.TUNNEL
    assert edges[171335071].structure_status is StructureStatus.TUNNEL  # covered=yes
    assert edges[122019455].structure_status is StructureStatus.STACKED  # layer != 0


def test_real_ways_never_gain_permission_they_do_not_declare() -> None:
    edges = {edge.osm_way_id: edge for edge in parse_osm_directed_edges(OSM_EXTRACT)}
    assert edges[8658216].access_status is AccessStatus.PROHIBITED  # access=private
    assert edges[23370662].access_status is AccessStatus.PROHIBITED  # bicycle=no
    assert edges[23258945].access_status is AccessStatus.REVIEW  # untagged track
    assert edges[28417065].access_status is AccessStatus.ADMISSIBLE  # secondary
    assert "private" in edges[8658216].access_reason
    assert "no bicycle permission" in edges[23258945].access_reason


def test_real_turn_restrictions_keep_their_from_via_to_members() -> None:
    restrictions = parse_turn_restrictions(OSM_EXTRACT)
    assert len(restrictions) == 4
    assert {item.restriction for item in restrictions} == {"no_left_turn"}
    first = next(item for item in restrictions if item.relation_id == 1781195)
    assert first.from_way_ids == (132695638,)
    assert first.via_node_ids == (1459263557,)
    assert first.to_way_ids == (132695614,)
    assert first.via_way_ids == ()


def test_real_altimetry_no_data_sentinel_becomes_missing() -> None:
    # The service answers HTTP 200 with z = -99999.0 outside coverage.
    response = ALTIMETRY["response"]
    assert response["elevations"][2] == -99999.0
    assert extract_elevations(response, 3) == (719.61, 1819.49, None)


def test_missing_elevation_stops_a_profile_instead_of_propagating() -> None:
    points = densify_lonlat([(6.0, 45.0), (6.001, 45.0)], 25.0)
    elevations = [100.0] * len(points)
    elevations[1] = None
    with pytest.raises(ValueError, match="Missing elevation"):
        build_profile_segments(build_edge(points, elevations))


def test_terrain_model_is_refused_on_the_real_bridge() -> None:
    bridge = way(30483374)
    points = densify_lonlat([(p["lon"], p["lat"]) for p in bridge["geometry"]], 10.0)
    edge = build_edge(
        points, [700.0 + index for index in range(len(points))], StructureStatus.BRIDGE
    )
    assert edge.elevation_provenance.measures_bare_ground
    with pytest.raises(ValueError, match="Terrain elevation"):
        build_profile_segments(edge)


def frozen_profile_points():
    geometry = way(PROFILE["osm_way_id"])["geometry"]
    points = densify_lonlat(
        [(p["lon"], p["lat"]) for p in geometry], PROFILE["requested_spacing_m"]
    )
    assert len(points) == PROFILE["point_count"]
    return points, [float(value) for value in PROFILE["elevations_m"]]


def test_frozen_real_profile_reproduces_its_geometry_and_grade_statistics() -> None:
    points, elevations = frozen_profile_points()
    segments = build_profile_segments(
        build_edge(points, elevations), max_abs_grade_ratio=10.0, max_elevation_jump_m=250.0
    )
    metrics = profile_metrics(segments, max_simulable_grade_ratio=0.5, elevation_break_m=5.0)
    assert metrics.segment_count == 150
    assert metrics.horizontal_length_m == pytest.approx(1163.519, abs=0.01)
    assert metrics.travelled_length_m == pytest.approx(1207.119, abs=0.01)
    assert metrics.net_dz_m == pytest.approx(254.100, abs=0.01)
    assert metrics.ascent_m == pytest.approx(266.370, abs=0.01)
    assert metrics.descent_m == pytest.approx(12.270, abs=0.01)
    assert metrics.min_grade_ratio == pytest.approx(-0.486888, abs=1e-6)
    assert metrics.max_grade_ratio == pytest.approx(0.752828, abs=1e-6)
    # Eleven segments of a real bare-earth profile exceed the simulator's bound.
    assert metrics.contract_violation_count == 11
    assert metrics.elevation_break_count == 1


def test_requested_spacing_is_only_an_upper_bound_on_real_geometry() -> None:
    points, elevations = frozen_profile_points()
    segments = build_profile_segments(
        build_edge(points, elevations), max_abs_grade_ratio=10.0, max_elevation_jump_m=250.0
    )
    metrics = profile_metrics(segments, max_simulable_grade_ratio=0.5, elevation_break_m=5.0)
    # 10 m was requested; densification never drops a source vertex, so the
    # realised spacing is dictated by the OSM geometry wherever it is finer.
    assert metrics.realised_max_spacing_m <= PROFILE["requested_spacing_m"]
    assert metrics.realised_mean_spacing_m == pytest.approx(7.757, abs=0.01)
    assert metrics.realised_min_spacing_m == pytest.approx(3.079, abs=0.01)


def test_conditioning_preserves_the_elevation_budget_and_cuts_noise() -> None:
    points, elevations = frozen_profile_points()
    chainage = [point[4] for point in points]
    conditioned = box_filter_elevations(chainage, elevations, 25.0)
    assert len(conditioned) == len(elevations)
    # A centred moving average keeps the mean elevation and the overall drop.
    assert sum(conditioned) / len(conditioned) == pytest.approx(
        sum(elevations) / len(elevations), abs=0.05
    )
    assert conditioned[-1] - conditioned[0] == pytest.approx(
        elevations[-1] - elevations[0], abs=2.5
    )
    raw_segments = build_profile_segments(
        build_edge(points, elevations), max_abs_grade_ratio=10.0, max_elevation_jump_m=250.0
    )
    conditioned_segments = build_profile_segments(
        build_edge(points, conditioned), max_abs_grade_ratio=10.0, max_elevation_jump_m=250.0
    )
    raw = profile_metrics(raw_segments, max_simulable_grade_ratio=0.5, elevation_break_m=5.0)
    smooth = profile_metrics(
        conditioned_segments, max_simulable_grade_ratio=0.5, elevation_break_m=5.0
    )
    # Cumulative ascent is where sampling noise accumulates, so it must fall.
    assert smooth.ascent_m < raw.ascent_m
    assert smooth.travelled_length_m < raw.travelled_length_m
    assert smooth.contract_violation_count < raw.contract_violation_count


def test_conditioning_does_not_bound_the_grade_on_a_hairpin() -> None:
    """Smoothing along chainage can steepen a bend rather than relax it.

    On a hairpin, two points a few metres apart in chainage sit on different
    levels of the bend.  Averaging pulls them together, and the segments either
    side must then absorb the difference.  The declared scenario is therefore
    not a guarantee of admissibility, which is why the pipeline still reports a
    contract violation instead of assuming conditioning fixed the profile.
    """
    points, elevations = frozen_profile_points()
    assert len(hairpin_turns(points)) == 21
    conditioned = box_filter_elevations([point[4] for point in points], elevations, 25.0)
    raw = profile_metrics(
        build_profile_segments(
            build_edge(points, elevations), max_abs_grade_ratio=10.0, max_elevation_jump_m=250.0
        ),
        max_simulable_grade_ratio=0.5,
        elevation_break_m=5.0,
    )
    smooth = profile_metrics(
        build_profile_segments(
            build_edge(points, conditioned), max_abs_grade_ratio=10.0, max_elevation_jump_m=250.0
        ),
        max_simulable_grade_ratio=0.5,
        elevation_break_m=5.0,
    )
    assert smooth.max_grade_ratio > raw.max_grade_ratio
    assert smooth.contract_violation_count == 3


def test_a_contract_violating_real_profile_is_never_handed_to_the_simulator() -> None:
    points, elevations = frozen_profile_points()
    segments = build_profile_segments(
        build_edge(points, elevations), max_abs_grade_ratio=10.0, max_elevation_jump_m=250.0
    )
    metrics = profile_metrics(segments, max_simulable_grade_ratio=0.5, elevation_break_m=5.0)
    assert metrics.contract_violation_count > 0
    with pytest.raises(ValueError, match=r"grade_ratios"):
        RoadProfile(
            [segment.travelled_length_m for segment in segments],
            [segment.grade_ratio for segment in segments],
        )


def test_an_admissible_real_profile_simulates_end_to_end() -> None:
    _, elevations = frozen_profile_points()
    # Reverse the way so the frozen ascent becomes a descent, then keep the
    # longest uninterrupted run of segments inside the simulator's validity
    # bound. The artefacts are scattered along the path, so a leading window
    # would be only a handful of segments.
    reversed_points = densify_lonlat(
        [(p["lon"], p["lat"]) for p in reversed(way(PROFILE["osm_way_id"])["geometry"])],
        PROFILE["requested_spacing_m"],
    )
    reversed_elevations = list(reversed(elevations))
    segments = build_profile_segments(
        build_edge(reversed_points, reversed_elevations),
        max_abs_grade_ratio=10.0,
        max_elevation_jump_m=250.0,
    )
    admissible: list = []
    current: list = []
    for segment in segments:
        if abs(segment.grade_ratio) > 0.5:
            current = []
            continue
        current.append(segment)
        if len(current) > len(admissible):
            admissible = list(current)
    assert len(admissible) > 10
    result = simulate_profile(
        RoadProfile(
            [segment.travelled_length_m for segment in admissible],
            [segment.grade_ratio for segment in admissible],
        )
    )
    assert result.stop_reason in {"route_end", "speed_threshold"}
    assert result.elapsed_time_s > 0
    assert result.moving_time_s + result.stationary_time_s == pytest.approx(
        result.elapsed_time_s, abs=1e-9
    )
