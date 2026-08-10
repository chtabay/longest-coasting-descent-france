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
routes terminate at `network_end` and all share the same −443.3 m net drop: they are ten variants
threading the same descent from Route des Lacs. The leader reaches the end of the admitted graph
still travelling at **56.8 km/h**. The figure is therefore a **lower bound on that corridor**, not
a measurement of where the bicycle stops. Of the VTC top 20, 10 stop definitively and 10 end at
the network.

The end point (45.086881, 6.058396) sits some 3 km inside the extract boundary, so this is not the
edge of the download. §4.1 identifies exactly what severs it: an 8.3 m `layer=-1` underpass on the
D 211, correctly excluded by the structure rule.

**A third of the VTC leader's surface is inferred, not tagged** (34.3 %, split
`asphalt_good` 66 % / `asphalt_degraded` 34 %). The paved leader is 100 % explicitly tagged
asphalt. The two records are therefore not equally well evidenced, and the VTC one inherits the
uncertainty of the surface inference on top of everything else.

### 4.1 Manual audit of the two leaders

Both leaders were audited edge by edge and joule by joule
(`scripts/phase3_audit_leader.py`, outputs in `outputs/phase3/audit/`). The energy budget is
**reconstructed from the trajectory**, summing the work of each force over the run's own samples,
so it is a check on the integrator rather than a restatement of it.

| | `paved_reference` rank 1 | `reference_vtc` rank 1 |
|---|---:|---:|
| Distance | 4 494.85 m | **6 291.22 m** |
| Edges / distinct OSM ways | 18 / — | 61 / 39 |
| Start | 45.052416, 6.076533 · 1 636.1 m | 45.107316, 6.081466 · 2 043.3 m |
| End | 45.047246, 6.084524 · 1 355.9 m | 45.086881, 6.058396 · 1 600.0 m |
| Net Δz / descent / ascent | −280.3 / 296.2 / 15.9 m | −443.3 / 450.8 / 7.5 m |
| Duration | 490.5 s | 710.7 s |
| Mean / max speed | 33.0 / 55.1 km/h | 31.9 / 68.3 km/h |
| **Speed at the end** | **0.0 km/h** | **56.8 km/h** |
| Initial kinetic energy | 0.8 kJ | 0.8 kJ |
| Gravity released | 241.1 kJ | 391.2 kJ |
| Rolling dissipated | 23.7 kJ (9.8 %) | 40.8 kJ (10.4 %) |
| Drag dissipated | 166.2 kJ (68.7 %) | 246.0 kJ (62.8 %) |
| Braking dissipated | 52.0 kJ (21.5 %) | 93.9 kJ (24.0 %) |
| Kinetic energy left at the end | 0.0 kJ | **11.4 kJ** |
| **Energy-budget residual** | **+0.004 %** | **+0.000 %** |
| Binding bends | 19 | 32 |
| Surface explicitly tagged asphalt | **100 %** | 65.7 % |
| Surface inferred | 0 % | **34.3 %** |
| Bridges / tunnels / covered / layer≠0 | none | none |
| Tracks / unpaved | none | none |
| Termination | **definitive physical stop** | **network end** |

Drag is the dominant sink on both — roughly two thirds of everything gravity releases — with
braking about a quarter and rolling resistance a tenth. That ordering is what a 15 km/h start into
a long fast descent should produce, and it is a useful sanity check on the physics: nothing here
is being won by an implausible rolling model.

**The paved leader is a real result.** It descends from Alpe d'Huez, uses 18 edges of explicitly
tagged asphalt, crosses no structure, and ends at 0.0 km/h having spent everything gravity gave it.

**The VTC leader is stopped by an 8.3 m gap in the model, not by physics.** It arrives at the end
of the admitted graph carrying **56.8 km/h and 11.4 kJ**. The road does not end there: the D 211
continues through OSM way 1453146526, which is 8.3 m long and tagged `layer=-1` — an underpass.
The preserved Phase 1B rule forbids giving a bridge, tunnel, covered way or non-zero layer a
terrain elevation, so that way is admitted to no graph and the corridor is severed at its mouth.

This is the rule working as designed, not a defect, and it must not be relaxed to make the number
larger. But it does fix how the figure may be read: **6 291.2 m is a lower bound on that corridor,
cut by an 8.3 m structure, and the corridor demonstrably continues.** Across the extract, 277
highway ways carry a structure tag or a non-zero layer (179 bridges, 60 tunnels, 21 covered,
17 layer≠0); 275 of them produce no graph edge at all, removing **10.87 km** of road. Structure
elevation is the single change that would most affect a distance ranking, and it is not a
modelling refinement — it needs a source that gives the roadway height rather than the ground's.

### 4.2 The five unfinished VTC seeds — closed

Five `reference_vtc` seeds exhausted the 5 000-expansion production budget. A seed that runs out of
allowance rather than out of graph has **not been answered**: its distance is a lower bound on its
own optimum, and a baseline containing one is not exhaustive.

`scripts/phase3_resolve_budget_limited.py` walks every seed once to find them, then re-runs only
those with a rising allowance until the walk ends because it ran out of graph. All five closed at
the first step (`budget_limited_reference_vtc.json`):

| seed | expansions needed | best distance |
|---|---:|---:|
| `osm-119440073-0-forward` | 6 050 | 3 602.9 m |
| `osm-119440074-1-forward` | 8 952 | 3 670.4 m |
| `osm-119558959-0-forward` | 10 097 | 3 744.8 m |
| `osm-28452295-0-reverse` | 10 097 | 3 896.5 m |
| `osm-28452295-1-reverse` | 10 100 | 3 961.7 m |

**0 seeds now stand unresolved.** None of the five reaches the Top 20 — rank 20 is 4 954.5 m — and
none comes near 6 291.2 m. The reserve is closed without moving the ranking, but it had to be
closed rather than assumed: the whole point of the exercise is that an unanswered seed is not a
small answer.

They needed between 6 050 and 10 100 expansions, barely above the production cap. **The cap is
therefore raised to 20 000**, which finishes every seed of both scenarios in one pass, so the
baseline no longer depends on a second script to be exhaustive.

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
unfavourable prefix genuinely can extend the total.

A synthetic case where `offset > 0` is strictly optimal is pinned in
`tests/test_phase3_distance.py` precisely so the optimiser cannot quietly specialise on the answer
the Oisans happens to give. The seed rises 4 % for 150 m before descending 6 %: from the node the
bicycle stops after **18.3 m**, started past the crest it runs **857.6 m**. The coarse pass finds
784.2 m of gain there and the fine pass 834.3 m, so the two-step screening strategy earns its
second pass as well.

### Cost: the same answer for a fifteenth of the work

The study answers a question about a **seed**, not about a route, and ranked routes share seeds
heavily — the whole `reference_vtc` top ten begins on one edge. The previous code ran the identical
study ten times, re-measured offset zero on every pass, and re-evaluated at 25 m every offset it had
already evaluated at 100 m. Memoising on `(seed, offset)` removes all three. Both passes still scan
their own full offset set, so the numbers are identical by construction rather than by hope.

| | `paved_reference` | `reference_vtc` |
|---|---:|---:|
| Routes studied / distinct seeds | 10 / 4 | 10 / **1** |
| Searches without caching | 95 | 110 |
| Searches performed | **40** | **8** |
| Searches avoided | 55 | 102 |
| Measured runtime | 21.7 s | 980.5 s |
| Projected runtime without caching | 51.5 s | **13 482 s** |
| **Rows differing from the uncached study** | **0 of 10** | **0 of 10** |

The two together fall from a projected 3 h 45 to 17 minutes — which is essentially the whole of the
4 h 46 the corrected rerun took, since the two regional rankings and the validation account for
about twenty minutes between them. The cost came from re-running an identical search, not from the
correctness fix.

## 5bis. The trip rule: what "each way piece once" is worth

The rule

> each physical way piece is traversed at most once, whichever direction

is a **definition of what a trip is**, not a physical claim. It cannot be justified by the physics
and it cannot be dropped quietly, so it is measured: `allow_cycles` lifts it in the engine, in the
oracle and in the global ranking, with everything else held fixed — same extract, same elevations,
same profile, same bends, same turn restrictions, same physics, same engine.

One thing the rule does **not** do: permit a U-turn. `continuations` already refuses to re-enter
the way piece just traversed, as a separate rule, so lifting the trip rule enables genuine loops
and nothing else.

### Are there cycles at all?

Asked first and separately, because a null physical result on a network with no loops would say
nothing. Strongly connected components of the real continuation graph (`cycle_topology.json`):

| | directed edges | components with a cycle | edges inside one |
|---|---:|---:|---:|
| `paved_reference` | 2 429 | 21 | 880 (**36.2 %**) |
| `reference_vtc` | 3 919 | 26 | 1 949 (**49.7 %**) |

The largest spans 376 edges over 126 ways around Avenue de Brandes. Cycles are not scarce here;
half the VTC network sits inside one.

### Can a coasting bicycle use them?

Almost never, and the reason is physical rather than topological: closing a cycle means regaining
the elevation just spent, and a bicycle that is only coasting usually cannot.

| | seeds compared | seeds where repetition helps | largest gain | median expansion blow-up |
|---|---:|---:|---:|---:|
| `paved_reference` | 64 | **1** | +22.7 m (+8.05 %) | ×1.0 |
| `reference_vtc` | 34 | **3** | **+162.0 m** (+2.58 %) | ×1.0 |

A median blow-up of ×1.0 means that on most seeds the lapping walk explores *precisely the same
tree*: no admissible continuation was ever one the rule had blocked.

**But the exceptions land where it hurts.** The largest is the VTC leader's own seed:
6 291.2 m → **6 453.3 m**, +162.0 m, 75 traversals of 72 distinct edges, for ×5.17 the expansions.
The VTC record is therefore **not stable under the change of definition**, and the rule cannot be
called free.

What it repeats is worth naming, because it decides whether the extra 162 m is a discovery or an
artefact of the definition. Exactly three edges are used twice, and **all three are roundabouts**:

| repeated edge | OSM way | positions in the route |
|---|---:|---|
| Rond-Point des Pistes | 234171512 | 6 and 10 |
| Rond-Point du Tour de France | 1040486385 | 23 and 30 |
| unnamed tertiary roundabout arc | 28429105 | 41 and 44 |

The bicycle goes round three roundabouts twice each. That is physically available to a rider and
the simulation of it is sound — the lateral envelope applies to the second lap exactly as to the
first — but whether it counts as *one trip* is a matter of definition, not of physics. It is
precisely the behaviour the trip rule exists to exclude. The route still ends at the same D 211
underpass, so the 8.3 m structure of §4.1 bounds both versions alike.

### Is a regional run with repetition affordable? Both regions, run.

| scenario | trip rule | expansions | budget-limited | best |
|---|---|---:|---:|---:|
| `paved_reference` | once per way piece | 16 877 | 0 | 4 494.8 m |
| `paved_reference` | repetition allowed | 25 625 (**×1.52**) | 0 | **4 494.8 m** — same route, no repeated edge |
| `reference_vtc` | once per way piece | 155 649 | 0 | ≥ 6 291.2 m |
| `reference_vtc` | repetition allowed | 373 854 (**×2.40**) | 0 | **≥ 6 453.3 m (+2.58 %)** — 75 traversals of 72 edges |

**The budget never binds in any of the four.** Repetition costs ×1.5 on the paved graph and ×2.4 on
the hybrid one, which is affordable: the regional run with cycles is a computation, not a fantasy.

Two honest notes on the cost. The wall-clock figures in
`cycle_rule_comparison_reference_vtc.json` are **not** a measure of the algorithm — that run
straddled long periods where the machine was asleep, so its 68 962 s says more about the laptop
than about the search. The expansion counts are the comparable quantity. And the whole regional
walk is now parallel (§10bis), which changes the runtime of every one of these and none of their
results.

**The paved answer is unchanged; the hybrid one is not.** `paved_reference` returns the identical
route, with no repeated edge, under both definitions — the trip rule costs it nothing.
`reference_vtc` gains 162 m by lapping three roundabouts twice each. So the rule is free on one
graph and not on the other, and which figure counts as "the" record is a question about the
definition of a trip that this study has not settled.

### Does the engine still find the optimum once the rule is gone?

**93 oracle checks with repetition allowed, 0 disagreements.** This is the case where a pruning
defect would have been easiest to miss, because lifting the rule multiplies the branching factor.
On synthetic graphs the mode is exercised on a flat loop, a loop too steep to complete, a loop
under two lateral limits, a loop left through a rising exit where leaving too early and too late
are both wrong, a loop with two exits, and a finiteness sweep across five lap grades.

### The bound that makes the mode safe, and where it stops holding

Every closed cycle returns the bicycle to the same elevation, so gravity nets to zero while rolling
resistance and drag only remove energy. Repetition is therefore self-limiting: the number of laps
is finite and the walk ends on its own with the budget untouched.

**That argument assumes the windless reference environment.** Under a wind able to supply energy
the aerodynamic term becomes a source over part of the lap, a closed cycle may return more than it
received, and neither the finiteness of the lap count nor the termination of the search is
guaranteed. Any wind scenario must re-establish its own bound before repetition may be allowed
under it. The cycle invariants in `tests/test_phase3_distance.py` say so.

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

- **The VTC record is network-limited, not energy-limited.** The whole VTC top 10 ends at
  `network_end`; the leader reaches the end of the admitted graph still travelling at 56.8 km/h,
  severed by an 8.3 m `layer=-1` underpass the structure rule correctly excludes. It bounds its
  corridor from below and nothing more. **This is the largest single reservation on the figure**,
  and closing it needs a source of roadway elevation for structures, not a modelling change.
- **A third of the VTC leader's surface is inferred** (34.3 %), against 0 % for the paved leader.
  The two records are not equally well evidenced.
- **The VTC record is not stable under the trip rule.** Allowing repetition takes its seed to
  6 453.3 m by lapping three roundabouts twice each (§5bis). Which figure is "the" record is a
  question about the definition of a trip, and the study has not settled it.
- 557.6 km of the network stays in `review` for want of an explicit bicycle tag, and structures
  still carry no roadway elevation.

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
- **CLOSED — the five unfinished `reference_vtc` seeds.** All resolved at 6 050 to 10 100
  expansions, reaching 3 602.9 to 3 961.7 m; none enters the Top 20 and none approaches 6 291.2 m.
  The production cap is now 20 000, above what any seed of either scenario needs, so the baseline
  is exhaustive in a single pass. See §4.2.
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

## 9bis. Every distance now carries why it ended

A distance without the reason the route ended is not a result. Only a definitive physical stop
measures the coasting distance; every other ending is a **lower bound**, and printing the two alike
is precisely what let 6 291.2 m read as a regional maximum. Four statuses, exhaustive and mutually
exclusive (`coastdown/termination.py`):

| status | meaning | how to read the distance |
|---|---|---|
| `physical_stop` | speed reached zero and nothing could restart the bicycle | **the coasting distance** |
| `model_gap` | the road continues and the model does not follow it | lower bound |
| `network_boundary` | nothing in the extract continues past that point | lower bound |
| `budget_limit` | the search ran out of allowance, not of graph | lower bound; nothing about the road is being reported |

`model_gap` covers two cases: no admitted edge at the junction is simulable, or every continuation
was refused by the trip rule — a coast ended by a definition has not measured how far the bicycle
rolls either. The `model_gap` / `network_boundary` distinction **cannot be drawn from the graph**,
because the graph is exactly what dropped the continuation; it is drawn by going back to the raw
extract and asking whether a highway way still runs through that node.

Applied to the four published variants:

| variant | leader | ranking |
|---|---|---|
| `paved_reference` · once per way piece | **4 494.8 m — PHYSICAL STOP** | 13 physical stops, 7 model gaps (top 20) |
| `paved_reference` · repetition allowed | **4 494.8 m — PHYSICAL STOP** | same route |
| `reference_vtc` · once per way piece | **≥ 6 291.2 m — MODEL GAP** | 10 physical stops, 10 model gaps (top 20) |
| `reference_vtc` · repetition allowed | **≥ 6 453.3 m — MODEL GAP** | 75 traversals of 72 edges |

Both VTC leaders are cut at the *same* underpass, so lifting the trip rule buys 162 m inside a
corridor that is itself truncated. Neither figure is a coasting distance.

The VTC leader's status names its cause: OSM way `1453146526` at node `13326635869`. **Neither
scenario has a single `network_boundary` route.** Every truncation in this region is something the
pipeline removed, not the edge of the download — which is what makes §9.1's structure reservation
the dominant one and not a footnote.

## 9ter. Phase A verdict

Two conclusions, deliberately separated. They point in opposite directions and merging them would
let either one flatter the other.

### A. Algorithmic validation — the regional engine can now serve as a reference

| criterion | evidence | verdict |
|---|---|---|
| Truly unpruned oracle | `exhaustive_routes`: no budget, no keep-best, no dominance, no ordering; raises rather than truncating | ✅ |
| Path **and** distance equality | 126 of 126 real Oisans seeds, identical path, worst disagreement **0.000000000 m** | ✅ |
| Equality under the harder semantics | 93 oracle checks with `allow_cycles=True`, 0 disagreements | ✅ |
| Exact global Top K | running floor, proved equal to ranking every route at once and invariant under seed order | ✅ |
| No unresolved seed | 0 of 2 383 paved and 0 of 3 851 VTC; the five that once ran out of allowance are closed | ✅ |
| In-edge starts | remeasured at 0.0 % gain, with a synthetic case where `offset > 0` strictly wins so the optimiser cannot specialise on the Oisans answer | ✅ |
| Cycles | 7 synthetic configurations, finiteness across five lap grades, engine = oracle where the exit timing has no obvious answer | ✅ |
| Braking | never chosen, only the envelope's minimum; the two representations differ by ≤ 0.13 % and are structurally equivalent | ✅ |
| Energy audit | budget reconstructed from the trajectory, independent of the integrator: residual **+0.004 %** (paved) and **+0.000 %** (VTC) | ✅ |
| Software tests | 185 tests, network refused for the whole session; `ruff check`, `ruff format --check`, `git diff --check` clean | ✅ |

**Verdict: yes.** The regional engine returns the optimum of an enumeration that shares none of its
pruning, on real data, in path as well as distance, under both trip definitions. The two defects
that invalidated the previous ranking are fixed and the failure mode that hid one of them — a
validation whose reference shared the flawed key — is gone. Nothing in the current results rests on
a search decision that has not been checked against something that prunes nothing.

This is a statement about the **search**, and about this region. It is not a statement about the
national problem, where §10 explains why this engine is the wrong shape.

### B. Physical coverage of the graph — not validated, and the dominant reservation

The engine is correct about the graph it is given. The graph is not the road.

- 277 highway ways in the extract carry a structure tag or a non-zero layer; **275 produce no edge
  at all**, removing **10.87 km** of road.
- **17 of the 40 ranked routes** (7 paved, 10 VTC) end at the edge of the admitted graph rather
  than at a physical stop.
- **Not one** ends at the edge of the download. Every truncation in this region is something the
  pipeline removed.
- The `reference_vtc` leader is `>= 6 291.2 m — model_gap`: it leaves the graph at **56.8 km/h**
  with 11.4 kJ in hand, severed by an **8.3 m** `layer=-1` underpass on the D 211.

An eight-metre gap truncates the best corridor the study has found. That is not a rounding error
and it will not be improved by a faster or more exhaustive search. **The Phase 1B rule is right and
stays unchanged**: terrain elevation on a structure invents a grade, and on a distance objective an
invented descent is exactly what the optimiser would select for. What has to change is the second
half of the behaviour — deleting the way — and that is Phase A2
(`docs/11_phase_a2_structure_continuity.md`), to be opened deliberately rather than by relaxing a
rule here.

**Verdict: the algorithmic result is sound and the physical coverage is not.** Phase A closes on
the first and hands the second to A2.

## 10bis. The regional walk now uses every core

`finished_paths` is a pure function of `(graph, profiles, seed)` and no seed can observe another,
so the walk was always parallel — it simply ran on one core. `global_longest(workers=N)` spreads it
over processes. Measured on `paved_reference`, 2 383 seeds:

| workers | runtime | speed-up | ranking |
|---:|---:|---:|---|
| 1 | 156.4 s | — | reference |
| 4 | 56.7 s | **×2.8** | identical |
| 8 | 44.7 s | **×3.5** | identical |

Two design points decide whether this is safe, and both are asserted by tests rather than assumed.

**Results are collected in submission order.** `_ranked_candidates` sorts by distance alone and
Python's sort is stable, so two routes of identical length are separated by their position in the
pool. A pool assembled in arrival order would rank exact ties differently from the sequential run.
`executor.map` yields in submission order, so the pool is built exactly as the sequential loop
builds it.

**The floor is held fixed instead of rising per seed.** That makes it *lower* than the sequential
floor, never higher, so more routes are recorded and never fewer. The extra ones are shorter than
the ranking's last entry: they cannot enter it, and they cannot eliminate a member of it either,
since elimination only ever comes from a longer route. Batch barriers were removed for the same
reason they were tempting — the cost per seed is wildly uneven, a handful of seeds dominate an
otherwise trivial region, and every barrier idles the pool waiting for one straggler.

The graph is shipped once per worker as an initialiser argument, not once per task: 15.5 MB,
0.22 s to load.

## 10. Where the search goes next

### The depth-first walk is correct and it does not scale

Everything in this report rests on a search that re-simulates the whole path at every expansion.
That is what made it correct — it is the only way the branch being judged and the route being
published carry the same number — and it is quadratic in path length. Measured on this region:

| | seeds | expansions | runtime |
|---|---:|---:|---:|
| `paved_reference`, once per way piece | 2 383 | 16 877 | 423 s |
| `paved_reference`, repetition allowed | 2 383 | 25 625 | 608 s |
| `reference_vtc`, once per way piece | 3 851 | 155 649 | 3 941 s |

A single 61-edge VTC route costs 55–93 s to search from its seed. The Oisans extract is 371.6 km of
paved road; France is three orders of magnitude larger, and the cost is worse than linear in it
because long routes are exactly what the objective selects for.

### What the state actually needs to be

The walk carries `(path, set of used way pieces)`. The set is there only to enforce the trip rule,
and it is what makes the state exponential: two arrivals at the same place with the same energy are
different states if they got there differently, so nothing can ever be merged.

Dropping the rule collapses the state to `(position, energy, previous edge)` — position and energy
because that is all the physics needs, previous edge because turn restrictions and the no-u-turn
rule look one step back. That state is dominated in the ordinary sense: at the same position and
previous edge, more energy is never worse. Dominance turns the enumeration into a value function.

**This report does not build that engine.** It records the measurements that decide whether the
transition is justified, and on the evidence here it is: the trip rule costs almost nothing in
answer (1 of 64 paved seeds, 3 of 34 VTC seeds) while being the sole reason the state cannot be
compressed. Removing it is not primarily a change of question — it is what makes a national search
tractable, and the question it changes has been measured rather than assumed.

The transition still has to handle, correctly and not by hand-waving: dissipative cycles, so the
value iteration terminates; the transitions themselves; manoeuvre restrictions; the lateral
envelope, which couples adjacent edges and so is not a property of a single edge; and energy
dominance under all of the above.

### One caveat that outranks the engine

The VTC record is bounded by an 8.3 m underpass with no roadway elevation, not by physics. Ten of
the twenty VTC routes and seven of the twenty paved ones end at the edge of the admitted graph.
**A faster engine will not improve those numbers; a source of structure elevation will.** Whichever
engine comes next, 10.87 km of removed road in one small region is the larger error term.

---

Road geometry and tags: © OpenStreetMap contributors, ODbL 1.0.
Elevations: © IGN — RGE ALTI® via Géoplateforme, Licence Ouverte / Open Licence (Etalab) 2.0.
