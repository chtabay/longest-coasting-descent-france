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

The numerical simulation stops when one of the following occurs:

- the route ends;
- speed remains below a threshold for a specified dwell time;
- the solver reaches a prohibited or non-traversable edge;
- an operational constraint requires stopping.

Provisional numerical threshold: 0.30 m/s for at least 2 seconds. This is an implementation definition, not a claim that a real bicycle is perfectly immobile.

Threshold crossings and dwell expiry are interpolated within a nominal time step. Speed is
clamped at zero, so rolling resistance cannot reverse the bicycle. A positive net force on a
descent or in a tailwind may accelerate it again before the dwell expires.

Every result retains separate clocks: total elapsed time; time with speed above the numerical
zero tolerance (`1e-12 m/s`); stationary time; first entry at or below the operational speed
threshold; first physical zero-speed event; and dwell-qualified stop time. Optional event times
are `None` when absent. A transient zero followed by downhill restart is preserved rather than
being mislabeled as a qualified stop. No national objective metric is selected yet.

## Numerical integration

Acceleration is held constant over an inspectable substep and recomputed from its ending
state. Nominal time steps are split at slope-segment boundaries, route end, zero speed and
stop-dwell expiry. The exact constant-acceleration kinematic root locates spatial boundaries;
the remaining nominal time continues on the new grade. This prevents an old grade from being
applied beyond its segment and interpolates route arrival rather than adding a full step.

## Objective function

Primary:

`argmax_R T_coast(R)`

A route may contain short flat or uphill sections if kinetic energy allows them to be crossed without pedalling and without triggering the stop condition.

## Important consequence

The solution is not necessarily:

- the road with the greatest elevation loss;
- the longest continuously descending road;
- the route with the lowest average slope;
- the fastest descent.

A long, gentle route with short momentum-crossable rises may dominate a steep mountain descent in elapsed time.
