# Phase 1B live Oisans reconstruction

source = live  
retrieved (UTC) = 2026-08-07T07:21:53+00:00  
OSM database timestamp = 2026-08-07T07:20:17Z  
OSM response = 7631277 bytes, SHA-256 6315ac69f15245324487448a396e8f780e16c09740afda1bb8b9a9de85bdcbcc  
IGN altimetry service = API Géoplateforme - Calcul altimétrique version 0.32.1  
primary elevation resource = ign_rge_alti_par_territoires  
control elevation resource = ign_rge_alti_wld

## Graph

- raw OSM highway ways: 4514
- directed edges created: 8770
- admissible: 3999, prohibited: 318, to review: 4453
- structures detected: 350 bridge, 149 tunnel/covered, 32 stacked
- turn-restriction relations: 4
- ways selected for profiling: 8

## Profiles

64 profile results were built (8 ways x 4 spacings x 2 variants) and 58 were simulated.

`raw` is the unmodified sampled terrain profile. `conditioned` applies the declared 25 m centred moving average on elevation against chainage, which is the named scenario of the geometry contract, applied identically at every spacing so the comparison stays fair.

3 raw and 3 conditioned results exceeded the simulator's |grade| <= 0.5 validity bound and were reported unsimulated rather than clipped.

## Reading the outputs

- `sampling_comparison.csv` — geometry and grade statistics per way, spacing and variant.
- `profile_simulations.csv` — separated coasting-time metrics for the same keys, with an explicit reason when a result was not simulated.
- `elevation_source_comparison.csv` — primary against control resource on identical points.
- `graph_quality.csv` — every directed edge with the tags that drove its access and structure decision.
- `structure_review.csv` — edges that must not receive terrain elevation.
- `manual_edge_audit.csv` — the hand-inspected sample.
- `http_transaction_log.csv` — every request, status, size and duration.

## Caveats

- RGE ALTI is a bare-earth terrain model; bridge, tunnel, covered and layer!=0 edges receive no elevation and stay in structure_review.csv.
- The altimetry API does not return a vertical datum; NGF-IGN 1969 is asserted from the RGE ALTI product specification.
- The control resource shares the producer and the acquisition campaign, so agreement between the two bounds sampling and pyramid effects only, not absolute vertical accuracy.
- BD TOPO cross-checking of structures is not performed in this phase.
- The selected ways are a deterministic validation sample; no regional or national ranking is produced or implied.

© OpenStreetMap contributors, ODbL 1.0. © IGN — RGE ALTI® via Géoplateforme, Licence Ouverte / Open Licence (Etalab) 2.0.
