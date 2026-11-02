from pathlib import Path

import pytest

pytest.importorskip("airflow")

from airflow.dag_processing.dagbag import DagBag  # noqa: E402

DAGS = Path(__file__).resolve().parent.parent / "docker" / "airflow" / "dags"


@pytest.fixture(scope="module")
def dagbag():
    return DagBag(dag_folder=DAGS)


def test_documented_mongo_connection_is_accepted(monkeypatch):
    """docs/raw-data.md tells the infrastructure to set this exact value."""
    from airflow.providers.mongo.hooks.mongo import MongoHook

    monkeypatch.setenv("AIRFLOW_CONN_MONGO_RAW", "mongo://mongo:27017")
    MongoHook(mongo_conn_id="mongo_raw").get_conn().close()


def test_dag_loads_without_errors(dagbag):
    assert dagbag.import_errors == {}


def test_dag_shape(dagbag):
    dag = dagbag.dags["ingest_raw"]
    assert {task.task_id for task in dag.tasks} == {"sentry", "emdat", "geonames", "gem"}
    assert all(not task.upstream_task_ids for task in dag.tasks)
    assert dag.catchup is False
    assert {task.task_id: [asset.name for asset in task.outlets] for task in dag.tasks} == {
        "sentry": ["raw_sentry"],
        "emdat": ["raw_emdat"],
        "geonames": ["raw_geonames"],
        "gem": ["raw_gem"],
    }
