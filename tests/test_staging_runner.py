"""Needs a PostgreSQL: the `conn` fixture (conftest.py) reads WAREHOUSE_TEST_DSN."""

from datetime import UTC, datetime

import mongomock
import pytest

from ingestion.store import RawStore
from staging.quality import StagingQualityError
from staging.runner import disaster_tables, stage

NOW = datetime(2026, 11, 1, 0, 3, tzinfo=UTC)
INPUTS = ["emdat_events"]


def emdat(dis_no, year=2020):
    return {"DisNo": dis_no, "Start Year": year, "Start Month": 8, "Start Day": 4, "Total Deaths": 1}


@pytest.fixture
def store():
    return RawStore(mongomock.MongoClient()["raw"])


def write(store, rows, minute):
    store.write_batch("emdat_events", "2026-11", rows, {"dataset_version": "x"}, "run", NOW.replace(minute=minute))


def run(conn, store, run_id="run1"):
    return stage(conn, store, "disasters", INPUTS, disaster_tables, run_id, max_reject_rate=0.10)


def disasters_in(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT dis_no FROM staging.stg_disaster ORDER BY dis_no")
        return [row[0] for row in cur.fetchall()]


def test_waiting_when_raw_missing(conn, store):
    result = run(conn, store)

    assert result.status == "waiting"
    assert "emdat_events" in result.detail
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass('staging.stg_disaster')")
        assert cur.fetchone()[0] is None


def test_empty_raw_batch_builds_nothing(conn, store):
    write(store, [emdat("a")], minute=4)
    run(conn, store)
    write(store, [], minute=5)

    result = run(conn, store, "run2")
    assert result.status == "waiting"
    assert "empty" in result.detail
    assert disasters_in(conn) == ["a"]


def test_built_then_unchanged(conn, store):
    write(store, [emdat("a"), emdat("b")], minute=4)

    first = run(conn, store)
    assert (first.status, first.counts) == ("built", {"stg_disaster": 2})
    assert run(conn, store, "run2").status == "unchanged"


def test_force_rebuilds_unchanged_inputs(conn, store):
    """After a fix in the staging code, the same raw batch must be rebuilt on demand."""
    write(store, [emdat("a")], minute=4)
    run(conn, store)

    result = stage(conn, store, "disasters", INPUTS, disaster_tables, "run2", max_reject_rate=0.10, force=True)
    assert result.status == "built"


def test_new_batch_rebuilds(conn, store):
    write(store, [emdat("a"), emdat("b")], minute=4)
    run(conn, store)
    write(store, [emdat("c")], minute=5)

    assert run(conn, store, "run2").status == "built"
    assert disasters_in(conn) == ["c"]


def test_too_many_rejects_fail_without_writing(conn, store):
    write(store, [emdat("a"), emdat("b")], minute=4)
    run(conn, store)
    write(store, [emdat("c"), emdat("d", year=None)], minute=5)

    with pytest.raises(StagingQualityError):
        run(conn, store, "run2")
    assert disasters_in(conn) == ["a", "b"]
