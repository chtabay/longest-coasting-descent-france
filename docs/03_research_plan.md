# Research execution plan

This is a technical execution plan, not a teaching plan.

## Phase 0 — Definition and baseline

**Status: complete.** The deterministic simulator, validation, event handling, optional
rotational inertia, regression tests and synthetic benchmark are implemented. Generated
artifacts live in `outputs/`; no national candidate is claimed.

Deliverables:

- formal objective and admissibility rules;
- executable one-dimensional physical simulator;
- synthetic tests proving expected qualitative behavior;
- list of unresolved assumptions.

Exit gate:

- a reviewer can reproduce simulations on artificial slopes;
- units and sign conventions are explicit;
- stop behavior is tested.

Remaining model uncertainties (parameter calibration, bearing losses, surface behavior and
the operational meaning of stopping) are registered for sensitivity analysis rather than
silently treated as resolved.

## Phase 1 — Source reconnaissance

Evaluate candidate sources for:

- routable bicycle network;
- legal access and surfaces;
- elevation;
- bridges and tunnels;
- administrative boundary;
- optional curvature, traffic and speed constraints.

Deliverable: source matrix with license, resolution, coverage, access method, defects and selected combination.

Exit gate: one small French test region can be reconstructed reproducibly.

## Phase 2 — Regional prototype

Choose a mountainous test area and build:

- graph extraction;
- elevation enrichment;
- directed edge profiles;
- candidate route generation;
- simulation and ranking;
- maps and profile plots.

Exit gate: plausible known descents appear near the top and failure cases are explainable.

## Phase 3 — Search algorithm

Develop a national-search strategy that avoids naive enumeration.

Candidate methods to compare:

- downhill-connected components and seed extraction;
- dynamic programming on discretized kinetic-energy state;
- label-setting search with dominance pruning;
- beam search or A* style upper bounds;
- coarse-to-fine regional screening.

Exit gate: benchmark against exhaustive search on small subgraphs and quantify missed-optimum risk.

## Phase 4 — Metropolitan France run

- partition and process the national graph;
- generate top candidates;
- re-run finalists with high-resolution elevation;
- audit bridges, tunnels, geometry and legal access manually and programmatically.

Exit gate: stable top-N list under repeat runs and documented compute budget.

## Phase 5 — Robustness and validation

- sensitivity analysis;
- scenario ranking;
- GPS or field-data comparison where possible;
- error decomposition;
- rank stability assessment.

Exit gate: final winner and challengers remain interpretable under plausible parameter changes, or the report explicitly states that no unique robust winner exists.

## Phase 6 — Final reference package

- reproducible code and environment;
- frozen source metadata;
- final report;
- maps, profiles and tables;
- limitations and safety statement;
- independent code/model review.
