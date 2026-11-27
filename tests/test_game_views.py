"""Needs a PostgreSQL: the `conn` fixture (conftest.py) reads WAREHOUSE_TEST_DSN."""

from pathlib import Path

import pytest

from conftest import DSN
from game.publish import publish
from staging.warehouse import ensure_schema, transaction

SIMULATION_DDL = Path(__file__).parents[1] / "docker/airflow/dags/simulation/schema.sql"
PASSWORD = "reader-test-password"


@pytest.fixture
def warehouse(conn):
    with transaction(conn):
        ensure_schema(conn)
        with conn.cursor() as cur:
            cur.execute("DROP SCHEMA IF EXISTS game CASCADE")
            cur.execute("DROP SCHEMA IF EXISTS simulation CASCADE")
            cur.execute(SIMULATION_DDL.read_text(encoding="utf-8"))
            cur.execute("""INSERT INTO staging.stg_asteroid (des, fullname, diameter_m, mass_kg, entry_speed_kms, impact_date)
                VALUES ('kept', '(2000 AA)', 140, 1e9, 20, '2030-01-01'),
                       ('removed', NULL, 50, 1e8, 15, '2031-01-01')""")
            cur.execute("INSERT INTO staging.stg_asteroid_removed (des) VALUES ('removed')")
            cur.execute("""INSERT INTO staging.stg_city
                (geonameid, name, country_name, latitude, longitude, population, is_capital, gem_level)
                VALUES (1, 'Paris', 'France', 48.85, 2.35, 2100000, true, 'country')""")
            for des in ("kept", "removed"):
                cur.execute("""INSERT INTO simulation.event_toll
                    (des, geonameid, impact_date, origin, deaths, damage_usd, magnitude, peak_wind_kmh,
                     shaking_class, wind_class, energy_mt, burst_altitude_m, exposed_population,
                     disc_radius_km, model_version)
                    VALUES (%s, 1, '2030-01-01', 'Simulated', 1000, 5000000, 6.5, 300,
                            '6-7', '252+ km/h', 50, 0, 2100000, 15, 'test')""", (des,))
            cur.execute("""INSERT INTO staging.stg_disaster
                (dis_no, event_name, disaster_subgroup, disaster_type, country, start_date, date_precision,
                 deaths, damage_adjusted_usd)
                VALUES ('quake', 'Kobe', 'Geophysical', 'Earthquake', 'Japan', '1995-01-17', 'day', 5297, 200000000000),
                       ('blast', NULL, 'Industrial accident', 'Explosion (Industrial)', 'Lebanon', '2020-08-04', 'day', 218, NULL),
                       ('famine', NULL, 'Climatological', 'Drought', 'China', '1928-01-01', 'year', 3000000, NULL),
                       ('unknown', NULL, 'Geophysical', 'Earthquake', 'Chile', '1960-05-22', 'day', NULL, NULL)""")
            cur.execute("""INSERT INTO simulation.historical_intensity (dis_no, magnitude, max_wind_kmh, shaking_class, wind_class)
                VALUES ('quake', 6.9, NULL, '6-7', 'Not applicable')""")
    return conn


def rows(conn, query):
    with conn.cursor() as cur:
        cur.execute(query)
        return cur.fetchall()


def test_scenarios_skip_removed_asteroids(warehouse):
    publish(warehouse, PASSWORD)
    assert rows(warehouse, "SELECT des, asteroid_name, city, deaths, shaking_class FROM game.asteroid_scenario") == [
        ("kept", "(2000 AA)", "Paris", 1000, "6-7")]


def test_disasters_keep_sudden_events_with_known_deaths(warehouse):
    publish(warehouse, PASSWORD)
    assert rows(warehouse, "SELECT dis_no, year, shaking_class FROM game.historical_disaster ORDER BY dis_no") == [
        ("blast", 2020, "Not applicable"), ("quake", 1995, "6-7")]


def test_publishing_again_keeps_the_views(warehouse):
    publish(warehouse, PASSWORD)
    publish(warehouse, PASSWORD)
    assert rows(warehouse, "SELECT count(*) FROM game.historical_disaster") == [(2,)]


def test_reader_sees_the_views_but_not_the_tables(warehouse, request):
    publish(warehouse, PASSWORD)
    driver = pytest.importorskip(request.node.callspec.params["conn"])
    reader = driver.connect(DSN, user="game_reader", password=PASSWORD)
    try:
        assert rows(reader, "SELECT count(*) FROM game.asteroid_scenario") == [(1,)]
        reader.rollback()
        with pytest.raises(Exception, match="permission denied"):
            rows(reader, "SELECT count(*) FROM staging.stg_disaster")
    finally:
        reader.close()


def test_empty_password_is_refused(warehouse):
    with pytest.raises(ValueError, match="GAME_READER_PASSWORD"):
        publish(warehouse, "")
