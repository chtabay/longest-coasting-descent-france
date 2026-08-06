# Longest coasting descent in France

Reference study to identify the route in France that maximizes **continuous coasting time** for a 75 kg rider on a standard Decathlon-style hybrid bicycle, starting at 15 km/h.

This repository is designed as a high-reference solution: assumptions, data, algorithms, uncertainty and validation must remain auditable and reproducible.

## Status

Phase 0 initialized:

- research question and acceptance criteria;
- baseline physical model;
- repository architecture;
- staged research plan;
- first Codex mission.

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

## Scientific posture

The final answer must include:

- a central estimate;
- uncertainty intervals or scenario ranges;
- sensitivity analysis;
- reproducible candidate generation;
- evidence that the winner is not an artefact of data or pruning;
- explicit limitations and safety caveats.
