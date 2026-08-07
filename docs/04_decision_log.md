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
