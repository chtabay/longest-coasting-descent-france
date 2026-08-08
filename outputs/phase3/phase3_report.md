# Phase 3 — Revalidating the objective: maximum coasting distance

Experimental regional prototype on the Oisans. **No national claim.** The national search has not
started.

## 0. The two problems, side by side

| | Old objective | Definitive objective |
|---|---|---|
| Maximise | `elapsed_time_s` | `distance_travelled_m` |
| Run ends | speed ≤ 0.30 m/s held for 2 s | speed zero **and** no forward acceleration available |
| Bends | route ended at the first bend needing braking | rider brakes exactly as much as the envelope demands and continues |
| Leading Oisans candidate | **734 m**, drops **1.8 m**, 420 s, 6.3 km/h mean | **4495 m**, drops **280 m**, 490 s, 33.0 km/h mean |
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

## 4. Regional result

Search: **2 383 seeds, 29 327 expansions, 3 158 routes, 0 seeds budget-limited** for
`paved_reference`; **3 851 seeds, 305 723 expansions, 5 289 routes, 39 budget-limited (1.0 %)** for
`reference_vtc`. Both scenarios return the same leader, which is correct: the winner is sealed, so
both admit it.

### Experimental regional record

| | |
|---|---|
| **Distance** | **4 495 m** |
| Duration | 490 s |
| Start / end elevation | 1 636 m → 1 356 m |
| Net elevation change | −280 m |
| Ascent crossed | 15.9 m |
| Mean speed | 33.0 km/h |
| Maximum speed | 55.1 km/h |
| Minimum speed before stopping | 0.1 km/h |
| Braking energy | 52 kJ over 19 binding constraints |
| Restarts | 0 |
| Termination | definitive physical stop |
| Roads | Rue de Piégut → Rue de la Piscine → D 211e → Rue Sainte Marie → … |
| Surface | asphalt throughout, explicitly tagged |

It descends from Alpe d'Huez and ends by genuinely running out of energy, not by running out of
road. That matches the intuition of "longest coast" — which is worth stating plainly *and* worth
distrusting: the parameters were not chosen to produce it, and the sensitivity below is what the
claim rests on.

**Not every ranked route is energy-limited.** Of the paved top 20, **12 end in a definitive stop,
7 at the end of the network and 1 with no admissible continuation**. The eight network-limited
routes are lower bounds on what their corridor could deliver, not measurements of it.

## 5. Start point

Seeds sit at graph nodes; the event allows a start anywhere along an edge. Screening at 100 m then
refining at 25 m over the top 10 of each scenario:

- median gain **0.0 %**, maximum **8.5 %**;
- the 100 m screening pass captured **75 %** of the refined gain where a gain existed.

**National strategy:** screen at 100 m, refine at 25 m on the shortlist only. Node seeding alone
is not sufficient — an 8.5 % gain reorders a ranking.

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

- **40 of 40** real subgraphs give the identical optimum, distance and path, against a brute-force
  enumeration that shares none of the engine's shortcuts.
- 3 cases in `tests/test_phase3_distance.py`: a flat stopping on resistance alone
  inside its exact energy bracket; long gentle versus short steep compared at equal drop; a
  descent then a long flat; a small clearable rise; a rise consuming all the energy; a zero at a
  boundary that restarts and one that does not; a mid-segment zero that is always definitive; a
  start from rest; a bend that costs speed without ending the run; the cycle rule containing a
  loop; a geometrically longer branch that is energetically worse; a fork whose furthest choice is
  neither steepest nor lowest; a forbidden road never entered.
- 148 tests pass with the network refused for the whole session.

## 8. The degeneracy of the new objective, disclosed

A grade just beyond `−Crr` gives a positive equilibrium speed: the bicycle never stops and the
distance is bounded by the extent of the network rather than by energy. Measured on the paved
Oisans network: **4.4 km of 371.6 km, 1.19 %**. For comparison, 42.1 % of the network is steep
enough that the bicycle never stops at all, and 27.7 % sustains more than 10 m/s.

This is a physically correct answer of a different kind, and a reader must be able to tell which
kind a row reports. Runs hitting the integrator's time cap would be lower bounds; none of the
ranked routes does.

## 9. Open limitations

- Eight of the paved top 20 are network-limited; their corridors are unexplored beyond the extract.
- 39 of 3 851 `reference_vtc` seeds hit the expansion budget.
- The depth-first walk uses the per-edge envelope and the authoritative evaluation the route-level
  one; they now agree on outcome, but the walk remains mildly optimistic near junctions.
- Rolling-resistance coefficients are bounded from the literature, not measured, and the high
  bound reorders the ranking.
- Wind is zero and air density fixed; neither is a scenario yet.
- Structures still carry no roadway elevation and remain non-simulable.
- 557.6 km of the network stays in `review` for want of an explicit bicycle tag.

---

Road geometry and tags: © OpenStreetMap contributors, ODbL 1.0.
Elevations: © IGN — RGE ALTI® via Géoplateforme, Licence Ouverte / Open Licence (Etalab) 2.0.
