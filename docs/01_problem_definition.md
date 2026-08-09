# Formal problem definition

## Directed route

Represent an admissible route as an ordered sequence of directed network edges:

`R = (e1, e2, ..., en)`

Each edge contains at least:

- horizontal or geodesic length;
- elevation profile;
- legal bicycle access;
- surface and road class when available;
- geometry for curvature and junction analysis.

## Initial state

- rider mass: 75 kg;
- bicycle and equipment mass: scenario parameter, provisional central value 15 kg;
- initial speed: 15 km/h = 4.1667 m/s;
- initial position: beginning of the selected route;
- pedalling power after start: 0 W.

## Dynamics

For positive motion along the route:

`m_eff dv/dt = -m_real g sin(theta) - Crr m_real g cos(theta) - 0.5 rho CdA v_rel |v_rel|`

where:

- `grade_ratio = rise/run = tan(theta)` in the direction of travel;
- negative `grade_ratio` and `theta` mean downhill;
- `m_real` is rider plus bicycle translational mass;
- `m_eff = m_real + m_rot_eq` includes optional equivalent rotational mass;
- `v_rel = v - v_wind`, with positive wind denoting a tailwind.

The equivalent rotational mass affects inertia only. It is not included in gravity, rolling
resistance or aerodynamic force.

## Stop condition

The run ends at the **definitive physical stop**: the speed reaches zero and no spontaneous
forward acceleration is available to restart the bicycle from rest. At rest the aerodynamic term
vanishes, so the criterion is

`a(0) > 0`  which for zero wind is  `grade_ratio < -Crr`

Because `a(v)` is non-increasing in speed — drag only ever opposes motion — `a(0)` is the largest
acceleration available on a segment. A segment able to restart the bicycle could therefore never
have stopped it, so **a zero reached inside a segment is always definitive** and only a zero
landing exactly on a segment boundary can be followed by a restart, decided by the segment about
to be entered. Speed is clamped at zero: the bicycle never rolls backwards.

The run also ends when the route ends, or when no legally and physically admissible continuation
exists.

A bend does not end a run. Braking is never discretionary and the search never selects an amount;
the bicycle follows its natural dynamics wherever they respect a maximum-speed envelope derived
from bend geometry, and exactly enough energy is removed where they would not.

The Phase 0 dwell rule — 0.30 m/s held for 2 s — remains the frozen reference implementation in
`simulate_profile` and is still used by the Phase 0 and Phase 1 artifacts. It is not the stop
condition of the study, because a route hovering just above the threshold accumulated time
without bound and so the threshold, not the terrain, set the answer.

## Numerical integration

Acceleration is held constant over an inspectable substep and recomputed from its ending
state. Nominal time steps are split at slope-segment boundaries, route end, zero speed and
stop-dwell expiry. The exact constant-acceleration kinematic root locates spatial boundaries;
the remaining nominal time continues on the new grade. This prevents an old grade from being
applied beyond its segment and interpolates route arrival rather than adding a full step.

## Objective function

Primary, and exclusive:

`argmax_R D_coast(R)`   — travelled distance to the definitive physical stop

Elapsed time, moving time, mean speed, elevation loss and maximum speed are secondary metrics.
**No condition is imposed** on mean grade, minimum descent, mean speed, descent share or
duration. A nearly level route may win if it genuinely rolls further.

A route may contain descents, flats and rises, provided the bicycle crosses them on the energy it
already has.

Each physical way piece may be traversed at most once per trip, whichever direction. This is part
of the definition of a trip, not a search heuristic: without it a rider could shuttle across a dip
and accumulate unbounded distance, and the measurement would describe the search rather than the
terrain. Genuinely distinct crossings of a sector by different physical ways remain available.

## Important consequence

The solution is not necessarily:

- the road with the greatest elevation loss;
- the longest continuously descending road;
- the route with the lowest average slope;
- the fastest descent;
- the route that rolls for the longest time.

Phase 2 measured the last of these directly: under an elapsed-time objective the leading Oisans
candidate was 734 m long, dropped 1.8 m and averaged 6.3 km/h, because a nearly balanced bicycle
creeps for a long while. Under distance the same network yields a 5.3 km run over a 692 m drop.

Distance has a degeneracy of its own and it is disclosed rather than suppressed: a grade sitting
just beyond `-Crr` gives a positive equilibrium speed, so the bicycle never stops and the answer
is bounded by the extent of the network rather than by energy. In the Oisans paved network that
band covers 3.7 km of 349 km, or 1.1 %.
