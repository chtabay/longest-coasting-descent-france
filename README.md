# Longest coasting descent in France

Reference study to identify the route in France that maximizes **continuous coasting time** for a 75 kg rider on a standard Decathlon-style hybrid bicycle, starting at 15 km/h.

This repository is designed as a high-reference solution: assumptions, data, algorithms, uncertainty and validation must remain auditable and reproducible.

## Status

Phase 0 complete:

- research question and acceptance criteria;
- event-split one-dimensional physical model;
- explicit SI-unit API and signed grade-ratio convention;
- optional rotating-inertia equivalent mass;
- validation and synthetic regression suite;
- reproducible CSV, Markdown and SVG benchmark outputs.

Phase 1A complete: typed geometry/elevation contract, provenance types, structure rejection and
a deterministic offline fixture reconstruction.

Phase 1B complete, on real data: the Oisans road graph is extracted from OpenStreetMap through
Overpass and profiled against IGN RGE ALTI through the Géoplateforme altimetry API. Outputs,
provenance, checksums and the full HTTP transaction log are under `outputs/phase1/live/`; the
method and the measured service behaviour are in `docs/10_phase1b_live_reconstruction.md`.

```bash
PYTHONPATH=src python scripts/phase1b_live_oisans.py
```

The offline suite never touches the network: `tests/conftest.py` refuses every outbound socket,
and the reconstruction is exercised against verbatim frozen extracts of real responses.

Phase 2 complete: a routable regional Oisans graph with bicycle-usability classes,
surface-dependent rolling resistance, a measured choice of elevation-profile method, a
lateral-acceleration constraint on bends, an exhaustive coasting search validated against brute
force, and an experimental regional ranking with its sensitivity. See
`outputs/phase2/phase2_report.md`.

```bash
PYTHONPATH=src python scripts/phase2_acquire_elevations.py   # network, resumable
PYTHONPATH=src python scripts/phase2_profile_method_study.py # offline
PYTHONPATH=src python scripts/phase2_regional_search.py      # offline
PYTHONPATH=src python scripts/phase2_independent_controls.py # network
```

**Phase 2's main result is negative.** Ranked by elapsed coasting time, the leading candidate is
734 m long and drops 1.8 m: maximising time rewards near-equilibrium creeping rather than
descending, and the order is unstable under rolling resistance. The ranking is a validation
instrument, not a list of the best descents.

No regional or national winner is claimed.

## Core definition, provisional

A candidate is a directed, legally cyclable route on the French road/path network. The bicycle starts at 15 km/h and the rider does not pedal. The simulated run ends at the earliest of:

1. speed below the operational stop threshold;
2. end of the admissible route;
3. a segment requiring a maneuver incompatible with continuous coasting;
4. a safety or legality constraint defined by the selected scenario.

The primary objective is elapsed coasting time. Distance, elevation loss and maximum speed are secondary outputs.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
pytest
python examples/synthetic_profiles.py
```

From a source checkout that has not been installed, the equivalent benchmark command is:

```bash
PYTHONPATH=src python examples/synthetic_profiles.py
```

The benchmark overwrites the reproducible Phase 0 artifacts in `outputs/`. It requires no
geodata and makes no claim about a real route.

## Repository map

- `docs/00_scope.md`: scope and non-goals
- `docs/01_problem_definition.md`: formal problem statement
- `docs/02_assumptions.md`: physical and operational assumptions
- `docs/03_research_plan.md`: execution phases and gates
- `docs/04_decision_log.md`: decisions to keep auditable
- `docs/05_data_sources_to_evaluate.md`: source-evaluation checklist
- `docs/06_phase0_adversarial_audit.md`: contradictory audit and gated Phase 0 verdict
- `docs/07_geometry_elevation_contract.md`: normative geometry/elevation contract
- `docs/08_source_matrix.md`: source matrix and the endpoints actually exercised
- `docs/10_phase1b_live_reconstruction.md`: live reconstruction method and measured service behaviour
- `prompts/codex_bootstrap.md`: first instruction to give Codex
- `src/coastdown/physics.py`: baseline coasting simulator
- `src/coastdown/geography.py`: typed geometry/elevation contract
- `src/coastdown/live_oisans.py`: deterministic reconstruction helpers, no network
- `scripts/phase1b_live_oisans.py`: live acquisition and publication
- `tests/`: executable checks, network refused

## Attribution

Road geometry and tags: © OpenStreetMap contributors, ODbL 1.0.
Elevations: © IGN — RGE ALTI® via Géoplateforme, Licence Ouverte / Open Licence (Etalab) 2.0.

## Phase 0 model

The public grade input is always a dimensionless rise/run ratio: negative downhill, zero
flat and positive uphill. Thus `-0.05` means a 5% descent. Explicit conversion helpers are
available for percent grades and angles.

Gravity, rolling resistance and aerodynamic drag are calculated from the real translating
mass. Their net force is divided by the effective inertial mass, which additionally contains
the optional rotating equivalent mass. The default 1.5 kg is provisional; pass
`rotating_equivalent_mass_kg=0` to disable it.

The deterministic solver uses constant-acceleration substeps within each nominal time step.
It splits substeps at every segment boundary, route end, zero-speed point and stop event. A
run stops when speed remains at or below 0.30 m/s for two seconds by default. Synthetic
time-step comparisons quantify the remaining first-order integration error.

## Scientific posture

The final answer must include:

- a central estimate;
- uncertainty intervals or scenario ranges;
- sensitivity analysis;
- reproducible candidate generation;
- evidence that the winner is not an artefact of data or pruning;
- explicit limitations and safety caveats.
