# Overview

This repo is a data engineering project. 

## Stack

- Docker
- Airflow for the orchestration
- MongoDB for the ingestion
- Postgres for the warehouse

# Rules

- do not setup the environment in a non reproducible way (for example execute PSQL commands that create databases), because the environment should be entirely defined by the docker config
- for commit messages use the caveman-commit skill
- after working on something, update the documentation: `README.md` (for the user), or `.agents/AGENTS.md` for repeatable how-to (section below)

# Code style

## Simplicity

- Write only what the task needs. No speculative abstraction, no unused parameters, no config for a single caller.
- Never comment code: a commented code should be deleted.
- One function, one job. If you need "and" to describe it, split it.
- No premature helpers. Duplicate twice before abstracting.

## Naming

- Names describe intent, not type or shape. `pending_ingestion_batches` beats `data` or `lst`.
- Long descriptive names are fine and expected.
- No invented abbreviations. Standard acronyms only (DB, API, HTTP, URL).
- Booleans read as assertions: `is_retryable`, `has_missing_columns`.

## Comments

- Every important file starts with a header comment explaining WHY the file exists, not HOW it works. The code already says how. Only a few sentences long.
- Comments inside code are the exception, not the default. Write one only for:
  - legal or license headers,
  - non-obvious intent (why this approach, not what it does),
  - warnings about consequences (data loss, ordering, external side effects).
- Never restate the code.
- Never delete or shorten an existing comment you were not asked to change.
- Stale comment is a bug. Update or delete it with the code.

# How to

## Add a python module inside Airflow

Add the python module in the `airflow/requirements.txt`.

## Add a new service

For service XXX, create `docker/XXX` and place inside `compose.yml`, a `.env.example` and `.env` if necessary. Include the new service in the `docker-compose.yml` at the repository root.
