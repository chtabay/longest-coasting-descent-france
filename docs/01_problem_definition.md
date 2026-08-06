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

`m dv/dt = m g sin(theta) - Crr m g cos(theta) - 0.5 rho CdA v_rel |v_rel|`

where positive grade angle means downhill in the direction of travel.

The reference implementation must later account for rotating mass or justify neglecting it.

## Stop condition

The numerical simulation stops when one of the following occurs:

- the route ends;
- speed remains below a threshold for a specified dwell time;
- the solver reaches a prohibited or non-traversable edge;
- an operational constraint requires stopping.

Provisional numerical threshold: 0.30 m/s for at least 2 seconds. This is an implementation definition, not a claim that a real bicycle is perfectly immobile.

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
