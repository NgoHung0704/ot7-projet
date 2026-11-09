"""Staging: the latest complete raw batches (MongoDB) → clean tables in the warehouse (PostgreSQL, schema `staging`).

Runs when ingest_raw publishes a new batch. Each task rebuilds its tables only when its raw inputs changed,
and ends as skipped while they are missing or unchanged. Rejected rows go to staging.quarantine.
"""

from contextlib import contextmanager
from datetime import datetime, timezone
from functools import partial

from airflow.providers.mongo.hooks.mongo import MongoHook
from airflow.providers.postgres.hooks.postgres import PostgresHook
from airflow.sdk import Asset, dag, get_current_context, task
from airflow.sdk.exceptions import AirflowSkipException

from ingestion.store import RawStore
from staging.runner import asteroid_tables, city_tables, disaster_tables, stage

MONGO_CONN_ID = "mongo_raw"
WAREHOUSE_CONN_ID = "postgres_warehouse"
RAW_DB = "raw"


@contextmanager
def connections():
    mongo = MongoHook(mongo_conn_id=MONGO_CONN_ID).get_conn()
    warehouse = PostgresHook(postgres_conn_id=WAREHOUSE_CONN_ID).get_conn()
    try:
        yield RawStore(mongo[RAW_DB]), warehouse
    finally:
        warehouse.close()
        mongo.close()


def run_stage(task_name: str, inputs: list[str], build) -> dict[str, int]:
    context = get_current_context()
    with connections() as (store, warehouse):
        result = stage(warehouse, store, task_name, inputs, build, context["run_id"],
                       context["params"]["max_reject_rate"])
    if result.status != "built":
        raise AirflowSkipException(result.detail)
    return result.counts


@dag(
    dag_id="staging",
    schedule=(Asset("raw_sentry") | Asset("raw_emdat") | Asset("raw_geonames") | Asset("raw_gem")),
    start_date=datetime(2026, 11, 1, tzinfo=timezone.utc),
    catchup=False,
    max_active_runs=1,
    tags=["staging"],
    params={"cities_per_continent": 15, "capital_min_population": 1_000_000, "max_reject_rate": 0.10},
    doc_md=__doc__,
)
def staging():
    @task(outlets=[Asset("stg_asteroid")])
    def asteroids() -> dict[str, int]:
        return run_stage("asteroids", ["sentry_objects", "sentry_details", "sentry_removed"], asteroid_tables)

    @task(outlets=[Asset("stg_disaster")])
    def disasters() -> dict[str, int]:
        return run_stage("disasters", ["emdat_events"], disaster_tables)

    @task(outlets=[Asset("stg_city")])
    def cities() -> dict[str, int]:
        params = get_current_context()["params"]
        build = partial(city_tables, per_continent=params["cities_per_continent"],
                        capital_min_population=params["capital_min_population"])
        return run_stage(
            "cities", ["geonames_cities", "geonames_countries", "geonames_admin1", "gem_exposure_adm1"], build
        )

    asteroids()
    disasters()
    cities()


staging()
