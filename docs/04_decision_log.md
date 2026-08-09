# Decision log

## D-001 — Primary metric

**Decision:** maximize elapsed continuous coasting time, not distance or elevation loss.

**Reason:** this matches the stated question and creates a non-trivial optimization problem.

## D-002 — Small rises are allowed

**Decision:** a route need not be monotonically descending. Short rises are allowed if crossed by inertia without pedalling.

**Reason:** otherwise the model would incorrectly discard physically continuous coasting runs.

## D-003 — Separate theoretical and operational rankings

**Decision:** publish both.

**Reason:** a mathematically optimal route may be unusable without braking or stopping.

## D-004 — Metropolitan France first

**Decision:** mainland France plus Corsica for the main study.

**Reason:** coherent data-processing scope; overseas territories can be a separate analysis.

## D-005 — No national claim before source audit

**Decision:** do not name a winner from intuition or a list of famous passes.

**Reason:** the objective may favor obscure gentle routes and is highly sensitive to network and elevation data.

## D-006 — Signed grade ratios

**Decision:** all public profile grades are dimensionless rise/run ratios: negative downhill,
zero flat and positive uphill. Explicit helpers convert percent to ratio and ratio to radians.

**Reason:** parameter naming and one convention prevent silent percent, angle and sign errors.

## D-007 — Equivalent rotational mass

**Decision:** use a provisional 1.5 kg equivalent rotational mass by default, with zero as an
explicit off switch. Add it only to effective inertial mass.

**Reason:** rotating components store kinetic energy but do not add rider/bicycle weight to
gravity or rolling force. The option enables transparent sensitivity analysis.

## D-008 — Event-split integration

**Decision:** retain inspectable constant-acceleration time integration but split every nominal
step at profile boundaries, route end, zero speed and stop-dwell expiry.

**Reason:** no segment may borrow its old grade beyond a boundary, and elapsed coasting time
must not receive a whole time step for a fractional arrival or stop event.

## D-009 — Elevation resource chosen by measurement, not by name

**Decision:** `ign_rge_alti_par_territoires` is the primary terrain source and `ign_rge_alti_wld`
is retained only as a same-producer control.

**Reason:** measured on 2026-08-07, a 0.5 m transect through `ign_rge_alti_wld` repeats each
value about seven times, so that resource answers on an approximately 3.5 m effective grid
despite being the one whose identifier reads as the RGE ALTI product. The same transect through
`ign_rge_alti_par_territoires` repeats each value twice, matching the announced 1 m grid. A
resource identifier is not evidence of resolution; the transect is.

## D-010 — A contract violation is published, never clipped

**Decision:** a sampled profile whose grades exceed the simulator's validity bound is reported
with its violation count and left unsimulated. It is never clipped, rescaled or dropped.

**Reason:** clipping would silently manufacture an admissible profile out of an artefact and
would put a coasting time on a road the model cannot describe. The count is itself a result:
11 of the 150 segments of the frozen 1163 m hairpin path exceed the bound at 10 m sampling.

## D-011 — Conditioning is a declared scenario published beside the raw profile

**Decision:** a centred moving average of elevation against chainage, window 25 m, is computed
for every profile and published next to the unmodified one, never instead of it.

**Reason:** sampling a terrain raster finer than its cell size produces alternating flat steps
and cell-height jumps that inflate 3D length and cumulative ascent without adding information.
The scenario is not a correction and carries no guarantee: on a hairpin it lowers the violation
count from 11 to 3 while raising the maximum grade from 0.753 to 0.838, because averaging along
chainage pulls together two points sitting on different levels of the same bend.

## D-012 — Requested spacing is reported as an upper bound

**Decision:** every profile record publishes realised mean, minimum and maximum spacing next to
the requested value.

**Reason:** densification subdivides source chords but never removes a source vertex. Requesting
25 m on OSM way 708124926 realises a 3.33 m mean spacing because the mapped geometry is already
finer, so a comparison that quoted only the requested spacing would describe four experiments
that are in part the same one.

## D-013 — The validation sample is stratified and deliberately includes the hard case

**Decision:** one way per highway class, plus the way carrying the most hairpins.

**Reason:** taking the first ways in Overpass order returned six consecutive identifiers from a
single village import, all benign, which validated nothing. Highway class and hairpin count are
properties of the road register and of geometry, not of coasting time, so neither can bias the
ranking the study will eventually produce.

## D-014 — Legal cyclability is not usability

**Decision:** grade every way into `paved_reference`, `reference_vtc`, `extended_vtc`,
`excluded` or `review` from highway, surface, smoothness, tracktype, mtb:scale, bicycle,
access and vehicle. Rank on `paved_reference` first, then `reference_vtc`.

**Reason:** Phase 1B admitted OSM way 708124926 — a `highway=cycleway` with `surface=dirt`,
`mtb:type=downhill` and `mtb:scale=2` — alongside a departmental road, because both are legally
cyclable. A downhill mountain-bike trail is not a route for a standard hybrid bicycle, and no
amount of physics downstream repairs an admissibility model that cannot tell them apart.

## D-015 — A missing surface tag is assumed sealed on a classified road, and charged for it

**Decision:** a mainland `primary`/`secondary`/`tertiary`/`unclassified`/`residential` way with
no `surface` tag enters `reference_vtc` with `surface_is_assumed` set and the degraded-asphalt
rolling-resistance scenario, never `paved_reference`.

**Reason:** 2 900 of 4 514 ways carry no surface tag. Refusing all of them would gut the study;
accepting them as good asphalt would grant a quality nobody recorded. Paying for the assumption
in the physics keeps the ranking honest and keeps `paved_reference` a genuinely evidence-based
subset. The conservative doctrine is not relaxed for `track`, which is why 557.6 km stays in
`review`.

## D-016 — Rolling resistance is a surface scenario, not a constant

**Decision:** five surface classes, each with a central coefficient and an explicit low/high
interval that the sensitivity analysis sweeps. Two significant figures at most.

**Reason:** rolling resistance dominates the end of a coast and varies by roughly an order of
magnitude between asphalt and dirt: on a 3 % descent, asphalt completes a 2 km run in 261 s
while dirt stops after 715 m. No coast-down test was performed for this study, so the unpaved
values are bounded from the published range rather than measured, and their intervals say so.

## D-017 — The production elevation method is chosen by measurement

**Decision:** `raw_25m`, selected over `raw_10m`, `adaptive_geometry`, `robust_median_local` and
`net_dz_constrained` on 400 real edges.

**Reason:** applying the declared criteria in order eliminates the robust filter on elevation
conservation (0.425 m median loss) and the adaptive method on noise (1 572 implausible segments
against 257). Temporal stability does not discriminate — every method's elapsed time moves by
about 0.04 % between a 0.01 s and a 0.10 s step. `raw_25m` wins on implausible segments, on
hairpin grades and on simulable share, at an exact elevation budget.

## D-018 — Curvature is read from the fine geometry, never from the production profile

**Decision:** bends are measured on the 5 m base samples; the 25 m profile feeds the simulator
only.

**Reason:** subsampling to a uniform 25 m grid drops precisely the sharp-bend vertices the
sampler retained. Measured on the production profile the paved graph showed 3 916 bends; measured
on the base geometry it shows 44 994, of which 2 717 are under 15 m radius. The turn constraint
was almost blind, and the ranking it produced was wrong.

## D-019 — A route ends where the rider would have to brake

**Decision:** the admissible time of a candidate is the time at the first bend whose required
lateral acceleration exceeds the scenario limit, not the time to the bottom.

**Reason:** the reference event forbids braking, so a run that demands it has ended. Discarding
such routes entirely would lose the information; extending them to the bottom would report a time
the rider cannot achieve.

## D-020 — Each way piece is traversed at most once per route

**Decision:** the cycle rule bans re-entering a way piece in either direction within one route.

**Reason:** without it a rider could shuttle back and forth across a dip and accumulate unbounded
time, so the search would measure its own patience rather than the terrain. The rule is stricter
than "no repeated directed edge" because both directions of a piece are the same shuttle.

## D-021 — Phase 2 does not produce a usable ranking, and says so

**Decision:** publish the regional Top 20 as a validation instrument and state that the objective
is degenerate, rather than presenting the leaders as the best descents in the Oisans.

**Reason:** ranked by elapsed time, the leading `paved_reference` candidate is 734 m long and
drops 1.8 m at a mean of 6.3 km/h. Both the low and the high rolling-resistance bounds *reduce*
its time, by 18 % and 51 %: it is optimal only at the central coefficient, and only because it is
near equilibrium there. Maximising elapsed time rewards creeping, not descending. Phase 3 needs a
discriminating objective chosen deliberately.

## D-022 — The objective is distance, and it carries no side conditions

**Decision:** the primary objective is `max distance_travelled_m` until the definitive physical
stop. Elapsed time, moving time, mean speed and elevation become secondary metrics. No minimum
grade, minimum descent, minimum mean speed, descent share or duration is imposed.

**Reason:** Phase 2 maximised elapsed time and produced a degenerate optimum — 734 m in 420 s at
6.3 km/h — because a nearly balanced bicycle creeps for a long while. Distance does not reward
creeping: crawling adds seconds, not metres. Adding side conditions to repair a badly chosen
objective would hide the problem rather than fix it, so the objective is changed instead and left
unconditioned. A nearly level road may still win, and if it does it will be because it genuinely
rolls further.

## D-023 — The run ends at the definitive physical stop, not at a threshold

**Decision:** the run ends when speed reaches zero and no spontaneous forward acceleration can
restart the bicycle. The bicycle never rolls backwards.

**Reason:** the 0.30 m/s / 2 s dwell rule was a numerical convenience, and under a time objective
it set the answer: a route hovering just above the threshold accumulated time indefinitely. At
rest the aerodynamic term vanishes, so the restart criterion is exactly `a(0) > 0`, which for zero
wind reduces to `grade < -Crr`. The test is evaluated through the acceleration function rather
than the algebraic form so that a non-zero along-route wind, which does exert force at rest, is
handled by the same rule.

## D-024 — Only a zero on a segment boundary can be followed by a restart

**Decision:** a zero reached inside a segment terminates the run; a zero reached exactly on a
boundary is decided by the segment about to be entered.

**Reason:** `a(v)` is non-increasing in speed, because drag only ever opposes motion, so `a(0)` is
the largest acceleration available on a segment. A segment that could restart the bicycle could
never have stopped it: the speed would have decayed towards a positive equilibrium instead of
reaching zero. The boundary case is therefore the only one that needs deciding, and it is decided
by the following segment, which is what `segment_index_at_distance` already returns for a distance
sitting exactly on a boundary.

## D-025 — Braking is a constraint, never a choice

**Decision:** the optimiser never selects a braking amount. A maximum-speed envelope is built from
the bend radii of the 5 m geometry, the bicycle follows its natural dynamics wherever they respect
it, and exactly enough energy is removed where they would not. Phase 2's rule — end the route at
the first bend requiring braking — is abandoned.

**Reason:** ending a route at the first bend measured the geometry's worst point rather than the
road's length, and it discarded descents a rider would simply have braked through. Two
representations are computed: energy removed at the constraint, and anticipated braking at a
declared 1.5 m/s². They are equivalent for distance and the equivalence is structural, not
numerical: both leave the constraint at the same place and the same speed, so the state governing
everything downstream is identical. Braking *energy* differs between them, but that figure only
records how much speed had to be removed and is not a discriminator.

## D-026 — Bends are measured across the joined route, not edge by edge

**Decision:** the authoritative evaluation of a finished route computes bend radii over the
concatenated 5 m geometry of all its edges.

**Reason:** the radius estimator needs a chord of geometry either side of a point, so per-edge
evaluation is blind within 15 m of every edge end. Ways are cut at 974 shared interior nodes, so
that blind band sits on almost every junction — exactly where a bicycle turns. The depth-first
walk still uses the cheaper per-edge envelope and is therefore mildly optimistic near junctions;
that is acceptable and declared, because the envelope moves distance by well under a percent.

## D-027 — The maximum-distance objective has its own degeneracy, and it is disclosed

**Decision:** publish the fact that a grade sitting just beyond `-Crr` gives a positive equilibrium
speed, so the bicycle never stops and the distance is bounded by the extent of the network rather
than by energy. Runs that hit the integrator's time cap are reported as lower bounds, not as
stops.

**Reason:** the answer is physically correct — on such a road the bicycle really does roll on —
but it is a different kind of answer from "this descent is long", and a reader must be able to
tell which one the ranking is reporting.
