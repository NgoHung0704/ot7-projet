"""Writes into the warehouse schema `staging`, with either PostgreSQL driver (psycopg2 or psycopg 3):
Airflow's PostgresHook hands out psycopg 3 in the team image. Group calls in `transaction(conn)`."""

import re
from contextlib import contextmanager
from pathlib import Path

DDL = Path(__file__).with_name("staging.sql")
SCHEMA_LOCK = 41570  # the three staging tasks may create the schema at the same time
BATCH = 1000  # rows per INSERT: well under PostgreSQL's 65,535 parameters per statement
IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]*$")


@contextmanager
def transaction(conn):
    """Commit on success, roll back on error. (psycopg 3's `with conn:` would also close the connection.)"""
    try:
        yield conn
    except BaseException:
        conn.rollback()
        raise
    else:
        conn.commit()


def _identifier(name: str) -> str:
    if not IDENTIFIER.match(name):
        raise ValueError(f"unexpected SQL identifier {name!r}")
    return name


def _insert(cur, statement: str, rows: list[tuple], placeholders: str) -> None:
    for start in range(0, len(rows), BATCH):
        chunk = rows[start:start + BATCH]
        cur.execute(f"{statement} VALUES {', '.join([placeholders] * len(chunk))}",
                    [value for row in chunk for value in row])


def ensure_schema(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(%s)", (SCHEMA_LOCK,))
        cur.execute(DDL.read_text(encoding="utf-8"))


def replace_table(conn, table: str, columns: list[str], rows: list[dict]) -> int:
    """Readers see the old rows until the transaction commits, then the new ones."""
    target = f"staging.{_identifier(table)}"
    names = ", ".join(_identifier(column) for column in columns)
    with conn.cursor() as cur:
        cur.execute(f"TRUNCATE {target}")
        _insert(cur, f"INSERT INTO {target} ({names})", [tuple(row[c] for c in columns) for row in rows],
                f"({', '.join(['%s'] * len(columns))})")
    return len(rows)


def replace_quarantine(conn, source: str, rejects: list[dict], run_id: str) -> int:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM staging.quarantine WHERE source = %s", (source,))
        _insert(
            cur,
            "INSERT INTO staging.quarantine (source, natural_key, check_name, reason, raw_payload, run_id)",
            [(r["source"], r["natural_key"], r["check_name"], r["reason"], r["raw_payload"], run_id)
             for r in rejects],
            "(%s, %s, %s, %s, %s::jsonb, %s)",
        )
    return len(rejects)


def last_inputs(conn, task: str) -> dict[str, str]:
    """Raw load_id per collection used by the task's last build ({} before the first one)."""
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass('staging.build_log')")
        if cur.fetchone()[0] is None:
            return {}
        cur.execute("SELECT collection, load_id FROM staging.build_log WHERE task = %s", (task,))
        return dict(cur.fetchall())


def record_inputs(conn, task: str, inputs: dict[str, str]) -> None:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM staging.build_log WHERE task = %s", (task,))
        _insert(cur, "INSERT INTO staging.build_log (task, collection, load_id)",
                [(task, collection, load_id) for collection, load_id in inputs.items()], "(%s, %s, %s)")
