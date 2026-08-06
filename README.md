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

No national winner is claimed yet.

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
- `prompts/codex_bootstrap.md`: first instruction to give Codex
- `src/coastdown/physics.py`: baseline coasting simulator
- `tests/`: executable checks

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
