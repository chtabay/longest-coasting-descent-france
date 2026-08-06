# Phase 1B live Oisans reconstruction

The offline fixture remains under `tests/fixtures/` and its generated validation outputs remain
under `outputs/phase1/`. They are never observations. Real reconstruction writes only to
`outputs/phase1/live/`, and does so atomically after OSM and RGE ALTI requests succeed.

## Single command

```bash
PYTHONPATH=src python scripts/phase1b_live_oisans.py
```

The command:

1. records responses from the three official Géoplateforme discovery endpoints;
2. submits the exact versioned Overpass query embedded in the script;
3. preserves the OSM timestamp, byte size and SHA-256;
4. constructs conservative directed edges with OSM IDs and complete tags;
5. selects a few compact, normal, admissible ways only;
6. densifies them at 2, 5, 10 and 25 metres in EPSG:2154;
7. queries `ign_rge_alti_wld`, caching each response and checksum;
8. builds normative 3D profiles and separated-time simulations;
9. lists bridges, tunnels and non-zero-layer edges for review without applying terrain heights;
10. atomically publishes the live manifest, CSVs, map and report.

Raw responses remain in `.cache/phase1b-live/` and are not committed. A failed request removes
the temporary output rather than manufacturing or relabelling fixture results.

## Outputs and validation

Successful live execution creates `data_manifest.json`, `osm_extraction_summary.json`,
`graph_quality.csv`, `sampling_comparison.csv`, `structure_review.csv`,
`profile_simulations.csv`, `profiles/*.csv`, `real_graph_map.svg` and `phase1b_report.md`. Every manifest/report
identifies `source = live`, retrieval time, source timestamp/identifiers and checksums.

The manual GitHub workflow `.github/workflows/phase1b-live.yml` runs unit/static checks, performs
this compact reconstruction, requires non-empty OSM and altimetry checksums, and uploads outputs
as an artifact. It never runs on ordinary pushes.

## Copernicus command

Copernicus GLO-30 is optional and credentials/catalogue authorization may be required. No
credential is embedded. Once authorized, use the Copernicus Data Space catalogue to retrieve
only the tile intersecting bbox `(6.02, 45.02, 6.18, 45.16)`, record release/tile/SHA-256, and
compare it as a coarse DSM control—not as the primary road elevation source.

No route ranking is performed or implied.
