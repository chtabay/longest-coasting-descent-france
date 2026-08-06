# Phase 0 contradictory technical audit

Date: 2026-08-06

## Purpose and scope

This audit challenges commit `cf72151` before any authorization for a national geodata run.
It is deliberately separate from the implementation's original acceptance tests. It reviews
signs and equations, API validation, event ordering, numerical convergence, generated
artifacts and scientific claims. It does not acquire geodata or evaluate a real route.

## Reproduction

```bash
pytest
ruff check .
ruff format --check .
PYTHONPATH=src python examples/synthetic_profiles.py
git diff --check
```

The audit adds independent invariant tests in `tests/test_adversarial_audit.py` for:

- the analytic mechanical-energy solution on a nearly lossless constant slope;
- simultaneous zero speed and segment-boundary events followed by a downhill restart;
- the documented headwind/tailwind sign;
- exact `max_time_s` handling and strictly increasing trace times;
- precedence of route end over a later stop-dwell expiry.

## Findings

### A-001 — No blocking implementation defect reproduced

**Severity:** none observed; confidence limited to the tested model domain.

The independent energy check, colliding-event case, event precedence and wind-sign tests pass.
Existing tests also cover terminal speed, invalid/non-finite inputs, multiple boundaries in one
nominal step, interpolated route end and stop, monotonic distance and time-step refinement.

This is evidence against the specific failure modes tested, not proof of correctness for all
profiles or parameters.

### A-002 — Rotating equivalent mass is uncalibrated

**Severity:** high scientific uncertainty; not a software blocker for source reconnaissance.

The 1.5 kg default is a transparent placeholder. It is neither derived from wheel moments of
inertia nor calibrated against a reference bicycle. It changes the synthetic comparison by
-0.392656 s. A national ranking must not rely on the central value alone: zero and plausible
measured/calculated scenarios are mandatory, and the default should be revisited after a
bicycle specification is frozen.

### A-003 — Stop semantics mix motion and operational tolerance

**Severity:** high for the objective definition.

The reported elapsed time includes time spent below 0.30 m/s, including stationary dwell,
until two seconds expire. That is deterministic and documented, but it is not identical to
physical moving time. Before national ranking, results must expose at least physical-zero
time, threshold-entry time and dwell-qualified termination time, or justify one explicitly as
the optimization metric. Sensitivity to threshold and dwell is required.

### A-004 — Numerical evidence remains synthetic and local

**Severity:** medium.

The integrator is first-order because acceleration is frozen within each substep. The current
comparison differs by 0.095901 s between 0.2 s and 0.025 s, which is acceptable for that one
profile but cannot establish a universal error bound. Regional and national work must use a
declared production step and rerun finalists at finer steps. Sharp grade alternation, near-stop
routes and strong wind scenarios need convergence monitoring.

### A-005 — Real-world resistance model is intentionally incomplete

**Severity:** high scientific uncertainty.

No bearing/freehub losses, speed-dependent rolling resistance, surface-specific behavior,
braking, steering or lateral dynamics are modeled. Constant `Crr`, `CdA` and air density are
scenario assumptions. These omissions prohibit presenting the central synthetic model as a
measured prediction and require sensitivity ranges before a national winner can be claimed.

### A-006 — Segment length and grade provenance must be fixed before ingestion

**Severity:** blocking for elevation ingestion.

The dynamics integrate distance along the route while grade is rise over horizontal run.
Geodata adapters must document whether edge length is horizontal/geodesic, three-dimensional
surface length or polyline length, then convert consistently. Elevation smoothing, duplicate
samples and bridge/tunnel artifacts must be resolved in the regional prototype. The profile
API alone cannot detect a semantically wrong but numerically plausible length/grade pair.

### A-007 — Input-unit guard is not dimensional typing

**Severity:** medium.

Names and conversion helpers make the public convention clear, and the 50% bound catches many
mistakes. It cannot distinguish 0.05 radians from a 0.05 ratio or detect all percent/ratio
confusion. Future ingestion code must call explicit conversion functions at its boundary and
record source units; it must not pass unlabelled numeric arrays directly.

### A-008 — Generated SVG volume is acceptable but not a validation oracle

**Severity:** low.

The committed CSV preserves numeric summaries while SVG traces are downsampled for display.
Charts are useful for review, but regression decisions must use numeric invariants and CSV/test
values rather than pixel or polyline equality.

## Decision

### Phase 0 software gate: pass with reservations

The simulator is sufficiently deterministic, inspectable and tested to support **Phase 1
source reconnaissance** and a small **Phase 2 regional prototype**. No blocking defect was
reproduced within the stated one-dimensional synthetic scope.

### National geodata run: not authorized

The audit does **not** authorize Phase 4 or a national winner claim. Authorization requires:

1. explicit moving-time versus dwell-qualified objective outputs;
2. a sourced/calculated rotating-inertia scenario range;
3. a documented edge-length/elevation/grade construction contract;
4. convergence checks on adversarial regional profiles and finer reruns for finalists;
5. sensitivity scenarios for `Crr`, `CdA`, air density, wind, threshold and dwell;
6. validation of bridge, tunnel, surface and legal-access handling;
7. exhaustive-search comparison on small graphs before national pruning is trusted.

## Residual risk statement

Passing this audit means the Phase 0 engine is fit to help test later pipeline components. It
does not mean its provisional parameters are authoritative, its operational result is safe to
ride, or any national optimum has been identified.
