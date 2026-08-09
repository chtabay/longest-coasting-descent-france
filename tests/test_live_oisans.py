import itertools

import pytest

from coastdown import AccessStatus, StructureStatus
from coastdown.live_oisans import (
    classify_access,
    densify_lonlat,
    extract_elevations,
    parse_osm_directed_edges,
    structure_status,
)


def test_access_is_conservative_and_honors_explicit_bicycle_tags() -> None:
    assert classify_access({"highway": "track"}) is AccessStatus.REVIEW
    assert classify_access({"highway": "track", "bicycle": "yes"}) is AccessStatus.ADMISSIBLE
    assert classify_access({"highway": "residential", "bicycle": "no"}) is AccessStatus.PROHIBITED
    assert classify_access({"highway": "path", "access": "private"}) is AccessStatus.PROHIBITED


def test_structure_priority_and_layer_detection() -> None:
    assert structure_status({"bridge": "yes", "layer": "1"}) is StructureStatus.BRIDGE
    assert structure_status({"tunnel": "yes"}) is StructureStatus.TUNNEL
    assert structure_status({"layer": "-1"}) is StructureStatus.STACKED
    assert structure_status({}) is StructureStatus.NORMAL


def test_osm_oneway_and_bicycle_override_build_expected_directions() -> None:
    payload = {
        "elements": [
            {
                "type": "way",
                "id": 10,
                "tags": {"highway": "secondary", "oneway": "yes"},
                "geometry": [{"lon": 6.0, "lat": 45.0}, {"lon": 6.01, "lat": 45.01}],
            },
            {
                "type": "way",
                "id": 11,
                "tags": {"highway": "secondary", "oneway": "yes", "oneway:bicycle": "no"},
                "geometry": [{"lon": 6.0, "lat": 45.0}, {"lon": 6.01, "lat": 45.01}],
            },
        ]
    }
    edges = parse_osm_directed_edges(payload)
    assert [(edge.osm_way_id, edge.direction) for edge in edges] == [
        (10, "forward"),
        (11, "forward"),
        (11, "reverse"),
    ]


def test_densification_is_deterministic_and_spacing_bounded() -> None:
    first = densify_lonlat(((6.0, 45.0), (6.001, 45.0)), 25)
    second = densify_lonlat(((6.0, 45.0), (6.001, 45.0)), 25)
    assert first == second
    assert first[0][4] == 0
    assert first[-1][4] > 70
    assert all(after[4] - before[4] <= 25 for before, after in itertools.pairwise(first))


def test_altimetry_response_validation() -> None:
    assert extract_elevations({"elevations": [100, {"z": 101.5}]}, 2) == (100, 101.5)
    with pytest.raises(ValueError):
        extract_elevations({"elevations": [100]}, 2)
