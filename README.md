# Asteroid impacts vs. historical disasters

OT7 Data Engineering, INSA Lyon — Project 1: data architecture and dimensional model.

A web game where the player guesses which is deadlier: a real historical disaster (EM-DAT) or the simulated impact of an asteroid from NASA's Sentry risk list on a major city. The full design is in the report.

# How to run

Always run Compose **from the repository root**. The root `docker-compose.yml` includes
each component's compose file (`airflow/docker-compose.yml`, and later others), so a single
command starts the whole stack.

## Configuration

Each component has its own `.env` holding everything it needs, and the root `.env` only
holds settings genuinely shared across components:

| File | Content |
|---|---|
| `.env` | `COMPOSE_PROJECT_NAME` (and later any cross-component setting) |
| `airflow/.env` | Everything Airflow needs: admin account, JWT secret, `_PIP_ADDITIONAL_REQUIREMENTS`, pgAdmin, and its internal `POSTGRES_*` metadata database |

Both are git-ignored. Create them from the templates:

```bash
cp .env.example .env
cp airflow/.env.example airflow/.env
```

The root compose file lists both files as interpolation sources for the included
component (`env_file: [.env, airflow/.env]`), so the component file can use the
project-level variables without duplicating them. Check what Compose actually
resolves with:

```bash
docker compose config --environment
```

## First run

```bash
docker compose up airflow-init
```

## How to add a Python module in the Airflow container

Add the python module in the `airflow/requirements.txt`

# Details

## Star schema

- `fact_event_toll`: one event at one place, either one historical disaster in one country or one asteroid striking one city. Measures: `deaths`, `damage_usd`.
- `dim_event`: name, origin (Historical or Simulated), disaster type, intensity (magnitude, wind speed and their classes), and the asteroid attributes.
- `dim_location`: city or country of the event.
- `dim_date`: calendar.
| `docker/<service>/Dockerfile` | One Docker image per service, built by CI |
| `.github/workflows/docker-images.yml` | CI: builds and publishes the images |

## Docker images

Every push to `main` rebuilds each `docker/<service>/Dockerfile` and publishes it to GitHub Container Registry:

```
ghcr.io/ngohung0704/ot7-projet/<service>:latest       # last commit on main
ghcr.io/ngohung0704/ot7-projet/<service>:sha-<commit>  # a precise commit
ghcr.io/ngohung0704/ot7-projet/<service>:1.2.3         # a v1.2.3 git tag
```

Pull requests only build the images, to check that they still build. The build context is the repository root, so a Dockerfile can copy any folder (`COPY sql/schema.sql ...`).

**Add an image:** create `docker/<name>/Dockerfile` and push. No workflow change needed. Renaming the folder renames the image.

| Image | Content |
|---|---|
| `app` | Placeholder, to be written |

```bash
docker pull ghcr.io/ngohung0704/ot7-projet/app:latest
```

## Sources

- NASA/JPL Sentry API: https://ssd-api.jpl.nasa.gov/doc/sentry.html
- EM-DAT, CRED / UCLouvain: https://doc.emdat.be/
- ImpactEffect Python module: https://github.com/Daniel-Xing/impact-effects
