"""Pure-Python helpers for the live Oisans reconstruction.

Nothing here touches the network.  Every function is deterministic so that the
offline test suite can exercise the whole reconstruction logic against frozen
extracts, and so that ``scripts/phase1b_live_oisans.py`` only owns transport,
caching and file layout.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .geography import AccessStatus, StructureStatus, lonlat_to_lambert93

# The Geoplateforme altimetry service answers HTTP 200 with this value when a
# requested point is outside the resource coverage.  It is a sentinel, never an
# elevation, and must not reach a profile.
NO_DATA_SENTINEL = -99999.0
NO_DATA_THRESHOLD = -9_000.0

ONEWAY_FORWARD_VALUES = frozenset({"yes", "1", "true"})
ONEWAY_REVERSE_VALUES = frozenset({"-1", "reverse"})
ONEWAY_EXEMPT_VALUES = frozenset({"no", "0", "false"})

# Highway classes a bicycle may legally use in France without an explicit tag.
DEFAULT_CYCLABLE_HIGHWAYS = frozenset(
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
        "service",
        "cycleway",
        "road",
    }
)
FORBIDDEN_HIGHWAYS = frozenset({"motorway", "motorway_link", "proposed", "construction"})
POSITIVE_BICYCLE_VALUES = frozenset({"yes", "designated", "permissive", "official"})
NEGATIVE_ACCESS_VALUES = frozenset({"no", "private"})


@dataclass(frozen=True)
class OSMDirectedGeometry:
    edge_id: str
    osm_way_id: int
    direction: str
    lonlat: tuple[tuple[float, float], ...]
    tags: tuple[tuple[str, str], ...]
    access_status: AccessStatus
    structure_status: StructureStatus
    node_ids: tuple[int, ...] = ()
    access_reason: str = ""


@dataclass(frozen=True)
class TurnRestriction:
    relation_id: int
    restriction: str
    from_way_ids: tuple[int, ...]
    via_node_ids: tuple[int, ...]
    via_way_ids: tuple[int, ...]
    to_way_ids: tuple[int, ...]
    except_values: tuple[str, ...] = ()

    @property
    def applies_to_bicycles(self) -> bool:
        """A turn ban that excepts bicycles does not constrain this study's rider."""
        return "bicycle" not in self.except_values


@dataclass(frozen=True)
class ProfileMetrics:
    """Geometry and grade statistics of one oriented, sampled profile."""

    segment_count: int
    horizontal_length_m: float
    travelled_length_m: float
    net_dz_m: float
    ascent_m: float
    descent_m: float
    min_grade_ratio: float
    max_grade_ratio: float
    grade_quantiles: tuple[tuple[str, float], ...]
    contract_violation_count: int
    elevation_break_count: int
    zero_grade_segment_count: int
    # Densification subdivides source chords but never removes a source vertex,
    # so the requested spacing is an upper bound.  Where OSM geometry is already
    # finer than the request, the realised spacing is the source spacing and the
    # nominal value would misdescribe the experiment.
    realised_mean_spacing_m: float
    realised_min_spacing_m: float
    realised_max_spacing_m: float


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def classify_access(tags: dict[str, str]) -> AccessStatus:
    """Conservatively classify bicycle access; missing permission is never invented."""
    if tags.get("bicycle") in NEGATIVE_ACCESS_VALUES:
        return AccessStatus.PROHIBITED
    explicit_bicycle_yes = tags.get("bicycle") in POSITIVE_BICYCLE_VALUES
    if tags.get("access") in NEGATIVE_ACCESS_VALUES and not explicit_bicycle_yes:
        return AccessStatus.PROHIBITED
    if tags.get("vehicle") in NEGATIVE_ACCESS_VALUES and not explicit_bicycle_yes:
        return AccessStatus.PROHIBITED
    if tags.get("highway") in FORBIDDEN_HIGHWAYS:
        return AccessStatus.PROHIBITED
    if explicit_bicycle_yes:
        return AccessStatus.ADMISSIBLE
    if tags.get("highway") in DEFAULT_CYCLABLE_HIGHWAYS:
        return AccessStatus.ADMISSIBLE
    return AccessStatus.REVIEW


def access_reason(tags: dict[str, str]) -> str:
    """Explain the access decision so every edge stays auditable."""
    if tags.get("bicycle") in NEGATIVE_ACCESS_VALUES:
        return f"bicycle={tags['bicycle']}"
    explicit_bicycle_yes = tags.get("bicycle") in POSITIVE_BICYCLE_VALUES
    if tags.get("access") in NEGATIVE_ACCESS_VALUES and not explicit_bicycle_yes:
        return f"access={tags['access']} without bicycle override"
    if tags.get("vehicle") in NEGATIVE_ACCESS_VALUES and not explicit_bicycle_yes:
        return f"vehicle={tags['vehicle']} without bicycle override"
    if tags.get("highway") in FORBIDDEN_HIGHWAYS:
        return f"highway={tags['highway']}"
    if explicit_bicycle_yes:
        return f"bicycle={tags['bicycle']}"
    if tags.get("highway") in DEFAULT_CYCLABLE_HIGHWAYS:
        return f"highway={tags.get('highway')} cyclable by default"
    return f"highway={tags.get('highway')} carries no bicycle permission"


def structure_status(tags: dict[str, str]) -> StructureStatus:
    if tags.get("bridge") not in {None, "no"}:
        return StructureStatus.BRIDGE
    if tags.get("tunnel") not in {None, "no"} or tags.get("covered") == "yes":
        return StructureStatus.TUNNEL
    if tags.get("layer", "0") not in {"0", "+0", "-0"}:
        return StructureStatus.STACKED
    return StructureStatus.NORMAL


def surface_quality(tags: dict[str, str]) -> str:
    """Report the surface evidence without turning silence into a guarantee."""
    parts = [
        f"{key}={tags[key]}"
        for key in ("surface", "smoothness", "tracktype")
        if tags.get(key) is not None
    ]
    return ";".join(parts) if parts else "unspecified"


def bicycle_directions(tags: dict[str, str]) -> tuple[str, ...]:
    """Directions a bicycle may legally travel along the way's node order.

    ``oneway:bicycle`` overrides ``oneway`` in both directions, which is how the
    tag is defined: ``oneway:bicycle=no`` is the contraflow exemption and
    ``oneway:bicycle=yes`` restricts a two-way road for bicycles only.
    ``junction=roundabout`` implies ``oneway=yes`` when ``oneway`` is absent.
    """
    bicycle_oneway = tags.get("oneway:bicycle")
    if bicycle_oneway in ONEWAY_EXEMPT_VALUES:
        return ("forward", "reverse")
    if bicycle_oneway in ONEWAY_FORWARD_VALUES:
        return ("forward",)
    if bicycle_oneway in ONEWAY_REVERSE_VALUES:
        return ("reverse",)
    oneway = tags.get("oneway")
    if oneway is None and tags.get("junction") == "roundabout":
        oneway = "yes"
    if oneway in ONEWAY_FORWARD_VALUES:
        return ("forward",)
    if oneway in ONEWAY_REVERSE_VALUES:
        return ("reverse",)
    return ("forward", "reverse")


def parse_osm_directed_edges(payload: dict[str, Any]) -> tuple[OSMDirectedGeometry, ...]:
    """Convert Overpass ways with embedded geometry to conservative directed edges."""
    edges: list[OSMDirectedGeometry] = []
    for element in payload.get("elements", []):
        if element.get("type") != "way" or "highway" not in element.get("tags", {}):
            continue
        geometry = element.get("geometry") or []
        lonlat = tuple((float(point["lon"]), float(point["lat"])) for point in geometry)
        if len(lonlat) < 2:
            continue
        tags = {str(key): str(value) for key, value in element.get("tags", {}).items()}
        access = classify_access(tags)
        reason = access_reason(tags)
        structure = structure_status(tags)
        node_ids = tuple(int(node) for node in element.get("nodes", ()))
        way_id = int(element["id"])
        for direction in bicycle_directions(tags):
            oriented = lonlat if direction == "forward" else tuple(reversed(lonlat))
            oriented_nodes = node_ids if direction == "forward" else tuple(reversed(node_ids))
            edges.append(
                OSMDirectedGeometry(
                    f"osm-way-{way_id}-{direction}",
                    way_id,
                    direction,
                    oriented,
                    tuple(sorted(tags.items())),
                    access,
                    structure,
                    oriented_nodes,
                    reason,
                )
            )
    return tuple(edges)


def parse_turn_restrictions(payload: dict[str, Any]) -> tuple[TurnRestriction, ...]:
    """Extract ``type=restriction`` relations with their from/via/to members."""
    restrictions: list[TurnRestriction] = []
    for element in payload.get("elements", []):
        if element.get("type") != "relation":
            continue
        tags = element.get("tags", {})
        if tags.get("type") != "restriction":
            continue
        roles: dict[tuple[str, str], list[int]] = {}
        for member in element.get("members", []):
            key = (str(member.get("role", "")), str(member.get("type", "")))
            roles.setdefault(key, []).append(int(member["ref"]))
        restrictions.append(
            TurnRestriction(
                int(element["id"]),
                str(tags.get("restriction", tags.get("restriction:bicycle", "unknown"))),
                tuple(roles.get(("from", "way"), ())),
                tuple(roles.get(("via", "node"), ())),
                tuple(roles.get(("via", "way"), ())),
                tuple(roles.get(("to", "way"), ())),
                tuple(
                    item.strip() for item in str(tags.get("except", "")).split(";") if item.strip()
                ),
            )
        )
    return tuple(restrictions)


def densify_lonlat(
    lonlat: Iterable[tuple[float, float]], spacing_m: float
) -> tuple[tuple[float, float, float, float, float], ...]:
    """Densify in Lambert-93; return lon, lat, x, y and horizontal chainage."""
    if not math.isfinite(spacing_m) or spacing_m <= 0:
        raise ValueError("spacing_m must be finite and positive.")
    points = tuple(lonlat)
    if len(points) < 2:
        raise ValueError("At least two geometry points are required.")
    output: list[tuple[float, float, float, float, float]] = []
    chainage = 0.0
    first_x, first_y = lonlat_to_lambert93(*points[0])
    output.append((*points[0], first_x, first_y, chainage))
    for start, end in itertools.pairwise(points):
        start_x, start_y = lonlat_to_lambert93(*start)
        end_x, end_y = lonlat_to_lambert93(*end)
        length = math.hypot(end_x - start_x, end_y - start_y)
        if length <= 1e-9:
            continue
        pieces = max(1, math.ceil(length / spacing_m))
        for piece in range(1, pieces + 1):
            fraction = piece / pieces
            lon = start[0] + fraction * (end[0] - start[0])
            lat = start[1] + fraction * (end[1] - start[1])
            x = start_x + fraction * (end_x - start_x)
            y = start_y + fraction * (end_y - start_y)
            previous = output[-1]
            chainage += math.hypot(x - previous[2], y - previous[3])
            output.append((lon, lat, x, y, chainage))
    return tuple(output)


def extract_elevations(response: dict[str, Any], expected_count: int) -> tuple[float | None, ...]:
    """Read an altimetry response, mapping the no-data sentinel to ``None``.

    The service answers HTTP 200 with ``z = -99999.0`` outside coverage.  Passing
    that straight through would silently insert a 100 km cliff into a profile,
    so it becomes an explicit missing value that the geometry contract rejects.
    """
    raw = response.get("elevations") or response.get("elevation")
    if not isinstance(raw, list):
        raise TypeError("Altimetry response has no elevations list.")
    values: list[float | None] = []
    for item in raw:
        value = float(item.get("z")) if isinstance(item, dict) else float(item)
        if not math.isfinite(value) or value <= NO_DATA_THRESHOLD:
            values.append(None)
        else:
            values.append(value)
    if len(values) != expected_count:
        raise ValueError("Altimetry response count does not match the request.")
    return tuple(values)


def box_filter_elevations(
    chainage_m: Sequence[float], elevations: Sequence[float], window_m: float
) -> tuple[float, ...]:
    """Centred moving average of elevation over a chainage window.

    This is the declared conditioning scenario of the geometry contract, not a
    correction of the data.  It low-pass filters at the digital terrain model's
    own effective ground resolution: sampling a raster finer than its cell size
    produces alternating flat steps and cell-height jumps, which inflate 3D
    length and cumulative ascent without adding information.  A window of zero
    returns the raw series unchanged.
    """
    if len(chainage_m) != len(elevations):
        raise ValueError("chainage_m and elevations must have equal length.")
    if not math.isfinite(window_m) or window_m < 0:
        raise ValueError("window_m must be finite and non-negative.")
    if window_m == 0 or not elevations:
        return tuple(float(value) for value in elevations)
    half = window_m / 2.0
    count = len(elevations)
    smoothed: list[float] = []
    low = 0
    high = 0
    for index in range(count):
        while low < count and chainage_m[index] - chainage_m[low] > half:
            low += 1
        while high < count and chainage_m[high] - chainage_m[index] <= half:
            high += 1
        window = elevations[low:high]
        smoothed.append(math.fsum(window) / len(window))
    return tuple(smoothed)


def quantile(values: Sequence[float], fraction: float) -> float:
    """Linear-interpolation quantile; ``fraction`` is in [0, 1]."""
    if not values:
        raise ValueError("quantile requires at least one value.")
    if not 0.0 <= fraction <= 1.0:
        raise ValueError("fraction must lie in [0, 1].")
    ordered = sorted(values)
    position = fraction * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (position - lower) * (ordered[upper] - ordered[lower])


def profile_metrics(
    segments: Sequence[Any],
    *,
    max_simulable_grade_ratio: float,
    elevation_break_m: float,
) -> ProfileMetrics:
    """Summarise a sequence of :class:`~coastdown.geography.ProfileSegment`."""
    if not segments:
        raise ValueError("profile_metrics requires at least one segment.")
    grades = [segment.grade_ratio for segment in segments]
    changes = [segment.elevation_change_m for segment in segments]
    spacings = [segment.horizontal_length_m for segment in segments]
    return ProfileMetrics(
        segment_count=len(segments),
        horizontal_length_m=math.fsum(segment.horizontal_length_m for segment in segments),
        travelled_length_m=math.fsum(segment.travelled_length_m for segment in segments),
        net_dz_m=math.fsum(changes),
        ascent_m=math.fsum(value for value in changes if value > 0),
        descent_m=-math.fsum(value for value in changes if value < 0),
        min_grade_ratio=min(grades),
        max_grade_ratio=max(grades),
        grade_quantiles=tuple(
            (name, quantile(grades, fraction))
            for name, fraction in (
                ("p05", 0.05),
                ("p25", 0.25),
                ("p50", 0.50),
                ("p75", 0.75),
                ("p95", 0.95),
            )
        ),
        contract_violation_count=sum(
            1 for value in grades if abs(value) > max_simulable_grade_ratio
        ),
        elevation_break_count=sum(1 for value in changes if abs(value) > elevation_break_m),
        zero_grade_segment_count=sum(1 for value in grades if value == 0.0),
        realised_mean_spacing_m=math.fsum(spacings) / len(spacings),
        realised_min_spacing_m=min(spacings),
        realised_max_spacing_m=max(spacings),
    )


def bearing_deg(start: tuple[float, float], end: tuple[float, float]) -> float:
    """Planimetric bearing of a projected segment, in degrees."""
    return math.degrees(math.atan2(end[1] - start[1], end[0] - start[0]))


def hairpin_turns(
    points: Sequence[tuple[float, float, float, float, float]],
    *,
    minimum_turn_deg: float = 100.0,
    chord_m: float = 30.0,
) -> tuple[int, ...]:
    """Indices where the roadway reverses direction within ``chord_m``.

    A hairpin is the case where a terrain model is most likely to attach the
    roadway to the hillside above or below it, so these indices drive the manual
    audit rather than any scoring.
    """
    if chord_m <= 0:
        raise ValueError("chord_m must be positive.")
    projected = [(point[2], point[3]) for point in points]
    chainage = [point[4] for point in points]
    found: list[int] = []
    count = len(points)
    for index in range(count):
        back = index
        while back > 0 and chainage[index] - chainage[back] < chord_m:
            back -= 1
        forward = index
        while forward < count - 1 and chainage[forward] - chainage[index] < chord_m:
            forward += 1
        if back == index or forward == index:
            continue
        incoming = bearing_deg(projected[back], projected[index])
        outgoing = bearing_deg(projected[index], projected[forward])
        turn = abs((outgoing - incoming + 180.0) % 360.0 - 180.0)
        if turn >= minimum_turn_deg:
            found.append(index)
    # Collapse consecutive indices so one bend counts once.
    collapsed: list[int] = []
    for index in found:
        if not collapsed or index - collapsed[-1] > 1:
            collapsed.append(index)
    return tuple(collapsed)
