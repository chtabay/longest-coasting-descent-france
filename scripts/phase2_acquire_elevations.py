"""Acquire the terrain elevations the regional Oisans search needs.

Separate from the search itself because it is the only part that touches the
network, it takes minutes rather than seconds, and it must be resumable: a run
interrupted after four hundred requests should not repeat them.

Every distinct sample point is fetched once.  Junction nodes are shared between
ways and the base grid of neighbouring ways often coincides, so deduplicating on
rounded coordinates removes a material fraction of the work and makes the result
independent of the order in which ways are processed.
"""

from __future__ import annotations

import argparse
import json
import math
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from coastdown.graph import (
    admitted_forward_edges,
    junction_node_ids,
    piece_sample_points,
    way_pieces,
)
from coastdown.live_oisans import sha256_bytes

USER_AGENT = (
    "coastdown-france-phase2/1.0 (+https://github.com/chtabay/longest-coasting-descent-france)"
)
BBOX = (45.02, 6.02, 45.16, 6.18)
OVERPASS_ENDPOINT = "https://overpass-api.de/api/interpreter"
ALTIMETRY_ENDPOINT = "https://data.geopf.fr/altimetrie/1.0/calcul/alti/rest/elevation.json"
RESOURCE = "ign_rge_alti_par_territoires"
MAX_POINTS_PER_REQUEST = 200
REQUEST_PAUSE_S = 0.12
TRANSIENT_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
MAX_ATTEMPTS = 4
RETRY_BASE_DELAY_S = 5.0

BASE_SPACING_M = 5.0
KEEP_VERTEX_ABOVE_DEG = 15.0
COORDINATE_DECIMALS = 7
NO_DATA_THRESHOLD = -9_000.0


def overpass_query() -> str:
    south, west, north, east = BBOX
    return (
        "[out:json][timeout:300];\n"
        f'way["highway"]({south},{west},{north},{east})->.roads;\n'
        'relation(bw.roads)["type"="restriction"]->.restrictions;\n'
        "(.roads;.restrictions;);\n"
        "out meta geom;\n"
    )


def fetch(url: str, *, data: bytes | None = None, timeout: int = 300) -> bytes:
    last: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        request = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            if error.code not in TRANSIENT_STATUS_CODES:
                raise
            last = error
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            last = error
        if attempt < MAX_ATTEMPTS:
            time.sleep(RETRY_BASE_DELAY_S * 2 ** (attempt - 1))
    raise RuntimeError(f"request failed after {MAX_ATTEMPTS} attempts: {url[:120]}") from last


def load_overpass(cache: Path) -> tuple[dict, str, int]:
    """Reuse the frozen extract when present so the graph does not drift."""
    path = cache / "oisans-overpass.json"
    if not path.exists():
        payload = fetch(
            OVERPASS_ENDPOINT, data=urllib.parse.urlencode({"data": overpass_query()}).encode()
        )
        path.write_bytes(payload)
    raw = path.read_bytes()
    return json.loads(raw), sha256_bytes(raw), len(raw)


def key_of(longitude: float, latitude: float) -> str:
    return f"{longitude:.{COORDINATE_DECIMALS}f},{latitude:.{COORDINATE_DECIMALS}f}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--overpass-cache", default=".cache/phase1b-live")
    parser.add_argument("--cache", default=".cache/phase2")
    parser.add_argument("--scenario", default="extended_vtc")
    parser.add_argument("--limit-requests", type=int, default=0, help="0 means no limit")
    arguments = parser.parse_args()

    overpass_cache = Path(arguments.overpass_cache)
    overpass_cache.mkdir(parents=True, exist_ok=True)
    cache = Path(arguments.cache)
    cache.mkdir(parents=True, exist_ok=True)
    store_path = cache / "elevations.json"
    store: dict[str, float] = (
        json.loads(store_path.read_text(encoding="utf-8")) if store_path.exists() else {}
    )
    print(f"elevation store: {len(store)} points already known")

    osm, digest, size = load_overpass(overpass_cache)
    print(f"overpass extract: {size} bytes sha256={digest}")
    forward = admitted_forward_edges(osm, arguments.scenario)
    junctions = junction_node_ids(forward)

    # Sample exactly the graph pieces, not the raw ways: the graph is cut at
    # junctions and each piece restarts its own chainage grid, so sampling whole
    # ways would fetch points the search never asks about and miss the ones it
    # does.
    wanted: dict[str, tuple[float, float]] = {}
    pieces = 0
    for edge in forward:
        for _, geometry, _, _ in way_pieces(edge, junctions):
            try:
                samples = piece_sample_points(geometry)
            except ValueError:
                continue
            pieces += 1
            for sample in samples:
                wanted[key_of(sample.longitude, sample.latitude)] = (
                    sample.longitude,
                    sample.latitude,
                )
    print(
        f"{len(forward)} ways admitted by {arguments.scenario} -> {pieces} graph pieces; "
        f"{len(wanted)} distinct points"
    )

    missing = [value for key, value in wanted.items() if key not in store]
    print(f"{len(missing)} points still to fetch")
    if not missing:
        print("nothing to do")
        return

    started = time.monotonic()
    requests_made = 0
    for offset in range(0, len(missing), MAX_POINTS_PER_REQUEST):
        if arguments.limit_requests and requests_made >= arguments.limit_requests:
            print("request limit reached; rerun to continue")
            break
        chunk = missing[offset : offset + MAX_POINTS_PER_REQUEST]
        url = f"{ALTIMETRY_ENDPOINT}?" + urllib.parse.urlencode(
            {
                "lon": "|".join(f"{point[0]:.7f}" for point in chunk),
                "lat": "|".join(f"{point[1]:.7f}" for point in chunk),
                "resource": RESOURCE,
                "delimiter": "|",
                "measures": "false",
                "zonly": "true",
            }
        )
        payload = json.loads(fetch(url))
        values = payload.get("elevations")
        if not isinstance(values, list) or len(values) != len(chunk):
            raise RuntimeError("altimetry response does not match the request")
        for point, value in zip(chunk, values):
            number = float(value)
            # Outside coverage the service answers 200 with -99999.0. It is
            # recorded as missing so the profile builder refuses the edge rather
            # than inheriting a 100 km cliff.
            store[key_of(*point)] = number if number > NO_DATA_THRESHOLD else float("nan")
        requests_made += 1
        if requests_made % 25 == 0:
            store_path.write_text(json.dumps(store), encoding="utf-8")
            done = offset + len(chunk)
            rate = done / max(1e-9, time.monotonic() - started)
            print(
                f"  {done}/{len(missing)} points, {requests_made} requests, "
                f"{rate:.0f} points/s, {(len(missing) - done) / max(rate, 1e-9):.0f}s left"
            )
        time.sleep(REQUEST_PAUSE_S)

    store_path.write_text(json.dumps(store), encoding="utf-8")
    no_data = sum(1 for value in store.values() if math.isnan(value))
    manifest = {
        "retrieved_at_utc": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "overpass_sha256": digest,
        "overpass_bytes": size,
        "resource": RESOURCE,
        "endpoint": ALTIMETRY_ENDPOINT,
        "base_spacing_m": BASE_SPACING_M,
        "keep_vertex_above_deg": KEEP_VERTEX_ABOVE_DEG,
        "scenario": arguments.scenario,
        "ways_admitted": len(forward),
        "graph_pieces_sampled": pieces,
        "points_known": len(store),
        "points_without_coverage": no_data,
        "requests_made_this_run": requests_made,
        "licence": "Licence Ouverte / Open Licence (Etalab) 2.0",
        "attribution": "© IGN — RGE ALTI® via Géoplateforme",
    }
    (cache / "elevation_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        f"stored {len(store)} points ({no_data} without coverage) in {store_path}; "
        f"{requests_made} requests in {time.monotonic() - started:.0f}s"
    )


if __name__ == "__main__":
    main()
