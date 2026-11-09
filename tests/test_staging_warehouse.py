"""Needs a PostgreSQL: set WAREHOUSE_TEST_DSN (e.g. the local `database` service on port 5433)."""

import os
from datetime import datetime

import pytest

DSN = os.environ.get("WAREHOUSE_TEST_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="WAREHOUSE_TEST_DSN not set")
psycopg2 = pytest.importorskip("psycopg2")

from staging.quality import reject  # noqa: E402
from staging.warehouse import (  # noqa: E402
    ensure_schema,
    last_inputs,
    record_inputs,
    replace_quarantine,
    replace_table,
)

REMOVED = ["des", "removed_at"]
WHEN = datetime(2026, 11, 2, 14, 22, 18)


@pytest.fixture
def conn():
    connection = psycopg2.connect(DSN)
    with connection, connection.cursor() as cur:
        cur.execute("DROP SCHEMA IF EXISTS staging CASCADE")
    yield connection
    connection.close()


def scalar(conn, sql):
    with conn.cursor() as cur:
        cur.execute(sql)
        return cur.fetchone()[0]


def removed(*designations):
    return [{"des": des, "removed_at": WHEN} for des in designations]


def test_ensure_schema_is_idempotent(conn):
    with conn:
        ensure_schema(conn)
        ensure_schema(conn)
    with conn.cursor() as cur:
        cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'staging'")
        tables = {row[0] for row in cur.fetchall()}
    assert tables == {"stg_asteroid", "stg_asteroid_removed", "stg_disaster", "stg_city", "quarantine", "build_log"}


def test_replace_table_replaces_rows(conn):
    with conn:
        ensure_schema(conn)
        replace_table(conn, "stg_asteroid_removed", REMOVED, removed("a", "b"))
    with conn:
        assert replace_table(conn, "stg_asteroid_removed", REMOVED, removed("c")) == 1

    assert scalar(conn, "SELECT count(*) FROM staging.stg_asteroid_removed") == 1


def test_failed_write_keeps_previous_rows(conn):
    with conn:
        ensure_schema(conn)
        replace_table(conn, "stg_asteroid_removed", REMOVED, removed("a", "b"))

    with pytest.raises(psycopg2.Error):
        with conn:
            replace_table(conn, "stg_asteroid_removed", REMOVED, removed("x", "x"))

    assert scalar(conn, "SELECT count(*) FROM staging.stg_asteroid_removed") == 2


def test_quarantine_is_replaced_per_source(conn):
    def rejected(source, key):
        return reject(source, key, "missing_data", "no mass", {"des": key})

    with conn:
        ensure_schema(conn)
        replace_quarantine(conn, "sentry", [rejected("sentry", "a"), rejected("sentry", "b")], "run1")
        replace_quarantine(conn, "emdat", [rejected("emdat", "x")], "run1")
    with conn:
        replace_quarantine(conn, "sentry", [rejected("sentry", "c")], "run2")

    with conn.cursor() as cur:
        cur.execute("SELECT source, count(*) FROM staging.quarantine GROUP BY source")
        assert dict(cur.fetchall()) == {"sentry": 1, "emdat": 1}


def test_build_log_roundtrip(conn):
    with conn:
        ensure_schema(conn)
        record_inputs(conn, "disasters", {"emdat_events": "l1"})
    assert last_inputs(conn, "disasters") == {"emdat_events": "l1"}

    with conn:
        record_inputs(conn, "disasters", {"emdat_events": "l2"})
    assert last_inputs(conn, "disasters") == {"emdat_events": "l2"}
    assert last_inputs(conn, "cities") == {}
