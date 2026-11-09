"""Writes into the warehouse schema `staging`. Callers own the transaction (`with conn:`)."""

from pathlib import Path

from psycopg2 import sql
from psycopg2.extras import execute_values

DDL = Path(__file__).with_name("staging.sql")
SCHEMA_LOCK = 41570  # the three staging tasks may create the schema at the same time


def ensure_schema(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(%s)", (SCHEMA_LOCK,))
        cur.execute(DDL.read_text(encoding="utf-8"))


def replace_table(conn, table: str, columns: list[str], rows: list[dict]) -> int:
    """Readers see the old rows until the caller commits, then the new ones."""
    target = sql.Identifier("staging", table)
    with conn.cursor() as cur:
        cur.execute(sql.SQL("TRUNCATE {}").format(target))
        if rows:
            insert = sql.SQL("INSERT INTO {} ({}) VALUES %s").format(
                target, sql.SQL(", ").join(map(sql.Identifier, columns))
            )
            execute_values(cur, insert, [tuple(row[column] for column in columns) for row in rows])
    return len(rows)


def replace_quarantine(conn, source: str, rejects: list[dict], run_id: str) -> int:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM staging.quarantine WHERE source = %s", (source,))
        if rejects:
            execute_values(
                cur,
                "INSERT INTO staging.quarantine (source, natural_key, check_name, reason, raw_payload, run_id) "
                "VALUES %s",
                [(r["source"], r["natural_key"], r["check_name"], r["reason"], r["raw_payload"], run_id)
                 for r in rejects],
                template="(%s, %s, %s, %s, %s::jsonb, %s)",
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
        execute_values(
            cur,
            "INSERT INTO staging.build_log (task, collection, load_id) VALUES %s",
            [(task, collection, load_id) for collection, load_id in inputs.items()],
        )
