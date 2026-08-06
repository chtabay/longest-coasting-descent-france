# Assumptions register

All values below are provisional until sourced, measured or calibrated.

## Central physical scenario

| Parameter | Provisional value | Treatment |
|---|---:|---|
| Rider mass | 75 kg | fixed by question |
| Bicycle + equipment | 15 kg | sensitivity range required |
| Total mass | 90 kg | derived |
| Initial speed | 4.1667 m/s | fixed by question |
| Rolling resistance Crr | 0.006 | scenario parameter |
| Aerodynamic CdA | 0.55 m² | scenario parameter |
| Air density rho | 1.225 kg/m³ | environmental scenario |
| Wind along route | 0 m/s | central scenario |
| Drivetrain losses | none during freewheel | verify bearing/freehub treatment |
| Rotational equivalent mass | 1.5 kg | provisional; set to 0 kg to disable |

The real translational mass is 90 kg in the central scenario. The effective inertial mass is
91.5 kg with the default rotating equivalent mass. Only the latter is used as the denominator
of acceleration; gravity and rolling resistance continue to use the real 90 kg mass. The
1.5 kg value is a transparent scenario placeholder, not a measured or authoritative constant.

## Rider posture

Central scenario: upright hybrid-bike posture, hands on flat bar. A more tucked posture must be included in sensitivity analysis because aerodynamic drag can change the ranking.

## Surface

Central scenario: ordinary paved road in usable condition. Surface-specific rolling resistance should be incorporated when source quality permits.

## Weather

The main national ranking should use standardized neutral weather, not historical weather at one instant. Wind scenarios may be added separately.

## Braking

Two models:

- theoretical: no braking force;
- operational: speed is constrained or route edges are penalized according to curvature, junctions and legal/safety constraints.

## Elevation

Elevation must be sampled from a documented digital elevation model or authoritative road-altitude source. Bridges, tunnels and viaducts require special handling because terrain elevation can be wrong for the carriageway.

## Uncertainty obligations

At minimum, vary:

- bicycle mass;
- Crr;
- CdA;
- air density;
- elevation smoothing;
- stop threshold;
- optional headwind/tailwind scenarios.

## Numerical limitations

- Acceleration is constant only within each event-split substep; aerodynamic acceleration is
  therefore first-order in time and must be checked by time-step refinement.
- Grade is piecewise constant. No suspension, bearing/freehub loss, steering, braking,
  drivetrain motion, tire deformation dynamics or lateral dynamics is modeled.
- The 50% grade-ratio input bound is a guard against obvious input errors, not proof that a
  caller supplied ratios rather than percent or angle values.
- The operational 0.30 m/s threshold and two-second dwell are study definitions requiring
  sensitivity analysis, not a universal physical definition of stopping.
