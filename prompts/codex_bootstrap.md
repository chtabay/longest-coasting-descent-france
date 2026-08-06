# First Codex mission

You are working in the repository `longest-coasting-descent-france`.

The project seeks a reproducible, high-reference answer to this question:

> Which admissible route in metropolitan France including Corsica maximizes continuous coasting time for a 75 kg rider on a standard hybrid bicycle, starting at 15 km/h and applying no pedalling power?

Read all files in `docs/` and the current implementation before modifying anything.

## Mission

Complete Phase 0 only. Do not begin national data acquisition yet.

1. Audit the mathematical model and sign conventions in `src/coastdown/physics.py`.
2. Improve numerical reliability near zero speed and on transitions between positive and negative grades.
3. Add rotating-wheel inertia through a documented equivalent-mass option, while keeping a switch that disables it.
4. Add unit-aware validation at API boundaries or another robust strategy preventing silent km/h, m/s, percent-grade and angle confusion.
5. Expand tests to cover:
   - flat road deceleration;
   - constant downhill terminal-speed behavior;
   - a short uphill crossed by inertia;
   - an uphill that causes stopping;
   - sensitivity to mass, CdA and Crr;
   - deterministic repeatability;
   - no negative distance and no NaN/Inf output.
6. Add one benchmark/example that compares several synthetic profiles and writes plots to `outputs/`.
7. Update documentation only where implementation decisions require it.
8. Run the full test suite and report exact commands and results.

## Constraints

- Keep physics, route representation and plotting separated.
- Prefer simple, inspectable numerical methods over opaque abstractions.
- Every parameter must have a unit in its name, type, docstring or validation layer.
- Do not claim that provisional constants are authoritative.
- Do not add web-sourced values without recording the source and retrieval date.
- Do not introduce national geodata dependencies in Phase 0.
- Preserve a clean public API suitable for later graph-search integration.

## Definition of done

Phase 0 is complete when:

- tests pass;
- synthetic outputs are generated reproducibly;
- numerical stop behavior is stable;
- physical assumptions and unresolved questions are explicit;
- the code can simulate any one-dimensional road profile supplied as distance and grade samples.

Finish by providing:

- a concise change summary;
- test output;
- unresolved modeling risks;
- the next recommended commit, without implementing Phase 1.
