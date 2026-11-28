from collections import defaultdict
from datetime import date, datetime

import pytest

from duel import Duel, is_fair
from game.rounds import LEVELS, START, Candidates, generate_rounds, pick_probability

SCENARIOS = [(f"a{i}", 100 + i % 3, deaths, deaths * 50_000)
             for i, deaths in enumerate([0, 0, 0, 0, 3, 40, 900, 12_000, 300_000, 2_000_000])]
DISASTERS = [(f"d{i}", deaths, damage)
             for i, (deaths, damage) in enumerate([(1, None), (8, 2_000_000), (60, 90_000_000), (500, None),
                                                    (4_000, 3_000_000_000), (90_000, 40_000_000_000)])]
CANDIDATES = Candidates(SCENARIOS, DISASTERS, ["France", "Peru"])


def generate(seed=7, rounds=3_000, players=40):
    return generate_rounds(CANDIDATES, seed, rounds, players)


def test_same_seed_gives_the_same_rounds():
    assert generate() == generate()
    assert generate() != generate(seed=8)


def test_sample_has_the_asked_rounds_players_and_six_months():
    rounds = generate()
    assert [r["round_id"] for r in rounds] == list(range(1, 3_001))
    assert len({r["player_id"] for r in rounds}) == 40
    played = [r["played_at"] for r in rounds]
    assert played == sorted(played)
    assert START <= min(played).date() and max(played) < datetime(2026, 11, 1)
    assert all(r["played_at"].date() >= date.fromisoformat(r["player_signup_date"]) for r in rounds)


def test_every_pair_follows_the_game_rules():
    scenarios = {(des, geonameid): (deaths, damage) for des, geonameid, deaths, damage in SCENARIOS}
    disasters = {dis_no: (deaths, damage) for dis_no, deaths, damage in DISASTERS}
    for r in generate():
        asteroid_deaths, asteroid_damage = scenarios[r["asteroid_des"], r["geonameid"]]
        disaster_deaths, disaster_damage = disasters[r["dis_no"]]
        duel = Duel({"deaths": asteroid_deaths, "damage_usd": asteroid_damage},
                    {"deaths": disaster_deaths, "damage_usd": disaster_damage})
        assert is_fair(duel)
        assert r["correct_deaths"] == (r["chose_asteroid_deaths"] == (asteroid_deaths > disaster_deaths))
        if disaster_damage is None:
            assert r["chose_asteroid_damage"] is None and r["correct_damage"] is None
        else:
            assert r["correct_damage"] == (r["chose_asteroid_damage"] == (asteroid_damage > disaster_damage))


def test_asteroid_is_worse_in_about_half_the_rounds():
    scenarios = {des: deaths for des, _, deaths, _ in SCENARIOS}
    disasters = {dis_no: deaths for dis_no, deaths, _ in DISASTERS}
    rounds = generate()
    asteroid_worse = sum(scenarios[r["asteroid_des"]] > disasters[r["dis_no"]] for r in rounds)
    assert 0.45 < asteroid_worse / len(rounds) < 0.55


def test_levels_only_rise_and_change_between_days():
    by_player = defaultdict(list)
    for r in generate():
        by_player[r["player_id"]].append(r)
    reached = set()
    for rounds in by_player.values():
        ranks = [LEVELS.index(r["player_level"]) for r in rounds]
        assert ranks == sorted(ranks) and ranks[0] == 0
        assert len({(r["played_at"].date(), r["player_level"]) for r in rounds}) == len({r["played_at"].date() for r in rounds})
        reached.update(r["player_level"] for r in rounds)
    assert reached == set(LEVELS)


def test_bias_towards_the_asteroid_fades_with_the_level():
    for gap in (-2, -1, 0, 1):
        beginner, intermediate, expert = (pick_probability(level, gap) for level in LEVELS)
        assert beginner > intermediate > expert
    assert pick_probability("expert", 1) > 0.5 > pick_probability("expert", -1)
    assert pick_probability("beginner", -1) > 0.5


def test_pool_without_a_fair_pair_stops_with_an_error():
    with pytest.raises(RuntimeError, match="no fair pair"):
        generate_rounds(Candidates([("a", 1, 0, 0)], [("d", 10**6, None)], ["France"]), 1, 5, 1)


def test_rerun_with_the_same_seed_replaces_the_stored_sample():
    import mongomock
    from ingestion.store import RawStore

    store = RawStore(mongomock.MongoClient()["raw"])
    for minute in (1, 2):
        store.write_batch("game_rounds", "synthetic", generate(), {}, "manual", datetime(2026, 11, 28, 0, minute))
    stored = [{k: v for k, v in doc.items() if k not in ("_id", "_meta")} for doc in store.read_latest("game_rounds")]
    assert store.db["game_rounds"].count_documents({}) == 3_000
    assert sorted(stored, key=lambda doc: doc["round_id"]) == generate()


def test_fewer_rounds_than_players_is_refused():
    with pytest.raises(ValueError, match="at least one round per player"):
        generate(rounds=10, players=40)
