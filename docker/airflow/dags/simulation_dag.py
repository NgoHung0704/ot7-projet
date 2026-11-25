"""Build conditional impact estimates and historical intensity classes after staging publishes data."""

from datetime import datetime, timedelta, timezone

from airflow.providers.postgres.hooks.postgres import PostgresHook
from airflow.sdk import Asset, dag, task

from simulation.runner import rebuild


@dag(
    dag_id="simulation",
    schedule=Asset("stg_asteroid") | Asset("stg_city") | Asset("stg_disaster"),
    start_date=datetime(2026, 11, 1, tzinfo=timezone.utc),
    catchup=False,
    max_active_runs=1,
    tags=["simulation"],
    doc_md=__doc__,
)
def simulation():
    @task(outlets=[Asset("simulation_results")], execution_timeout=timedelta(minutes=30))
    def simulate_impacts() -> dict[str, int]:
        conn = PostgresHook(postgres_conn_id="postgres_warehouse").get_conn()
        try:
            return rebuild(conn)
        finally:
            conn.close()

    simulate_impacts()


simulation()
