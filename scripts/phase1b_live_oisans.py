"""One-command compact live Oisans reconstruction (network required)."""

from __future__ import annotations

import argparse
import csv
import json
import math
import shutil
import tempfile
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from coastdown import (
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
    canonical_json_bytes,
    densify_lonlat,
    extract_elevations,
    parse_osm_directed_edges,
    sha256_bytes,
)

BBOX = (45.02, 6.02, 45.16, 6.18)  # south, west, north, east
OVERPASS_ENDPOINT = "https://overpass-api.de/api/interpreter"
IGN_DISCOVERY_URLS = (
    "https://data.geopf.fr/telechargement",
    "https://data.geopf.fr/altimetrie/resources",
    "https://data.geopf.fr/altimetrie/resources/ign_rge_alti_wld",
)
ALTIMETRY_ENDPOINT = "https://data.geopf.fr/altimetrie/1.0/calcul/alti/rest/elevation.json"
RGE_RESOURCE = "ign_rge_alti_wld"
SPACINGS_M = (2.0, 5.0, 10.0, 25.0)


def overpass_query() -> str:
    south, west, north, east = BBOX
    return f"""[out:json][timeout:180];
way[\"highway\"]({south},{west},{north},{east})->.roads;
relation(bw.roads)[\"type\"=\"restriction\"]->.restrictions;
(.roads;node(w.roads);.restrictions;);
out meta geom;
"""


def fetch(url: str, *, data: bytes | None = None, timeout: int = 240) -> bytes:
    request = urllib.request.Request(
        url, data=data, headers={"User-Agent": "coastdown-france-phase1b/1.0"}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def fetch_elevations(points, cache_dir: Path) -> tuple[float, ...]:
    values: list[float] = []
    for offset in range(0, len(points), 200):
        chunk = points[offset : offset + 200]
        params = urllib.parse.urlencode(
            {
                "lon": "|".join(f"{point[0]:.9f}" for point in chunk),
                "lat": "|".join(f"{point[1]:.9f}" for point in chunk),
                "resource": RGE_RESOURCE,
                "delimiter": "|",
                "measures": "false",
                "zonly": "true",
            }
        )
        request_url = f"{ALTIMETRY_ENDPOINT}?{params}"
        payload = fetch(request_url)
        request_id = sha256_bytes(request_url.encode())[:16]
        cache_file = cache_dir / f"rge-alti-{request_id}-{offset:06d}.json"
        cache_file.write_bytes(payload)
        values.extend(extract_elevations(json.loads(payload), len(chunk)))
    return tuple(values)


def select_edges(edges: tuple[OSMDirectedGeometry, ...], maximum: int) -> list[OSMDirectedGeometry]:
    selected = []
    seen_ways: set[int] = set()
    for edge in edges:
        if (
            edge.direction == "forward"
            and edge.structure_status is StructureStatus.NORMAL
            and edge.access_status.value == "admissible"
            and edge.osm_way_id not in seen_ways
        ):
            dense = densify_lonlat(edge.lonlat, 25)
            if 80 <= dense[-1][4] <= 2_000:
                selected.append(edge)
                seen_ways.add(edge.osm_way_id)
        if len(selected) >= maximum:
            break
    if len(selected) < 2:
        raise RuntimeError("Fewer than two compact normal admissible OSM ways were found.")
    return selected


def quantile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    position = fraction * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (position - lower) * (ordered[upper] - ordered[lower])


def write_map(
    edges: tuple[OSMDirectedGeometry, ...], selected: list[OSMDirectedGeometry], path: Path
) -> None:
    all_points = [point for edge in edges for point in edge.lonlat]
    min_lon, max_lon = min(p[0] for p in all_points), max(p[0] for p in all_points)
    min_lat, max_lat = min(p[1] for p in all_points), max(p[1] for p in all_points)
    chosen = {edge.edge_id for edge in selected}
    lines = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="900" height="700">',
        '<rect width="100%" height="100%" fill="white"/>',
    ]
    for edge in edges:
        points = " ".join(
            f"{30 + 840 * (lon - min_lon) / (max_lon - min_lon):.1f},{670 - 640 * (lat - min_lat) / (max_lat - min_lat):.1f}"
            for lon, lat in edge.lonlat
        )
        color = "#d73027" if edge.edge_id in chosen else "#aaaaaa"
        lines.append(
            f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="{3 if edge.edge_id in chosen else 1}"/>'
        )
    lines.extend(
        [
            '<text x="20" y="25" font-family="sans-serif">Live OSM Oisans compact graph — no ranking</text>',
            "</svg>",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", default=".cache/phase1b-live")
    parser.add_argument("--output", default="outputs/phase1/live")
    parser.add_argument("--max-edges", type=int, default=4)
    args = parser.parse_args()
    cache = Path(args.cache)
    cache.mkdir(parents=True, exist_ok=True)
    retrieved = datetime.now(UTC).replace(microsecond=0).isoformat()

    discovery = {}
    for index, url in enumerate(IGN_DISCOVERY_URLS):
        payload = fetch(url)
        (cache / f"ign-discovery-{index}.json").write_bytes(payload)
        discovery[url] = {"bytes": len(payload), "sha256": sha256_bytes(payload)}

    query = overpass_query()
    osm_bytes = fetch(
        OVERPASS_ENDPOINT,
        data=urllib.parse.urlencode({"data": query}).encode(),
    )
    (cache / "oisans-overpass.json").write_bytes(osm_bytes)
    osm = json.loads(osm_bytes)
    edges = parse_osm_directed_edges(osm)
    selected = select_edges(edges, args.max_edges)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix="phase1b-", dir=output.parent))
    try:
        (temporary / "profiles").mkdir()
        rows = []
        elevation_files_before = set(cache.glob("rge-alti-*.json"))
        for edge in selected:
            tags = dict(edge.tags)
            for spacing in SPACINGS_M:
                points = densify_lonlat(edge.lonlat, spacing)
                elevations = fetch_elevations(points, cache)
                profile_path = temporary / "profiles" / f"{edge.edge_id}-{spacing:g}m.csv"
                with profile_path.open("w", newline="", encoding="utf-8") as profile_handle:
                    profile_writer = csv.writer(profile_handle, lineterminator="\n")
                    profile_writer.writerow(
                        [
                            "source",
                            "retrieved_at",
                            "chainage_m",
                            "longitude",
                            "latitude",
                            "x_epsg2154_m",
                            "y_epsg2154_m",
                            "elevation_rge_alti_m",
                        ]
                    )
                    for point, elevation in zip(points, elevations):
                        profile_writer.writerow(
                            [
                                "live",
                                retrieved,
                                point[4],
                                point[0],
                                point[1],
                                point[2],
                                point[3],
                                elevation,
                            ]
                        )
                elevation_provenance = SourceProvenance(
                    "IGN",
                    "RGE ALTI API",
                    RGE_RESOURCE,
                    retrieved,
                    ALTIMETRY_ENDPOINT,
                    "EPSG:4326 request / EPSG:2154 profile",
                    "metre",
                )
                geometry_provenance = SourceProvenance(
                    "OpenStreetMap contributors",
                    f"OSM way {edge.osm_way_id}",
                    str(osm.get("osm3s", {}).get("timestamp_osm_base", "unknown")),
                    retrieved,
                    OVERPASS_ENDPOINT,
                    "EPSG:4326",
                    "degree",
                    sha256_bytes(osm_bytes),
                )
                samples = tuple(
                    ElevationSample(point[2], point[3], elevation, point[4], elevation_provenance)
                    for point, elevation in zip(points, elevations)
                )
                road_edge = DirectedRoadEdge(
                    edge.edge_id,
                    samples,
                    geometry_provenance,
                    elevation_provenance,
                    "EPSG:2154",
                    edge.access_status,
                    edge.structure_status,
                    edge.tags,
                )
                segments = build_profile_segments(
                    road_edge, max_abs_grade_ratio=1.0, max_elevation_jump_m=100
                )
                profile = RoadProfile(
                    [segment.travelled_length_m for segment in segments],
                    [segment.grade_ratio for segment in segments],
                )
                simulation = simulate_profile(profile)
                grades = [segment.grade_ratio for segment in segments]
                dzs = [segment.elevation_change_m for segment in segments]
                rows.append(
                    {
                        "source": "live",
                        "retrieved_at": retrieved,
                        "osm_way_id": edge.osm_way_id,
                        "edge_id": edge.edge_id,
                        "spacing_m": spacing,
                        "horizontal_length_m": sum(item.horizontal_length_m for item in segments),
                        "travelled_length_m": sum(item.travelled_length_m for item in segments),
                        "net_dz_m": sum(dzs),
                        "ascent_m": sum(max(0, value) for value in dzs),
                        "descent_m": -sum(min(0, value) for value in dzs),
                        "min_grade_ratio": min(grades),
                        "q05_grade_ratio": quantile(grades, 0.05),
                        "median_grade_ratio": quantile(grades, 0.5),
                        "q95_grade_ratio": quantile(grades, 0.95),
                        "max_grade_ratio": max(grades),
                        "anomaly_count": sum(abs(value) > 0.5 for value in grades),
                        "elapsed_time_s": simulation.elapsed_time_s,
                        "moving_time_s": simulation.moving_time_s,
                        "stationary_time_s": simulation.stationary_time_s,
                        "first_below_threshold_time_s": simulation.first_below_threshold_time_s,
                        "first_zero_speed_time_s": simulation.first_zero_speed_time_s,
                        "qualified_stop_time_s": simulation.qualified_stop_time_s,
                        "stop_reason": simulation.stop_reason,
                        "highway": tags.get("highway", ""),
                        "surface": tags.get("surface", ""),
                    }
                )
        with (temporary / "sampling_comparison.csv").open(
            "w", newline="", encoding="utf-8"
        ) as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        shutil.copy(temporary / "sampling_comparison.csv", temporary / "profile_simulations.csv")

        restrictions = [item for item in osm.get("elements", []) if item.get("type") == "relation"]
        summary = {
            "source": "live",
            "retrieved_at": retrieved,
            "osm_timestamp": osm.get("osm3s", {}).get("timestamp_osm_base"),
            "query": query,
            "endpoint": OVERPASS_ENDPOINT,
            "response_bytes": len(osm_bytes),
            "response_sha256": sha256_bytes(osm_bytes),
            "directed_edges": len(edges),
            "selected_profile_edges": len(selected),
            "restriction_relations": len(restrictions),
        }
        (temporary / "osm_extraction_summary.json").write_bytes(canonical_json_bytes(summary))
        with (temporary / "graph_quality.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerow(["source", "edge_id", "osm_way_id", "direction", "access", "structure"])
            for edge in edges:
                writer.writerow(
                    [
                        "live",
                        edge.edge_id,
                        edge.osm_way_id,
                        edge.direction,
                        edge.access_status.value,
                        edge.structure_status.value,
                    ]
                )
        with (temporary / "structure_review.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerow(
                ["source", "osm_way_id", "structure", "osm_tags", "bd_topo_status", "decision"]
            )
            for edge in edges:
                if edge.structure_status is not StructureStatus.NORMAL:
                    writer.writerow(
                        [
                            "live",
                            edge.osm_way_id,
                            edge.structure_status.value,
                            json.dumps(dict(edge.tags), sort_keys=True),
                            "catalogue discovered; compact object match pending",
                            "review_required",
                        ]
                    )
        write_map(edges, selected, temporary / "real_graph_map.svg")
        elevation_files = sorted(set(cache.glob("rge-alti-*.json")) - elevation_files_before)
        manifest = {
            "source": "live",
            "retrieved_at": retrieved,
            "bbox_wgs84": BBOX,
            "ign_discovery": discovery,
            "rge_resource": RGE_RESOURCE,
            "rge_endpoint": ALTIMETRY_ENDPOINT,
            "osm": summary,
            "altimetry_cache_files": [
                {
                    "name": path.name,
                    "bytes": path.stat().st_size,
                    "sha256": sha256_bytes(path.read_bytes()),
                }
                for path in elevation_files
            ],
            "limitations": [
                "RGE terrain elevations are not assigned to structure edges",
                "BD TOPO compact object matching remains review-only",
                "Copernicus control requires a separately authorized download",
                "No regional or national ranking is produced",
            ],
        }
        (temporary / "data_manifest.json").write_bytes(canonical_json_bytes(manifest))
        (temporary / "phase1b_report.md").write_text(
            f"# Phase 1B live Oisans report\n\nsource = live  \nretrieved = {retrieved}  \n"
            f"OSM timestamp = {summary['osm_timestamp']}  \nOSM SHA-256 = {summary['response_sha256']}\n\n"
            f"Built {len(rows)} spacing/profile results from {len(selected)} real OSM ways and live RGE ALTI elevations. Structure edges remain review-only; terrain elevation was not assigned. This is pipeline validation, not a route ranking.\n",
            encoding="utf-8",
        )
        if output.exists():
            shutil.rmtree(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary.rename(output)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    print(f"Wrote verified live outputs to {output}")


if __name__ == "__main__":
    main()
