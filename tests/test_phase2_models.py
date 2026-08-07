"""Usability, surfaces, sampling, curvature and profile-method behaviour."""

from __future__ import annotations

import itertools
import math

import pytest

from coastdown.curvature import (
    LATERAL_LIMIT_SCENARIOS_M_S2,
    bend_radii,
    circumradius_m,
    permitted_speed_m_s,
)
from coastdown.elevation_profile import (
    METHOD_NAMES,
    build_profile,
    restore_net_elevation,
    robust_median_filter,
    score_profile,
)
from coastdown.sampling import (
    reverse_samples,
    sample_polyline,
    subsample_uniform,
    turn_angles_deg,
)
from coastdown.surfaces import SurfaceClass, all_scenarios, coefficient, rolling_resistance
from coastdown.usability import UsabilityClass, assess_usability

LATITUDE = 45.05
METRE_DEG = 1.0 / (111_320.0 * math.cos(math.radians(LATITUDE)))


def line(length_m: float, points: int = 21, lat: float = LATITUDE):
    return [(index * (length_m / (points - 1)) * METRE_DEG, lat) for index in range(points)]


# --------------------------------------------------------------------------
# usability
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("tags", "expected"),
    [
        ({"highway": "tertiary", "surface": "asphalt"}, UsabilityClass.PAVED_REFERENCE),
        (
            {"highway": "secondary", "surface": "asphalt", "smoothness": "excellent"},
            UsabilityClass.PAVED_REFERENCE,
        ),
        # A sealed but battered road is rideable and no longer the robust reference.
        (
            {"highway": "secondary", "surface": "asphalt", "smoothness": "bad"},
            UsabilityClass.REFERENCE_VTC,
        ),
        # Cobbles are sealed but rough.
        ({"highway": "residential", "surface": "sett"}, UsabilityClass.REFERENCE_VTC),
        # A classified mainland road with no surface tag is assumed sealed.
        ({"highway": "tertiary"}, UsabilityClass.REFERENCE_VTC),
        # A track carries no bicycle permission of its own, so an untagged one
        # stays in review however good its surface is: the conservative access
        # doctrine is not relaxed to fill the extended class.
        ({"highway": "track", "surface": "compacted"}, UsabilityClass.REVIEW),
        (
            {"highway": "track", "surface": "compacted", "bicycle": "yes"},
            UsabilityClass.EXTENDED_VTC,
        ),
        (
            {"highway": "track", "surface": "gravel", "tracktype": "grade2", "bicycle": "yes"},
            UsabilityClass.EXTENDED_VTC,
        ),
        (
            {"highway": "track", "surface": "gravel", "tracktype": "grade4", "bicycle": "yes"},
            UsabilityClass.EXCLUDED,
        ),
        ({"highway": "path", "surface": "grass", "bicycle": "yes"}, UsabilityClass.EXCLUDED),
        ({"highway": "footway"}, UsabilityClass.EXCLUDED),
        ({"highway": "steps", "bicycle": "yes"}, UsabilityClass.EXCLUDED),
        ({"highway": "residential", "bicycle": "no"}, UsabilityClass.EXCLUDED),
        # An untagged path states nothing about permission or surface.
        ({"highway": "path"}, UsabilityClass.REVIEW),
    ],
)
def test_usability_classification(tags, expected) -> None:
    assert assess_usability(tags).usability is expected


def test_a_downhill_mountain_bike_trail_is_not_a_hybrid_bicycle_route() -> None:
    # OSM way 708124926 in the study area: a cycleway by tag, a downhill trail in
    # reality. Phase 1B ranked it beside a departmental road.
    run_dmc = {
        "highway": "cycleway",
        "surface": "dirt",
        "bicycle": "designated",
        "mtb:type": "downhill",
        "mtb:scale": "2",
    }
    assessment = assess_usability(run_dmc)
    assert assessment.usability is UsabilityClass.EXCLUDED
    assert "mtb" in assessment.reason
    # The mtb:scale alone is enough, even without mtb:type.
    assert assess_usability({**run_dmc, "mtb:type": "cross_country"}).usability is (
        UsabilityClass.EXCLUDED
    )
    # Grade 0 is rideable terrain, so it is not excluded on that ground alone.
    assert (
        assess_usability(
            {"highway": "track", "surface": "compacted", "bicycle": "yes", "mtb:scale": "0"}
        ).usability
        is UsabilityClass.EXTENDED_VTC
    )


def test_an_assumed_surface_is_recorded_and_charged_the_degraded_scenario() -> None:
    stated = assess_usability({"highway": "tertiary", "surface": "asphalt"})
    assumed = assess_usability({"highway": "tertiary"})
    assert not stated.surface_is_assumed
    assert assumed.surface_is_assumed
    assert stated.surface_class is SurfaceClass.ASPHALT_GOOD
    assert assumed.surface_class is SurfaceClass.ASPHALT_DEGRADED
    assert coefficient(assumed.surface_class) > coefficient(stated.surface_class)


def test_scenarios_are_nested() -> None:
    paved = assess_usability({"highway": "tertiary", "surface": "asphalt"})
    assert paved.admitted_by("paved_reference")
    assert paved.admitted_by("reference_vtc")
    assert paved.admitted_by("extended_vtc")
    gravel = assess_usability({"highway": "track", "surface": "compacted", "bicycle": "yes"})
    assert not gravel.admitted_by("paved_reference")
    assert not gravel.admitted_by("reference_vtc")
    assert gravel.admitted_by("extended_vtc")


# --------------------------------------------------------------------------
# surfaces
# --------------------------------------------------------------------------


def test_rolling_resistance_scenarios_are_ordered_and_bounded() -> None:
    ordered = [
        SurfaceClass.ASPHALT_GOOD,
        SurfaceClass.ASPHALT_DEGRADED,
        SurfaceClass.STABILISED_GRAVEL,
        SurfaceClass.COMPACT_TRACK,
        SurfaceClass.DIRT,
    ]
    centrals = [coefficient(item) for item in ordered]
    assert centrals == sorted(centrals), "resistance must rise as the surface degrades"
    for scenario in all_scenarios():
        assert scenario.low <= scenario.central <= scenario.high
        assert scenario.basis and scenario.uncertainty
    # The unpaved classes must not pretend to be better known than they are.
    assert (
        rolling_resistance(SurfaceClass.DIRT).relative_width
        > rolling_resistance(SurfaceClass.ASPHALT_GOOD).relative_width
    )


def test_an_unsuitable_surface_has_no_coefficient() -> None:
    with pytest.raises(ValueError, match="UNSUITABLE"):
        rolling_resistance(SurfaceClass.UNSUITABLE)


# --------------------------------------------------------------------------
# sampling
# --------------------------------------------------------------------------


def test_sampling_lands_on_exact_multiples_of_the_requested_spacing() -> None:
    samples = sample_polyline(line(200.0), 10.0)
    grid = [sample.chainage_m for sample in samples if sample.on_uniform_grid]
    assert grid[0] == 0.0
    for position in grid[:-1]:
        assert abs(position / 10.0 - round(position / 10.0)) < 1e-6
    assert samples[-1].chainage_m == pytest.approx(200.0, abs=0.5)


def test_horizontal_length_survives_sampling() -> None:
    coordinates = line(500.0, points=41)
    samples = sample_polyline(coordinates, 25.0)
    assert samples[-1].chainage_m == pytest.approx(500.0, abs=1.0)


def test_a_sharp_vertex_is_retained_even_at_a_coarse_spacing() -> None:
    # A 90 degree corner 12 m along a 60 m polyline: a 25 m grid would skip it.
    corner = [
        (0.0, LATITUDE),
        (12 * METRE_DEG, LATITUDE),
        (12 * METRE_DEG, LATITUDE + 48 * METRE_DEG),
    ]
    samples = sample_polyline(corner, 25.0, keep_vertex_above_deg=15.0)
    assert any(
        sample.is_source_vertex and abs(sample.chainage_m - 12.0) < 1.0 for sample in samples
    )
    strict = sample_polyline(corner, 25.0, keep_vertex_above_deg=180.0)
    assert not any(abs(sample.chainage_m - 12.0) < 0.5 for sample in strict[1:-1])


def test_reversing_samples_mirrors_them_without_moving_the_ground_points() -> None:
    samples = sample_polyline(line(300.0), 10.0)
    mirrored = reverse_samples(samples)
    assert len(mirrored) == len(samples)
    assert mirrored[0].chainage_m == 0.0
    assert mirrored[-1].chainage_m == pytest.approx(samples[-1].chainage_m)
    assert {(round(s.x_m, 6), round(s.y_m, 6)) for s in samples} == {
        (round(s.x_m, 6), round(s.y_m, 6)) for s in mirrored
    }


def test_subsampling_reproduces_a_coarser_grid_exactly() -> None:
    samples = sample_polyline(line(500.0, points=51), 5.0)
    coarse = subsample_uniform(samples, 5.0, 25.0)
    positions = [sample.chainage_m for sample in coarse[:-1]]
    assert all(abs(value % 25.0) < 1e-6 for value in positions)
    with pytest.raises(ValueError, match="integer multiple"):
        subsample_uniform(samples, 5.0, 7.0)


def test_turn_angles_are_zero_on_a_straight_line() -> None:
    projected = [(float(index) * 10.0, 0.0) for index in range(6)]
    assert max(turn_angles_deg(projected)) < 1e-9


# --------------------------------------------------------------------------
# curvature
# --------------------------------------------------------------------------


def test_circumradius_recovers_a_known_circle() -> None:
    radius = 40.0
    points = [(radius * math.cos(angle), radius * math.sin(angle)) for angle in (0.0, 0.5, 1.0)]
    assert circumradius_m(*points) == pytest.approx(radius, rel=1e-9)
    assert math.isinf(circumradius_m((0.0, 0.0), (10.0, 0.0), (20.0, 0.0)))


def test_metre_scale_digitising_noise_does_not_invent_a_bend() -> None:
    # A straight road whose vertices wobble by 0.4 m, which consecutive-vertex
    # curvature would report as a radius of a few metres.
    chainage = [float(index) * 5.0 for index in range(40)]
    xs = [float(index) * 5.0 for index in range(40)]
    ys = [0.4 * (-1) ** index for index in range(40)]
    bends = bend_radii(chainage, xs, ys, xs, ys, chord_m=15.0)
    assert all(bend.radius_m > 30.0 for bend in bends), "noise must not become a hairpin"


def test_a_real_bend_is_measured_close_to_its_true_radius() -> None:
    radius = 25.0
    angles = [index * 0.08 for index in range(40)]
    xs = [radius * math.cos(angle) for angle in angles]
    ys = [radius * math.sin(angle) for angle in angles]
    chainage = [radius * angle for angle in angles]
    bends = bend_radii(chainage, xs, ys, xs, ys, chord_m=15.0)
    assert bends
    assert min(bend.radius_m for bend in bends) == pytest.approx(radius, rel=0.05)


def test_permitted_speed_follows_the_scenario_limit() -> None:
    limit = LATERAL_LIMIT_SCENARIOS_M_S2["nominal"]
    speed = permitted_speed_m_s(25.0, limit)
    assert speed * speed / 25.0 == pytest.approx(limit)
    assert permitted_speed_m_s(25.0, LATERAL_LIMIT_SCENARIOS_M_S2["conservative"]) < speed
    assert permitted_speed_m_s(25.0, LATERAL_LIMIT_SCENARIOS_M_S2["committed"]) > speed


# --------------------------------------------------------------------------
# profile methods
# --------------------------------------------------------------------------


def noisy_profile():
    """A 3 % descent quantised onto a coarse terrain grid, as the service does."""
    samples = sample_polyline(line(400.0, points=41), 5.0)
    elevations = []
    for sample in samples:
        true_height = 1000.0 - 0.03 * sample.chainage_m
        elevations.append(round(true_height / 1.5) * 1.5)  # 1.5 m quantisation
    return samples, elevations


def test_the_median_filter_removes_a_spike_a_mean_would_smear() -> None:
    chainage = [float(index) * 5.0 for index in range(21)]
    clean = [100.0 - 0.02 * value for value in chainage]
    spiked = list(clean)
    spiked[10] += 8.0
    filtered = robust_median_filter(chainage, spiked, 20.0)
    assert abs(filtered[10] - clean[10]) < 1.0
    assert max(abs(a - b) for a, b in zip(filtered, clean)) < 1.5


def test_restoring_the_net_elevation_is_exact_and_linear() -> None:
    chainage = [float(index) * 10.0 for index in range(11)]
    values = [100.0 - 0.01 * value for value in chainage]
    shifted = [value + 3.0 for value in values]
    shifted[-1] -= 5.0
    restored = restore_net_elevation(chainage, shifted, values[-1] - values[0])
    assert restored[-1] - restored[0] == pytest.approx(values[-1] - values[0], abs=1e-9)


def test_every_method_builds_and_only_some_preserve_the_elevation_budget() -> None:
    samples, elevations = noisy_profile()
    reference_net = elevations[-1] - elevations[0]
    reference_ascent = math.fsum(
        max(0.0, after - before) for before, after in itertools.pairwise(elevations)
    )
    scores = {}
    for method in METHOD_NAMES:
        built = build_profile(method, samples, elevations)
        scores[method] = score_profile(
            built, reference_net_dz_m=reference_net, reference_ascent_m=reference_ascent
        )
    # The raw and constrained methods keep the measured budget exactly.
    for method in ("raw_10m", "raw_25m", "net_dz_constrained"):
        assert abs(scores[method].net_dz_error_m) < 1e-6, method
    # Coarser sampling and filtering both suppress the quantisation ascent.
    assert scores["raw_25m"].ascent_m <= scores["raw_10m"].ascent_m
    assert scores["net_dz_constrained"].ascent_m <= scores["raw_10m"].ascent_m


def test_an_unknown_method_is_refused() -> None:
    samples, elevations = noisy_profile()
    with pytest.raises(ValueError, match="Unknown profile method"):
        build_profile("gaussian_blur", samples, elevations)
