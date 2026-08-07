# Phase 2 — Regional Oisans coasting prototype

Experimental regional prototype. **No national claim is made, and the regional
ranking below should not be read as a list of the best descents in the Oisans.**
Its main result is negative and is stated first, because it changes what Phase 3
has to do.

Inputs: the frozen Overpass extract (7 632 640 bytes, SHA-256
`23d4a626ce08e02a2c25a0076fd3b2afd410cbb48ee82c979168c5b32dbcb93d`, OSM base
2026-08-07T19:49:47Z) and 85 914 RGE ALTI elevation points acquired from
`ign_rge_alti_par_territoires` in 330 requests, none outside coverage. Both are
cached, so the whole ranking is reproducible offline.

---

## 1. The headline result: the objective as defined does not select descents

Ranked by elapsed coasting time, the best route in `paved_reference` is **734 m
long and drops 1.8 m**. It never exceeds its 15 km/h starting speed, averages
6.3 km/h, and rolls for 420 s. Rank 7 covers 769 m for 5.1 m of drop. Rank 17 of
the raw candidate set crawls 129 m in 198 s at a mean of 2.4 km/h.

These are not bugs. They are the correct answer to the question as posed. On a
near-level road the net force is the small difference between two small terms,
so the bicycle decelerates very slowly and stays above the 0.30 m/s stop
threshold for a long time. Maximising *elapsed time* therefore rewards
near-equilibrium creeping, not descending.

The sensitivity analysis confirms the diagnosis rather than merely suspecting
it. Both the low **and** the high rolling-resistance bounds *reduce* the top
routes' times, by a median of 18 % and 51 % respectively. A genuine descent
would gain time with lower resistance. A route that loses time in both
directions is sitting on a knife edge: it is optimal only for the central
coefficient, and only because it is nearly balanced there.

Two consequences for Phase 3:

- the event needs a discriminating definition — a minimum net descent, a minimum
  mean speed, or an objective other than elapsed time (moving time above a speed
  floor, or distance) — chosen deliberately rather than inherited;
- the 0.30 m/s / 2 s stop rule is load-bearing. A route hovering just above the
  threshold accumulates time indefinitely, so the rule sets the answer.

The `manual_top10_audit.csv` flags carry this: `mean speed below 5.4 km/h:
near-equilibrium creep` and `ascent is a large share of descent`.

## 2. The second definition effect: no braking truncates the real descents

The genuinely fast routes exist and the engine finds them — 3.8 km for 303 m of
drop, peaking near 85 km/h. They do not reach the top of the ranking because the
braking-free rule ends the run at the first bend the rider cannot hold. Their
admissible time is the time to that bend, not the time to the bottom.

That is the correct reading of the stated rules, and it is why the constraint
had to be measured properly rather than assumed away (§5).

## 3. Bicycle usability, and why it was needed

Phase 1B ranked ways on legal cyclability alone, which placed OSM way
708124926 — `highway=cycleway`, `surface=dirt`, `mtb:type=downhill`,
`mtb:scale=2`, named "Run DMC" — beside a departmental road. Phase 2 grades every
way for the reference bicycle:

| class | ways | length | meaning |
|---|---:|---:|---|
| `paved_reference` | 828 | 222.4 km | explicit sealed surface; the primary ranking |
| `reference_vtc` | 529 | 108.3 km | rideable, incl. classified roads with no surface tag |
| `extended_vtc` | 508 | 40.8 km | firm unsealed, materially more uncertain |
| `excluded` | 1 212 | 256.2 km | not rideable or not permitted |
| `review` | 1 437 | 557.6 km | no permission or no quality evidence recorded |

Run DMC and DH5 are now `excluded` on `mtb:type=downhill`.

A classified mainland road with no `surface` tag is accepted as sealed — 1 023
ways, 147.2 km — but the assumption is recorded on the edge and **charged the
degraded-asphalt scenario**, so it costs time rather than being granted free.

`review` is large (557.6 km) mostly because French `track` ways rarely carry an
explicit `bicycle` tag. The conservative doctrine inherited from Phase 1A was not
relaxed to fill the extended class; the consequence is that `extended_vtc` is
small and that a real share of the rural network is neither admitted nor refused.

## 4. Rolling resistance by surface

One coefficient across asphalt, gravel and dirt is a modelling error: resistance
dominates the end of a coast and varies by roughly an order of magnitude. Five
scenario classes replace it, each with a central value, a low/high interval, a
basis and a stated uncertainty (`regional_graph_summary.json`).

| class | central | low | high |
|---|---:|---:|---:|
| asphalt, good | 0.0060 | 0.0045 | 0.0080 |
| asphalt, degraded | 0.0100 | 0.0070 | 0.0150 |
| stabilised gravel | 0.018 | 0.012 | 0.028 |
| compact track | 0.028 | 0.018 | 0.045 |
| dirt | 0.045 | 0.028 | 0.075 |

Anchored on the published range for a well-inflated tyre on smooth hard surfaces
(Wilson & Papadopoulos, *Bicycling Science*, 3rd ed., ch. 6). **No coast-down
test was run for this study**; the unpaved values are bounded from the
literature, not measured, and their intervals widen accordingly. Any ranking
that depends on separating two unpaved routes is not supported by this model.

The effect is real, not cosmetic: on a 3 % descent, asphalt reaches the end of a
2 km run in 261 s while dirt stops after 715 m.

## 5. Elevation profile method, chosen by measurement

Five methods were built from the same samples and scored on 400 real edges
(`elevation_method_comparison.csv`, `elevation_method_summary.json`).

| method | simulable | median segs | median abs net-dz error | ascent inflation | segments > 25 % | hairpin worst grade | time-step spread |
|---|---:|---:|---:|---:|---:|---:|---:|
| `raw_10m` | 91 % | 26 | 0.000 m | 0.921 | 749 | 0.219 | 4.3e-4 |
| **`raw_25m`** | **95 %** | **11** | **0.000 m** | **0.833** | **257** | **0.158** | 4.6e-4 |
| `adaptive_geometry` | 83 % | 34 | 0.000 m | 0.961 | 1 572 | 0.265 | 4.4e-4 |
| `robust_median_local` | 90 % | 26 | 0.425 m | 0.793 | 668 | 0.193 | 4.1e-4 |
| `net_dz_constrained` | 90 % | 26 | 0.000 m | 0.799 | 674 | 0.195 | 4.1e-4 |

Applying the criteria in order: `robust_median_local` fails elevation
conservation (0.425 m median loss) and is eliminated; `adaptive_geometry` is
worst on every noise metric; temporal stability and stop stability do not
discriminate (all spreads ~0.04 %, no run changes its stop reason).
**`raw_25m` is selected**: fewest implausible segments, best hairpin behaviour,
highest simulable share, exact elevation budget.

Curvature is computed from the 5 m base geometry, not from the 25 m production
profile, so coarse sampling does not blind the bend check (§6).

`net_dz_constrained` is retained as the sensitivity alternative and shows the
value of the constraint: it matches the robust filter's noise reduction while
keeping the elevation budget exact.

## 6. Bends, and a defect found by checking

`a_lat = v²/R`, with the radius taken from a circle through points a declared arc
apart so that metre-scale digitising noise cannot invent a bend. Three scenario
limits: 0.20 g (conservative), 0.35 g (nominal), 0.50 g (committed) — limits on
what a rider will accept without braking, not tyre-friction limits.

The first implementation read curvature from the production profile. Subsampling
to a uniform 25 m grid **drops exactly the sharp-bend vertices the sampler had
kept**, so hairpins looked like straight lines: 3 916 bends detected across the
paved graph instead of **44 994**, of which 2 717 are under 15 m radius. The
constraint was almost blind, and the first ranking it produced was wrong. Reading
the fine geometry fixed it, and the ranking changed substantially.

Across the ranked routes: 3 of 20 `reference_vtc` routes are turn-limited at the
nominal limit and 6 at the conservative limit; none of the paved 20 at nominal,
2 at conservative (`turn_constraint_audit.csv`).

## 7. Independent controls

**Copernicus GLO-30** — genuinely independent (different mission, sensor and
datum), read directly from the open AWS mirror. 1 500 points compared:

- mean difference **+4.75 m**, median +3.46 m — a datum and model-kind offset
  (EGM2008 against NGF-IGN 1969; surface model against bare earth), not an error
  in either source;
- residual scatter after removing the mean: **σ 9.02 m**, p95 |residual|
  16.71 m, max 96.53 m;
- 26 gross inconsistencies beyond 25 m, with the worst sectors listed.

At 30 m posting this cannot validate the grade of a 25 m segment and is not used
to correct anything. It does establish that RGE ALTI carries no gross systematic
error over the study area. Decoding it required implementing the TIFF
floating-point predictor: ignoring it does not give slightly wrong elevations, it
gives values around 1e35, which is how the omission was caught.

**IGN BD TOPO** via the Géoplateforme WFS, 6 841 road features:

- 1 172.0 km of BD TOPO road against 1 185.3 km of OSM highway — the OSM extract
  also carries paths, tracks and footways, so the totals are not expected to match;
- structures: **96 bridges agree**, 83 OSM-only, **15 tunnels agree**, 79
  OSM-only, 63 BD TOPO-only, at a 30 m match radius.

The OSM-only counts are concentrated on paths and tracks, which the BD TOPO road
layer does not carry. BD TOPO does not replace OSM as the cycling graph: its
legal cycling semantics are thinner. **Structures still receive no elevation from
either source and remain non-simulable.**

## 8. The routable graph

Ways are cut at every shared interior node — 502 admitted ways carry 974 such
nodes that routing would otherwise not see.

| | `paved_reference` | `reference_vtc` |
|---|---:|---:|
| directed edges | 2 429 | 3 919 |
| nodes with outgoing edges | 1 325 | 1 965 |
| directed length | 426.4 km | 637.8 km |
| simulable edges | 2 400 | 3 873 |
| turn restrictions enforced | 3 | 3 |

Junctions are derived once from the widest scenario so that geometry does not
move between scenarios, and the reverse direction mirrors the forward samples
rather than re-sampling, so both directions of a road are measured on the same
ground.

Non-simulable edges are those whose 25 m profile still exceeds |grade| 0.5 —
between 0.512 and 0.755 — which is the terrain model failing to describe the
roadway, reported rather than clipped.

`no_*` and `only_*` restrictions are enforced between edges, and `except=bicycle`
disables a restriction, because a motor-vehicle turn ban does not apply here.

## 9. Search and its validation

Depth-first enumeration under an explicit **cycle rule: each way piece at most
once per route, in at most one direction**. Without it a rider could shuttle
across a dip and accumulate unbounded time.

- `paved_reference`: 2 400 seeds, 47 464 expansions, 3 233 routes, **0 seeds
  budget-limited**;
- `reference_vtc`: 3 873 seeds, 503 651 expansions, 5 427 routes, **80 of 3 873
  seeds (2.1 %) hit the 5 000-expansion budget** and are reported, not hidden.

**Validation: 40 of 40** real subgraphs give the identical optimum, by time and
by path, against a brute-force enumeration that shares none of the engine's
shortcuts (`routing_validation.csv`). 17 further adversarial graphs are covered
in `tests/test_phase2_graph_and_search.py`: long gentle beats short steep; the
engine takes the gentler branch when the steeper one dead-ends; inertia crosses
a flat and a small rise; an unclimbable rise ends the route; the cycle rule
contains a loop; a 12 m bend at speed is a violation while a 150 m bend keeps
margin; forbidden roads and bridges never enter the graph.

## 10. Start point

Seeds sit at graph nodes, but the event allows a start anywhere along an edge.
Re-running the 20 ranked routes from offsets inside their first edge:
**median gain 0.0 %, maximum 14.5 %** (paved rank 8, starting 74.8 m in).

So the node-seeded approximation is usually exact but not always, and a 14.5 %
gain is more than enough to reorder a ranking. It is an approximation, it is
declared, and Phase 3 should seed inside edges for the shortlist.

## 11. Sensitivity — the ranking is not stable

Stability is the share of ranked positions unchanged; 1.0 means the order is
identical.

| variant | top 1 unchanged | order stability | median Δt |
|---|---|---:|---:|
| time step 0.01 s | yes | **1.00** | −0.02 % |
| lateral limit 0.50 g | yes | **1.00** | 0 % |
| time step 0.20 s | yes | 0.70 | +0.06 % |
| rotating mass 3 kg | yes | 0.65 | −0.9 % |
| rotating mass 0 kg | yes | 0.50 | −0.1 % |
| method `net_dz_constrained` | yes | 0.50 | 0 % |
| method `raw_10m` | yes | 0.45 | 0 % |
| CdA 0.65 m² | yes | 0.35 | −10 % |
| lateral limit 0.20 g | yes | 0.15 | 0 % |
| **Crr high** | **no** | **0.15** | **−51 %** |
| CdA 0.45 m² | yes | 0.10 | −15 % |
| **Crr low** | **no** | **0.10** | **−18 %** |

**Verdict: completely dependent on the assumptions.** Only the integrator step
and the permissive lateral limit leave the order intact. Rolling resistance
changes both the order and the leader, and it does so in *both* directions,
which is the signature of the near-equilibrium artefact of §1.

## 12. Phase 2 gate

| requirement | status |
|---|---|
| real regional graph is routable | yes — 2 429 / 3 919 directed edges over 426 / 638 km |
| turn restrictions applied | yes — `no_*` and `only_*` between edges, `except=bicycle` honoured |
| surface really influences the model | yes — five sourced scenarios; asphalt against dirt changes a 2 km run from completion to a 715 m stop |
| explicit reference-bicycle definition | yes — five usability classes, documented rules |
| production elevation method chosen | yes — `raw_25m`, selected on measured criteria |
| turn constraints taken into account | yes — three scenarios, per-route critical bend, admissible time truncated at the first violation |
| engine finds the exact optimum on validation graphs | yes — 40/40 real subgraphs, 17 adversarial cases |
| real regional ranking produced and audited | yes — and the audit is what shows it is not usable as a ranking |
| sensitivity of the best candidates known | yes — and it is poor |

## 13. Open limitations

- The elapsed-time objective has a degenerate optimum; the leading candidates are
  near-level creeps, not descents.
- The stop rule sets the answer for those candidates.
- The ranking order is unstable under rolling resistance and drag area.
- 80 of 3 873 `reference_vtc` seeds hit the expansion budget.
- Start points are node-seeded; up to 14.5 % of time is left on the table.
- 557.6 km of the network stays in `review` for want of an explicit bicycle tag.
- Structures have no roadway elevation and remain non-simulable.
- Rolling-resistance coefficients are bounded from the literature, not measured.
- Wind is zero and air density fixed; neither is a scenario yet.
- Copernicus cannot validate small-segment grades and BD TOPO cannot supply deck
  heights, so neither control closes the elevation question for structures.

---

Road geometry and tags: © OpenStreetMap contributors, ODbL 1.0.
Elevations: © IGN — RGE ALTI® via Géoplateforme, Licence Ouverte / Open Licence (Etalab) 2.0.
Topographic cross-check: © IGN — BD TOPO®, Licence Ouverte 2.0.
Independent elevation control: Copernicus DEM, © DLR e.V. 2010-2014, © Airbus DS 2014-2018.
