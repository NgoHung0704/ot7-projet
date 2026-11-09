# Asteroid impacts vs. historical disasters

OT7 Data Engineering, INSA Lyon

A web game where the player guesses which is deadlier: a real historical disaster (EM-DAT) or the simulated impact of an asteroid from NASA's Sentry risk list on a major city. 

# How to run

### Download EM dat dataset

TODO: link + instruction to put it in the right folder

### Environment configuration

```bash
cp .env.example .env
cp airflow/.env.example airflow/.env
cp mongo/.env.example mongo/.env
cp postgres/.env.example postgres/.env
```
Fill the .env files accordingly.

### Airflow first run

To setup Airflow, run the first time:

```bash
docker compose up airflow-init
```

### Run

```bash
docker compose up
```

# Pipeline details

## Overview

TODO: put a diagram showing the whole pipeline 

## Airflow

TODO: describe the airflow DAG

## Postgres & mongo

TODO: justify the use