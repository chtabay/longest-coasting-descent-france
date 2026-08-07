"""Independent controls on the Phase 2 inputs: Copernicus GLO-30 and IGN BD TOPO.

Phase 1B compared RGE ALTI against another RGE ALTI resource, which bounds
sampling and pyramid effects but says nothing about absolute accuracy: same
producer, same acquisition, same errors.  Copernicus GLO-30 is a genuinely
independent measurement — different mission, different sensor, different
vertical datum — so it can expose a systematic bias that no internal comparison
would ever reveal.

Its 30 m posting cannot validate the grade of a 25 m segment, and it is a
*surface* model that includes vegetation and buildings where RGE ALTI is bare
earth.  It is therefore used only to find mean bias, gross inconsistencies and
problem sectors, never to correct an elevation.

BD TOPO is IGN's authoritative topographic database.  It does not replace OSM as
the cycling graph — its legal cycling semantics are thinner — but it is the right
source to ask whether the bridges, tunnels and stacked ways OSM declares are
really there, and whether either source is missing structures the other sees.

Both endpoints are open and need no credential, which is checked rather than
assumed: any refusal is recorded and the run continues.
"""

from __future__ import annotations

import argparse
import csv
import itertools
import json
import math
import statistics
import struct
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

from coastdown.elevation_store import elevations_for, load_store
from coastdown.geography import StructureStatus, lonlat_to_lambert93
from coastdown.graph import build_graph
from coastdown.live_oisans import parse_osm_directed_edges, sha256_bytes
from coastdown.textio import write_text_lf

USER_AGENT = (
    "coastdown-france-phase2/1.0 (+https://github.com/chtabay/longest-coasting-descent-france)"
)
BBOX = (45.02, 6.02, 45.16, 6.18)  # south, west, north, east

COPERNICUS_TILE_URL = (
    "https://copernicus-dem-30m.s3.amazonaws.com/"
    "Copernicus_DSM_COG_10_N45_00_E006_00_DEM/Copernicus_DSM_COG_10_N45_00_E006_00_DEM.tif"
)
COPERNICUS_LICENCE = "Copernicus DEM open data terms; © DLR e.V. 2010-2014, © Airbus DS 2014-2018"

WFS_ENDPOINT = "https://data.geopf.fr/wfs/ows"
BDTOPO_ROADS = "BDTOPO_V3:troncon_de_route"
BDTOPO_LICENCE = "Licence Ouverte / Open Licence (Etalab) 2.0"
BDTOPO_ATTRIBUTION = "© IGN — BD TOPO®"
WFS_PAGE = 1000
STRUCTURE_MATCH_RADIUS_M = 30.0


def fetch(url: str, *, byte_range: tuple[int, int] | None = None, timeout: int = 180) -> bytes:
    headers = {"User-Agent": USER_AGENT}
    if byte_range is not None:
        headers["Range"] = f"bytes={byte_range[0]}-{byte_range[1]}"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


# ---------------------------------------------------------------------------
# A minimal GeoTIFF reader, enough for a tiled float32 Copernicus COG.
# rasterio would be the normal tool; it is not a dependency of this study and
# pulling in GDAL to read a few hundred pixels is not proportionate.
# ---------------------------------------------------------------------------


class GeoTiff:
    def __init__(self, url: str) -> None:
        self.url = url
        header = fetch(url, byte_range=(0, 4095))
        if header[:2] not in (b"II", b"MM"):
            raise ValueError("not a TIFF")
        self.endian = "<" if header[:2] == b"II" else ">"
        magic = struct.unpack(self.endian + "H", header[2:4])[0]
        if magic != 42:
            raise ValueError(f"unsupported TIFF magic {magic}")
        ifd_offset = struct.unpack(self.endian + "I", header[4:8])[0]
        block = (
            header
            if ifd_offset + 2 < len(header)
            else fetch(url, byte_range=(ifd_offset, ifd_offset + 65535))
        )
        base = 0 if block is header else ifd_offset
        self.tags = self._read_ifd(block, ifd_offset - base)
        self.width = self.tags[256][0]
        self.height = self.tags[257][0]
        self.tile_width = self.tags[322][0]
        self.tile_height = self.tags[323][0]
        self.tile_offsets = self.tags[324]
        self.tile_counts = self.tags[325]
        self.compression = self.tags[259][0]
        self.bits = self.tags[258][0]
        self.sample_format = self.tags.get(339, [1])[0]
        self.predictor = self.tags.get(317, [1])[0]
        scale = self.tags[33550]
        tiepoint = self.tags[33922]
        self.pixel_scale = (scale[0], scale[1])
        self.origin = (tiepoint[3], tiepoint[4])
        if self.bits != 32 or self.sample_format != 3:
            raise ValueError(
                f"expected float32 samples, got bits={self.bits} format={self.sample_format}"
            )
        self._cache: dict[int, list[float]] = {}

    def _read_ifd(self, block: bytes, offset: int) -> dict[int, list]:
        count = struct.unpack_from(self.endian + "H", block, offset)[0]
        tags: dict[int, list] = {}
        sizes = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 11: 4, 12: 8, 16: 8}
        codes = {1: "B", 2: "c", 3: "H", 4: "I", 11: "f", 12: "d", 16: "Q"}
        for index in range(count):
            entry = offset + 2 + index * 12
            tag, kind, length = struct.unpack_from(self.endian + "HHI", block, entry)
            if kind not in sizes:
                continue
            payload_size = sizes[kind] * length
            if kind == 5:
                values_raw = self._payload(block, entry + 8, payload_size)
                pairs = struct.unpack(self.endian + "II" * length, values_raw)
                tags[tag] = [pairs[i] / pairs[i + 1] for i in range(0, len(pairs), 2)]
                continue
            raw = self._payload(block, entry + 8, payload_size)
            tags[tag] = list(struct.unpack(self.endian + codes[kind] * length, raw))
        return tags

    def _payload(self, block: bytes, position: int, size: int) -> bytes:
        if size <= 4:
            return block[position : position + size]
        pointer = struct.unpack_from(self.endian + "I", block, position)[0]
        if pointer + size <= len(block):
            return block[pointer : pointer + size]
        return fetch(self.url, byte_range=(pointer, pointer + size - 1))

    def _tile(self, index: int) -> list[float]:
        if index in self._cache:
            return self._cache[index]
        raw = fetch(
            self.url,
            byte_range=(
                self.tile_offsets[index],
                self.tile_offsets[index] + self.tile_counts[index] - 1,
            ),
        )
        if self.compression in (8, 32946):
            raw = zlib.decompress(raw)
        elif self.compression != 1:
            raise ValueError(f"unsupported TIFF compression {self.compression}")
        if self.predictor == 3:
            raw = self._undo_float_predictor(raw)
        elif self.predictor not in (1, 0):
            raise ValueError(f"unsupported TIFF predictor {self.predictor}")
        values = list(struct.unpack(self.endian + "f" * (self.tile_width * self.tile_height), raw))
        if len(self._cache) > 24:
            self._cache.clear()
        self._cache[index] = values
        return values

    def _undo_float_predictor(self, raw: bytes) -> bytes:
        """Reverse TIFF predictor 3, floating-point horizontal differencing.

        The encoder splits every row into byte planes — all the most significant
        bytes, then the next, and so on — and stores horizontal differences of
        that byte stream. Ignoring it does not produce slightly wrong elevations,
        it produces numbers like 1e35, which is how this was caught.
        """
        width = self.tile_width
        bytes_per_sample = self.bits // 8
        row_bytes = width * bytes_per_sample
        output = bytearray(len(raw))
        for row_start in range(0, len(raw), row_bytes):
            row = bytearray(raw[row_start : row_start + row_bytes])
            if len(row) < row_bytes:
                break
            accumulated = bytes(bytearray(itertools.accumulate(row, lambda a, b: (a + b) & 0xFF)))
            for sample_index in range(width):
                base = row_start + sample_index * bytes_per_sample
                for byte_index in range(bytes_per_sample):
                    plane = byte_index if self.endian == ">" else bytes_per_sample - byte_index - 1
                    output[base + byte_index] = accumulated[plane * width + sample_index]
        return bytes(output)

    def sample(self, longitude: float, latitude: float) -> float | None:
        column = (longitude - self.origin[0]) / self.pixel_scale[0]
        row = (self.origin[1] - latitude) / self.pixel_scale[1]
        x, y = int(column), int(row)
        if not (0 <= x < self.width and 0 <= y < self.height):
            return None
        tiles_across = (self.width + self.tile_width - 1) // self.tile_width
        index = (y // self.tile_height) * tiles_across + (x // self.tile_width)
        tile = self._tile(index)
        value = tile[(y % self.tile_height) * self.tile_width + (x % self.tile_width)]
        return None if value < -1000 or not math.isfinite(value) else value


def wfs_features(type_name: str, bbox: tuple[float, float, float, float]) -> list[dict]:
    south, west, north, east = bbox
    features: list[dict] = []
    start = 0
    while True:
        query = urllib.parse.urlencode(
            {
                "SERVICE": "WFS",
                "VERSION": "2.0.0",
                "REQUEST": "GetFeature",
                "TYPENAMES": type_name,
                "COUNT": WFS_PAGE,
                "STARTINDEX": start,
                "SRSNAME": "urn:ogc:def:crs:OGC:1.3:CRS84",
                "BBOX": f"{west},{south},{east},{north},urn:ogc:def:crs:OGC:1.3:CRS84",
                "OUTPUTFORMAT": "application/json",
            }
        )
        payload = json.loads(fetch(f"{WFS_ENDPOINT}?{query}"))
        page = payload.get("features", [])
        features.extend(page)
        if len(page) < WFS_PAGE:
            break
        start += WFS_PAGE
        time.sleep(0.1)
    return features


def midpoint(geometry: dict) -> tuple[float, float] | None:
    kind = geometry.get("type")
    if kind == "LineString":
        line = geometry["coordinates"]
    elif kind == "MultiLineString" and geometry["coordinates"]:
        line = geometry["coordinates"][0]
    else:
        return None
    if len(line) < 2:
        return None
    return tuple(line[len(line) // 2][:2])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--overpass-cache", default=".cache/phase1b-live/oisans-overpass.json")
    parser.add_argument("--elevations", default=".cache/phase2/elevations.json")
    parser.add_argument("--output", default="outputs/phase2")
    parser.add_argument("--sample-points", type=int, default=1500)
    arguments = parser.parse_args()

    output = Path(arguments.output)
    output.mkdir(parents=True, exist_ok=True)
    osm = json.loads(Path(arguments.overpass_cache).read_bytes())
    store = load_store(arguments.elevations)
    report: dict[str, object] = {
        "retrieved_at_utc": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "bbox_wgs84_south_west_north_east": list(BBOX),
    }

    # --- Copernicus GLO-30 ---------------------------------------------------
    graph = build_graph(osm, "reference_vtc")
    rows: list[dict[str, object]] = []
    try:
        started = time.monotonic()
        tile = GeoTiff(COPERNICUS_TILE_URL)
        edges = sorted(
            (edge for edge in graph.edges.values() if edge.direction == "forward"),
            key=lambda edge: -edge.horizontal_length_m,
        )
        differences: list[float] = []
        taken = 0
        for edge in edges:
            if taken >= arguments.sample_points:
                break
            rge = elevations_for(store, edge.samples)
            if rge is None:
                continue
            step = max(1, len(edge.samples) // 6)
            for sample, reference in list(zip(edge.samples, rge))[::step]:
                if taken >= arguments.sample_points:
                    break
                control = tile.sample(sample.longitude, sample.latitude)
                if control is None:
                    continue
                taken += 1
                differences.append(control - reference)
                rows.append(
                    {
                        "osm_way_id": edge.osm_way_id,
                        "longitude": round(sample.longitude, 6),
                        "latitude": round(sample.latitude, 6),
                        "rge_alti_m": round(reference, 2),
                        "copernicus_glo30_m": round(control, 2),
                        "difference_m": round(control - reference, 2),
                    }
                )
        mean = statistics.mean(differences)
        centred = [value - mean for value in differences]
        ordered = sorted(abs(value) for value in centred)
        gross = [row for row in rows if abs(row["difference_m"] - mean) > 25.0]
        sectors = Counter(row["osm_way_id"] for row in gross)
        report["copernicus_glo30"] = {
            "status": "compared",
            "tile_url": COPERNICUS_TILE_URL,
            "licence": COPERNICUS_LICENCE,
            "vertical_datum": "EGM2008 geoid, against NGF-IGN 1969 for RGE ALTI",
            "model_kind": "surface model (includes vegetation and buildings)",
            "points_compared": len(differences),
            "mean_difference_m": round(mean, 2),
            "median_difference_m": round(statistics.median(differences), 2),
            "stdev_after_removing_mean_m": round(statistics.pstdev(centred), 2),
            "p95_abs_residual_m": round(ordered[int(0.95 * (len(ordered) - 1))], 2),
            "max_abs_residual_m": round(ordered[-1], 2),
            "gross_inconsistencies_over_25m": len(gross),
            "worst_sectors_osm_way_ids": [way for way, _ in sectors.most_common(10)],
            "elapsed_s": round(time.monotonic() - started, 1),
            "interpretation": (
                "The mean difference is dominated by the geoid separation between EGM2008 "
                "and NGF-IGN 1969 and by the surface-versus-terrain distinction, so it is a "
                "datum offset rather than an error in either source. Only the residual "
                "scatter after removing that mean carries information, and at 30 m posting "
                "it cannot validate the grade of an individual 25 m segment."
            ),
        }
        with (output / "copernicus_control.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError, OSError) as error:
        report["copernicus_glo30"] = {
            "status": "blocked",
            "tile_url": COPERNICUS_TILE_URL,
            "error": f"{type(error).__name__}: {error}",
            "consequence": "no independent elevation control was applied in this run",
        }
        print(f"Copernicus control blocked: {error}")

    # --- BD TOPO -------------------------------------------------------------
    try:
        started = time.monotonic()
        features = wfs_features(BDTOPO_ROADS, BBOX)
        osm_edges = parse_osm_directed_edges(osm)
        forward = [edge for edge in osm_edges if edge.direction == "forward"]

        def bd_structure(properties: dict) -> str:
            position = properties.get("position_par_rapport_au_sol")
            try:
                level = int(position) if position not in (None, "") else 0
            except (TypeError, ValueError):
                level = 0
            if level > 0:
                return "bridge"
            if level < 0:
                return "tunnel"
            return "normal"

        bd_structures: list[tuple[float, float, str, dict]] = []
        bd_classes: Counter[str] = Counter()
        bd_length = 0.0
        for feature in features:
            properties = feature.get("properties", {})
            bd_classes[str(properties.get("nature"))] += 1
            geometry = feature.get("geometry") or {}
            point = midpoint(geometry)
            kind = bd_structure(properties)
            if point and kind != "normal":
                bd_structures.append((point[0], point[1], kind, properties))
            if geometry.get("type") == "LineString":
                coordinates = geometry["coordinates"]
                for start, end in itertools.pairwise(coordinates):
                    a = lonlat_to_lambert93(start[0], start[1])
                    b = lonlat_to_lambert93(end[0], end[1])
                    bd_length += math.hypot(b[0] - a[0], b[1] - a[1])

        index: dict[tuple[int, int], list[int]] = defaultdict(list)
        projected = []
        for position, (longitude, latitude, kind, _) in enumerate(bd_structures):
            x, y = lonlat_to_lambert93(longitude, latitude)
            projected.append((x, y, kind))
            index[(int(x // 100), int(y // 100))].append(position)

        def nearest(x: float, y: float, kind: str) -> float | None:
            best: float | None = None
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for position in index.get((int(x // 100) + dx, int(y // 100) + dy), ()):
                        other_x, other_y, other_kind = projected[position]
                        if other_kind != kind:
                            continue
                        distance = math.hypot(other_x - x, other_y - y)
                        if best is None or distance < best:
                            best = distance
            return best

        structure_rows = []
        agreements = Counter()
        for edge in forward:
            if edge.structure_status is StructureStatus.NORMAL:
                continue
            kind = "bridge" if edge.structure_status is StructureStatus.BRIDGE else "tunnel"
            middle = edge.lonlat[len(edge.lonlat) // 2]
            x, y = lonlat_to_lambert93(*middle)
            distance = nearest(x, y, kind)
            matched = distance is not None and distance <= STRUCTURE_MATCH_RADIUS_M
            agreements[f"{kind}_{'agree' if matched else 'osm_only'}"] += 1
            structure_rows.append(
                {
                    "osm_way_id": edge.osm_way_id,
                    "osm_structure": edge.structure_status.value,
                    "bd_topo_kind_searched": kind,
                    "nearest_bd_topo_match_m": round(distance, 1) if distance is not None else "",
                    "agreement": "agree" if matched else "osm_only",
                    "osm_url": f"https://www.openstreetmap.org/way/{edge.osm_way_id}",
                }
            )
        osm_structure_points = []
        for edge in forward:
            if edge.structure_status is StructureStatus.NORMAL:
                continue
            middle = edge.lonlat[len(edge.lonlat) // 2]
            osm_structure_points.append(
                (
                    *lonlat_to_lambert93(*middle),
                    "bridge" if edge.structure_status is StructureStatus.BRIDGE else "tunnel",
                )
            )
        bd_only = 0
        for (x, y, kind), (_, _, _, properties) in zip(projected, bd_structures):
            closest = None
            for other_x, other_y, other_kind in osm_structure_points:
                if other_kind != kind:
                    continue
                distance = math.hypot(other_x - x, other_y - y)
                if closest is None or distance < closest:
                    closest = distance
            if closest is None or closest > STRUCTURE_MATCH_RADIUS_M:
                bd_only += 1
                structure_rows.append(
                    {
                        "osm_way_id": "",
                        "osm_structure": "",
                        "bd_topo_kind_searched": kind,
                        "nearest_bd_topo_match_m": round(closest, 1) if closest is not None else "",
                        "agreement": "bd_topo_only",
                        "osm_url": "",
                    }
                )
        with (output / "bdtopo_cross_check.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(structure_rows[0]), lineterminator="\n")
            writer.writeheader()
            writer.writerows(structure_rows)

        osm_length = 0.0
        for edge in forward:
            points = [lonlat_to_lambert93(*item) for item in edge.lonlat]
            osm_length += math.fsum(
                math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in itertools.pairwise(points)
            )
        report["bd_topo"] = {
            "status": "compared",
            "endpoint": WFS_ENDPOINT,
            "layer": BDTOPO_ROADS,
            "licence": BDTOPO_LICENCE,
            "attribution": BDTOPO_ATTRIBUTION,
            "features_returned": len(features),
            "bd_topo_length_km": round(bd_length / 1000, 1),
            "osm_highway_length_km": round(osm_length / 1000, 1),
            "bd_topo_natures": dict(bd_classes.most_common(12)),
            "structures": {
                **dict(agreements),
                "bd_topo_only": bd_only,
                "match_radius_m": STRUCTURE_MATCH_RADIUS_M,
            },
            "elapsed_s": round(time.monotonic() - started, 1),
            "interpretation": (
                "BD TOPO is used to test the structures OSM declares, not to replace OSM as "
                "the cycling graph: its legal cycling semantics are thinner. Length totals "
                "differ because BD TOPO carries the road register while the OSM extract also "
                "carries paths, tracks and footways."
            ),
        }
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError, OSError, KeyError) as error:
        report["bd_topo"] = {
            "status": "blocked",
            "endpoint": WFS_ENDPOINT,
            "error": f"{type(error).__name__}: {error}",
            "consequence": "structures rest on OSM tagging alone in this run",
        }
        print(f"BD TOPO cross-check blocked: {error}")

    report["conclusion"] = (
        "Structures without a roadway elevation remain non-simulable regardless of what "
        "either control reports; neither source supplies a deck height."
    )
    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    write_text_lf(output / "independent_controls.json", payload)
    print(
        f"sha256 {sha256_bytes(payload.encode())[:16]}  wrote {output / 'independent_controls.json'}"
    )
    print(json.dumps(report, indent=2, sort_keys=True)[:2600])


if __name__ == "__main__":
    main()
