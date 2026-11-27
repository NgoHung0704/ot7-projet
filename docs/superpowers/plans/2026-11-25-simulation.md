# Simulation implementation plan

**Goal:** Implement the independently deliverable parts of #11 and #12 on the simulation branch, synchronized with main.

**Architecture:** ImpactEffect 1.0.0 supplies atmospheric entry and local physical effects. Concentric exposure bands supply a documented educational casualty and building-loss proxy. A transactional Airflow task publishes natural-keyed simulation results and historical intensity mappings for the warehouse loader of #10.

**Tech stack:** Existing Python/Airflow/PostgreSQL stack, ImpactEffect 1.0.0, NumPy 2.5.3.

**Spec:** GitHub issues #11/#12 and `docs/simulation-model.md` (replace the old discussion draft with the implemented assumptions).

## Constraints and decisions

- Keep the existing star schema unchanged; #10 owns dimension/fact loading. Do not claim #11/#12 closed until their warehouse integration and real-data demo pass.
- Density 2600 kg/m³, entry angle 45°, dry-rock target 2500 kg/m³; use Sentry entry velocity in km/s.
- Simulate every staged asteroid. Radius assumes uniform exposed population at 3000 persons/km²; regional GEM occupants are the exposed population, falling back to city population only for country-level GEM.
- Fixed explicit pressure/thermal bands are educational assumptions, not calibrated scientific fatality curves. Combine survival probabilities; use maximum damage fraction to prevent overlapping losses.
- Cache physics by diameter and entry speed. Measure the 20 m, 140 m and 1 km cases and a 2200 × 100 synthetic workload; target under 5 minutes on this machine, not a team-agreed SLA.
- Bad/nonfinite inputs fail the build; missing exposure is never silently converted to zero. Historical unknown intensity stays not applicable.

## Tasks

- [x] Add boundary tests, then implement shared shaking/wind classes and scale-aware EM-DAT mapping.
- [x] Smoke-test the installed physics package; test energy, airburst, wind units, band overlap, caps and exposure fallbacks before implementing the simulation functions.
- [x] Test transactional persistence, repeat loads, rollback and empty upstream tables; implement a simulation schema and Asset-triggered DAG, plus a warehouse handoff query.
- [x] Run the full suite, real physics reference cases and benchmark; document measured numbers, assumptions, commands and warehouse blockers in the README/model document.

## Execution record

- Merged origin/main into the requested feature branch without conflicts.
- Baseline: 50 passed, 23 skipped without PostgreSQL/Airflow. Corrected the DAG test's import guard to avoid the local `airflow/` namespace falsely implying an installed Airflow runtime.
- Unit/numerical checks: 62 passed, including offline NASA Sentry references. Energy ratios 1.0920, 0.9937 and 0.9803.
- Windows with real PostgreSQL and both drivers: 142 passed, 1 skipped (Airflow).
- Full Airflow/Linux image with real PostgreSQL: 148 passed, including the trigger-regression test.
- Built the production Airflow Dockerfile successfully; `pip check` found no broken requirements.
- Synthetic computation benchmark with NumPy 2: 220,000 pairs in 30.501 seconds, excluding database I/O.
- Review fixed AND-trigger staleness; follow-up review found no additional concrete issues.
- Ruling: preserve NumPy 2 and add the removed Inf alias before importing ImpactEffect, rather than breaking the existing SciPy dependency tree with NumPy 1.
- Ruling: publish natural-keyed simulation tables and Asset now; #10 retains surrogate keys, SCD and final fact loading. Real-data star-query demo/full-DAG performance remain integration acceptance work.

## Review focus

- No deaths beyond the chosen exposed population, including fractional occupants and zero population.
- NULL/NaN/negative intensity and exposure do not become plausible fabricated data.
- Tiny objects and airbursts avoid invalid seismic/thermal library paths.
- An upstream empty source does not leave old simulation results looking current.
- All persistence is atomic and rerunnable, and both PostgreSQL drivers remain supported.
