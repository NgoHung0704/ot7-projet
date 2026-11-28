"""Load the report's star schema from staging and the simulation, so the demo queries run on real data.

The schema file is the report's deliverable sql/schema.sql, mounted in the Airflow containers.
"""

from pathlib import Path

from staging.warehouse import transaction

LOAD = Path(__file__).with_name("load.sql")
UPGRADE = Path(__file__).with_name("upgrade.sql")
STAR_TABLES = ("dim_event", "dim_location", "dim_date", "dim_player", "fact_event_toll", "fact_round")
# Held by every writer of the star schema, so two DAGs never run schema.sql or upsert at the same time.
STAR_LOCK = 41572


def lock_star_schema(cur, schema_sql: Path) -> None:
    cur.execute("SELECT pg_advisory_xact_lock(%s)", (STAR_LOCK,))
    cur.execute(UPGRADE.read_text(encoding="utf-8"))
    cur.execute(schema_sql.read_text(encoding="utf-8"))


def load(conn, schema_sql: Path) -> dict[str, int]:
    with transaction(conn):
        with conn.cursor() as cur:
            cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            # Staging and the simulation replace tables with TRUNCATE, which is not MVCC-safe.
            cur.execute("LOCK TABLE staging.stg_asteroid, staging.stg_asteroid_removed, staging.stg_city, "
                        "staging.stg_disaster, simulation.event_toll, simulation.historical_intensity IN SHARE MODE")
            lock_star_schema(cur, schema_sql)
            cur.execute(LOAD.read_text(encoding="utf-8"))
            counts = {}
            for table in STAR_TABLES:
                cur.execute(f"SELECT count(*) FROM {table}")
                counts[table] = cur.fetchone()[0]
    return counts
