# Phase 1B live Oisans reconstruction

The offline fixtures under `tests/fixtures/` and the generated validation outputs under
`outputs/phase1/` are never observations. Real reconstruction writes only to
`outputs/phase1/live/`, and does so atomically once every request, parse and profile has
succeeded. A failure removes the temporary directory instead of publishing a partial result or
relabelling fixture output.

## Single command

```bash
PYTHONPATH=src python scripts/phase1b_live_oisans.py
```

The command:

1. records the Géoplateforme service root, resource index and both resource descriptions, plus
   the Overpass status endpoint, keeping each response's byte size and SHA-256;
2. submits the versioned Overpass query embedded in the script and preserves the OSM database
   timestamp, response size and SHA-256;
3. builds conservative directed edges carrying OSM way and node identifiers and complete tags;
4. extracts `type=restriction` relations with their from/via/to members;
5. selects a stratified validation sample of ways;
6. densifies each one at 2, 5, 10 and 25 m in EPSG:2154 and reports the *realised* spacing;
7. queries `ign_rge_alti_par_territoires`, caching every response with its checksum;
8. builds a raw and a conditioned profile, computes the geometry and grade statistics of both,
   and simulates whichever satisfies the simulator's validity bound;
9. samples `ign_rge_alti_wld` on the same points as an independent control;
10. lists bridges, tunnels, covered ways and non-zero-layer ways for review without applying
    terrain heights;
11. publishes the manifest, CSVs, map and report atomically.

Raw responses stay in `.cache/phase1b-live/` and are not committed.

## What the services actually do

Verified 2026-08-07 by probing, not by reading documentation or trusting the previous code.

| Endpoint | Behaviour |
|---|---|
| `https://data.geopf.fr/telechargement` | **HTTP 405** to GET. Not a discovery endpoint. Removed. |
| `https://data.geopf.fr/altimetrie/` | 200, returns the service version string, now recorded as the elevation source version. |
| `https://data.geopf.fr/altimetrie/resources` | 200, JSON index of 9 altimetry resources. |
| `https://data.geopf.fr/altimetrie/resources/{id}` | 200, JSON resource description. |
| `.../calcul/alti/rest/elevation.json` | 200. `zonly=true` returns a list of floats; without it, a list of objects. **200 points per GET is the ceiling; 400 returns HTTP 414.** POST form returns 500 and POST JSON rejects the parameter encoding. |
| `https://wxs.ign.fr/...` | DNS failure. The historical host no longer resolves. |
| `https://overpass-api.de/api/interpreter` | 200, about 7.6 MB for the study bbox in roughly 5 s. Returns **504** when the instance behind the load balancer is saturated, which the pipeline retries with backoff. |

Two service behaviours are load-bearing:

- **No-data sentinel.** Outside coverage the altimetry service answers HTTP 200 with
  `z = -99999.0`. It is a sentinel, never an elevation. It is mapped to a missing value, which
  the geometry contract rejects, so a run fails loudly instead of inserting a 100 km cliff.
- **Resolution does not follow the identifier.** `ign_rge_alti_wld` is the pyramid product and
  answers on an approximately 3.5 m effective grid; `ign_rge_alti_par_territoires` answers on
  the announced 1 m grid. See D-009.

## Raw and conditioned profiles

Every profile is published twice.

- `raw` is the unmodified sampled terrain profile.
- `conditioned` applies the declared 25 m centred moving average of elevation against chainage,
  identically at every spacing so the sampling comparison stays fair.

Neither replaces the other. A result whose grades exceed the simulator's `|grade| <= 0.5`
validity bound is published with its violation count and left unsimulated (D-010), because
clipping would put a coasting time on a road the model cannot describe.

Conditioning is not a guarantee. On a hairpin it can raise the maximum grade while lowering the
violation count, since averaging along chainage pulls together two points that sit on different
levels of the same bend (D-011). That behaviour is pinned by
`tests/test_phase1b_live_extract.py`.

## Sampling comparison

The requested spacing is an upper bound. Densification subdivides source chords but never removes
a source vertex, so where OSM geometry is finer than the request the realised spacing is the
source spacing. Realised mean, minimum and maximum spacing are published beside the requested
value (D-012); a comparison that quoted only the request would misdescribe the experiment.

## Outputs

Successful live execution creates, under `outputs/phase1/live/`:

| File | Content |
|---|---|
| `data_manifest.json` | per-source provenance, parameters, timings, counts, limitations, and every cached altimetry response with size and SHA-256 |
| `osm_extraction_summary.json` | exact Overpass query, database timestamp, response digest, way and relation identifiers, node identifiers of the selected ways, auditable counts |
| `graph_quality.csv` | one row per directed edge with the tags that drove its access and structure decision |
| `sampling_comparison.csv` | geometry and grade statistics per way, spacing and variant |
| `profile_simulations.csv` | separated coasting-time metrics, with an explicit reason when a result was not simulated |
| `elevation_source_comparison.csv` | primary against control resource on identical points |
| `structure_review.csv` | edges that must not receive terrain elevation |
| `manual_edge_audit.csv` | the hand-inspected sample |
| `turn_restrictions.csv` | restriction relations with from/via/to members |
| `http_transaction_log.csv` | every request attempt with status, size, digest and duration |
| `profiles/` | per-point measured and conditioned elevations |
| `real_graph_map.svg` | the extracted graph coloured by access and structure |
| `phase1b_report.md` | narrative summary |

Every manifest and report identifies `source = live`, the retrieval time, the source timestamps
and identifiers, and the checksums.

The manual workflow `.github/workflows/phase1b-live.yml` runs the unit and static checks, performs
the reconstruction, requires non-empty OSM and altimetry checksums, and uploads the outputs as an
artifact. It never runs on ordinary pushes.

## Tests never touch the network

`tests/conftest.py` refuses every outbound socket for the whole session, and a test proves the
guard is active. The suite runs against verbatim frozen extracts under `tests/fixtures/`, each
carrying its producer, licence, attribution and the digest of the response it was cut from.

## Copernicus command

Copernicus GLO-30 remains optional and may require catalogue authorization. No credential is
embedded. Once authorized, retrieve only the tile intersecting bbox `(6.02, 45.02, 6.18, 45.16)`,
record release, tile and SHA-256, and treat it as a coarse DSM control — not as a road elevation
source, and not as an independent check of absolute accuracy for a bare-earth model.

No route ranking is performed or implied.
