"""Publish the read-only `game` views once the simulation tables exist.

The views read live data, so this only needs to run again when their definition changes.
"""

import os
from datetime import datetime, timezone

from airflow.providers.postgres.hooks.postgres import PostgresHook
from airflow.sdk import Asset, dag, task

from game.publish import publish


@dag(
    dag_id="game_views",
    schedule=Asset("simulation_results"),
    start_date=datetime(2026, 11, 1, tzinfo=timezone.utc),
    catchup=False,
    max_active_runs=1,
    tags=["game"],
    doc_md=__doc__,
)
def game_views():
    @task(outlets=[Asset("game_views")])
    def publish_game_views() -> None:
        conn = PostgresHook(postgres_conn_id="postgres_warehouse").get_conn()
        try:
            publish(conn, os.environ.get("GAME_READER_PASSWORD", ""))
        finally:
            conn.close()

    publish_game_views()


game_views()
