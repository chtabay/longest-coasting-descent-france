"""Rebuild deterministic Phase 1 outputs from the compact frozen fixture."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

from coastdown import (
    AccessStatus,
    DirectedRoadEdge,
    ElevationSample,
    SourceProvenance,
    StructureStatus,
    build_profile_segments,
    edge_to_road_profile,
    simulate_profile,
)
from coastdown.textio import write_text_lf

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/phase1_oisans_edges.json"
OUTPUT = ROOT / "outputs/phase1"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_edges() -> list[DirectedRoadEdge]:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    checksum = digest(FIXTURE)
    geometry = SourceProvenance(
        "OpenStreetMap contributors",
        "compact Oisans fixture",
        "frozen fixture v1",
        "2026-08-06",
        "https://www.openstreetmap.org/",
        payload["crs"],
        "metre",
        checksum,
    )
    edges = []
    for raw in payload["edges"]:
        elevation_dataset = (
            "terrain fixture" if raw["structure"] == "normal" else "unknown roadway elevation"
        )
        elevation = SourceProvenance(
            "offline fixture",
            elevation_dataset,
            "v1",
            "2026-08-06",
            FIXTURE.relative_to(ROOT).as_posix(),
            payload["crs"],
            "metre",
            checksum,
        )
        samples = []
        chainage = 0.0
        previous = None
        for x, y, z in raw["samples"]:
            if previous:
                chainage += ((x - previous[0]) ** 2 + (y - previous[1]) ** 2) ** 0.5
            samples.append(ElevationSample(x, y, z, chainage, elevation))
            previous = (x, y)
        edges.append(
            DirectedRoadEdge(
                raw["id"],
                tuple(samples),
                geometry,
                elevation,
                payload["crs"],
                AccessStatus(raw["access"]),
                StructureStatus(raw["structure"]),
                (("name", raw["name"]),),
                (() if raw["structure"] == "normal" else ("roadway_elevation_unknown",)),
            )
        )
    return edges


def svg_map(edges: list[DirectedRoadEdge], path: Path) -> None:
    points = [sample for edge in edges for sample in edge.samples]
    min_x, max_x = min(p.x_m for p in points), max(p.x_m for p in points)
    min_y, max_y = min(p.y_m for p in points), max(p.y_m for p in points)
    lines = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="600">',
        '<rect width="100%" height="100%" fill="white"/>',
    ]
    for edge in edges:
        coords = " ".join(
            f"{40 + 720 * (p.x_m - min_x) / (max_x - min_x):.1f},{560 - 520 * (p.y_m - min_y) / (max_y - min_y):.1f}"
            for p in edge.samples
        )
        color = "#1b7837" if edge.structure_status is StructureStatus.NORMAL else "#d73027"
        lines.append(f'<polyline points="{coords}" fill="none" stroke="{color}" stroke-width="4"/>')
    lines.append(
        '<text x="20" y="25" font-family="sans-serif">Compact Oisans Phase 1 fixture — not a ranking</text>'
    )
    lines.append("</svg>")
    write_text_lf(path, "\n".join(lines))


def svg_profile(edge: DirectedRoadEdge, path: Path, *, grade: bool = False) -> None:
    segments = build_profile_segments(edge)
    if grade:
        xs = [0.0] + [sample.chainage_m for sample in edge.samples[1:]]
        ys = [segments[0].grade_ratio * 100] + [segment.grade_ratio * 100 for segment in segments]
        label = "Grade (%)"
    else:
        xs = [sample.chainage_m for sample in edge.samples]
        ys = [float(sample.elevation_m) for sample in edge.samples]
        label = "Elevation (m)"
    x_span = max(xs) - min(xs) or 1
    y_span = max(ys) - min(ys) or 1
    points = " ".join(
        f"{50 + 700 * (x - min(xs)) / x_span:.1f},{350 - 300 * (y - min(ys)) / y_span:.1f}"
        for x, y in zip(xs, ys)
    )
    write_text_lf(
        path,
        "\n".join(
            [
                '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="400">',
                '<rect width="100%" height="100%" fill="white"/>',
                f'<text x="20" y="25" font-family="sans-serif">{edge.edge_id} — {label}</text>',
                '<line x1="50" y1="350" x2="750" y2="350" stroke="black"/>',
                f'<polyline points="{points}" fill="none" stroke="#2166ac" stroke-width="3"/>',
                "</svg>",
            ]
        ),
    )


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    edges = load_edges()
    manifest = json.loads((ROOT / "data/phase1_manifest.json").read_text(encoding="utf-8"))
    manifest["fixture"] = {
        "path": FIXTURE.relative_to(ROOT).as_posix(),
        "bytes": FIXTURE.stat().st_size,
        "sha256": digest(FIXTURE),
    }
    write_text_lf(OUTPUT / "download_manifest.json", json.dumps(manifest, indent=2) + "\n")
    svg_map(edges, OUTPUT / "study_area_map.svg")
    svg_map(edges, OUTPUT / "compact_graph_map.svg")
    for edge in edges:
        if edge.structure_status is StructureStatus.NORMAL:
            svg_profile(edge, OUTPUT / f"{edge.edge_id}_elevation.svg")
            svg_profile(edge, OUTPUT / f"{edge.edge_id}_grade.svg", grade=True)

    with (OUTPUT / "edge_quality.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["edge_id", "access", "structure", "simulable", "quality_flags"])
        for edge in edges:
            writer.writerow(
                [
                    edge.edge_id,
                    edge.access_status.value,
                    edge.structure_status.value,
                    edge.structure_status is StructureStatus.NORMAL,
                    ";".join(edge.quality_flags),
                ]
            )

    with (OUTPUT / "uncertain_edges.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["edge_id", "structure", "reason"])
        for edge in edges:
            if edge.structure_status is not StructureStatus.NORMAL:
                writer.writerow(
                    [
                        edge.edge_id,
                        edge.structure_status.value,
                        "roadway elevation unavailable; terrain DEM forbidden",
                    ]
                )

    with (OUTPUT / "profile_simulations.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(
            [
                "edge_id",
                "elapsed_time_s",
                "moving_time_s",
                "first_below_threshold_time_s",
                "first_zero_speed_time_s",
                "qualified_stop_time_s",
                "stationary_time_s",
                "stop_reason",
            ]
        )
        for edge in edges:
            if edge.structure_status is not StructureStatus.NORMAL:
                continue
            result = simulate_profile(edge_to_road_profile(edge))
            writer.writerow(
                [
                    edge.edge_id,
                    result.elapsed_time_s,
                    result.moving_time_s,
                    result.first_below_threshold_time_s,
                    result.first_zero_speed_time_s,
                    result.qualified_stop_time_s,
                    result.stationary_time_s,
                    result.stop_reason,
                ]
            )

    with (OUTPUT / "profile_segments.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(
            [
                "edge_id",
                "segment",
                "horizontal_length_m",
                "dz_m",
                "grade_ratio",
                "angle_rad",
                "travelled_length_m",
            ]
        )
        for edge in edges:
            if edge.structure_status is StructureStatus.NORMAL:
                for index, segment in enumerate(build_profile_segments(edge)):
                    writer.writerow(
                        [
                            edge.edge_id,
                            index,
                            segment.horizontal_length_m,
                            segment.elevation_change_m,
                            segment.grade_ratio,
                            segment.grade_angle_rad,
                            segment.travelled_length_m,
                        ]
                    )

    # Offline fixture cannot honestly compare raster sources/spacings; preserve explicit NA rows.
    write_text_lf(
        OUTPUT / "elevation_source_comparison.csv",
        "edge_id,source,status\nfixture,RGE_ALTI_5m,network_refresh_required\nfixture,Copernicus_GLO30,network_refresh_required\n",
    )
    write_text_lf(
        OUTPUT / "sampling_spacing_comparison.csv",
        "spacing_m,status,reason\n2,not_run,raster_not_downloaded\n5,not_run,raster_not_downloaded\n10,not_run,raster_not_downloaded\n25,not_run,raster_not_downloaded\n",
    )
    write_text_lf(
        OUTPUT / "phase1_report.md",
        "# Phase 1 compact Oisans reconstruction\n\n"
        "This offline reconstruction validates typed provenance, oriented 3D profiles, structure "
        "rejection and separated simulation times. Two normal fixture edges are simulable; one "
        "bridge, one tunnel and one stacked-road case are rejected for review because roadway "
        "elevations are unknown. The fixture elevations are test values, not a substitute for the "
        "pending RGE ALTI download.\n\nLive OSM and RGE ALTI acquisition was attempted on "
        "2026-08-06 and blocked by the execution proxy (`CONNECT 403`). Consequently no real "
        "source/spacing comparison is claimed: the CSVs mark those rows "
        "`network_refresh_required` or `not_run`. See `download_manifest.json` for bounds, "
        "candidate URLs, fixture byte size and SHA-256.\n\nNo regional or national ranking is "
        "presented.\n",
    )


if __name__ == "__main__":
    main()
