"""Run against the disposable PostgreSQL selected by WAREHOUSE_TEST_DSN."""

from datetime import date, datetime

import pytest

from test_star_schema import SCHEMA, rows, warehouse  # noqa: F401  (fixture)
from warehouse.load import load
from warehouse.rounds import load_rounds

# Fixture tolls: asteroid 'a' kills 1,000 in Paris (1) and 2,000 in Lima (2), damage 5,000,000;
# Kobe killed 5,297 with $200 billion of damage; the Pakistan flood has no known deaths.


def game_round(round_id, played_at, level="beginner", **changes):
    document = {"round_id": round_id, "player_id": "p1", "player_country": "France", "player_level": level,
                "player_signup_date": "2026-05-01", "played_at": played_at, "asteroid_des": "a",
                "geonameid": 1, "dis_no": "1995-0001-JPN", "chose_asteroid_deaths": False, "correct_deaths": True,
                "chose_asteroid_damage": True, "correct_damage": False, "response_time_s": 6.5}
    return {**document, **changes}


ROUNDS = [game_round(1, datetime(2026, 5, 2, 9)),
          game_round(2, datetime(2026, 5, 2, 18), chose_asteroid_deaths=True, correct_deaths=False),
          game_round(3, datetime(2026, 6, 10, 12), level="intermediate", geonameid=2,
                     chose_asteroid_damage=False, correct_damage=True)]


@pytest.fixture
def star(warehouse):  # noqa: F811
    load(warehouse, SCHEMA)
    return warehouse


def loaded_rounds(conn):
    return rows(conn, """SELECT r.round_id, p.level, d.full_date, e.event_id, l.city, r.chose_asteroid_deaths,
                                r.correct_deaths, r.chose_asteroid_damage, r.correct_damage
                         FROM fact_round r JOIN dim_player p USING (player_key) JOIN dim_date d USING (date_key)
                         JOIN dim_event e ON e.event_key = r.asteroid_event_key JOIN dim_location l USING (location_key)
                         ORDER BY r.round_id""")


def quarantined(conn):
    return rows(conn, "SELECT natural_key, check_name FROM staging.quarantine WHERE source = 'game_rounds' ORDER BY 1")


def test_rounds_land_in_fact_round_with_the_level_of_the_day(star):
    assert load_rounds(star, ROUNDS, SCHEMA, "run") == {"loaded": 3, "quarantined": 0, "player_versions": 2}
    assert loaded_rounds(star) == [
        (1, "beginner", date(2026, 5, 2), "a", "Paris", 0, 1, 1, 0),
        (2, "beginner", date(2026, 5, 2), "a", "Paris", 1, 0, 1, 0),
        (3, "intermediate", date(2026, 6, 10), "a", "Lima", 0, 1, 0, 1),
    ]


def test_level_change_keeps_the_old_version_for_older_rounds(star):
    load_rounds(star, ROUNDS, SCHEMA, "run")
    assert rows(star, "SELECT level, valid_from, valid_to, is_current, country FROM dim_player ORDER BY valid_from") == [
        ("beginner", date(2026, 5, 1), date(2026, 6, 10), False, "France"),
        ("intermediate", date(2026, 6, 10), date(9999, 12, 31), True, "France"),
    ]


def test_loading_the_same_rounds_twice_creates_no_duplicate(star):
    load_rounds(star, ROUNDS, SCHEMA, "run")
    assert load_rounds(star, ROUNDS, SCHEMA, "run") == {"loaded": 3, "quarantined": 0, "player_versions": 2}
    assert len(loaded_rounds(star)) == 3


def test_new_country_overwrites_every_version(star):
    load_rounds(star, ROUNDS, SCHEMA, "run")
    load_rounds(star, [*ROUNDS, game_round(4, datetime(2026, 7, 1), level="intermediate", player_country="Peru")],
                SCHEMA, "run")
    assert rows(star, "SELECT DISTINCT country FROM dim_player") == [("Peru",)]
    assert rows(star, "SELECT count(*) FROM dim_player")[0][0] == 2


def test_round_with_an_unknown_event_is_quarantined(star):
    unknown = [game_round(5, datetime(2026, 5, 3), asteroid_des="nope"),
               game_round(6, datetime(2026, 5, 3), dis_no="2010-0244-PAK")]
    assert load_rounds(star, [*ROUNDS, *unknown], SCHEMA, "run")["quarantined"] == 2
    assert quarantined(star) == [("5", "referential"), ("6", "referential")]
    assert len(loaded_rounds(star)) == 3


def test_round_whose_answers_disagree_with_the_tolls_is_quarantined(star):
    wrong = [game_round(7, datetime(2026, 5, 3), correct_deaths=False),
             game_round(8, datetime(2026, 5, 3), chose_asteroid_damage=None, correct_damage=None)]
    assert load_rounds(star, [*ROUNDS, *wrong], SCHEMA, "run")["quarantined"] == 2
    assert quarantined(star) == [("7", "consistency"), ("8", "consistency")]


def test_new_sample_replaces_the_rounds_of_the_previous_one(star):
    load_rounds(star, ROUNDS, SCHEMA, "run")
    load_rounds(star, [ROUNDS[0], game_round(3, datetime(2026, 6, 10), asteroid_des="nope")], SCHEMA, "run")
    assert [row[0] for row in loaded_rounds(star)] == [1]


def test_round_played_before_signup_or_with_half_a_damage_answer_is_quarantined(star):
    odd = [game_round(9, datetime(2026, 4, 30)),
           game_round(10, datetime(2026, 5, 3), chose_asteroid_damage=None)]
    assert load_rounds(star, [*ROUNDS, *odd], SCHEMA, "run")["quarantined"] == 2
    assert quarantined(star) == [("10", "consistency"), ("9", "consistency")]
