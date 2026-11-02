from pathlib import Path

import pytest

pytest.importorskip("airflow")

from airflow.dag_processing.dagbag import DagBag  # noqa: E402

DAGS = Path(__file__).resolve().parent.parent / "docker" / "airflow" / "dags"


@pytest.fixture(scope="module")
def dagbag():
    return DagBag(dag_folder=DAGS)


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
