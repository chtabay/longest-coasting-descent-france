"""One-command live Oisans reconstruction from OpenStreetMap and IGN RGE ALTI.

Network is required.  Nothing is published unless every request, parse and
profile succeeds; a failure removes the temporary directory instead of leaving a
partial or relabelled result.  No route ranking is produced or implied.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

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
    OSMDirectedGeometry,
    box_filter_elevations,
    canonical_json_bytes,
    densify_lonlat,
    extract_elevations,
    hairpin_turns,
    parse_osm_directed_edges,
    parse_turn_restrictions,
    profile_metrics,
    sha256_bytes,
    surface_quality,
)
from coastdown.textio import write_text_lf

USER_AGENT = (
    "coastdown-france-phase1b/2.0 (+https://github.com/chtabay/longest-coasting-descent-france)"
)

BBOX = (45.02, 6.02, 45.16, 6.18)  # south, west, north, east
OVERPASS_ENDPOINT = "https://overpass-api.de/api/interpreter"
OVERPASS_STATUS_ENDPOINT = "https://overpass-api.de/api/status"

ALTIMETRY_ROOT = "https://data.geopf.fr/altimetrie/"
ALTIMETRY_ENDPOINT = "https://data.geopf.fr/altimetrie/1.0/calcul/alti/rest/elevation.json"
ALTIMETRY_RESOURCE_INDEX = "https://data.geopf.fr/altimetrie/resources"

# Verified 2026-08-07: ign_rge_alti_wld is the *pyramid* resource and answers on
# an approximately 3.5 m effective grid; ign_rge_alti_par_territoires answers on
# the announced 1 m grid.  The finer resource is primary and the pyramid is kept
# as an independent same-producer control.  See docs/08_source_matrix.md.
PRIMARY_RESOURCE = "ign_rge_alti_par_territoires"
CONTROL_RESOURCE = "ign_rge_alti_wld"
CONTROL_SPACING_M = 10.0

# Verified 2026-08-07: 200 points per GET is accepted (URI ~5.9 kB); 400 points
# returns HTTP 414 Request-URI Too Long.
ALTIMETRY_MAX_POINTS_PER_REQUEST = 200
ALTIMETRY_REQUEST_PAUSE_S = 0.15

SPACINGS_M = (2.0, 5.0, 10.0, 25.0)

# The simulator's own validity bound.  A profile whose grades exceed it is not
# rejected silently: it is reported as a contract violation and left unsimulated.
MAX_SIMULABLE_GRADE_RATIO = 0.5
# Diagnostic bounds, wide enough to *measure* an artefact instead of raising on
# it.  Anything beyond them is a hard data error worth surfacing.
DIAGNOSTIC_MAX_GRADE_RATIO = 10.0
DIAGNOSTIC_MAX_ELEVATION_JUMP_M = 250.0
# Physical implausibility threshold used only to count elevation breaks.
ELEVATION_BREAK_M = 5.0

# Declared conditioning scenario: centred moving average of elevation over this
# chainage window.  Chosen at the terrain model's own effective ground
# resolution scale; see docs/10_phase1b_live_reconstruction.md.
CONDITIONING_WINDOW_M = 25.0

SELECTION_MIN_LENGTH_M = 250.0
SELECTION_MAX_LENGTH_M = 2_000.0
# The validation sample is stratified by highway class, an attribute of the road
# register that is independent of the quantity the study will eventually rank
# (coasting time). Taking the lowest OSM way identifier inside each stratum keeps
# the choice reproducible and prevents an unintentionally favourable sample.
SELECTION_HIGHWAY_STRATA = (
    "secondary",
    "tertiary",
    "unclassified",
    "residential",
    "primary",
    "service",
    "cycleway",
)

OSM_LICENCE = "ODbL 1.0"
OSM_ATTRIBUTION = "© OpenStreetMap contributors"
IGN_LICENCE = "Licence Ouverte / Open Licence (Etalab) 2.0"
IGN_ATTRIBUTION = "© IGN — RGE ALTI® via Géoplateforme"
# The altimetry service does not return a vertical reference.  RGE ALTI is
# published in NGF-IGN 1969 on mainland France (IGN 1978 on Corsica); the study
# area is mainland, so this is asserted from the product specification and
# flagged as an assertion, not as a service response.
IGN_VERTICAL_DATUM = (
    "NGF-IGN 1969 (asserted from RGE ALTI product specification, not returned by the API)"
)

LIMITATIONS = (
    (
        "RGE ALTI is a bare-earth terrain model; bridge, tunnel, covered and layer!=0 "
        "edges receive no elevation and stay in structure_review.csv."
    ),
    (
        "The altimetry API does not return a vertical datum; NGF-IGN 1969 is asserted "
        "from the RGE ALTI product specification."
    ),
    (
        "The control resource shares the producer and the acquisition campaign, so "
        "agreement between the two bounds sampling and pyramid effects only, not "
        "absolute vertical accuracy."
    ),
    "BD TOPO cross-checking of structures is not performed in this phase.",
    (
        "The selected ways are a deterministic validation sample; no regional or "
        "national ranking is produced or implied."
    ),
)


# Overpass answers 504 when the instance behind the load balancer is saturated,
# and 429 when the caller is over its slot allowance. Both are transient and
# carry no information about the query, so a bounded retry is correct. Every
# attempt, including the failed ones, is recorded in http_transaction_log.csv.
TRANSIENT_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
MAX_ATTEMPTS = 4
RETRY_BASE_DELAY_S = 5.0


@dataclass
class HttpTransaction:
    label: str
    attempt: int
    method: str
    url: str
    status: int
    final_url: str
    content_type: str
    response_bytes: int
    sha256: str
    elapsed_s: float
    redirected: bool
    outcome: str


@dataclass
class Session:
    transactions: list[HttpTransaction] = field(default_factory=list)

    def fetch(
        self,
        label: str,
        url: str,
        *,
        data: bytes | None = None,
        timeout: int = 300,
        max_attempts: int = MAX_ATTEMPTS,
    ) -> bytes:
        method = "POST" if data else "GET"
        last_error: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            request = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT})
            started = time.monotonic()
            try:
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    body = response.read()
                    self.transactions.append(
                        HttpTransaction(
                            label,
                            attempt,
                            method,
                            url,
                            response.status,
                            response.geturl(),
                            response.headers.get("Content-Type", ""),
                            len(body),
                            sha256_bytes(body),
                            time.monotonic() - started,
                            response.geturl() != url,
                            "ok",
                        )
                    )
                    return body
            except urllib.error.HTTPError as error:
                body = error.read()
                transient = error.code in TRANSIENT_STATUS_CODES
                self.transactions.append(
                    HttpTransaction(
                        label,
                        attempt,
                        method,
                        url,
                        error.code,
                        error.headers.get("Location", url),
                        error.headers.get("Content-Type", ""),
                        len(body),
                        sha256_bytes(body),
                        time.monotonic() - started,
                        False,
                        "transient" if transient else "fatal",
                    )
                )
                if not transient:
                    raise
                last_error = error
            except (urllib.error.URLError, TimeoutError, OSError) as error:
                self.transactions.append(
                    HttpTransaction(
                        label,
                        attempt,
                        method,
                        url,
                        0,
                        url,
                        "",
                        0,
                        "",
                        time.monotonic() - started,
                        False,
                        f"transport:{type(error).__name__}",
                    )
                )
                last_error = error
            if attempt < max_attempts:
                delay = RETRY_BASE_DELAY_S * 2 ** (attempt - 1)
                print(f"  retry {attempt}/{max_attempts - 1} for {label} in {delay:.0f}s")
                time.sleep(delay)
        raise RuntimeError(f"{label} failed after {max_attempts} attempts") from last_error


def overpass_query() -> str:
    south, west, north, east = BBOX
    return (
        "[out:json][timeout:300];\n"
        f'way["highway"]({south},{west},{north},{east})->.roads;\n'
        'relation(bw.roads)["type"="restriction"]->.restrictions;\n'
        "(.roads;.restrictions;);\n"
        "out meta geom;\n"
    )


def altimetry_url(points: list[tuple[float, float]], resource: str) -> str:
    parameters = urllib.parse.urlencode(
        {
            "lon": "|".join(f"{point[0]:.7f}" for point in points),
            "lat": "|".join(f"{point[1]:.7f}" for point in points),
            "resource": resource,
            "delimiter": "|",
            "measures": "false",
            "zonly": "true",
        }
    )
    return f"{ALTIMETRY_ENDPOINT}?{parameters}"


def fetch_elevations(
    session: Session,
    points: list[tuple[float, float]],
    resource: str,
    cache_dir: Path,
    cache_index: dict[str, dict[str, object]],
) -> tuple[float | None, ...]:
    values: list[float | None] = []
    for offset in range(0, len(points), ALTIMETRY_MAX_POINTS_PER_REQUEST):
        chunk = points[offset : offset + ALTIMETRY_MAX_POINTS_PER_REQUEST]
        url = altimetry_url(chunk, resource)
        digest = sha256_bytes(url.encode())
        cache_file = cache_dir / f"rge-alti-{resource}-{digest[:20]}.json"
        payload = session.fetch(f"altimetry:{resource}", url)
        cache_file.write_bytes(payload)
        cache_index[cache_file.name] = {
            "name": cache_file.name,
            "resource": resource,
            "request_url_sha256": digest,
            "point_count": len(chunk),
            "bytes": len(payload),
            "sha256": sha256_bytes(payload),
        }
        values.extend(extract_elevations(json.loads(payload), len(chunk)))
        time.sleep(ALTIMETRY_REQUEST_PAUSE_S)
    return tuple(values)


def edge_length_m(edge: OSMDirectedGeometry) -> float:
    return densify_lonlat(edge.lonlat, 25.0)[-1][4]


def hairpin_count(edge: OSMDirectedGeometry) -> int:
    return len(hairpin_turns(densify_lonlat(edge.lonlat, 10.0)))


def select_profile_edges(
    edges: tuple[OSMDirectedGeometry, ...], maximum: int
) -> list[OSMDirectedGeometry]:
    """Deterministic, stratified validation sample; explicitly not a ranking.

    One way is taken per highway class, plus the way carrying the most hairpins.
    Hairpins are where a bare-earth model is most likely to attach a roadway to
    the hillside above or below it, so including that way deliberately stresses
    the weakest part of the reconstruction instead of avoiding it.  Neither
    criterion is correlated with the objective the study will later optimise.
    """
    candidates = [
        edge
        for edge in edges
        if edge.direction == "forward"
        and edge.structure_status is StructureStatus.NORMAL
        and edge.access_status is AccessStatus.ADMISSIBLE
        and SELECTION_MIN_LENGTH_M <= edge_length_m(edge) <= SELECTION_MAX_LENGTH_M
    ]
    if len(candidates) < 2:
        raise RuntimeError("Fewer than two admissible normal ways matched the selection window.")
    candidates.sort(key=lambda edge: edge.osm_way_id)

    lowest_per_class: dict[str, OSMDirectedGeometry] = {}
    for edge in candidates:
        lowest_per_class.setdefault(dict(edge.tags).get("highway", ""), edge)
    stratified = [
        lowest_per_class[name] for name in SELECTION_HIGHWAY_STRATA if name in lowest_per_class
    ]
    # Ties resolve to the lowest way identifier, so the pick stays reproducible.
    most_hairpins = max(candidates, key=lambda edge: (hairpin_count(edge), -edge.osm_way_id))

    selected: list[OSMDirectedGeometry] = []
    seen: set[int] = set()
    for edge in [*stratified[: max(1, maximum - 1)], most_hairpins]:
        if edge.osm_way_id in seen:
            continue
        seen.add(edge.osm_way_id)
        selected.append(edge)
    return selected[:maximum]


def build_edge(
    edge: OSMDirectedGeometry,
    points: tuple[tuple[float, float, float, float, float], ...],
    elevations: tuple[float | None, ...],
    geometry_provenance: SourceProvenance,
    elevation_provenance: SourceProvenance,
    suffix: str,
) -> DirectedRoadEdge:
    samples = tuple(
        ElevationSample(point[2], point[3], elevation, point[4], elevation_provenance)
        for point, elevation in zip(points, elevations)
    )
    return DirectedRoadEdge(
        f"{edge.edge_id}-{suffix}",
        samples,
        geometry_provenance,
        elevation_provenance,
        "EPSG:2154",
        edge.access_status,
        edge.structure_status,
        edge.tags,
    )


def metrics_row(
    edge: OSMDirectedGeometry,
    spacing: float,
    variant: str,
    metrics,
    missing: int,
    hairpins: int,
    retrieved: str,
) -> dict[str, object]:
    tags = dict(edge.tags)
    quantiles = dict(metrics.grade_quantiles)
    return {
        "source": "live",
        "retrieved_at": retrieved,
        "osm_way_id": edge.osm_way_id,
        "edge_id": edge.edge_id,
        "highway": tags.get("highway", ""),
        "ref": tags.get("ref", ""),
        "name": tags.get("name", ""),
        "surface_quality": surface_quality(tags),
        "requested_spacing_m": spacing,
        "realised_mean_spacing_m": round(metrics.realised_mean_spacing_m, 3),
        "realised_min_spacing_m": round(metrics.realised_min_spacing_m, 3),
        "realised_max_spacing_m": round(metrics.realised_max_spacing_m, 3),
        "variant": variant,
        "conditioning_window_m": CONDITIONING_WINDOW_M if variant == "conditioned" else 0.0,
        "segment_count": metrics.segment_count,
        "horizontal_length_m": round(metrics.horizontal_length_m, 3),
        "travelled_length_3d_m": round(metrics.travelled_length_m, 3),
        "net_dz_m": round(metrics.net_dz_m, 3),
        "ascent_m": round(metrics.ascent_m, 3),
        "descent_m": round(metrics.descent_m, 3),
        "min_grade_ratio": round(metrics.min_grade_ratio, 6),
        "p05_grade_ratio": round(quantiles["p05"], 6),
        "p25_grade_ratio": round(quantiles["p25"], 6),
        "p50_grade_ratio": round(quantiles["p50"], 6),
        "p75_grade_ratio": round(quantiles["p75"], 6),
        "p95_grade_ratio": round(quantiles["p95"], 6),
        "max_grade_ratio": round(metrics.max_grade_ratio, 6),
        "contract_violation_count": metrics.contract_violation_count,
        "elevation_break_count": metrics.elevation_break_count,
        "zero_grade_segment_count": metrics.zero_grade_segment_count,
        "missing_elevation_count": missing,
        "hairpin_count": hairpins,
    }


def simulation_row(
    edge: OSMDirectedGeometry,
    spacing: float,
    variant: str,
    metrics,
    retrieved: str,
) -> dict[str, object]:
    row: dict[str, object] = {
        "source": "live",
        "retrieved_at": retrieved,
        "osm_way_id": edge.osm_way_id,
        "edge_id": edge.edge_id,
        "requested_spacing_m": spacing,
        "realised_mean_spacing_m": round(metrics.realised_mean_spacing_m, 3),
        "variant": variant,
        "conditioning_window_m": CONDITIONING_WINDOW_M if variant == "conditioned" else 0.0,
        "simulated": False,
        "not_simulated_reason": "",
        "travelled_length_3d_m": round(metrics.travelled_length_m, 3),
        "net_dz_m": round(metrics.net_dz_m, 3),
        "elapsed_time_s": "",
        "moving_time_s": "",
        "stationary_time_s": "",
        "first_below_threshold_time_s": "",
        "first_zero_speed_time_s": "",
        "qualified_stop_time_s": "",
        "travelled_distance_m": "",
        "final_speed_m_s": "",
        "completed_route": "",
        "stop_reason": "",
    }
    if metrics.contract_violation_count:
        row["not_simulated_reason"] = (
            f"{metrics.contract_violation_count} segment(s) exceed "
            f"|grade| {MAX_SIMULABLE_GRADE_RATIO}"
        )
    return row


def run_simulation(segments, row: dict[str, object]) -> None:
    profile = RoadProfile(
        [segment.travelled_length_m for segment in segments],
        [segment.grade_ratio for segment in segments],
    )
    result = simulate_profile(profile)
    row.update(
        {
            "simulated": True,
            "not_simulated_reason": "",
            "elapsed_time_s": round(result.elapsed_time_s, 6),
            "moving_time_s": round(result.moving_time_s, 6),
            "stationary_time_s": round(result.stationary_time_s, 6),
            "first_below_threshold_time_s": (
                ""
                if result.first_below_threshold_time_s is None
                else round(result.first_below_threshold_time_s, 6)
            ),
            "first_zero_speed_time_s": (
                ""
                if result.first_zero_speed_time_s is None
                else round(result.first_zero_speed_time_s, 6)
            ),
            "qualified_stop_time_s": (
                ""
                if result.qualified_stop_time_s is None
                else round(result.qualified_stop_time_s, 6)
            ),
            "travelled_distance_m": round(result.travelled_distance_m, 3),
            "final_speed_m_s": round(result.speed_m_s[-1], 6),
            "completed_route": result.completed_route,
            "stop_reason": result.stop_reason,
        }
    )


def write_csv(path: Path, rows: list[dict[str, object]], fieldnames: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_map(
    edges: tuple[OSMDirectedGeometry, ...],
    selected: list[OSMDirectedGeometry],
    path: Path,
) -> None:
    south, west, north, east = BBOX
    width, height, margin = 900, 780, 30
    span_lon = east - west
    span_lat = north - south
    chosen = {edge.osm_way_id for edge in selected}
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">',
        '<rect width="100%" height="100%" fill="white"/>',
    ]
    palette = {
        StructureStatus.NORMAL: "#9ecae1",
        StructureStatus.BRIDGE: "#fd8d3c",
        StructureStatus.TUNNEL: "#756bb1",
        StructureStatus.STACKED: "#31a354",
    }
    drawn: set[int] = set()
    for edge in edges:
        if edge.osm_way_id in drawn:
            continue
        drawn.add(edge.osm_way_id)
        # Drop vertices that land within a pixel of the previous one. At this
        # scale one pixel is about 14 m on the ground, so nothing visible is
        # lost and the file stops carrying full survey geometry.
        pixels: list[tuple[float, float]] = []
        for lon, lat in edge.lonlat:
            position = (
                margin + (width - 2 * margin) * (lon - west) / span_lon,
                height - margin - (height - 2 * margin) * (lat - south) / span_lat,
            )
            if (
                not pixels
                or max(abs(position[0] - pixels[-1][0]), abs(position[1] - pixels[-1][1])) >= 1.0
            ):
                pixels.append(position)
        if len(pixels) < 2:
            pixels = [
                (
                    margin + (width - 2 * margin) * (lon - west) / span_lon,
                    height - margin - (height - 2 * margin) * (lat - south) / span_lat,
                )
                for lon, lat in (edge.lonlat[0], edge.lonlat[-1])
            ]
        points = " ".join(f"{x:.1f},{y:.1f}" for x, y in pixels)
        if edge.osm_way_id in chosen:
            colour, stroke = "#d73027", 3.0
        elif edge.access_status is AccessStatus.PROHIBITED:
            colour, stroke = "#cccccc", 0.6
        else:
            colour, stroke = palette[edge.structure_status], 0.9
        lines.append(
            f'<polyline points="{points}" fill="none" stroke="{colour}" stroke-width="{stroke}"/>'
        )
    legend = [
        ("selected profile way", "#d73027"),
        ("normal admissible/review", "#9ecae1"),
        ("bridge", "#fd8d3c"),
        ("tunnel or covered", "#756bb1"),
        ("stacked (layer != 0)", "#31a354"),
        ("prohibited to bicycles", "#cccccc"),
    ]
    lines.append(
        '<text x="20" y="24" font-family="sans-serif" font-size="15">'
        "Live OSM Oisans road graph — pipeline validation, not a ranking</text>"
    )
    for index, (label, colour) in enumerate(legend):
        y = 44 + 18 * index
        lines.append(f'<rect x="20" y="{y - 9}" width="18" height="10" fill="{colour}"/>')
        lines.append(f'<text x="44" y="{y}" font-family="sans-serif" font-size="12">{label}</text>')
    lines.append("</svg>")
    write_text_lf(path, "\n".join(lines))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", default=".cache/phase1b-live")
    parser.add_argument("--output", default="outputs/phase1/live")
    parser.add_argument("--max-edges", type=int, default=6)
    arguments = parser.parse_args()

    started = time.monotonic()
    cache = Path(arguments.cache)
    cache.mkdir(parents=True, exist_ok=True)
    retrieved = datetime.now(UTC).replace(microsecond=0).isoformat()
    session = Session()
    timings: dict[str, float] = {}

    # --- discovery -----------------------------------------------------------
    phase = time.monotonic()
    discovery: dict[str, dict[str, object]] = {}
    for label, url in (
        ("ign-service-root", ALTIMETRY_ROOT),
        ("ign-resource-index", ALTIMETRY_RESOURCE_INDEX),
        ("ign-resource-primary", f"{ALTIMETRY_RESOURCE_INDEX}/{PRIMARY_RESOURCE}"),
        ("ign-resource-control", f"{ALTIMETRY_RESOURCE_INDEX}/{CONTROL_RESOURCE}"),
        ("overpass-status", OVERPASS_STATUS_ENDPOINT),
    ):
        payload = session.fetch(label, url)
        (cache / f"discovery-{label}.txt").write_bytes(payload)
        discovery[label] = {
            "url": url,
            "bytes": len(payload),
            "sha256": sha256_bytes(payload),
        }
    service_version = json.loads((cache / "discovery-ign-service-root.txt").read_bytes()).get(
        "message", "unknown"
    )
    discovery["ign-service-root"]["service_version"] = service_version
    timings["discovery_s"] = time.monotonic() - phase

    # --- OpenStreetMap extraction -------------------------------------------
    phase = time.monotonic()
    query = overpass_query()
    osm_bytes = session.fetch(
        "overpass-interpreter",
        OVERPASS_ENDPOINT,
        data=urllib.parse.urlencode({"data": query}).encode(),
    )
    (cache / "oisans-overpass.json").write_bytes(osm_bytes)
    osm = json.loads(osm_bytes)
    timings["overpass_s"] = time.monotonic() - phase

    phase = time.monotonic()
    raw_ways = [
        element
        for element in osm.get("elements", [])
        if element.get("type") == "way" and "highway" in element.get("tags", {})
    ]
    edges = parse_osm_directed_edges(osm)
    restrictions = parse_turn_restrictions(osm)
    selected = select_profile_edges(edges, arguments.max_edges)
    timings["graph_build_s"] = time.monotonic() - phase

    osm_timestamp = osm.get("osm3s", {}).get("timestamp_osm_base")
    geometry_provenance = SourceProvenance(
        producer="OpenStreetMap contributors",
        dataset="OSM road network, Overpass bounded extract",
        version=f"osm base {osm_timestamp}",
        retrieval_date=retrieved,
        source_url=OVERPASS_ENDPOINT,
        original_crs="EPSG:4326",
        original_units="degree",
        sha256=sha256_bytes(osm_bytes),
        discovery_url="https://www.openstreetmap.org/copyright",
        licence=OSM_LICENCE,
        attribution=OSM_ATTRIBUTION,
        byte_size=len(osm_bytes),
    )

    def elevation_provenance(resource: str) -> SourceProvenance:
        return SourceProvenance(
            producer="IGN",
            dataset=f"RGE ALTI via Géoplateforme altimetry API, resource {resource}",
            version=service_version,
            retrieval_date=retrieved,
            source_url=ALTIMETRY_ENDPOINT,
            original_crs="EPSG:4326 request / EPSG:2154 profile",
            original_units="metre",
            discovery_url=f"{ALTIMETRY_RESOURCE_INDEX}/{resource}",
            vertical_datum=IGN_VERTICAL_DATUM,
            licence=IGN_LICENCE,
            attribution=IGN_ATTRIBUTION,
            elevation_model_kind="terrain",
        )

    output = Path(arguments.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix="phase1b-", dir=output.parent))
    cache_index: dict[str, dict[str, object]] = {}
    try:
        (temporary / "profiles").mkdir()
        sampling_rows: list[dict[str, object]] = []
        simulation_rows: list[dict[str, object]] = []
        comparison_rows: list[dict[str, object]] = []
        audit_rows: list[dict[str, object]] = []

        phase = time.monotonic()
        for edge in selected:
            hairpins = hairpin_count(edge)
            for spacing in SPACINGS_M:
                points = densify_lonlat(edge.lonlat, spacing)
                lonlat = [(point[0], point[1]) for point in points]
                elevations = fetch_elevations(session, lonlat, PRIMARY_RESOURCE, cache, cache_index)
                missing = sum(1 for value in elevations if value is None)
                if missing:
                    raise RuntimeError(
                        f"{edge.edge_id} at {spacing:g} m has {missing} point(s) outside "
                        f"{PRIMARY_RESOURCE} coverage; a live profile cannot be built."
                    )
                chainage = [point[4] for point in points]
                measured = [float(value) for value in elevations]
                conditioned = box_filter_elevations(chainage, measured, CONDITIONING_WINDOW_M)

                variants = {"raw": measured, "conditioned": list(conditioned)}
                for variant, series in variants.items():
                    road_edge = build_edge(
                        edge,
                        points,
                        tuple(series),
                        geometry_provenance,
                        elevation_provenance(PRIMARY_RESOURCE),
                        f"{spacing:g}m-{variant}",
                    )
                    segments = build_profile_segments(
                        road_edge,
                        max_abs_grade_ratio=DIAGNOSTIC_MAX_GRADE_RATIO,
                        max_elevation_jump_m=DIAGNOSTIC_MAX_ELEVATION_JUMP_M,
                    )
                    metrics = profile_metrics(
                        segments,
                        max_simulable_grade_ratio=MAX_SIMULABLE_GRADE_RATIO,
                        elevation_break_m=ELEVATION_BREAK_M,
                    )
                    sampling_rows.append(
                        metrics_row(edge, spacing, variant, metrics, missing, hairpins, retrieved)
                    )
                    row = simulation_row(edge, spacing, variant, metrics, retrieved)
                    if metrics.contract_violation_count == 0:
                        run_simulation(segments, row)
                    simulation_rows.append(row)

                profile_path = temporary / "profiles" / f"{edge.edge_id}-{spacing:g}m.csv"
                with profile_path.open("w", newline="", encoding="utf-8") as handle:
                    writer = csv.writer(handle, lineterminator="\n")
                    writer.writerow(
                        [
                            "source",
                            "retrieved_at",
                            "osm_way_id",
                            "chainage_m",
                            "longitude",
                            "latitude",
                            "x_epsg2154_m",
                            "y_epsg2154_m",
                            "elevation_measured_m",
                            "elevation_conditioned_m",
                        ]
                    )
                    for point, measured_z, conditioned_z in zip(points, measured, conditioned):
                        writer.writerow(
                            [
                                "live",
                                retrieved,
                                edge.osm_way_id,
                                f"{point[4]:.4f}",
                                f"{point[0]:.7f}",
                                f"{point[1]:.7f}",
                                f"{point[2]:.3f}",
                                f"{point[3]:.3f}",
                                f"{measured_z:.2f}",
                                f"{conditioned_z:.4f}",
                            ]
                        )

                if spacing == CONTROL_SPACING_M:
                    control = fetch_elevations(
                        session, lonlat, CONTROL_RESOURCE, cache, cache_index
                    )
                    if any(value is None for value in control):
                        raise RuntimeError(
                            f"{edge.edge_id} has points outside {CONTROL_RESOURCE} coverage."
                        )
                    differences = [
                        float(primary) - float(other) for primary, other in zip(measured, control)
                    ]
                    ordered = sorted(abs(value) for value in differences)
                    comparison_rows.append(
                        {
                            "source": "live",
                            "retrieved_at": retrieved,
                            "osm_way_id": edge.osm_way_id,
                            "edge_id": edge.edge_id,
                            "spacing_m": spacing,
                            "primary_resource": PRIMARY_RESOURCE,
                            "control_resource": CONTROL_RESOURCE,
                            "point_count": len(differences),
                            "mean_difference_m": round(sum(differences) / len(differences), 4),
                            "min_difference_m": round(min(differences), 3),
                            "max_difference_m": round(max(differences), 3),
                            "p95_absolute_difference_m": round(
                                ordered[int(0.95 * (len(ordered) - 1))], 3
                            ),
                            "max_absolute_difference_m": round(ordered[-1], 3),
                        }
                    )
        timings["profiles_s"] = time.monotonic() - phase

        # --- graph quality ---------------------------------------------------
        graph_rows = []
        for edge in edges:
            tags = dict(edge.tags)
            graph_rows.append(
                {
                    "source": "live",
                    "edge_id": edge.edge_id,
                    "osm_way_id": edge.osm_way_id,
                    "direction": edge.direction,
                    "node_count": len(edge.node_ids),
                    "first_node_id": edge.node_ids[0] if edge.node_ids else "",
                    "last_node_id": edge.node_ids[-1] if edge.node_ids else "",
                    "highway": tags.get("highway", ""),
                    "access_status": edge.access_status.value,
                    "access_reason": edge.access_reason,
                    "structure_status": edge.structure_status.value,
                    "oneway": tags.get("oneway", ""),
                    "oneway_bicycle": tags.get("oneway:bicycle", ""),
                    "junction": tags.get("junction", ""),
                    "bicycle": tags.get("bicycle", ""),
                    "access": tags.get("access", ""),
                    "vehicle": tags.get("vehicle", ""),
                    "surface": tags.get("surface", ""),
                    "smoothness": tags.get("smoothness", ""),
                    "tracktype": tags.get("tracktype", ""),
                    "bridge": tags.get("bridge", ""),
                    "tunnel": tags.get("tunnel", ""),
                    "covered": tags.get("covered", ""),
                    "layer": tags.get("layer", ""),
                    "selected_for_profile": edge.osm_way_id
                    in {item.osm_way_id for item in selected}
                    and edge.direction == "forward",
                }
            )
        write_csv(temporary / "graph_quality.csv", graph_rows, list(graph_rows[0]))

        structure_rows = [row for row in graph_rows if row["structure_status"] != "normal"]
        for row in structure_rows:
            row["decision"] = "review_required"
            row["reason"] = (
                "terrain model cannot describe a deck, bore or stacked level; "
                "roadway elevation is unknown"
            )
        write_csv(
            temporary / "structure_review.csv",
            structure_rows,
            list(structure_rows[0]) if structure_rows else ["source"],
        )

        restriction_rows = [
            {
                "source": "live",
                "relation_id": item.relation_id,
                "restriction": item.restriction,
                "from_way_ids": ";".join(str(value) for value in item.from_way_ids),
                "via_node_ids": ";".join(str(value) for value in item.via_node_ids),
                "via_way_ids": ";".join(str(value) for value in item.via_way_ids),
                "to_way_ids": ";".join(str(value) for value in item.to_way_ids),
            }
            for item in restrictions
        ]
        if restriction_rows:
            write_csv(
                temporary / "turn_restrictions.csv", restriction_rows, list(restriction_rows[0])
            )

        # --- manual audit sample --------------------------------------------
        # The longest instance of each category is taken, because a 15 m stub
        # illustrates nothing.  Length plays no part in the structure decision
        # itself, so this cannot bias the result.  Ties resolve to the lowest
        # way identifier.
        forward_edges = [edge for edge in edges if edge.direction == "forward"]

        def longest_matching(predicate) -> OSMDirectedGeometry | None:
            matches = [edge for edge in forward_edges if predicate(edge, dict(edge.tags))]
            if not matches:
                return None
            return max(matches, key=lambda edge: (edge_length_m(edge), -edge.osm_way_id))

        hairpin_edge = max(selected, key=hairpin_count)
        plain_edge = next(
            (edge for edge in selected if edge.osm_way_id != hairpin_edge.osm_way_id),
            selected[0],
        )
        # Whichever profiled way the terrain model damaged most, so the audit
        # documents an actual defect rather than only well-behaved cases.
        violations_by_way: dict[int, int] = {}
        for row in sampling_rows:
            if row["variant"] == "raw":
                way = int(row["osm_way_id"])
                violations_by_way[way] = violations_by_way.get(way, 0) + int(
                    row["contract_violation_count"]
                )
        worst_way = max(violations_by_way, key=lambda key: (violations_by_way[key], -key))
        worst_edge = (
            next(edge for edge in selected if edge.osm_way_id == worst_way)
            if violations_by_way[worst_way]
            else None
        )
        audit_targets = [
            ("normal_road", plain_edge),
            ("hairpin", hairpin_edge),
            ("worst_raw_artifact", worst_edge),
            ("bridge", longest_matching(lambda edge, tags: tags.get("bridge") not in (None, "no"))),
            ("tunnel", longest_matching(lambda edge, tags: tags.get("tunnel") not in (None, "no"))),
            ("covered", longest_matching(lambda edge, tags: tags.get("covered") == "yes")),
            (
                "layer_non_zero",
                longest_matching(
                    lambda edge, tags: (
                        tags.get("layer") not in (None, "0")
                        and tags.get("bridge") in (None, "no")
                        and tags.get("tunnel") in (None, "no")
                    )
                ),
            ),
            (
                "ambiguous_bicycle_access",
                longest_matching(lambda edge, tags: edge.access_status is AccessStatus.REVIEW),
            ),
        ]
        for category, edge in audit_targets:
            if edge is None:
                continue
            tags = dict(edge.tags)
            dense = densify_lonlat(edge.lonlat, 10.0)
            audit_rows.append(
                {
                    "source": "live",
                    "category": category,
                    "osm_way_id": edge.osm_way_id,
                    "edge_id": edge.edge_id,
                    "osm_url": f"https://www.openstreetmap.org/way/{edge.osm_way_id}",
                    "node_count": len(edge.node_ids),
                    "geometry_points": len(edge.lonlat),
                    "horizontal_length_m": round(dense[-1][4], 1),
                    "hairpin_count": len(hairpin_turns(dense)),
                    "access_status": edge.access_status.value,
                    "access_reason": edge.access_reason,
                    "structure_status": edge.structure_status.value,
                    "surface_quality": surface_quality(tags),
                    "pipeline_decision": (
                        "profiled"
                        if edge.osm_way_id in {item.osm_way_id for item in selected}
                        else "not profiled"
                    ),
                    "elevation_assigned": edge.structure_status is StructureStatus.NORMAL
                    and edge.osm_way_id in {item.osm_way_id for item in selected},
                    "tags": json.dumps(tags, sort_keys=True, ensure_ascii=False),
                }
            )
        write_csv(temporary / "manual_edge_audit.csv", audit_rows, list(audit_rows[0]))

        write_csv(temporary / "sampling_comparison.csv", sampling_rows, list(sampling_rows[0]))
        write_csv(temporary / "profile_simulations.csv", simulation_rows, list(simulation_rows[0]))
        write_csv(
            temporary / "elevation_source_comparison.csv",
            comparison_rows,
            list(comparison_rows[0]),
        )
        write_csv(
            temporary / "http_transaction_log.csv",
            [
                {
                    "label": item.label,
                    "attempt": item.attempt,
                    "outcome": item.outcome,
                    "method": item.method,
                    "url": item.url if len(item.url) <= 300 else f"{item.url[:297]}...",
                    "status": item.status,
                    "redirected": item.redirected,
                    "final_url": item.final_url
                    if len(item.final_url) <= 300
                    else f"{item.final_url[:297]}...",
                    "content_type": item.content_type,
                    "response_bytes": item.response_bytes,
                    "response_sha256": item.sha256,
                    "elapsed_s": round(item.elapsed_s, 3),
                }
                for item in session.transactions
            ],
            [
                "label",
                "attempt",
                "outcome",
                "method",
                "url",
                "status",
                "redirected",
                "final_url",
                "content_type",
                "response_bytes",
                "response_sha256",
                "elapsed_s",
            ],
        )

        # --- summaries --------------------------------------------------------
        counts = {
            "raw_osm_highway_ways": len(raw_ways),
            "directed_edges_created": len(edges),
            "directed_edges_admissible": sum(
                1 for edge in edges if edge.access_status is AccessStatus.ADMISSIBLE
            ),
            "directed_edges_prohibited": sum(
                1 for edge in edges if edge.access_status is AccessStatus.PROHIBITED
            ),
            "directed_edges_review": sum(
                1 for edge in edges if edge.access_status is AccessStatus.REVIEW
            ),
            "directed_edges_normal": sum(
                1 for edge in edges if edge.structure_status is StructureStatus.NORMAL
            ),
            "directed_edges_bridge": sum(
                1 for edge in edges if edge.structure_status is StructureStatus.BRIDGE
            ),
            "directed_edges_tunnel": sum(
                1 for edge in edges if edge.structure_status is StructureStatus.TUNNEL
            ),
            "directed_edges_stacked": sum(
                1 for edge in edges if edge.structure_status is StructureStatus.STACKED
            ),
            "structure_edges_total": len(structure_rows),
            "restriction_relations": len(restrictions),
            "osm_nodes_returned": sum(
                1 for element in osm.get("elements", []) if element.get("type") == "node"
            ),
            "profile_ways_selected": len(selected),
            "profile_results": len(sampling_rows),
            "profile_simulations_run": sum(1 for row in simulation_rows if row["simulated"]),
        }
        summary = {
            "source": "live",
            "retrieved_at": retrieved,
            "bbox_wgs84_south_west_north_east": list(BBOX),
            "endpoint": OVERPASS_ENDPOINT,
            "query": query,
            "osm_timestamp_base": osm_timestamp,
            "response_bytes": len(osm_bytes),
            "response_sha256": sha256_bytes(osm_bytes),
            "licence": OSM_LICENCE,
            "attribution": OSM_ATTRIBUTION,
            "counts": counts,
            "way_ids": sorted(int(way["id"]) for way in raw_ways),
            "restriction_relation_ids": sorted(item.relation_id for item in restrictions),
            "selected_way_ids": sorted(edge.osm_way_id for edge in selected),
            "selected_way_node_ids": {
                str(edge.osm_way_id): list(edge.node_ids) for edge in selected
            },
            "node_id_note": (
                "Individual node identifiers for non-selected ways are pinned by "
                "response_sha256 rather than duplicated here."
            ),
        }
        (temporary / "osm_extraction_summary.json").write_bytes(canonical_json_bytes(summary))

        timings["total_s"] = time.monotonic() - started
        manifest = {
            "source": "live",
            "retrieved_at": retrieved,
            "bbox_wgs84_south_west_north_east": list(BBOX),
            "discovery": discovery,
            "sources": [
                {
                    "producer": "OpenStreetMap contributors",
                    "product": "OSM road network",
                    "resource": "Overpass API bounded extract",
                    "discovery_url": "https://www.openstreetmap.org/copyright",
                    "request_url": OVERPASS_ENDPOINT,
                    "retrieved_at_utc": retrieved,
                    "bytes": len(osm_bytes),
                    "sha256": sha256_bytes(osm_bytes),
                    "horizontal_crs": "EPSG:4326",
                    "vertical_datum": None,
                    "units": "degree",
                    "licence": OSM_LICENCE,
                    "attribution": OSM_ATTRIBUTION,
                    "database_timestamp": osm_timestamp,
                },
                {
                    "producer": "IGN",
                    "product": "RGE ALTI via Géoplateforme altimetry API",
                    "resource": PRIMARY_RESOURCE,
                    "role": "primary terrain elevation",
                    "discovery_url": f"{ALTIMETRY_RESOURCE_INDEX}/{PRIMARY_RESOURCE}",
                    "request_url": ALTIMETRY_ENDPOINT,
                    "retrieved_at_utc": retrieved,
                    "service_version": service_version,
                    "horizontal_crs": "EPSG:4326 request, EPSG:2154 profile",
                    "vertical_datum": IGN_VERTICAL_DATUM,
                    "units": "metre",
                    "licence": IGN_LICENCE,
                    "attribution": IGN_ATTRIBUTION,
                    "elevation_model_kind": "terrain",
                },
                {
                    "producer": "IGN",
                    "product": "RGE ALTI via Géoplateforme altimetry API",
                    "resource": CONTROL_RESOURCE,
                    "role": "independent same-producer control",
                    "discovery_url": f"{ALTIMETRY_RESOURCE_INDEX}/{CONTROL_RESOURCE}",
                    "request_url": ALTIMETRY_ENDPOINT,
                    "retrieved_at_utc": retrieved,
                    "service_version": service_version,
                    "horizontal_crs": "EPSG:4326 request, EPSG:2154 profile",
                    "vertical_datum": IGN_VERTICAL_DATUM,
                    "units": "metre",
                    "licence": IGN_LICENCE,
                    "attribution": IGN_ATTRIBUTION,
                    "elevation_model_kind": "terrain",
                },
            ],
            "altimetry_cache_files": [cache_index[key] for key in sorted(cache_index)],
            "altimetry_cache_file_count": len(cache_index),
            "http_transactions": len(session.transactions),
            "parameters": {
                "spacings_m": list(SPACINGS_M),
                "conditioning_window_m": CONDITIONING_WINDOW_M,
                "max_simulable_grade_ratio": MAX_SIMULABLE_GRADE_RATIO,
                "elevation_break_m": ELEVATION_BREAK_M,
                "altimetry_max_points_per_request": ALTIMETRY_MAX_POINTS_PER_REQUEST,
                "selection_min_length_m": SELECTION_MIN_LENGTH_M,
                "selection_max_length_m": SELECTION_MAX_LENGTH_M,
            },
            "timings_s": {key: round(value, 2) for key, value in timings.items()},
            "counts": counts,
            "limitations": LIMITATIONS,
        }
        (temporary / "data_manifest.json").write_bytes(canonical_json_bytes(manifest))

        simulated = counts["profile_simulations_run"]
        raw_blocked = sum(
            1 for row in simulation_rows if row["variant"] == "raw" and not row["simulated"]
        )
        conditioned_blocked = sum(
            1 for row in simulation_rows if row["variant"] == "conditioned" and not row["simulated"]
        )
        report_lines = [
            "# Phase 1B live Oisans reconstruction",
            "",
            "source = live  ",
            f"retrieved (UTC) = {retrieved}  ",
            f"OSM database timestamp = {osm_timestamp}  ",
            f"OSM response = {len(osm_bytes)} bytes, SHA-256 {sha256_bytes(osm_bytes)}  ",
            f"IGN altimetry service = {service_version}  ",
            f"primary elevation resource = {PRIMARY_RESOURCE}  ",
            f"control elevation resource = {CONTROL_RESOURCE}",
            "",
            "## Graph",
            "",
            f"- raw OSM highway ways: {counts['raw_osm_highway_ways']}",
            f"- directed edges created: {counts['directed_edges_created']}",
            (
                f"- admissible: {counts['directed_edges_admissible']}, "
                f"prohibited: {counts['directed_edges_prohibited']}, "
                f"to review: {counts['directed_edges_review']}"
            ),
            (
                f"- structures detected: {counts['directed_edges_bridge']} bridge, "
                f"{counts['directed_edges_tunnel']} tunnel/covered, "
                f"{counts['directed_edges_stacked']} stacked"
            ),
            f"- turn-restriction relations: {counts['restriction_relations']}",
            f"- ways selected for profiling: {counts['profile_ways_selected']}",
            "",
            "## Profiles",
            "",
            (
                f"{counts['profile_results']} profile results were built "
                f"({counts['profile_ways_selected']} ways x {len(SPACINGS_M)} spacings x 2 "
                f"variants) and {simulated} were simulated."
            ),
            "",
            (
                "`raw` is the unmodified sampled terrain profile. `conditioned` applies the "
                f"declared {CONDITIONING_WINDOW_M:g} m centred moving average on elevation "
                "against chainage, which is the named scenario of the geometry contract, "
                "applied identically at every spacing so the comparison stays fair."
            ),
            "",
            (
                f"{raw_blocked} raw and {conditioned_blocked} conditioned results exceeded the "
                f"simulator's |grade| <= {MAX_SIMULABLE_GRADE_RATIO} validity bound and were "
                "reported unsimulated rather than clipped."
            ),
            "",
            "## Reading the outputs",
            "",
            (
                "- `sampling_comparison.csv` — geometry and grade statistics per way, spacing "
                "and variant."
            ),
            (
                "- `profile_simulations.csv` — separated coasting-time metrics for the same "
                "keys, with an explicit reason when a result was not simulated."
            ),
            (
                "- `elevation_source_comparison.csv` — primary against control resource on "
                "identical points."
            ),
            (
                "- `graph_quality.csv` — every directed edge with the tags that drove its "
                "access and structure decision."
            ),
            "- `structure_review.csv` — edges that must not receive terrain elevation.",
            "- `manual_edge_audit.csv` — the hand-inspected sample.",
            "- `http_transaction_log.csv` — every request, status, size and duration.",
            "",
            "## Caveats",
            "",
            *[f"- {item}" for item in LIMITATIONS],
            "",
            f"{OSM_ATTRIBUTION}, {OSM_LICENCE}. {IGN_ATTRIBUTION}, {IGN_LICENCE}.",
            "",
        ]
        write_text_lf(temporary / "phase1b_report.md", "\n".join(report_lines))
        write_map(edges, selected, temporary / "real_graph_map.svg")

        if output.exists():
            shutil.rmtree(output)
        temporary.rename(output)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise

    print(f"Wrote verified live outputs to {output}")
    print(
        f"  ways={counts['raw_osm_highway_ways']} edges={counts['directed_edges_created']} "
        f"profiled={counts['profile_ways_selected']} results={counts['profile_results']} "
        f"simulated={counts['profile_simulations_run']}"
    )
    print(f"  http={len(session.transactions)} requests, total {timings['total_s']:.1f}s")


if __name__ == "__main__":
    main()
