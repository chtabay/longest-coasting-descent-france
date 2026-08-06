"""Pure-Python helpers for the compact live Oisans reconstruction."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .geography import AccessStatus, StructureStatus, lonlat_to_lambert93


@dataclass(frozen=True)
class OSMDirectedGeometry:
    edge_id: str
    osm_way_id: int
    direction: str
    lonlat: tuple[tuple[float, float], ...]
    tags: tuple[tuple[str, str], ...]
    access_status: AccessStatus
    structure_status: StructureStatus


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def classify_access(tags: dict[str, str]) -> AccessStatus:
    """Conservatively classify bicycle access; missing permission is never invented."""
    if tags.get("bicycle") in {"no", "private"}:
        return AccessStatus.PROHIBITED
    if tags.get("access") in {"no", "private"} and tags.get("bicycle") not in {
        "yes",
        "designated",
        "permissive",
    }:
        return AccessStatus.PROHIBITED
    if tags.get("vehicle") in {"no", "private"} and tags.get("bicycle") not in {
        "yes",
        "designated",
        "permissive",
    }:
        return AccessStatus.PROHIBITED
    if tags.get("highway") in {"motorway", "motorway_link"}:
        return AccessStatus.PROHIBITED
    if tags.get("bicycle") in {"yes", "designated", "permissive"}:
        return AccessStatus.ADMISSIBLE
    if tags.get("highway") in {
        "primary",
        "secondary",
        "tertiary",
        "unclassified",
        "residential",
        "living_street",
        "service",
        "cycleway",
    }:
        return AccessStatus.ADMISSIBLE
    return AccessStatus.REVIEW


def structure_status(tags: dict[str, str]) -> StructureStatus:
    if tags.get("bridge") not in {None, "no"}:
        return StructureStatus.BRIDGE
    if tags.get("tunnel") not in {None, "no"} or tags.get("covered") == "yes":
        return StructureStatus.TUNNEL
    if tags.get("layer", "0") not in {"0", "+0", "-0"}:
        return StructureStatus.STACKED
    return StructureStatus.NORMAL


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
        structure = structure_status(tags)
        oneway = tags.get("oneway", "no")
        bicycle_override = tags.get("oneway:bicycle") == "no"
        directions = ["forward", "reverse"]
        if oneway in {"yes", "1", "true"} and not bicycle_override:
            directions = ["forward"]
        elif oneway == "-1" and not bicycle_override:
            directions = ["reverse"]
        for direction in directions:
            oriented = lonlat if direction == "forward" else tuple(reversed(lonlat))
            way_id = int(element["id"])
            edges.append(
                OSMDirectedGeometry(
                    f"osm-way-{way_id}-{direction}",
                    way_id,
                    direction,
                    oriented,
                    tuple(sorted(tags.items())),
                    access,
                    structure,
                )
            )
    return tuple(edges)


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
    for start, end in zip(points, points[1:]):
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


def extract_elevations(response: dict[str, Any], expected_count: int) -> tuple[float, ...]:
    raw = response.get("elevations") or response.get("elevation")
    if not isinstance(raw, list):
        raise ValueError("Altimetry response has no elevations list.")
    elevations = tuple(
        float(item.get("z")) if isinstance(item, dict) else float(item) for item in raw
    )
    if len(elevations) != expected_count or any(not math.isfinite(value) for value in elevations):
        raise ValueError("Altimetry response count or values are invalid.")
    return elevations
