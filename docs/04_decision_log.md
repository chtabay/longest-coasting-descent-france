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
