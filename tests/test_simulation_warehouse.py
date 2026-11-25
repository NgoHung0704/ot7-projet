"""Run against the disposable PostgreSQL selected by WAREHOUSE_TEST_DSN."""

from datetime import date

import pytest

from simulation.runner import rebuild
from staging.warehouse import ensure_schema, transaction


@pytest.fixture
def staged(conn):
    with transaction(conn):
        ensure_schema(conn)
        with conn.cursor() as cur:
            cur.execute("DROP SCHEMA IF EXISTS simulation CASCADE")
            cur.execute("""INSERT INTO staging.stg_asteroid
                (des, diameter_m, mass_kg, entry_speed_kms, impact_date)
                VALUES ('a', 140, 1e9, 20, '2030-01-01'), ('b', 20, 1e7, 20, '2031-01-01')""")
            cur.execute("""INSERT INTO staging.stg_city
                (geonameid, name, latitude, longitude, population, is_capital, gem_level,
                 occupants, repl_cost_per_occupant_usd)
                VALUES (1, 'One', 0, 0, 1000000, false, 'region', 2000000, 50000),
                       (2, 'Two', 1, 1, 1000000, false, 'country', NULL, 50000)""")
            cur.execute("""INSERT INTO staging.stg_disaster
                (dis_no, start_date, date_precision, magnitude, magnitude_scale)
                VALUES ('quake', '2000-01-01', 'day', 5.5, 'Moment Magnitude'),
                       ('flood', '2001-01-01', 'day', 200, 'Km2')""")
    return conn


def count(conn, table):
    with conn.cursor() as cur:
        cur.execute(f"SELECT count(*) FROM simulation.{table}")
        return cur.fetchone()[0]


def test_cartesian_load_and_rerun_have_no_duplicates(staged):
    assert rebuild(staged) == {"simulated": 4, "historical": 2}
    assert rebuild(staged) == {"simulated": 4, "historical": 2}
    assert count(staged, "event_toll") == 4
    with staged.cursor() as cur:
        cur.execute("SELECT impact_date, origin, exposed_population FROM simulation.event_toll WHERE des='a' AND geonameid=2")
        assert cur.fetchone() == (date(2030, 1, 1), "Simulated", 1_000_000)


def test_empty_upstream_replaces_old_results(staged):
    rebuild(staged)
    with transaction(staged):
        with staged.cursor() as cur:
            cur.execute("TRUNCATE staging.stg_asteroid")
    assert rebuild(staged) == {"simulated": 0, "historical": 2}
    assert count(staged, "event_toll") == 0


def test_bad_exposure_rolls_back_entire_output(staged):
    rebuild(staged)
    with transaction(staged):
        with staged.cursor() as cur:
            cur.execute("UPDATE staging.stg_city SET occupants=NULL WHERE gem_level='region'")
    with pytest.raises(ValueError, match="occupants"):
        rebuild(staged)
    assert count(staged, "event_toll") == 4
    assert count(staged, "historical_intensity") == 2


def test_q5_matches_shared_class_and_excludes_not_applicable(staged):
    rebuild(staged)
    with staged.cursor() as cur:
        cur.execute("""SELECT DISTINCT h.dis_no FROM simulation.event_toll s
            JOIN simulation.historical_intensity h
              ON (s.shaking_class = h.shaking_class AND s.shaking_class <> 'Not applicable')
              OR (s.wind_class = h.wind_class AND s.wind_class <> 'Not applicable')
            WHERE s.des = 'a'""")
        assert cur.fetchall() == [("quake",)]
