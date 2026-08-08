# Phase 3 — Revalidating the objective: maximum coasting distance

Experimental regional prototype on the Oisans. **No national claim.** The national search has not
started.

> **Status of this revision.** Every figure below comes from the rerun on the corrected engine.
> Two defects that invalidated the previous ranking are fixed and recorded in §9.2: the search
> pruned on a speed envelope different from the one it published, and the Top 20 was assembled
> from a per-seed cap rather than globally. The `paved_reference` record survives unchanged at
> 4 494.8 m; the `reference_vtc` ranking did not, and now leads at 6 291.2 m.
> **Two reserves are open and neither is closed by this revision:** five VTC seeds are unfinished,
> and the VTC leader is network-limited rather than energy-limited. See §4 and §9.1.

## 0. The two problems, side by side

| | Old objective | Definitive objective |
|---|---|---|
| Maximise | `elapsed_time_s` | `distance_travelled_m` |
| Run ends | speed ≤ 0.30 m/s held for 2 s | speed zero **and** no forward acceleration available |
| Bends | route ended at the first bend needing braking | rider brakes exactly as much as the envelope demands and continues |
| Leading Oisans candidate (paved) | **734 m**, drops **1.8 m**, 420 s, 6.3 km/h mean | **4495 m**, drops **280 m**, 490 s, 33.0 km/h mean |
| Why it led | a nearly balanced bicycle creeps just above the stop threshold | it is a real descent |
| Robustness | both the low *and* the high Crr bound cut its time (−18 %, −51 %) | leader unchanged in 13 of 17 sensitivity variants |

The old formulation did not reward descending. Crawling bought seconds; it buys no metres. The
change of objective, not a side condition bolted onto the old one, is what removed the
degeneracy.

## 1. The definitive physical stop

The run ends when speed reaches zero and nothing can restart the bicycle. At rest the aerodynamic
term vanishes, leaving gravity against rolling resistance:

    a(0) > 0   ⟺   −sin θ > Crr·cos θ   ⟺   grade < −Crr

`a(v)` is non-increasing in speed, because drag only ever opposes motion, so `a(0)` is the largest
acceleration a segment offers. A segment able to restart the bicycle could never have stopped it —
the speed would have decayed toward a positive equilibrium instead of reaching zero. Therefore
**a mid-segment zero is always definitive**, and only a zero landing on a segment boundary can be
followed by a restart, decided by the segment about to be entered. The bicycle never rolls
backwards.

The criterion is evaluated through the acceleration function rather than the algebraic form, so a
non-zero along-route wind — which does exert force at rest — is handled by the same rule.

**A flat cannot produce an endless coast.** On level ground the restart test is `0 < −Crr`, which
is false, and while moving, rolling resistance and drag always decelerate. Measured: 15 km/h on
asphalt at Crr 0.006 stops after **101 m**.

**Diagnostics** are published per route: distance to 5 km/h, to 1 km/h, to 0.30 m/s, to physical
zero, and the log of zero events with whether each restarted. No ranked route restarts (0 of 20).

**Threshold independence.** The numerical zero threshold was swept from 1e-4 to 1e-12 m/s. Median,
minimum and maximum distance change: **exactly 0.0**, order stability **1.000**. The ranking does
not depend on it.

## 2. Constrained braking

The optimiser never selects a braking amount. A maximum-speed envelope comes from the bend radii
of the 5 m geometry via `a_lat = v²/R`; the bicycle follows its natural dynamics wherever they
respect it and exactly enough energy is removed where they would not. Two representations:

- **ideal** — energy removed at the constraint;
- **anticipated** — braking ahead at a declared 1.5 m/s², from a backward pass in `v²`.

**They are equivalent for distance, and the reason is structural.** Both leave the constraint at
the same place and the same speed, so the state governing everything downstream is identical.
Measured over the 40 ranked routes: maximum relative difference **0.13 %**. The residual comes
from the one documented exception — a route that stops inside a braking zone and never reaches
the next constraint.

The braking **energy** differs between the two (52 kJ against 56 kJ on the leader) but that figure
is bookkeeping: it records how much speed had to be removed, and carrying more speed into a
constraint simply means more to destroy. It is not a discriminator and is not used as one.

Cost of the envelope against an unconstrained run: **0 % to 1.3 %** on the ranked routes.
Consequence: the search uses the cheap representation and the finalists the detailed one, which is
sound because the choice cannot move the objective.

Published per route: total distance, braking energy, braking distance, **binding constraints**
(distinct profile segments the envelope reduced — scale-free) and **braking substeps** (solver
work, which scales with the time step and is not a property of the road).

## 3. Three defects found by checking, and what they cost

All three share one shape: **two scales or two orientations that look interchangeable and are
not.** Each invalidated the ranking. Each was found by testing rather than by reading.

**3.1 Bends measured on the production profile.** The radius estimator ran on the 25 m profile,
which drops exactly the sharp-bend vertices the sampler had retained. 3 916 bends detected instead
of **44 994**, of which 2 717 are under 15 m radius. The turn constraint was nearly blind.
*Fixed:* radii are read from the 5 m geometry.

**3.2 Reverse profiles with no terrain.** `subsample_uniform` selected points whose chainage was a
multiple of the target spacing. Reversal renumbers chainage as `total − chainage`, and a total
that is not itself a multiple leaves nothing matching, so the profile collapsed to its two
endpoints: one averaged grade, no relief. This hit **1450 of 2400** simulable edges — every
reverse one. A featureless edge never stops a bicycle, so those edges dominated a distance
ranking, and the first reported "record" was built entirely from them.
*Fixed:* selection is by position in the grid sequence. Median segment is now 21.0 m forward and
21.5 m reverse, with zero single-segment edges. A regression test pins it on a 617.3 m edge,
deliberately not a multiple of 25.

**3.3 Two plan-length scales.** Bend chainage is measured on the 5 m geometry; the simulator works
in the travelled distance of the 25 m profile, whose polyline cuts every corner and is shorter.
Mapping by absolute chainage let the error accumulate to a whole segment, shifting the entire
envelope after the first junction. On one route the same trip read **929.5 m** under one envelope
and **4872 m** under the other.
*Fixed:* each edge is mapped by its own fraction of its own length. Both envelopes now agree.

Reported record across the three fixes: 5364 m → 5334 m → 4872 m → **4495 m**. Every intermediate
figure was an artefact.

**These defects predate Phase 3.** `reverse_samples` and the per-edge bend evaluation were
introduced in Phase 2, so **the Phase 2 ranking was affected by all three**. That ranking is
superseded and is marked as such rather than regenerated: it answers a question the study no
longer asks. Phase 2's *conclusion* — that the elapsed-time objective is degenerate — does not
rest on the defective ranking; it rests on the sensitivity signature, where both Crr bounds cut
the leader's time.

## 4. Regional result — rerun on the corrected engine

Everything in this section comes from the rerun after the two ranking defects of §9 were fixed.
The previous figures are superseded, and the change is set out rather than quietly replaced.

Search: **2 383 seeds, 16 877 expansions, 0 budget-limited** for `paved_reference`;
**3 851 seeds, 135 353 expansions, 5 budget-limited** for `reference_vtc`. Runtime 17 133 s.

The two scenarios no longer return the same leader, and that is the single largest change: with
unpaved and degraded surfaces admitted, `reference_vtc` reaches a different and much longer
corridor that the paved graph simply does not contain.

### What the corrections moved

| | old ranking | corrected ranking |
|---|---|---|
| `paved_reference` best | 4 494.8 m | **4 494.8 m** — unchanged |
| `paved_reference` top 20 | — | **6 of 20 routes were absent from it**, incl. a new rank 3 at 3 965.1 m |
| `reference_vtc` best | 4 494.8 m | **6 291.2 m (+40 %)** |
| `reference_vtc` top 20 | — | **20 of 20 routes changed** |
| `reference_vtc` budget-limited seeds | 39 | 5 |

The paved record surviving is a result, not a reprieve: the per-seed cap was hiding routes below
it, not above it. The VTC ranking was wrong outright, which is exactly the failure §9.2 predicted —
a walk pruning on a per-edge envelope discards long routes that the published envelope would have
kept.

### `paved_reference` — top 10

| rank | distance (m) | net Δz (m) | edges | v max (km/h) | binding bends | termination | inferred surface | corridor |
|---:|---:|---:|---:|---:|---:|---|---:|---|
| 1 | **4 494.8** | −280.3 | 18 | 55.1 | 19 | definitive stop | 0 % | Rue de Piégut … D 211G |
| 2 | 4 179.0 | −257.6 | 17 | 55.1 | 22 | definitive stop | 0 % | Rue de Piégut … Rue de la Grande Fontaine |
| 3 | 3 965.1 | −280.3 | 9 | 55.1 | 14 | definitive stop | 0 % | Rue de Piégut … D 211e |
| 4 | 3 809.8 | −252.6 | 13 | 55.1 | 18 | definitive stop | 0 % | Rue du Col … D 211G |
| 5 | 3 679.7 | −233.4 | 17 | 55.1 | 16 | definitive stop | 0 % | service … D 211G |
| 6 | 3 493.9 | −230.0 | 12 | 55.1 | 21 | definitive stop | 0 % | Rue du Col … Rue de la Grande Fontaine |
| 7 | 3 363.8 | −210.8 | 16 | 55.1 | 19 | definitive stop | 0 % | service … Rue de la Grande Fontaine |
| 8 | 3 280.1 | −252.6 | 4 | 55.1 | 13 | definitive stop | 0 % | Rue du Col … D 211e |
| 9 | 3 149.9 | −233.4 | 8 | 55.1 | 11 | definitive stop | 0 % | service … D 211e |
| 10 | 2 798.0 | −197.0 | 2 | 55.5 | 16 | definitive stop | 0 % | Route de Sardonne … D 44B |

Full table in `top20_paved.csv`. Of the paved top 20, **13 end in a definitive stop, 6 at the end
of the network and 1 with no admissible continuation**. The seven that do not stop are lower bounds
on what their corridor delivers, not measurements of it.

### `reference_vtc` — top 10

| rank | distance (m) | net Δz (m) | edges | v max (km/h) | binding bends | termination | inferred surface | corridor |
|---:|---:|---:|---:|---:|---:|---|---:|---|
| 1 | **6 291.2** | −443.3 | 61 | 68.3 | 32 | network end | 34.3 % | Route des Lacs … Avenue de Brandes |
| 2 | 6 253.6 | −443.3 | 57 | 56.9 | 28 | network end | 31.6 % | Route des Lacs … Avenue de Brandes |
| 3 | 6 174.7 | −443.3 | 60 | 68.3 | 37 | network end | 34.3 % | Route des Lacs … Avenue de Brandes |
| 4 | 6 159.2 | −443.3 | 59 | 68.3 | 37 | network end | 34.1 % | Route des Lacs … Avenue de Brandes |
| 5 | 6 141.2 | −443.3 | 59 | 68.3 | 31 | network end | 33.9 % | Route des Lacs … Avenue de Brandes |
| 6 | 6 096.0 | −443.3 | 61 | 68.3 | 33 | network end | 35.4 % | Route des Lacs … Chemin de la Chapelle |
| 7 | 6 058.4 | −443.3 | 57 | 56.9 | 29 | network end | 32.6 % | Route des Lacs … Chemin de la Chapelle |
| 8 | 5 979.5 | −443.3 | 60 | 68.3 | 38 | network end | 35.4 % | Route des Lacs … Chemin de la Chapelle |
| 9 | 5 964.0 | −443.3 | 59 | 68.3 | 37 | network end | 35.2 % | Route des Lacs … Chemin de la Chapelle |
| 10 | 5 946.1 | −443.3 | 59 | 68.3 | 32 | network end | 35.1 % | Route des Lacs … Chemin de la Chapelle |

Full table in `top20_vtc.csv`.

**The VTC record is not an energy-limited result and must not be read as one.** All ten leading
routes terminate at `network_end`, all share the same −443.3 m net drop, and the leader still
carries **8.6 km/h** when the admitted graph runs out. They are ten variants threading the same
descent from Route des Lacs. The figure is therefore a **lower bound on that corridor**, not a
measurement of where the bicycle stops. Of the VTC top 20, 10 stop definitively and 10 end at the
network.

The end point (45.086881, 6.058396) sits well inside the extract — the bounding box runs to
longitude 6.02, some 3 km further west — so the route is cut by a real dead end in the admitted
graph, not by the edge of the download. Which dead end, and whether the continuations there were
excluded by usability rather than absent, is settled in the manual audit of §4.1.

**A third of the VTC leader's surface is inferred, not tagged** (34.3 %, split
`asphalt_good` 66 % / `asphalt_degraded` 34 %). The paved leader is 100 % explicitly tagged
asphalt. The two records are therefore not equally well evidenced, and the VTC one inherits the
uncertainty of the surface inference on top of everything else.

### Open reserve: 5 unfinished VTC seeds

Five `reference_vtc` seeds exhaust the 5 000-expansion production budget. A seed that runs out of
allowance rather than out of graph has **not been answered**: its distance is a lower bound on its
own optimum. Until they are closed, the VTC baseline is exhaustive for 3 846 of 3 851 seeds and no
more, and the 6 291.2 m figure cannot be called a regional maximum even within the extract.
`scripts/phase3_resolve_budget_limited.py` identifies them and re-runs only those, raising the
allowance until each walk ends because it ran out of graph rather than out of budget; a seed that
stays unfinished at the highest allowance tried is reported as unfinished with its expansion count,
never truncated silently.

## 5. Start point — remeasured, and the earlier gain retracted

Seeds sit at graph nodes; the event allows a start anywhere along an edge. The size of that
approximation on the Oisans is now measured: **0.0 % on every ranked route of both scenarios.**

### The retracted figure, and what actually produced it

The earlier report published an 8.5 % gain from starting inside an edge, with a headline 315.9 m
on the leader. It was an artefact of comparing two different things, and the arithmetic is exact:

    4 494.85 m  (the distinct-ranked route's distance, used as the baseline)
  − 4 178.98 m  (what a fresh seed search returns for that seed)
  = 315.87 m    (the entire reported "gain")

`optimise_start` measured its baseline as `route.distance_m` — a *distinct-ranked* route — while
every candidate came from `search_distance_from_edge(keep_best=1)`, which returns that seed's own
best route. Those are different routes. Offset zero was never evaluated, so nothing caught it.
An adversarial review had also reported that `trim_edge_profile` cut one segment fewer than asked,
making the smallest offset a no-op; that was a real and separate defect, fixed, but it is not what
produced the 315.9 m.

*Fixed:* the baseline is measured with the same procedure at offset zero. Both previously published
seeds then have their optimum at **offset 0 with gain 0** — starting later only removes road.

### This is a measurement, not a theorem

Zero gain here does not generalise. Starting later means restarting at 15 km/h from the new point,
so on a different profile — a rise before a descent, a bend that costs speed early — dropping an
unfavourable prefix genuinely can extend the total. A synthetic case where `offset > 0` is strictly
optimal is pinned in `tests/test_phase3_distance.py` precisely so the optimiser cannot quietly
specialise on the answer the Oisans happens to give.

## 6. Sensitivity: is distance more robust than time?

**Yes, materially — but it is not robust.**

| variant | leader unchanged | order stability | median Δ distance |
|---|---|---:|---:|
| zero threshold 1e-3 / 1e-9 | yes | **1.000** | **0.000** |
| integrator step 0.01 s / 0.20 s | yes | 1.000 | 0.000 |
| braking anticipated | yes | 1.000 | 0.000 |
| Crr low | yes | 1.000 | +0.00 % |
| rotating mass 0 / 3 kg | yes | 1.000 | ±0.00 % |
| lateral limit 0.50 g | yes | 1.000 | +0.04 % |
| CdA 0.45 m² | yes | 0.900 | 0.00 % |
| braking disabled | yes | 0.700 | +0.27 % |
| elevation method `raw_10m` | yes | 0.444 | +0.78 % |
| elevation method `net_dz_constrained` | **no** | 1.000 | +1.19 % |
| **Crr high** | **no** | 0.000 | −0.01 % |
| **CdA 0.65 m²** | **no** | 0.000 | −0.01 % |
| **lateral limit 0.20 g** | **no** | 0.000 | −0.37 % |

Read against Phase 2, where rolling resistance changed both the order and the leader and only the
integrator step left the order intact: the leader now survives **13 of 17** variants, and the
numerical threshold, the integrator step, the braking model and the rotating mass have no effect
at all.

What still breaks it: the **high** bounds of rolling resistance and drag area, and the
**conservative** lateral limit. Each costs one route 88 % to 94 % of its distance — a route that
only just reaches its length under central assumptions collapses under pessimistic ones. The order
statistic reads 0.000 in those rows because one collapse shifts every position below it; the
median change is near zero, so the failure is concentrated, not diffuse.

## 7. Validation

### What the old 40/40 did and did not establish

The previous report claimed 40 of 40 real subgraphs matched "a brute-force enumeration that shares
none of the engine's shortcuts". **That claim was false in its second half.**
`brute_force_distance_routes` walked with the *same* per-edge envelope as the engine and only
reported with the route-level one. The two implementations shared the flawed pruning key, so their
agreement said nothing about it — which is why the defect of §9.2 survived a validation designed to
catch exactly that kind of error. Two procedures making the same mistake agree.

### The oracle that replaces it

`exhaustive_routes` applies **no budget, no keep-best, no dominance and no ordering heuristic**,
and records prefixes as routes in their own right. It shares the *evaluation* with the engine —
unavoidable and intended, since that evaluation is the definition of the objective — but it shares
no pruning key, because it prunes nothing. It **raises rather than truncating** at its path cap: a
silently truncated oracle would be worse than no oracle, because a short enumeration reports an
optimum no larger than the true one and an engine defect could hide behind it.

- **126 of 126** real Oisans seeds: identical optimum, **identical path**, worst disagreement
  **0.000000000 m**. Coverage is every seed whose subgraph an unpruned oracle can enumerate.
- **40 of 40** in the published `routing_validation.csv`, now against that oracle rather than
  against a co-defective brute force.
- Equality also holds **with `allow_cycles=True`**, which is the case that matters: lifting the
  trip rule multiplies the branching factor, and that is where a pruning defect would reappear
  unnoticed.
- The exact global ranking is proved equal to ranking every route at once, and invariant under
  seed order.

**159 tests** pass with the network refused for the whole session, 46 of them in
`tests/test_phase3_distance.py`.

## 8. The degeneracy of the new objective, disclosed

A grade just beyond `−Crr` gives a positive equilibrium speed: the bicycle never stops and the
distance is bounded by the extent of the network rather than by energy. Measured on the paved
Oisans network: **4.4 km of 371.6 km, 1.19 %**. For comparison, 42.1 % of the network is steep
enough that the bicycle never stops at all, and 27.7 % sustains more than 10 m/s.

This is a physically correct answer of a different kind, and a reader must be able to tell which
kind a row reports. Runs hitting the integrator's time cap would be lower bounds; none of the
ranked routes does.

## 9. Open limitations

### 9.1 Still open

- **Five `reference_vtc` seeds are unfinished.** They exhaust the production budget, so their
  distances are lower bounds on their own optima and the VTC baseline is exhaustive for 3 846 of
  3 851 seeds. Until they close, 6 291.2 m is not a regional maximum even within the extract.
- **The VTC record is network-limited, not energy-limited.** The whole VTC top 10 ends at
  `network_end`; the leader still carries 8.6 km/h when the admitted graph runs out. It bounds its
  corridor from below and nothing more.
- **A third of the VTC leader's surface is inferred** (34.3 %), against 0 % for the paved leader.
  The two records are not equally well evidenced.
- **The trip rule is a definition, and it is unmeasured on real data.** `allow_cycles` shows on a
  synthetic lappable loop that lifting it takes 250.5 m to 601.2 m — same data, same physics,
  4 laps. Its effect on the Oisans is not yet known.

### 9.2 Fixed since the last report, recorded so the history stays legible

- **FIXED — the search pruned on one speed envelope and reported on another.** The walk chained
  per-edge simulations under `edge_bend_limits`, blind within one chord of every junction, while
  the published distance came from the joined-geometry envelope. Branches were therefore kept or
  dropped on a quantity the study never publishes: on one seed the walk kept a route worth 159.3 m
  where a full enumeration reached 1020.9 m. `simulate_path` is now the single definition of what
  a path does; every expansion re-simulates the whole path. That is quadratic in path length and
  much slower, and it is the price of pruning on the published quantity. `_run_edge` was deleted
  rather than left unused. **Cost of the defect: the entire `reference_vtc` ranking (4 494.8 →
  6 291.2 m) and 6 of the 20 paved routes.**
- **FIXED — the Top 20 was assembled from a per-seed cap.** Keeping the two best routes of each
  seed and ranking the union is not the global ranking: one seed can legitimately own several of
  the leading places. `global_longest` keeps a running floor instead, proved equal to ranking every
  route at once and invariant under seed order.
- **FIXED — `optimise_start` compared unlike quantities.** Baseline `route.distance_m` (a
  distinct-ranked route) against candidates from a fresh seed search (that seed's own best), with
  offset zero never evaluated. The 315.9 m "gain" is exactly 4 494.85 − 4 178.98. Remeasured: both
  seeds have their optimum at offset 0, gain 0. See §5.
- Reviewed and **refuted on impact**, recorded so the same alarm is not raised twice: the
  untoleranced chord comparison in `bend_radii` (0 of 48 643 bends change); the direction
  asymmetry in `subsample_uniform` (a discretisation property — the 5 m sample set that drives
  every geometric quantity is identical both ways); the plan/travelled frame mix in
  `route_bend_limits` (dead for every published row, all of which carry `start_offset_m = 0`);
  and the un-rebased bends in `trim_edge_profile` (latent, no published number moves — fixed
  regardless).
### 9.3 Standing limitations of the model and the data

- Seven of the paved top 20 and ten of the VTC top 20 are network-limited; their corridors are
  unexplored beyond the extract.
- Rolling-resistance coefficients are bounded from the literature, not measured, and the high
  bound reorders the ranking.
- Wind is zero and air density fixed; neither is a scenario yet.
- Structures still carry no roadway elevation and remain non-simulable.
- 557.6 km of the network stays in `review` for want of an explicit bicycle tag.

---

Road geometry and tags: © OpenStreetMap contributors, ODbL 1.0.
Elevations: © IGN — RGE ALTI® via Géoplateforme, Licence Ouverte / Open Licence (Etalab) 2.0.
