# Phase A2 — Graph continuity across structures

**Status: mission statement only. Nothing here is implemented, and the Phase 1B rule is
unchanged until this phase is opened deliberately.**

## Why this phase exists

The preserved rule from Phase 1B is correct and stays correct:

> a bridge, tunnel, covered way or non-zero layer must not automatically receive terrain
> elevation.

A digital terrain model describes the ground. On a bridge it describes what is under the deck; in
a tunnel, the mountain above the bore. Giving a structure the terrain height invents a grade that
does not exist, and on a distance objective an invented grade is not a small error — a fictitious
descent is exactly what a maximum-distance search will select for. Refusing the elevation is the
only safe default, and it was the right first decision.

What is *not* correct is the second half of the current behaviour: a way with no usable elevation
produces **no graph edge at all**, so the road it belongs to is severed. The rule protects the
altimetry and silently damages the topology.

## What it costs, measured

On the Oisans extract alone (`outputs/phase3/audit/`, `outputs/phase3/phase3_report.md` §4.1):

| | count |
|---|---:|
| Highway ways carrying a structure tag or a non-zero layer | 277 |
| — of which bridges | 179 |
| — tunnels | 60 |
| — covered | 21 |
| — `layer` ≠ 0 | 17 |
| Producing no edge in the `reference_vtc` graph | **275** |
| Road removed | **10.87 km** |

And the case that makes it concrete rather than statistical. The `reference_vtc` leader is
recorded as `>= 6291.2 m — model_gap`: it reaches the end of the admitted graph **still travelling
at 56.8 km/h with 11.4 kJ in hand**. The road does not end there. The D 211 continues through OSM
way `1453146526`, which is **8.3 m long** and tagged `layer=-1` — an underpass. Eight metres of
missing roadway profile truncate the best corridor the study has found.

Ten of the twenty VTC routes and seven of the twenty paved routes end the same way. In this
region, **every** truncation is a structure or an otherwise dropped way; not one is the edge of the
download. That is the argument for this phase: the largest error term in the current results is not
the search, the physics or the integrator. It is 10.87 km of road that the model removed.

### The truncations are not marginal, and this is the measurement that decides the priority

Across the 40 ranked routes, **17 end as `model_gap` and all 17 are still rolling** — final speeds
from 11.0 to 56.8 km/h, median 56.8. What blocks them:

| cause | routes |
|---|---:|
| structure with `layer` ≠ 0 | 11 |
| bridge | 4 |
| a residential way dropped for a non-structure reason | 2 |

**Fifteen of seventeen are structures.**

The VTC leader is not cut on a flat. It is cut on a **−9.5 % mean grade over its last 984 m**, with
the final edge at **−13.4 %**, accelerating, at 56.8 km/h. Continuing that run with the energy it
carries:

| if the road beyond the underpass were | it would travel |
|---|---|
| dead flat | **+383 m**, then stop |
| −2 % or steeper | **it never stops** — equilibrium speed, still rolling past 20 km |

The D 211 descends at −9.5 % there. So `>= 6291.2 m` does not mean "6 291 and a little": that route
is **not energy-limited at all**, and its true distance is plausibly kilometres greater. The `>=`
carries an unknown order of magnitude, not a rounding allowance.

All of it turns on **8.3 m** of missing roadway profile between two well-surveyed stretches of
secondary road — case 1 below, the easiest of the three.

## Objective

Replace

    structure with no roadway elevation  ->  way deleted

with

    structure with no roadway elevation  ->  roadway profile reconstructed, bounded,
                                             or explicitly uncertain

The corridor is never silently severed. If the profile cannot be established, that is published as
an uncertainty attached to the edge, not expressed by deleting the road.

## Three cases, to be handled distinctly

### 1. Short structure with reliable approaches — longitudinal interpolation

A structure short relative to the sampling, whose two ends join admitted edges with trustworthy
elevations. The roadway is interpolated longitudinally between the two connection points.

This is the D 211 case: 8.3 m between two well-surveyed stretches of secondary road. Over such a
span a linear roadway is a far better model than either the terrain or a deleted way, and the
residual error is bounded by the length.

Open questions to settle before implementing: what maximum length qualifies as "short", whether it
should be absolute or relative to the elevation sampling, and what makes an approach "reliable" —
at minimum both ends admitted, simulable, and not themselves structures.

### 2. Long structure with its own altimetric information — use a source that describes the deck

A viaduct or a tunnel of real length cannot be interpolated: its profile is a design decision, not
a straight line between its ends. Here the requirement is a source that describes **the roadway
itself** rather than the ground — BD TOPO carries structure objects, and its usability for deck
height must be established the same way every other source in this study has been: producer,
product, edition, request URL, UTC datetime, byte size, SHA-256, horizontal CRS, vertical datum,
units, licence, attribution.

Until such a source is verified for a given structure, that structure belongs in case 3. It does
not fall back to case 1.

### 3. Indeterminate profile — publish the uncertainty, do not delete the road

Where neither interpolation nor a roadway source applies, the edge is admitted with an **explicit
uncertainty**, not removed. The intended form is a bracket rather than a point estimate:

- an **optimistic** profile — the most favourable roadway consistent with what is known;
- a **pessimistic** profile — the least favourable;
- a result reported as a range whenever a route crosses such an edge.

A route whose distance depends on an indeterminate structure must be visibly marked as such, on
the same principle as the termination statuses: a reader must never have to guess which numbers are
measurements and which are bounds.

## Constraints this phase inherits

- **No artificial data may be labelled `live`.** A reconstructed roadway profile is a
  reconstruction and must be recorded as one, with its method, on every edge that carries it.
- **The Phase 1B rule is not repealed.** Terrain elevation on a structure stays forbidden. This
  phase adds reconstruction, bounding and disclosure; it does not relax the prohibition.
- **Every route carries a termination status** (`coastdown.termination`). Reconstruction will move
  routes out of `model_gap`, and the honest way to show that is to publish the before and after,
  not to quietly restate a larger number.
- **Results are published only after complete success**, and no national or regional ranking is
  claimed on the strength of a partially reconstructed graph.

## What this phase must produce

1. A classifier assigning every structure way to case 1, 2 or 3, with counts for the Oisans
   extract and the reason for each assignment.
2. Reconstruction for case 1, with a regression test on a real short structure from the frozen
   extract.
3. A verified roadway-elevation source for case 2, or an explicit statement that none is available
   yet and that all long structures therefore sit in case 3.
4. Optimistic/pessimistic bracketing for case 3, and a route-level flag when a result depends on
   one.
5. A rerun of the regional baseline showing, side by side, the distance and termination status of
   each leader before and after — in particular whether the VTC leader's `>= 6291.2 m` becomes a
   `physical_stop` and where.

## Not in scope

The national search. This phase is about whether the graph describes the road, which has to be
settled before the size of the graph becomes the problem.
