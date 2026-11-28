"""Game rounds: generate_rounds writes the synthetic sample of the report into MongoDB (raw.game_rounds), as the
game would, and load_rounds loads the latest sample into fact_round and dim_player.

generate_rounds is triggered by hand. The same seed always gives the same rounds, and a new run replaces the
previous sample. Run it after game_views and load_warehouse: rounds pointing to events the star schema does not
know yet go to quarantine.
"""

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from airflow.providers.mongo.hooks.mongo import MongoHook
from airflow.providers.postgres.hooks.postgres import PostgresHook
from airflow.sdk import Asset, Param, dag, get_current_context, task

from game.rounds import generate_rounds, read_candidates
from ingestion.store import RawStore
from warehouse.rounds import load_rounds

COLLECTION = "game_rounds"
SYNTHETIC_BATCH = "synthetic"
ROUNDS = 200_000
PLAYERS = 2_000
# The repository's sql/ folder, mounted read-only by docker/airflow/docker-compose.yml.
STAR_SCHEMA_SQL = Path("/opt/airflow/sql/schema.sql")


@contextmanager
def raw_store():
    client = MongoHook(mongo_conn_id="mongo_raw").get_conn()
    try:
        yield RawStore(client["raw"])
    finally:
        client.close()


@contextmanager
def warehouse():
    conn = PostgresHook(postgres_conn_id="postgres_warehouse").get_conn()
    try:
        yield conn
    finally:
        conn.close()


@dag(
    dag_id="generate_rounds",
    schedule=None,
    start_date=datetime(2026, 11, 1, tzinfo=timezone.utc),
    catchup=False,
    max_active_runs=1,
    # Typed, so that a seed typed in the trigger form gives the same rounds as the same number in code.
    params={"seed": Param(2026, type="integer")},
    tags=["game"],
    doc_md=__doc__,
)
def generate_rounds_dag():
    @task(outlets=[Asset("raw_game_rounds")], execution_timeout=timedelta(minutes=30))
    def generate() -> int:
        context = get_current_context()
        seed = context["params"]["seed"]
        with warehouse() as conn:
            candidates = read_candidates(conn)
        documents = generate_rounds(candidates, seed, ROUNDS, PLAYERS)
        with raw_store() as store:
            # A fixed batch id: each run replaces the previous sample instead of adding to it.
            store.write_batch(COLLECTION, SYNTHETIC_BATCH, documents, {"dataset_version": f"synthetic, seed {seed}"},
                              context["run_id"], datetime.now(timezone.utc))
        return len(documents)

    generate()


@dag(
    dag_id="load_rounds",
    schedule=Asset("raw_game_rounds"),
    start_date=datetime(2026, 11, 1, tzinfo=timezone.utc),
    catchup=False,
    max_active_runs=1,
    tags=["warehouse"],
    doc_md=__doc__,
)
def load_rounds_dag():
    @task(outlets=[Asset("fact_round")], execution_timeout=timedelta(minutes=30))
    def load() -> dict[str, int]:
        with raw_store() as store:
            documents = store.read_latest(COLLECTION)
        with warehouse() as conn:
            return load_rounds(conn, documents, STAR_SCHEMA_SQL, get_current_context()["run_id"])

    load()


generate_rounds_dag()
load_rounds_dag()
