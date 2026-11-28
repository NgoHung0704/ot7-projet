"""Run against the disposable PostgreSQL selected by WAREHOUSE_TEST_DSN."""

import re
from datetime import date
from pathlib import Path

import pytest

from simulation.runner import DDL as SIMULATION_DDL
from staging.warehouse import ensure_schema, transaction
from warehouse.load import STAR_TABLES, load

SQL = Path(__file__).resolve().parent.parent / "sql"
SCHEMA = SQL / "schema.sql"
TOLL_COLUMNS = ("des, geonameid, impact_date, origin, deaths, damage_usd, magnitude, peak_wind_kmh, shaking_class, "
                "wind_class, energy_mt, burst_altitude_m, exposed_population, disc_radius_km, model_version")


def drop_star(conn):
    with transaction(conn):
        with conn.cursor() as cur:
            cur.execute(f"DROP TABLE IF EXISTS {', '.join(STAR_TABLES)} CASCADE")


def add_toll(cur, des, geonameid, deaths, damage, shaking_class="6-7"):
    cur.execute(f"""INSERT INTO simulation.event_toll ({TOLL_COLUMNS})
        VALUES (%s, %s, '2030-01-01', 'Simulated', %s, %s, 6.5, 300, %s, '252+ km/h', 10, 0, %s, 5, 'test')""",
                (des, geonameid, deaths, damage, shaking_class, deaths * 10))


@pytest.fixture
def warehouse(conn):
    drop_star(conn)
    with transaction(conn):
        ensure_schema(conn)
        with conn.cursor() as cur:
            cur.execute("DROP SCHEMA IF EXISTS simulation CASCADE")
            cur.execute(SIMULATION_DDL.read_text(encoding="utf-8"))
            cur.execute("""INSERT INTO staging.stg_asteroid
                (des, fullname, diameter_m, mass_kg, entry_speed_kms, impact_probability, impact_date)
                VALUES ('a', '(2000 AA)', 140, 1e9, 20, 1e-5, '2030-01-01'),
                       ('b', NULL, 50, 1e8, 15, 2e-4, '2030-01-01')""")
            cur.execute("""INSERT INTO staging.stg_city
                (geonameid, name, country_name, latitude, longitude, population, is_capital, gem_level)
                VALUES (1, 'Paris', 'France', 48.85, 2.35, 2100000, true, 'country'),
                       (2, 'Lima', 'Peru', -12.04, -77.03, 10000000, true, 'country')""")
            for des, deaths in (("a", 1000), ("b", 0)):
                for geonameid in (1, 2):
                    add_toll(cur, des, geonameid, deaths * geonameid, deaths * 5000)
            cur.execute("""INSERT INTO staging.stg_disaster
                (dis_no, event_name, disaster_type, iso3, country, start_date, date_precision, deaths,
                 damage_adjusted_usd)
                VALUES ('1995-0001-JPN', 'Kobe', 'Earthquake', 'JPN', 'Japan', '1995-01-17', 'day', 5297, 200000000000),
                       ('2010-0244-PAK', NULL, 'Flood', 'PAK', 'Pakistan', '2010-07-28', 'day', NULL, NULL)""")
            cur.execute("""INSERT INTO simulation.historical_intensity (dis_no, magnitude, max_wind_kmh, shaking_class, wind_class)
                VALUES ('1995-0001-JPN', 6.9, NULL, '6-7', 'Not applicable')""")
    yield conn
    drop_star(conn)


def rows(conn, query, params=()):
    with conn.cursor() as cur:
        cur.execute(query, params)
        return cur.fetchall()


def table_counts(conn):
    return {table: rows(conn, f"SELECT count(*) FROM {table}")[0][0] for table in STAR_TABLES}


def test_schema_runs_twice_on_an_empty_database(warehouse):
    drop_star(warehouse)
    for _ in range(2):
        with transaction(warehouse):
            with warehouse.cursor() as cur:
                cur.execute(SCHEMA.read_text(encoding="utf-8"))
    assert table_counts(warehouse) == dict.fromkeys(STAR_TABLES, 0)


def test_fact_with_an_unknown_key_is_rejected(warehouse):
    load(warehouse, SCHEMA)
    with pytest.raises(Exception, match="foreign key"):
        with transaction(warehouse):
            with warehouse.cursor() as cur:
                cur.execute("INSERT INTO fact_event_toll (event_key, location_key, date_key) "
                            "SELECT 999999, location_key, date_key FROM fact_event_toll LIMIT 1")


def test_loading_twice_creates_no_duplicate(warehouse):
    first = load(warehouse, SCHEMA)
    assert load(warehouse, SCHEMA) == first == table_counts(warehouse)
    assert first["fact_event_toll"] == 2 * 2 + 2
    assert first["dim_event"] == 4
    assert first["dim_location"] == 2 + 2


def test_historical_disaster_is_one_country_with_its_adjusted_damage(warehouse):
    load(warehouse, SCHEMA)
    assert rows(warehouse, """
        SELECT e.event_name, e.origin, e.shaking_class, e.wind_class, l.location_id, l.city, d.full_date,
               f.deaths, f.damage_usd
        FROM fact_event_toll f JOIN dim_event e USING (event_key) JOIN dim_location l USING (location_key)
        JOIN dim_date d USING (date_key) WHERE e.origin = 'Historical' ORDER BY e.event_id""") == [
        ("Kobe", "Historical", "6-7", "Not applicable", "JPN", "Whole country", date(1995, 1, 17), 5297, 200_000_000_000),
        ("Flood in Pakistan", "Historical", "Not applicable", "Not applicable", "PAK", "Whole country",
         date(2010, 7, 28), None, None),
    ]


def test_new_size_of_an_asteroid_creates_a_version_and_keeps_old_scenarios(warehouse):
    load(warehouse, SCHEMA)
    with transaction(warehouse):
        with warehouse.cursor() as cur:
            cur.execute("UPDATE staging.stg_asteroid SET diameter_m = 160 WHERE des = 'a'")
            cur.execute("UPDATE simulation.event_toll SET deaths = deaths * 2 WHERE des = 'a'")
    load(warehouse, SCHEMA)
    versions = rows(warehouse, """
        SELECT e.diameter_m, e.is_current, e.valid_to < '9999-12-31', sum(f.deaths)
        FROM dim_event e JOIN fact_event_toll f USING (event_key)
        WHERE e.event_id = 'a' GROUP BY e.event_key ORDER BY e.event_key""")
    assert versions == [(140, False, True, 3000), (160, True, False, 6000)]


def test_new_impact_probability_overwrites_without_a_version(warehouse):
    load(warehouse, SCHEMA)
    with transaction(warehouse):
        with warehouse.cursor() as cur:
            cur.execute("UPDATE staging.stg_asteroid SET impact_probability = 0.5 WHERE des = 'a'")
    load(warehouse, SCHEMA)
    assert rows(warehouse, "SELECT impact_probability, is_current FROM dim_event WHERE event_id = 'a'") == [(0.5, True)]


def test_removed_asteroid_is_no_longer_current(warehouse):
    load(warehouse, SCHEMA)
    with transaction(warehouse):
        with warehouse.cursor() as cur:
            cur.execute("INSERT INTO staging.stg_asteroid_removed (des) VALUES ('b')")
    load(warehouse, SCHEMA)
    assert rows(warehouse, "SELECT event_id, is_current FROM dim_event WHERE origin = 'Simulated' ORDER BY 1") == [
        ("a", True), ("b", False)]
    assert rows(warehouse, "SELECT count(*) FROM fact_event_toll")[0][0] == 6


def demo_queries():
    text = (SQL / "queries.sql").read_text(encoding="utf-8")
    statements = [s.strip() for s in re.sub(r"--[^\n]*", "", text).split(";") if s.strip()]
    return [s.replace(":asteroid_des", "'a'") for s in statements]


def test_report_has_eight_demo_queries():
    assert len(demo_queries()) == 8


@pytest.mark.parametrize("number", range(1, 9))
def test_demo_query_runs_on_the_schema(warehouse, number):
    load(warehouse, SCHEMA)
    rows(warehouse, demo_queries()[number - 1])


def run_pseudocode_schema(conn):
    with transaction(conn):
        with conn.cursor() as cur:
            cur.execute((Path(__file__).parent / "fixtures" / "pseudocode_schema.sql").read_text(encoding="utf-8"))


def test_empty_tables_of_the_pseudocode_schema_are_replaced(warehouse):
    drop_star(warehouse)
    run_pseudocode_schema(warehouse)
    assert load(warehouse, SCHEMA)["fact_event_toll"] == 6


def test_pseudocode_tables_holding_rows_are_kept(warehouse):
    drop_star(warehouse)
    run_pseudocode_schema(warehouse)
    with transaction(warehouse):
        with warehouse.cursor() as cur:
            cur.execute("INSERT INTO dim_date (date_key) VALUES (20300101)")
    with pytest.raises(Exception, match="pseudocode"):
        load(warehouse, SCHEMA)
    assert rows(warehouse, "SELECT date_key FROM dim_date") == [(20300101,)]


def test_scenario_the_simulation_dropped_leaves_the_star_schema(warehouse):
    load(warehouse, SCHEMA)
    with transaction(warehouse):
        with warehouse.cursor() as cur:
            cur.execute("DELETE FROM simulation.event_toll WHERE des = 'a' AND geonameid = 2")
    load(warehouse, SCHEMA)
    assert rows(warehouse, """SELECT l.city FROM fact_event_toll f JOIN dim_event e USING (event_key)
                              JOIN dim_location l USING (location_key) WHERE e.event_id = 'a'""") == [("Paris",)]


def test_disaster_without_country_or_type_is_named_but_has_no_place(warehouse):
    with transaction(warehouse):
        with warehouse.cursor() as cur:
            cur.execute("INSERT INTO staging.stg_disaster (dis_no, start_date, date_precision, deaths) "
                        "VALUES ('1950-0001-XXX', '1950-01-01', 'year', 12)")
    load(warehouse, SCHEMA)
    assert rows(warehouse, "SELECT event_name, disaster_type FROM dim_event WHERE event_id = '1950-0001-XXX'") == [
        ("Unknown type in an unknown country", "Unknown type")]
    assert rows(warehouse, "SELECT count(*) FROM fact_event_toll")[0][0] == 6


def test_pseudocode_upgrade_refuses_any_table_holding_rows(warehouse):
    drop_star(warehouse)
    run_pseudocode_schema(warehouse)
    with transaction(warehouse):
        with warehouse.cursor() as cur:
            cur.execute("CREATE TABLE fact_round (round_id BIGINT)")
            cur.execute("INSERT INTO fact_round VALUES (1)")
    with pytest.raises(Exception, match="pseudocode"):
        load(warehouse, SCHEMA)
