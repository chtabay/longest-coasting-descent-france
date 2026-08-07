"""Whether a standard hybrid bicycle can actually ride a way, not merely whether it may.

Phase 1B ranked ways on legal cyclability alone, which let OSM way 708124926
("Run DMC", `highway=cycleway`, `surface=dirt`, `mtb:type=downhill`,
`mtb:scale=2`) sit beside a departmental road as if the two were interchangeable.
They are not: one is a downhill mountain-bike trail and the other is asphalt.

Classification is therefore two-stage. Legal access is decided first, by
:func:`coastdown.live_oisans.classify_access`, and nothing here can grant a
permission that stage refused. What remains is a question about the machine: can
the reference bicycle roll this way, and how confident is that answer.

The classes are nested by robustness::

    paved_reference  <  reference_vtc  <  extended_vtc

``paved_reference`` demands explicit evidence of a sealed surface and is the
subset on which the primary regional ranking is computed. ``reference_vtc``
additionally accepts a classified road whose surface tag is missing, because in
mainland France such a road is sealed in the overwhelming majority of cases —
but the assumption is recorded on the edge and is paid for in the physics, since
those edges are given the degraded-asphalt rolling-resistance scenario rather
than the good-asphalt one. ``extended_vtc`` accepts firm unsealed ways whose
resistance is materially more uncertain.

Silence is never read as permission or as quality: an untagged path stays in
``review`` rather than drifting into a ranking.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .geography import AccessStatus
from .live_oisans import classify_access
from .surfaces import (
    LOOSE_SURFACES,
    PAVED_ROUGH_SURFACES,
    PAVED_SMOOTH_SURFACES,
    STABILISED_SURFACES,
    UNSUITABLE_SURFACES,
    SurfaceClass,
)


class UsabilityClass(str, Enum):
    PAVED_REFERENCE = "paved_reference"
    REFERENCE_VTC = "reference_vtc"
    EXTENDED_VTC = "extended_vtc"
    EXCLUDED = "excluded"
    REVIEW = "review"


# Scenario name -> the classes it admits, widest last.
SCENARIO_ADMITS: dict[str, frozenset[UsabilityClass]] = {
    "paved_reference": frozenset({UsabilityClass.PAVED_REFERENCE}),
    "reference_vtc": frozenset({UsabilityClass.PAVED_REFERENCE, UsabilityClass.REFERENCE_VTC}),
    "extended_vtc": frozenset(
        {
            UsabilityClass.PAVED_REFERENCE,
            UsabilityClass.REFERENCE_VTC,
            UsabilityClass.EXTENDED_VTC,
        }
    ),
}

# Ways whose highway value describes something a bicycle cannot coast along at
# all, regardless of any other tag.
NON_RIDEABLE_HIGHWAYS = frozenset(
    {
        "steps",
        "elevator",
        "platform",
        "corridor",
        "via_ferrata",
        "raceway",
        "construction",
        "proposed",
        "rest_area",
        "services",
        "bus_stop",
    }
)

# Classified roads that are sealed in mainland France unless tagged otherwise.
IMPLICITLY_SEALED_HIGHWAYS = frozenset(
    {
        "primary",
        "primary_link",
        "secondary",
        "secondary_link",
        "tertiary",
        "tertiary_link",
        "unclassified",
        "residential",
        "living_street",
    }
)

# Ways that need an explicit bicycle permission before they are ridden at all.
FOOT_FIRST_HIGHWAYS = frozenset({"footway", "pedestrian", "bridleway"})

POSITIVE_BICYCLE_VALUES = frozenset({"yes", "designated", "permissive", "official"})

SMOOTHNESS_SEALED_QUALITY = frozenset({"excellent", "good"})
SMOOTHNESS_RIDEABLE = frozenset({"excellent", "good", "intermediate"})
SMOOTHNESS_EXCLUDED = frozenset({"very_bad", "horrible", "very_horrible", "impassable"})


@dataclass(frozen=True)
class UsabilityAssessment:
    usability: UsabilityClass
    surface_class: SurfaceClass
    surface_is_assumed: bool
    reason: str

    def admitted_by(self, scenario: str) -> bool:
        return self.usability in SCENARIO_ADMITS[scenario]


def _mtb_severity(value: str | None) -> int | None:
    """Numeric part of an ``mtb:scale`` value, or None when unparseable.

    ``mtb:scale`` runs 0 to 6 with ``+``/``-`` modifiers. Grade 0 is rideable on
    a firm path; anything above it describes terrain a hybrid bicycle has no
    business coasting down without braking.
    """
    if value is None:
        return None
    digits = "".join(character for character in value if character.isdigit())
    return int(digits) if digits else None


def assess_usability(tags: dict[str, str]) -> UsabilityAssessment:
    """Classify one way for the reference bicycle."""
    highway = tags.get("highway", "")
    surface = tags.get("surface")
    smoothness = tags.get("smoothness")
    tracktype = tags.get("tracktype")
    bicycle = tags.get("bicycle")

    access = classify_access(tags)
    if access is AccessStatus.PROHIBITED:
        return UsabilityAssessment(
            UsabilityClass.EXCLUDED, SurfaceClass.UNSUITABLE, False, "legal access refused"
        )

    if highway in NON_RIDEABLE_HIGHWAYS:
        return UsabilityAssessment(
            UsabilityClass.EXCLUDED, SurfaceClass.UNSUITABLE, False, f"highway={highway}"
        )

    if highway in FOOT_FIRST_HIGHWAYS and bicycle not in POSITIVE_BICYCLE_VALUES:
        return UsabilityAssessment(
            UsabilityClass.EXCLUDED,
            SurfaceClass.UNSUITABLE,
            False,
            f"highway={highway} without an explicit bicycle permission",
        )

    # A way advertised as mountain-bike terrain is not a hybrid-bicycle route,
    # whatever its highway class says.
    severity = _mtb_severity(tags.get("mtb:scale"))
    if tags.get("mtb:type") in {"downhill", "freeride"}:
        return UsabilityAssessment(
            UsabilityClass.EXCLUDED,
            SurfaceClass.UNSUITABLE,
            False,
            f"mtb:type={tags['mtb:type']}",
        )
    if severity is not None and severity >= 1:
        return UsabilityAssessment(
            UsabilityClass.EXCLUDED,
            SurfaceClass.UNSUITABLE,
            False,
            f"mtb:scale={tags.get('mtb:scale')}",
        )

    if surface in UNSUITABLE_SURFACES:
        return UsabilityAssessment(
            UsabilityClass.EXCLUDED, SurfaceClass.UNSUITABLE, False, f"surface={surface}"
        )
    if smoothness in SMOOTHNESS_EXCLUDED:
        return UsabilityAssessment(
            UsabilityClass.EXCLUDED, SurfaceClass.UNSUITABLE, False, f"smoothness={smoothness}"
        )

    if access is AccessStatus.REVIEW:
        return UsabilityAssessment(
            UsabilityClass.REVIEW,
            SurfaceClass.UNSUITABLE,
            False,
            "no bicycle permission is recorded for this way",
        )

    # --- sealed surfaces --------------------------------------------------
    if surface in PAVED_SMOOTH_SURFACES:
        if smoothness is not None and smoothness not in SMOOTHNESS_SEALED_QUALITY:
            return UsabilityAssessment(
                UsabilityClass.REFERENCE_VTC,
                SurfaceClass.ASPHALT_DEGRADED,
                False,
                f"surface={surface} but smoothness={smoothness}",
            )
        return UsabilityAssessment(
            UsabilityClass.PAVED_REFERENCE,
            SurfaceClass.ASPHALT_GOOD,
            False,
            f"surface={surface}"
            + (f", smoothness={smoothness}" if smoothness else ", smoothness unstated"),
        )

    if surface in PAVED_ROUGH_SURFACES:
        return UsabilityAssessment(
            UsabilityClass.REFERENCE_VTC,
            SurfaceClass.ASPHALT_DEGRADED,
            False,
            f"sealed but rough surface={surface}",
        )

    # --- surface not stated ----------------------------------------------
    if surface is None:
        if highway in IMPLICITLY_SEALED_HIGHWAYS:
            if smoothness in SMOOTHNESS_EXCLUDED:
                return UsabilityAssessment(
                    UsabilityClass.EXCLUDED,
                    SurfaceClass.UNSUITABLE,
                    False,
                    f"smoothness={smoothness}",
                )
            return UsabilityAssessment(
                UsabilityClass.REFERENCE_VTC,
                SurfaceClass.ASPHALT_DEGRADED,
                True,
                (
                    f"highway={highway} carries no surface tag; sealed is assumed for a "
                    "classified mainland road and charged the degraded-asphalt scenario"
                ),
            )
        if highway in {"service", "cycleway"}:
            return UsabilityAssessment(
                UsabilityClass.EXTENDED_VTC,
                SurfaceClass.STABILISED_GRAVEL,
                True,
                f"highway={highway} carries no surface tag; firm but unsealed is assumed",
            )
        return UsabilityAssessment(
            UsabilityClass.REVIEW,
            SurfaceClass.UNSUITABLE,
            False,
            f"highway={highway} carries neither a surface nor a quality tag",
        )

    # --- unsealed but possibly firm --------------------------------------
    if surface in STABILISED_SURFACES:
        return UsabilityAssessment(
            UsabilityClass.EXTENDED_VTC,
            SurfaceClass.STABILISED_GRAVEL,
            False,
            f"surface={surface}",
        )

    if surface in LOOSE_SURFACES:
        if tracktype == "grade1":
            return UsabilityAssessment(
                UsabilityClass.EXTENDED_VTC,
                SurfaceClass.STABILISED_GRAVEL,
                False,
                f"surface={surface}, tracktype=grade1",
            )
        if tracktype == "grade2" or smoothness in SMOOTHNESS_RIDEABLE:
            return UsabilityAssessment(
                UsabilityClass.EXTENDED_VTC,
                SurfaceClass.COMPACT_TRACK,
                False,
                f"surface={surface}"
                + (f", tracktype={tracktype}" if tracktype else f", smoothness={smoothness}"),
            )
        if tracktype in {"grade3", "grade4", "grade5"}:
            return UsabilityAssessment(
                UsabilityClass.EXCLUDED,
                SurfaceClass.UNSUITABLE,
                False,
                f"surface={surface}, tracktype={tracktype}",
            )
        return UsabilityAssessment(
            UsabilityClass.REVIEW,
            SurfaceClass.DIRT,
            False,
            f"surface={surface} with no quality tag to bound its resistance",
        )

    return UsabilityAssessment(
        UsabilityClass.REVIEW,
        SurfaceClass.UNSUITABLE,
        False,
        f"surface={surface} is not covered by the classification",
    )
