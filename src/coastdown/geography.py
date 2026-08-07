"""Typed Phase 1 geometry/elevation contract and small-profile builder."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from enum import Enum

from .models import RoadProfile


class AccessStatus(str, Enum):
    ADMISSIBLE = "admissible"
    PROHIBITED = "prohibited"
    REVIEW = "review"


class StructureStatus(str, Enum):
    NORMAL = "normal"
    BRIDGE = "bridge"
    TUNNEL = "tunnel"
    STACKED = "stacked"


@dataclass(frozen=True)
class SourceProvenance:
    """Everything needed to re-obtain and re-verify one source.

    ``elevation_model_kind`` is the field the structure rule reads.  It must be
    ``"terrain"`` for a bare-earth model, ``"surface"`` for a DSM, ``"roadway"``
    for a source that actually measures the trafficked surface, and ``None``
    when the provenance describes geometry rather than elevation.
    """

    producer: str
    dataset: str
    version: str
    retrieval_date: str
    source_url: str
    original_crs: str
    original_units: str
    sha256: str | None = None
    discovery_url: str | None = None
    vertical_datum: str | None = None
    licence: str | None = None
    attribution: str | None = None
    byte_size: int | None = None
    elevation_model_kind: str | None = None

    @property
    def measures_bare_ground(self) -> bool:
        """True when this source cannot describe a deck, tunnel bore or viaduct.

        An explicit ``elevation_model_kind`` always wins.  The dataset-name
        heuristic only applies to provenance records that predate the field, so
        that a source which never declares its kind still cannot silently pass
        the structure rule.
        """
        if self.elevation_model_kind is not None:
            return self.elevation_model_kind in {"terrain", "surface"}
        return self.dataset.lower().startswith(("terrain", "surface"))


@dataclass(frozen=True)
class ElevationSample:
    x_m: float
    y_m: float
    elevation_m: float | None
    chainage_m: float
    elevation_provenance: SourceProvenance
    quality_flags: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProfileSegment:
    horizontal_length_m: float
    elevation_change_m: float
    grade_ratio: float
    grade_angle_rad: float
    travelled_length_m: float


@dataclass(frozen=True)
class DirectedRoadEdge:
    edge_id: str
    samples: tuple[ElevationSample, ...]
    geometry_provenance: SourceProvenance
    elevation_provenance: SourceProvenance
    crs: str
    access_status: AccessStatus
    structure_status: StructureStatus = StructureStatus.NORMAL
    source_attributes: tuple[tuple[str, str], ...] = ()
    quality_flags: tuple[str, ...] = ()

    def reversed(self) -> DirectedRoadEdge:
        total = self.samples[-1].chainage_m
        samples = tuple(
            replace(sample, chainage_m=total - sample.chainage_m)
            for sample in reversed(self.samples)
        )
        return replace(self, edge_id=f"{self.edge_id}:reverse", samples=samples)


def lonlat_to_lambert93(longitude_deg: float, latitude_deg: float) -> tuple[float, float]:
    """Convert WGS84 longitude/latitude to Lambert-93 (EPSG:2154).

    Formula and EPSG constants implement the ellipsoidal Lambert Conic Conformal
    (2SP) conversion. Inputs are decimal degrees and outputs are metres.
    """
    longitude = math.radians(float(longitude_deg))
    latitude = math.radians(float(latitude_deg))
    if not all(math.isfinite(value) for value in (longitude, latitude)):
        raise ValueError("longitude_deg and latitude_deg must be finite.")
    if not -math.pi <= longitude <= math.pi or not -math.pi / 2 < latitude < math.pi / 2:
        raise ValueError("longitude_deg or latitude_deg is outside its valid range.")
    eccentricity = 0.0818191910428158
    n = 0.7256077650532670
    c = 11754255.426096
    false_easting = 700000.0
    false_northing = 12655612.049876
    longitude_origin = math.radians(3.0)
    sin_latitude = math.sin(latitude)
    latitude_iso = math.log(
        math.tan(math.pi / 4 + latitude / 2)
        * ((1 - eccentricity * sin_latitude) / (1 + eccentricity * sin_latitude))
        ** (eccentricity / 2)
    )
    radius = c * math.exp(-n * latitude_iso)
    angle = n * (longitude - longitude_origin)
    return (
        false_easting + radius * math.sin(angle),
        false_northing - radius * math.cos(angle),
    )


def build_profile_segments(
    edge: DirectedRoadEdge,
    *,
    max_abs_grade_ratio: float = 0.5,
    max_elevation_jump_m: float = 20.0,
) -> tuple[ProfileSegment, ...]:
    """Apply the normative geometry contract to an oriented sampled edge."""
    if edge.crs != "EPSG:2154":
        raise ValueError("Profile construction requires metric Lambert-93 / EPSG:2154 coordinates.")
    if (
        edge.structure_status is not StructureStatus.NORMAL
        and edge.elevation_provenance.measures_bare_ground
    ):
        raise ValueError(
            "Terrain elevation cannot be assigned blindly to bridge/tunnel/stacked edges."
        )
    if len(edge.samples) < 2:
        raise ValueError("An edge requires at least two elevation samples.")
    segments = []
    for start, end in zip(edge.samples, edge.samples[1:]):
        if start.elevation_m is None or end.elevation_m is None:
            raise ValueError("Missing elevation prevents profile construction.")
        dx = math.hypot(end.x_m - start.x_m, end.y_m - start.y_m)
        if dx <= 1e-9:
            raise ValueError("Duplicate points create a zero horizontal-length segment.")
        dz = end.elevation_m - start.elevation_m
        if abs(dz) > max_elevation_jump_m:
            raise ValueError("Abnormal elevation discontinuity exceeds max_elevation_jump_m.")
        grade = dz / dx
        if abs(grade) > max_abs_grade_ratio:
            raise ValueError("Extreme grade exceeds max_abs_grade_ratio.")
        segments.append(ProfileSegment(dx, dz, grade, math.atan(grade), math.hypot(dx, dz)))
    return tuple(segments)


def edge_to_road_profile(edge: DirectedRoadEdge) -> RoadProfile:
    segments = build_profile_segments(edge)
    return RoadProfile(
        (segment.travelled_length_m for segment in segments),
        (segment.grade_ratio for segment in segments),
    )
