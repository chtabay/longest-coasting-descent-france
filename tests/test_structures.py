"""Phase A2 case 1: a short structure gets a roadway, not a deletion.

The rule these tests protect is narrow and easy to break by accident. A
structure must never receive *terrain* elevation — a terrain model describes the
ground under a deck or above a bore, and on a maximum-distance objective an
invented descent is exactly what the search selects for. What it may receive is
a roadway **reconstructed from the admitted road on either side**, which is a
different claim about a different surface.

The failure mode worth naming: relaxing the length threshold, or falling back to
case 1 when a roadway source is missing, would let a viaduct's profile be
guessed as a straight line. Each of those is asserted against here.
"""

from __future__ import annotations

import itertools
import math

import pytest
from test_phase2_graph_and_search import ASPHALT, osm, straight, way

from coastdown.sampling import SamplePoint
from coastdown.structures import (
    PRODUCTION_SEGMENT_M,
    StructureCase,
    admissible_structure_ways,
    assess,
    assess_all,
    interpolated_elevations,
    polyline_length_m,
    structure_trigger,
    summarise,
)


def structure(way_id: int, length_m: float, tags: dict[str, str], first: int, last: int) -> dict:
    built = way(way_id, straight(0, length_m), {**ASPHALT, **tags})
    built["nodes"][0] = first
    built["nodes"][-1] = last
    return built


@pytest.mark.parametrize(
    ("tags", "expected"),
    [
        ({"bridge": "yes"}, "bridge"),
        ({"tunnel": "yes"}, "tunnel"),
        ({"covered": "yes"}, "covered"),
        ({"tunnel": "no"}, None),
        ({"layer": "-1"}, "layer"),
        ({"layer": "2"}, "layer"),
        ({"layer": "0"}, None),
        ({"bridge": "no"}, None),
        ({}, None),
    ],
)
def test_the_trigger_matches_the_phase_1b_rule(tags: dict[str, str], expected: str | None) -> None:
    """`layer=0` and `bridge=no` are ordinary road and must stay admitted."""
    assert structure_trigger(tags) == expected


def test_a_short_structure_between_two_known_ends_is_case_one() -> None:
    """The D 211 underpass, in miniature: 8 m between two profiled edges."""
    result = assess(structure(1, 8.0, {"layer": "-1"}, 10, 20), {10: 1000.0, 20: 999.0})
    assert result is not None
    assert result.case is StructureCase.SHORT_INTERPOLATED
    assert result.reconstructable
    assert result.length_m == pytest.approx(8.0, abs=0.5)
    assert "-12" in result.reason, "the reason must state the roadway grade it implies"


def test_a_long_structure_is_never_interpolated_however_well_connected() -> None:
    """A viaduct's profile is a design decision, not a line between its ends.

    Both ends are known here and the implied grade is gentle, so every
    ingredient of case 1 is present except the length. It must still be refused.
    """
    result = assess(structure(1, 400.0, {"bridge": "yes"}, 10, 20), {10: 1000.0, 20: 996.0})
    assert result is not None
    assert result.case is StructureCase.NEEDS_ROADWAY_SOURCE
    assert not result.reconstructable
    assert "deck" in result.reason


def test_a_missing_roadway_source_falls_to_case_three_not_back_to_case_one() -> None:
    """The rule that stops the easy answer leaking into the hard problem."""
    long_bridge = assess(structure(1, 300.0, {"bridge": "yes"}, 10, 20), {10: 1000.0, 20: 999.0})
    assert long_bridge is not None
    assert long_bridge.case is not StructureCase.SHORT_INTERPOLATED
    assert not admissible_structure_ways([long_bridge])


def test_a_structure_with_nothing_to_interpolate_between_is_indeterminate() -> None:
    for known in ({}, {10: 1000.0}, {20: 999.0}):
        result = assess(structure(1, 8.0, {"tunnel": "yes"}, 10, 20), known)
        assert result is not None
        assert result.case is StructureCase.INDETERMINATE
        assert not result.reconstructable


def test_endpoint_elevations_that_disagree_absurdly_are_refused() -> None:
    """A 10 m structure between ends 40 m apart is a data fault, not a ramp.

    Interpolating it would manufacture a 400 % descent — precisely the kind of
    invented grade the whole rule exists to prevent.
    """
    result = assess(structure(1, 10.0, {"bridge": "yes"}, 10, 20), {10: 1040.0, 20: 1000.0})
    assert result is not None
    assert result.case is StructureCase.INDETERMINATE
    assert "no road carries" in result.reason


def test_the_threshold_is_one_production_segment_and_is_stated_as_such() -> None:
    """Not a round number: the profile already models road at this granularity."""
    assert PRODUCTION_SEGMENT_M == 25.0
    just_under = assess(structure(1, 24.0, {"bridge": "yes"}, 10, 20), {10: 1000.0, 20: 999.0})
    just_over = assess(structure(2, 26.0, {"bridge": "yes"}, 10, 20), {10: 1000.0, 20: 999.0})
    assert just_under is not None and just_over is not None
    assert just_under.case is StructureCase.SHORT_INTERPOLATED
    assert just_over.case is StructureCase.NEEDS_ROADWAY_SOURCE


def test_the_interpolated_roadway_is_straight_between_its_ends() -> None:
    samples = tuple(
        SamplePoint(
            longitude=6.0 + index * 1e-4,
            latitude=45.0,
            x_m=index * 4.0,
            y_m=0.0,
            chainage_m=index * 4.0,
            on_uniform_grid=True,
            is_source_vertex=True,
        )
        for index in range(5)
    )
    values = interpolated_elevations(samples, 1000.0, 996.0)
    assert values[0] == pytest.approx(1000.0)
    assert values[-1] == pytest.approx(996.0)
    steps = [second - first for first, second in itertools.pairwise(values)]
    assert all(step == pytest.approx(steps[0]) for step in steps), "a straight line, not a curve"


def test_an_unevenly_sampled_structure_still_interpolates_by_chainage() -> None:
    """Interpolating by index instead of chainage would tilt the roadway."""
    samples = (
        SamplePoint(6.0, 45.0, 0.0, 0.0, 0.0, True, True),
        SamplePoint(6.0001, 45.0, 1.0, 0.0, 1.0, False, False),
        SamplePoint(6.0009, 45.0, 10.0, 0.0, 10.0, True, True),
    )
    values = interpolated_elevations(samples, 100.0, 90.0)
    assert values == [pytest.approx(100.0), pytest.approx(99.0), pytest.approx(90.0)]


def test_a_zero_length_structure_cannot_produce_a_slope() -> None:
    samples = (SamplePoint(6.0, 45.0, 0.0, 0.0, 0.0, True, True),)
    assert interpolated_elevations(samples, 100.0, 90.0) == [100.0]
    assert interpolated_elevations((), 100.0, 90.0) == []


def test_assess_all_ignores_ordinary_road_entirely() -> None:
    plain = way(1, straight(0, 100), ASPHALT)
    bridge = structure(2, 10.0, {"bridge": "yes"}, 10, 20)
    assessments = assess_all(osm(plain, bridge), {10: 1000.0, 20: 999.5})
    assert [item.osm_way_id for item in assessments] == [2]


def test_the_summary_accounts_for_every_structure_and_every_metre() -> None:
    ways = [
        structure(1, 8.0, {"bridge": "yes"}, 10, 20),
        structure(2, 300.0, {"tunnel": "yes"}, 30, 40),
        structure(3, 12.0, {"covered": "yes"}, 50, 60),
    ]
    assessments = assess_all(osm(*ways), {10: 1000.0, 20: 999.0})
    report = summarise(assessments)
    assert report["structures"] == 3
    assert sum(bucket["ways"] for bucket in report["by_case"].values()) == 3
    assert report["total_metres"] == pytest.approx(
        math.fsum(polyline_length_m(item["geometry"]) for item in ways), abs=1.0
    )
    assert report["by_trigger"] == {"bridge": 1, "covered": 1, "tunnel": 1}
