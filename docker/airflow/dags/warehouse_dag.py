"""Load the star schema after each simulation rebuild, so the report's demo queries see the latest data."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

from airflow.providers.postgres.hooks.postgres import PostgresHook
from airflow.sdk import Asset, dag, task

from warehouse.load import load

# The repository's sql/ folder, mounted read-only by docker/airflow/docker-compose.yml.
STAR_SCHEMA_SQL = Path("/opt/airflow/sql/schema.sql")


@dag(
    dag_id="load_warehouse",
    schedule=Asset("simulation_results"),
    start_date=datetime(2026, 11, 1, tzinfo=timezone.utc),
    catchup=False,
    max_active_runs=1,
    tags=["warehouse"],
    doc_md=__doc__,
)
def load_warehouse():
    @task(outlets=[Asset("star_schema")], execution_timeout=timedelta(minutes=30))
    def load_star_schema() -> dict[str, int]:
        conn = PostgresHook(postgres_conn_id="postgres_warehouse").get_conn()
        try:
            return load(conn, STAR_SCHEMA_SQL)
        finally:
            conn.close()

    load_star_schema()


load_warehouse()
