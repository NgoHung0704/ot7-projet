"""Monthly raw ingestion: Sentry, EM-DAT, GeoNames and GEM into MongoDB (database `raw`).

Each source is an independent task: one failing source does not stop the others.
A task with nothing new to write ends as skipped. Data contract for staging: docs/raw-data.md.
"""

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from airflow.providers.mongo.hooks.mongo import MongoHook
from airflow.sdk import Asset, dag, get_current_context, task
from airflow.sdk.exceptions import AirflowSkipException

from ingestion.common import batch_id_for, make_session
from ingestion.emdat import emdat_dir, ingest_emdat
from ingestion.gem import ingest_gem
from ingestion.geonames import ingest_geonames
from ingestion.sentry import ingest_sentry
from ingestion.store import RawStore

MONGO_CONN_ID = "mongo_raw"
RAW_DB = "raw"


@contextmanager
def raw_store():
    client = MongoHook(mongo_conn_id=MONGO_CONN_ID).get_conn()
    try:
        yield RawStore(client[RAW_DB])
    finally:
        client.close()


def batch_args() -> tuple[str, str, datetime]:
    """(batch_id, run_id, now): the batch is the month the run was triggered in."""
    context = get_current_context()
    return batch_id_for(context["dag_run"].run_after), context["run_id"], datetime.now(timezone.utc)


@dag(
    dag_id="ingest_raw",
    schedule="@monthly",
    start_date=datetime(2026, 11, 1, tzinfo=timezone.utc),
    catchup=False,
    tags=["ingestion"],
    default_args={"retries": 2, "retry_delay": timedelta(minutes=5)},
    doc_md=__doc__,
)
def ingest_raw():
    @task(outlets=[Asset("raw_sentry")])
    def sentry() -> dict[str, int]:
        with raw_store() as store:
            return ingest_sentry(store, make_session(), *batch_args())

    @task(outlets=[Asset("raw_emdat")])
    def emdat() -> int:
        with raw_store() as store:
            entry = ingest_emdat(store, emdat_dir(), *batch_args())
        if entry is None:
            raise AirflowSkipException(f"No new EM-DAT export in {emdat_dir()}")
        return entry["n_docs"]

    @task(outlets=[Asset("raw_geonames")])
    def geonames() -> dict[str, int]:
        with raw_store() as store:
            written = ingest_geonames(store, make_session(), *batch_args())
        if not written:
            raise AirflowSkipException("GeoNames files unchanged since the last batch")
        return written

    @task(outlets=[Asset("raw_gem")])
    def gem() -> int:
        with raw_store() as store:
            count = ingest_gem(store, make_session(), *batch_args())
        if count is None:
            raise AirflowSkipException("GEM repository unchanged since the last batch")
        return count

    sentry()
    emdat()
    geonames()
    gem()


ingest_raw()
