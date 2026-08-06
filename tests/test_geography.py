import math

import pytest

from coastdown import (
    AccessStatus,
    DirectedRoadEdge,
    ElevationSample,
    SourceProvenance,
    StructureStatus,
    build_profile_segments,
    edge_to_road_profile,
    lonlat_to_lambert93,
)


PROVENANCE = SourceProvenance(
    producer="fixture",
    dataset="road-altitude fixture",
    version="1",
    retrieval_date="2026-08-06",
    source_url="tests/fixtures/phase1_oisans_edges.json",
    original_crs="EPSG:2154",
    original_units="metre",
)
TERRAIN = SourceProvenance(
    producer="fixture",
    dataset="terrain fixture",
    version="1",
    retrieval_date="2026-08-06",
    source_url="tests/fixtures/phase1_oisans_edges.json",
    original_crs="EPSG:2154",
    original_units="metre",
)


def sample(x: float, z: float | None, chainage: float = 0) -> ElevationSample:
    return ElevationSample(x, 6_450_000, z, chainage, TERRAIN)


def edge(samples, structure=StructureStatus.NORMAL) -> DirectedRoadEdge:
    return DirectedRoadEdge(
        "test",
        tuple(samples),
        PROVENANCE,
        TERRAIN,
        "EPSG:2154",
        AccessStatus.ADMISSIBLE,
        structure,
    )


def test_wgs84_to_lambert93_reference_coordinate() -> None:
    # Eiffel Tower; reference rounded to metre from an independent EPSG:2154 transform.
    x_m, y_m = lonlat_to_lambert93(2.2945, 48.8584)
    assert x_m == pytest.approx(648_237, abs=2)
    assert y_m == pytest.approx(6_862_272, abs=2)


def test_geometry_contract_and_potential_energy_are_consistent() -> None:
    segment = build_profile_segments(edge([sample(0, 100), sample(100, 90, 100)]))[0]
    assert segment.horizontal_length_m == 100
    assert segment.elevation_change_m == -10
    assert segment.grade_ratio == -0.1
    assert segment.travelled_length_m == pytest.approx(math.sqrt(10_100))
    # m*g*sin(theta)*travelled_length equals m*g*dz for any mass.
    assert math.sin(segment.grade_angle_rad) * segment.travelled_length_m == pytest.approx(-10)


def test_reversing_edge_reverses_samples_and_grades_not_lengths() -> None:
    forward = edge([sample(0, 100, 0), sample(100, 90, 100), sample(200, 95, 200)])
    reverse = forward.reversed()
    forward_segments = build_profile_segments(forward)
    reverse_segments = build_profile_segments(reverse)
    assert [item.elevation_m for item in reverse.samples] == [95, 90, 100]
    assert [item.grade_ratio for item in reverse_segments] == pytest.approx(
        [-item.grade_ratio for item in reversed(forward_segments)]
    )
    assert [item.travelled_length_m for item in reverse_segments] == pytest.approx(
        [item.travelled_length_m for item in reversed(forward_segments)]
    )


@pytest.mark.parametrize(
    "structure", [StructureStatus.BRIDGE, StructureStatus.TUNNEL, StructureStatus.STACKED]
)
def test_terrain_elevation_is_rejected_for_structures(structure: StructureStatus) -> None:
    with pytest.raises(ValueError, match="Terrain elevation"):
        build_profile_segments(edge([sample(0, 100), sample(10, 99, 10)], structure))


def test_missing_duplicate_jump_and_extreme_grade_are_rejected() -> None:
    invalid_edges = [
        edge([sample(0, 100), sample(10, None, 10)]),
        edge([sample(0, 100), sample(0, 99, 0)]),
        edge([sample(0, 100), sample(100, 50, 100)]),
        edge([sample(0, 100), sample(10, 94, 10)]),
    ]
    for invalid in invalid_edges:
        with pytest.raises(ValueError):
            build_profile_segments(invalid)


def test_profile_uses_three_dimensional_travel_distance() -> None:
    profile = edge_to_road_profile(edge([sample(0, 100), sample(100, 90, 100)]))
    assert profile.segment_lengths_m == pytest.approx((math.sqrt(10_100),))
    assert profile.grade_ratios == (-0.1,)
