# Phase 1 source matrix and prototype decision

Consultation date recorded for this revision: **2026-08-07**. Live retrieval now succeeds; the
HTTP 403 recorded on 2026-08-06 was an execution-proxy limitation, not a property of the
services. Every endpoint below has been exercised and the observed behaviour is recorded in
`docs/10_phase1b_live_reconstruction.md` and in `outputs/phase1/live/http_transaction_log.csv`.

Three entries in the previous revision did not survive contact with the services:

- `https://data.geopf.fr/telechargement` answers **HTTP 405** to GET and is not a discovery
  endpoint;
- `https://wxs.ign.fr/` no longer resolves;
- `ign_rge_alti_wld` is the *pyramid* resource and answers on an approximately 3.5 m effective
  grid, not the 1 m grid its name suggests. `ign_rge_alti_par_territoires` is the 1 m product
  and is now primary (D-009).

The lesson is recorded rather than quietly fixed: a resource identifier, a documented URL and a
product name are all claims, and each must be measured before it is relied upon.

| Source | Producer | Licence / redistribution | Coverage, resolution, accuracy | CRS / vertical datum / formats | Access, update, size | Useful road/structure/cycling semantics | Missing values and known defects | Freeze / integrity |
|---|---|---|---|---|---|---|---|---|
| OpenStreetMap | OSM contributors / OSMF | ODbL 1.0; attribution and share-alike obligations for derived databases | Global, contributor-dependent geometry and completeness; no guaranteed metric accuracy | WGS84 storage; PBF, XML/Overpass JSON | Planet/diffs and bounded extracts; continuously edited; compact bbox intended here | `highway`, `oneway`, `access`, `bicycle`, `surface`, `smoothness`, `bridge`, `tunnel`, `layer`, restrictions | Tag absence is unknown, not permission; variable topology; stacked roads need tags | Freeze PBF/JSON, query and timestamp; SHA-256 |
| BD TOPO Transport | IGN | Licence Ouverte/Etalab 2.0 subject to product metadata/attribution | Metropolitan/overseas authoritative topographic coverage; metric product | Lambert-93 for mainland; IGN vertical metadata; GeoPackage/Shapefile depending delivery | IGN Géoservices downloads/API; periodic editions; departmental/national packages can be large | Road nature, direction/importance, structures and some restrictions; cycling detail must be checked field-by-field | Legal bicycle semantics may be less detailed/current than OSM; edition schema changes | Freeze edition/package and catalogue metadata; producer checksum plus SHA-256 |
| RGE ALTI 1 m | IGN | Licence Ouverte/Etalab 2.0 subject to metadata | Selected high-resolution coverage; 1 m grid; announced accuracy depends acquisition block | Lambert-93 / IGN69 mainland; raster/ASCII delivery | IGN download by packages; very large, so bbox/tile only | Terrain only; no road access or structure deck height | Water/void/acquisition seams; terrain under bridge and above tunnel is not roadway | Freeze tile edition and metadata; checksum/SHA-256 |
| RGE ALTI 5 m | IGN | Licence Ouverte/Etalab 2.0 subject to metadata | Broad French coverage; 5 m grid; accuracy depends source block | Lambert-93 / IGN69 mainland; ASCII/raster package | IGN download; materially smaller than 1 m but still avoid national commit | Prototype primary terrain elevation | Same bridge/tunnel issue; interpolation and seams; vertical datum must remain explicit | Freeze tile/department edition; checksum/SHA-256 |
| Copernicus DEM GLO-30 | European Union / Copernicus | Copernicus data terms; attribution/notice per terms | Global DSM, nominal 30 m posting; product accuracy documented globally, not road-specific | Geographic grid, EGM2008 vertical reference; GeoTIFF/COG | Copernicus Data Space; tiled, versioned; small control subset | Independent elevation control only | Surface model includes vegetation/buildings; coarse hairpins; vertical datum differs from IGN69 | Freeze tile/release; catalogue checksum and SHA-256 |

Primary links recorded:

- OSM copyright/licence: <https://www.openstreetmap.org/copyright>
- OSM tagging documentation: <https://wiki.openstreetmap.org/wiki/Map_features>
- IGN BD TOPO: <https://geoservices.ign.fr/bdtopo>
- IGN RGE ALTI: <https://geoservices.ign.fr/rgealti>
- IGN open-data licence: <https://www.ign.fr/institut/licence-ouverte-etendue-aux-donnees-ign>
- Copernicus DEM documentation/catalogue: <https://dataspace.copernicus.eu/explore-data/data-collections/copernicus-contributing-missions/collections-description/COP-DEM>

## Endpoints exercised on 2026-08-07

| Producer | Endpoint | Result |
|---|---|---|
| OSM | `https://overpass-api.de/api/interpreter` | 200, ~7.6 MB for the study bbox, ODbL declared in the response `copyright` field, database timestamp returned |
| OSM | `https://overpass-api.de/api/status` | 200, slot allowance |
| IGN | `https://data.geopf.fr/altimetrie/` | 200, service version string |
| IGN | `https://data.geopf.fr/altimetrie/resources` | 200, index of 9 altimetry resources |
| IGN | `https://data.geopf.fr/altimetrie/resources/ign_rge_alti_par_territoires` | 200, resource description |
| IGN | `https://data.geopf.fr/altimetrie/resources/ign_rge_alti_wld` | 200, resource description |
| IGN | `https://data.geopf.fr/altimetrie/1.0/calcul/alti/rest/elevation.json` | 200, ≤200 points per GET; 400 points returns HTTP 414 |
| IGN | `https://data.geopf.fr/telechargement` | **405**, removed from the pipeline |
| IGN | `https://wxs.ign.fr/calcul/alti/rest/elevation.json` | **DNS failure**, host retired |

The altimetry service does not return a vertical datum. NGF-IGN 1969 is asserted from the RGE
ALTI product specification for mainland France and is recorded in the manifest as an assertion,
not as a service response.

## Prototype decision

Use a compact OSM bounded extract for directed topology and detailed bicycle/structure tags;
cross-check road class and structures against the matching BD TOPO Transport edition. Use RGE
ALTI 5 m as the primary terrain surface, RGE ALTI 1 m on a few difficult edges when coverage is
available, and a small GLO-30 subset only as an independent coarse control. No terrain DEM is
accepted for a bridge, tunnel or stacked edge without roadway-compatible evidence.

This choice is based on complementary semantics, provenance and resolution—not Python-library
convenience. The CSV counterpart in `outputs/phase1/source_matrix.csv` is machine-readable.
