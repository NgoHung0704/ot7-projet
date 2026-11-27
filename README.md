# Asteroid impacts vs. historical disasters

OT7 Data Engineering, INSA Lyon

A web game where the player guesses which is deadlier: a real historical disaster (EM-DAT) or the simulated impact of an asteroid from NASA's Sentry risk list on a major city.

# How to run

Everything runs locally with Docker Compose. Run the commands from the repository root.

### 1. Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/), or Docker Engine with Compose 2.20 or later.
- About 8 GB of free disk space for the Docker images, and an internet connection: the pipeline downloads its data.

### 2. Create the configuration files (first time only)

```bash
cp .env.example .env
cp docker/airflow/.env.example docker/airflow/.env
cp docker/mongo/.env.example docker/mongo/.env
cp docker/postgres/.env.example docker/postgres/.env
cp docker/app/.env.example docker/app/.env
```

The example values work as they are on a local machine.

- On Linux, set `AIRFLOW_UID` in `docker/airflow/.env` to the output of `id -u`.
- If you change the warehouse user, password or database in `docker/postgres/.env`, change `AIRFLOW_CONN_POSTGRES_WAREHOUSE` in `docker/airflow/.env` the same way, and the database name `GAME_DB_NAME` in `docker/app/.env`.
- The `.env` files are git-ignored: never commit them.

### 3. Add the EM-DAT export (manual)

EM-DAT requires a free account, so its file cannot be downloaded by the pipeline.

1. Log in on [public.emdat.be](https://public.emdat.be) and download the public table as Excel, **with the historical events (before 2000) included**.
2. Put the `.xlsx` file in `docker/airflow/data/landing/emdat/`. Create the folder if needed.

Never commit this file: the EM-DAT licence forbids redistributing it, and this repository is public. `data/` is git-ignored. Without the file, the pipeline still runs and only skips EM-DAT.

### 4. Start the stack

```bash
docker compose up airflow-init
```

The first time, this builds the Airflow image and takes a few minutes. Wait until `airflow-init` exits with code 0. This step is needed only the first time.

```bash
docker compose up -d
```

After a change to `docker/airflow/Dockerfile` or `docker/airflow/requirements.txt`, add `--build` to rebuild the image. Check that everything is up:

```bash
docker compose ps
```

All services should be `running`, and `healthy` when they have a health check.

### 5. Run the pipeline

1. Open Airflow on [localhost:8080](http://localhost:8080). The user and password are `_AIRFLOW_WWW_USER_USERNAME` and `_AIRFLOW_WWW_USER_PASSWORD` in `docker/airflow/.env`.
2. New DAGs start paused: switch on **`ingest_raw`**, **`staging`**, **`simulation`** and **`game_views`**.
3. Trigger `ingest_raw` with the ▶ button.
   - The first run on an empty database takes about 30 minutes: it downloads the details of ~2,200 asteroids one at a time, as NASA's API requires.
   - The next runs take less than a minute. `ingest_raw` then runs by itself once a month.
4. `staging` starts by itself each time `ingest_raw` brings new data.
5. `simulation` rebuilds conditional asteroid × city tolls and historical intensity classes after staging changes. Trigger it manually after updating the simulation code.
6. `game_views` runs after `simulation` and publishes the read-only views the game reads.

### 6. Play

Open the game on [localhost:8501](http://localhost:8501) once `game_views` has run. After a change to `docker/app/`, rebuild it with `docker compose up -d --build app`.

### 7. Look at the data

| Data | Where | Login |
|---|---|---|
| Raw data, as downloaded (database `raw`) | mongo-express on [localhost:8081](http://localhost:8081) | `MONGO_EXPRESS_USERNAME` / `MONGO_EXPRESS_PASSWORD` in `docker/mongo/.env` |
| Clean tables (schema `staging`) | pgAdmin on [localhost:5050](http://localhost:5050) | `PGADMIN_DEFAULT_EMAIL` / `PGADMIN_DEFAULT_PASSWORD` in `docker/airflow/.env` |

The first time you open pgAdmin, register the warehouse:

1. *Add New Server*, any name.
2. In the *Connection* tab:
   - host `database`, port `5432`;
   - maintenance database, username and password: `POSTGRES_DB`, `POSTGRES_USER` and `POSTGRES_PASSWORD` from `docker/postgres/.env`.
3. The tables are under *Databases* → your database → *Schemas* → `staging` → *Tables*.

### 8. Stop

```bash
docker compose down
```

The data is kept for the next start.

```bash
docker compose down -v
```

This deletes all the data (raw, warehouse and Airflow history), to start again from scratch.

# Pipeline details

## Overview

```mermaid
flowchart LR
  S[NASA/JPL Sentry API] --> I
  E[EM-DAT Excel export] --> I
  G[GeoNames, GEM exposure] --> I
  I[[ingest_raw, monthly]] --> M[(MongoDB raw)]
  M --> T[[staging]]
  T --> P[(PostgreSQL warehouse, schema staging)]
  P --> S2[[simulation]]
  S2 --> R[(PostgreSQL schema simulation)]
  R --> V[[game_views]]
  V --> GV[(PostgreSQL schema game)]
  GV --> APP[Impact Duel game, Streamlit]
  R -.-> N[star schema loader: to come]
```

## Airflow

**`ingest_raw`** runs once a month. It has one task per source, so a source that fails does not stop the others.

| Task | Fetches | Into MongoDB `raw` |
|---|---|---|
| `sentry` | NASA/JPL Sentry: the asteroid list, the removed objects, and the details of each asteroid (details are fetched again only when an asteroid changed) | `sentry_objects`, `sentry_removed`, `sentry_details` |
| `emdat` | the EM-DAT export from `docker/airflow/data/landing/emdat/` | `emdat_events` |
| `geonames` | GeoNames: cities over 15,000 inhabitants, countries, regions | `geonames_cities`, `geonames_countries`, `geonames_admin1` |
| `gem` | GEM Global Exposure Model: building occupants and value per region | `gem_exposure_adm1` |

- Documents are stored as the source gives them, with a `_meta` field (source, month, URL, version, hash).
- `ingest_catalog` records each complete batch. Readers take the latest complete batch of a collection.
- A source that did not change is skipped: same EM-DAT file, same GEM commit, same GeoNames files.

**`staging`** runs each time `ingest_raw` publishes a new batch. It turns the raw data into clean tables in PostgreSQL, schema `staging`:

| Table | One row per |
|---|---|
| `stg_asteroid` | asteroid of the latest Sentry list: diameter in m, entry speed, energy, impact probability, most probable impact date |
| `stg_asteroid_removed` | asteroid removed from the Sentry list |
| `stg_disaster` | EM-DAT disaster: start date and its precision, deaths, damage in US$. Missing figures stay empty, never 0 |
| `stg_city` | impact city: the 15 most populous of each continent plus capitals over 1 M inhabitants, with their GEM region values |
| `quarantine` | rejected row, with the check that rejected it |

- A task rebuilds its tables only when its raw data changed.
- To rebuild after changing the staging code, trigger `staging` by hand with the configuration `{"force": true}`.

## Simulation

The `simulation` DAG stores one conditional estimate per asteroid × city in `simulation.event_toll`, and EM-DAT intensity classes in `simulation.historical_intensity`. Results include deaths, direct building replacement damage, magnitude and wind at 1 km. These are educational estimates with explicit assumptions, not NASA city-impact predictions. See [the model, reference cases and limitations](docs/simulation-model.md).

Rebuild the Airflow image after this change (`docker compose up -d --build`). To print the reference cases and time 220,000 synthetic pairs:

```powershell
$env:PYTHONPATH = 'docker/airflow/dags'
.venv/Scripts/python -m simulation.reference --benchmark
```

## Game views

The `game_views` DAG runs after `simulation`. It publishes the views the game reads, in schema `game`, and the read-only role `game_reader` that the game logs in with. Its password is `GAME_READER_PASSWORD` in the root `.env`.

| View | One row per |
|---|---|
| `asteroid_scenario` | asteroid still on the Sentry list × impact city: diameter, entry speed, city, population, coordinates, deaths, damage, intensity classes |
| `historical_disaster` | sudden EM-DAT disaster (earthquake, storm, flood, volcanic activity, mass movement, explosion, industrial accident) with a known death toll: deaths, inflation-adjusted damage when known, intensity classes |

The views read the `staging` and `simulation` tables live, so the game always sees the latest build. Run `game_views` again only after changing `docker/airflow/dags/game/views.sql`.

## Game

The `app` service runs **Impact Duel** (Streamlit, `docker/app/`). It logs in as `game_reader` and reads only the `game` views.

- A game has 10 rounds. Each round puts an asteroid striking a city against a historical disaster. The player picks which caused more deaths and which caused more material damage, then reveals the figures.
- One point per correct answer. When EM-DAT has no damage figure, the round asks only about deaths.
- The draw skips ties and pairs where one side is over 1,000 times worse than the other, and never replays an asteroid or a disaster within a game.
- The asteroid causes more deaths in half the rounds. 94% of Sentry scenarios kill no one, so without this rule "Disaster" would almost always be right. A harmless asteroid still appears in a quarter of the rounds.
- Asteroid figures are rounded to two significant figures: they are estimates, not predictions.
- The score lives in the browser session only. Rounds are not stored.

## Star schema

The final dimension/fact loader remains issue #10. [The Q5 example](sql/simulation_q5.sql) compares shared classes directly on simulation outputs while that loader is pending.

## Postgres & mongo

- **MongoDB holds the raw data.** The APIs return documents whose format can change. A schema-less store keeps them exactly as received, so the ingestion stays simple and nothing is lost.
- **PostgreSQL holds the warehouse.** It holds clean, typed tables: the `staging` and `simulation` schemas, the `game` views the game reads, and later the star schema the notebooks query.

## Tests

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements-dev.txt   # Linux / macOS: .venv/bin/pip
.venv/Scripts/python -m pytest
```

The tests that write to PostgreSQL run only when `WAREHOUSE_TEST_DSN` points to a database, for example the stack's warehouse: `postgresql://username:password@localhost:5433/warehouse`. They reset the `staging` schema, so do not point them at data you want to keep. `tests/test_dag.py` runs only where Airflow is installed, for example inside the Airflow image.
