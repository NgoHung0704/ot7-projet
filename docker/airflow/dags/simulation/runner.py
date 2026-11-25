"""Atomically rebuild simulation outputs from one consistent staging snapshot."""

from pathlib import Path

from simulation.intensity import historical_intensity
from simulation.model import simulate
from simulation.physics import profile
from staging.warehouse import transaction

DDL = Path(__file__).with_name("schema.sql")
RESULT_COLUMNS = ("des", "geonameid", "impact_date", "origin", "deaths", "damage_usd", "magnitude",
                  "peak_wind_kmh", "shaking_class", "wind_class", "energy_mt", "burst_altitude_m",
                  "exposed_population", "disc_radius_km", "model_version")
HISTORICAL_COLUMNS = ("dis_no", "magnitude", "max_wind_kmh", "shaking_class", "wind_class")


def _read(cur, table: str) -> list[dict]:
    cur.execute(f"SELECT * FROM staging.{table}")
    columns = [column[0] for column in cur.description]
    return [dict(zip(columns, row)) for row in cur.fetchall()]


def _write(cur, table: str, columns: tuple[str, ...], rows: list[dict]) -> None:
    for start in range(0, len(rows), 1000):
        batch = rows[start:start + 1000]
        placeholders = "(" + ",".join(["%s"] * len(columns)) + ")"
        cur.execute(f"INSERT INTO simulation.{table} ({','.join(columns)}) VALUES "
                    + ",".join([placeholders] * len(batch)),
                    [row[column] for row in batch for column in columns])


def rebuild(conn) -> dict[str, int]:
    profile.cache_clear()
    simulated = 0
    with transaction(conn):
        with conn.cursor() as cur:
            cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            # Staging replaces tables with TRUNCATE, which is not MVCC-safe; lock before taking a snapshot.
            cur.execute("LOCK TABLE staging.stg_asteroid, staging.stg_city, staging.stg_disaster IN SHARE MODE")
            cur.execute("SELECT pg_advisory_xact_lock(41571)")
            cur.execute(DDL.read_text(encoding="utf-8"))
            asteroids = _read(cur, "stg_asteroid")
            cities = _read(cur, "stg_city")
            disasters = _read(cur, "stg_disaster")
            cur.execute("TRUNCATE simulation.event_toll, simulation.historical_intensity")
            for asteroid in asteroids:
                rows = [{"des": asteroid["des"], "geonameid": city["geonameid"],
                         "impact_date": asteroid["impact_date"], "origin": "Simulated",
                         **simulate(asteroid, city)} for city in cities]
                _write(cur, "event_toll", RESULT_COLUMNS, rows)
                simulated += len(rows)
            historical = [{"dis_no": disaster["dis_no"],
                           **historical_intensity(disaster["magnitude"], disaster["magnitude_scale"])}
                          for disaster in disasters]
            _write(cur, "historical_intensity", HISTORICAL_COLUMNS, historical)
    return {"simulated": simulated, "historical": len(historical)}
