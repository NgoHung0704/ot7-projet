# Simulation model — issues #11 and #12

Implementation: `docker/airflow/dags/simulation/`. Version: `educational_bands_v1`.

This educational scenario asks: **if this asteroid strikes this city**, what are its immediate fatalities and direct building replacement losses? It is not a NASA city-impact prediction. Impact probability does not multiply the toll. Coefficients below are implementation assumptions, not calibrated fatality or fragility curves.

## Inputs and assumptions

- Read `staging.stg_asteroid`, `staging.stg_city` and `staging.stg_disaster`.
- Diameter in metres, **entry** velocity `v_imp` in km/s; density **2600 kg/m³**, angle **45°**, dry-land target density **2500 kg/m³**, water depth zero.
- Do not infer density from Sentry mass. `energy_mt` is an independent validation reference, not the physics input.
- Simulate every staged asteroid, including small airbursts with zero toll under this model.
- Regional GEM: exposed population = region `occupants`. Country GEM: exposed population = city `population`; country occupants is deliberately NULL.
- Spread exposed population uniformly over a disc centred on the city's coordinates. No area is available in staging, so assume **3000 persons/km²**: `R = sqrt(N/(pi*3000))`. This is a scenario area, not an observed city or GEM-region boundary. It does not recover the real spatial distribution of regional occupants.
- Exposed assets = exposed population × `repl_cost_per_occupant_usd`. Missing/nonfinite/negative required inputs fail the build; zero exposure gives zero toll.

These are implementation choices for a reviewable MVP. Changing them requires a model-version update and rebuild. A spatial exposure grid requires additional geographic data; a complete vulnerability framework exceeds the current staging contract.

## Physics

[ImpactEffect 1.0.0](https://pypi.org/project/ImpactEffect/1.0.0/) implements the [Collins, Melosh & Marcus (2005) Earth Impact Effects Program](https://doi.org/10.1111/j.1945-5100.2005.tb00157.x). Use numeric functions, not its interactive report.

- `cal_vmax` returns `(wind_m_per_second, overpressure_pa)`; convert wind with **×3.6**.
- `cal_themal` returns a mantissa and decimal exponent; reconstruct **J/m²**.
- Surface impacts with residual velocity ≥15 km/s use the fireball model. Airbursts have no surface fireball and no ground-impact seismic magnitude in this implementation. Real airburst thermal effects are omitted.
- Check the fireball horizon before calling the library: its thermal function otherwise calls `acos` outside its domain.
- Restore the removed `numpy.Inf` alias before importing the old library. Keep NumPy **2.5.3**, compatible with the Airflow image's SciPy; downgrading to NumPy 1.x caused a conflict.
- Solve band radii with 32 bisection steps from 1 m to 20,000 km, assuming radially decreasing hazard fields. A threshold still exceeded at the domain limit fails rather than silently truncating the radius.
- Cache physics by diameter and entry speed, independently of city; clear the cache at each DAG build.

Magnitude is the ground-impact source magnitude, not local shaking intensity. Wind is measured at **1 km from ground zero**, as #12 requests. For large objects this is inside the crater/fireball: extreme near-field wind values are formal model extrapolations, unsuitable as literal weather predictions.

## Casualty and building-loss rules

Collins et al. supplies physical quantities and motivates the hazard selection. **All thresholds and fractions below are our educational assumptions**, not coefficients claimed to come from that paper, GEM or NASA. They need team/scientific review before any use beyond the demo.

| Threshold | Fatality fraction | Building loss fraction |
|---|---:|---:|
| Overpressure ≥20 kPa | 0.01 | 0.10 |
| Overpressure ≥50 kPa | 0.10 | 0.50 |
| Overpressure ≥100 kPa | 0.50 | 1.00 |
| Overpressure ≥200 kPa | 0.95 | 1.00 |
| Thermal ≥100 kJ/m² | 0.01 | 0.05 |
| Thermal ≥300 kJ/m² | 0.10 | 0.20 |
| Thermal ≥1000 kJ/m² | 0.50 | 0.70 |

Partition the disc at every pressure/thermal radius. Annulus `[r1,r2]` contains `N*(r2²-r1²)/R²` people. For each hazard use the strongest applicable band. Fatality fraction = `1-(1-f_pressure)*(1-f_thermal)`, an explicit independence approximation. Building loss fraction = `max(loss_pressure,loss_thermal)` to avoid destroying an asset twice.

Sum annuli, round deaths to nearest integer and cap at `floor(N)`. Floor USD losses and cap at exposed asset value. Never derive economic loss from the number of deaths.

No tsunami, climate effects, evacuation, indirect mortality, time-of-day exposure or calibrated building-specific fragility is modelled. Direct replacement loss is narrower than EM-DAT economic damage; immediate fatalities also differ from EM-DAT total deaths.

## Shared intensity classes

Shaking: `<4`, `[4,5)`, …, `[8,9)`, `9+`. Stored labels are `4-5`, etc. Missing/nonfinite values are `Not applicable`; negative seismic magnitudes are valid and belong to `<4`.

Wind lower limits follow [NOAA/NHC Saffir–Simpson](https://www.nhc.noaa.gov/aboutsshws.php): **119,154,178,209,252 km/h**. Use continuous half-open intervals without fractional-speed gaps. Labels `119-154 km/h`, etc. mean lower inclusive, upper exclusive. Below 119 is below hurricane strength; missing/nonfinite/negative wind is `Not applicable`.

This is a numerical comparison only: Saffir–Simpson describes sustained hurricane winds, while an impact blast is transient. Matching categories do not imply equivalent damage mechanisms.

| EM-DAT scale | Interpretation |
|---|---|
| `Moment Magnitude`, `Richter` | seismic magnitude and shaking class |
| `Kph` | maximum wind and wind class |
| Anything else, including NULL | NULL measurements; `Not applicable` classes |

## Output and warehouse handoff

The DAG runs after **any** `stg_asteroid`, `stg_city` or `stg_disaster` publication. OR is intentional: unchanged staging tasks skip and do not republish. On first startup an early event may produce an empty intermediate build; later input publications rebuild it.

One transaction replaces `simulation.event_toll` (natural key `des,geonameid`) and `simulation.historical_intensity` (key `dis_no`). Toll rows include origin `Simulated`, impact date, deaths, damage, physical measurements/classes, exposed population, assumed disc radius, model version and build timestamp.

Lock staging tables in SHARE mode **before** taking the repeatable-read snapshot, because staging uses non-MVCC-safe `TRUNCATE`. Staging writers may wait during simulation. One active DAG run and an advisory transaction lock serialize builds. Empty successful inputs clear old outputs; errors roll back the entire output replacement. Success publishes `simulation_results`.

**#10 remains separate.** Its loader must resolve event/location/date surrogate keys, map `peak_wind_kmh` to `dim_event.max_wind_kmh`, load historical classes, and load `fact_event_toll` after dimensions. Origin is in `dim_event` in the current SQL. This branch leaves surrogate-key and SCD decisions to #10.

`sql/simulation_q5.sql` demonstrates matching directly on natural-keyed outputs, excluding `Not applicable`. A DB fixture verifies a matching earthquake. The real EM-DAT demo and final star-schema Q5 still require #10 and a loaded export.

## Reference cases

From the repository root, PowerShell:

```powershell
$env:PYTHONPATH = 'docker/airflow/dags'
.venv/Scripts/python -m simulation.reference --benchmark
```

Same synthetic city: 1,000,000 exposed people, radius 10.30065 km, replacement value $50,000/person; entry speed 20 km/s. Measured 2026-11-25:

| Diameter | Incoming Mt | Airburst | Magnitude | Wind at 1 km (km/h) | Deaths | Damage USD |
|---|---:|---:|---:|---:|---:|---:|
| 20 m | 0.520595 | 22.642 km | N/A | 17.539 | 0 | 0 |
| 140 m | 178.564202 | ground | 5.82124 | 14,277.156 | 815,775 | 50,000,000,000 |
| 1 km | 65,074.417617 | ground | 7.81695 | 162,782.294 | 975,000 | 50,000,000,000 |

These verify reproducibility, not casualty calibration. Zero toll for 20 m means it misses the selected bands, not that it is harmless. The near-field wind caveat above applies.

### Independent energy check

`tests/fixtures/sentry_reference.json` saves three NASA/JPL responses retrieved 2026-11-25, near those diameters. Tests use them offline. See the [Sentry API field definitions](https://ssd-api.jpl.nasa.gov/doc/sentry.html).

| Designation | Diameter m | Entry km/s | Sentry Mt | Computed Mt | Ratio |
|---|---:|---:|---:|---:|---:|
| 2025 DB15 | 20.000 | 12.85 | 0.1968 | 0.2149 | 1.0920 |
| 2005 NX55 | 140.364 | 27.19 | 334.7 | 332.6071 | 0.9937 |
| 2010 ER12 | 1013.104 | 26.37 | 120,000 | 117,633.9187 | 0.9803 |

All are within a factor of two. This verifies incoming energy and units; it does not independently validate atmospheric or near-field physics against Purdue.

### Timing

2200 distinct synthetic asteroid profiles ×100 city populations = **220,000 pairs**, **30.501 seconds** on this Windows/Python 3.12/NumPy 2 machine; cache 2200 misses and 217,800 hits. Target: **under 5 minutes for computation** here, an implementation target rather than a team-agreed SLA. It excludes PostgreSQL I/O/ingestion. Task timeout: 30 minutes. A full real-data DAG benchmark is still required before declaring #11 done.

## Verification

Tests cover every class boundary/scale, band areas/overlap, population caps including fractional occupants, invalid/zero exposure, probability semantics, airburst, horizon and saved Sentry energy. DB tests exercise both drivers, reruns, empty replacement, rollback and Q5 matching. DAG tests run in Airflow/Linux; Windows skips them without Airflow.

Disposable database:

```powershell
docker compose -f tests/docker-compose.yml -p ot7-simulation-tests up -d --wait
$env:WAREHOUSE_TEST_DSN = 'postgresql://test:test@127.0.0.1:55433/warehouse_test?connect_timeout=5'
.venv/Scripts/python -m pytest
docker compose -f tests/docker-compose.yml -p ot7-simulation-tests down
```

This tmpfs database uses port 55433, separate from the real warehouse. Never point tests at data to preserve: the existing fixture resets staging.
