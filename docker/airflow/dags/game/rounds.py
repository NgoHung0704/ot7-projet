"""Synthetic game rounds, until the game records its own: the report's player questions (Q1, Q2, Q7, Q8)
need rounds, and the game stores none. The documents are those the game would write.

Each round is drawn like a game round (docker/app/duel.py): same pool of events, same fairness and balance
rules. The player picks the asteroid with probability logistic(SENSITIVITY · gap + BIAS[level]), where gap is
log10 of the asteroid's toll over the disaster's: people overestimate rare and spectacular hazards
(Lichtenstein et al., 1978; Slovic, 1987), less so with experience.
"""

import math
import random
import uuid
from bisect import bisect_left, bisect_right
from datetime import date, datetime, timedelta
from typing import NamedTuple

START = date(2026, 5, 1)
END = date(2026, 11, 1)
LEVELS = ("beginner", "intermediate", "expert")
# Rounds a player must have played on earlier days to reach each level.
ROUNDS_TO_REACH = {"beginner": 0, "intermediate": 30, "expert": 120}
SENSITIVITY = 1.5
BIAS = {"beginner": 2.0, "intermediate": 1.0, "expert": 0.3}
SIGNUP_BEFORE_END = 30  # days: the last players to sign up still play for a month
MAX_RATIO = 1000  # same as the game
HARMLESS_SHARE = 0.25  # same as the game
PAIR_TRIES = 20
DRAW_ATTEMPTS = 10_000


class Candidates(NamedTuple):
    scenarios: list[tuple]  # (des, geonameid, deaths, damage_usd)
    disasters: list[tuple]  # (dis_no, deaths, damage_usd), damage None when EM-DAT has no figure
    countries: list[str]


def read_candidates(conn) -> Candidates:
    """The game's own pool, in a fixed order so that a seed always gives the same rounds."""
    with conn.cursor() as cur:
        cur.execute("SELECT des, geonameid, deaths, damage_usd FROM game.asteroid_scenario ORDER BY des, geonameid")
        scenarios = [tuple(row) for row in cur.fetchall()]
        cur.execute("SELECT dis_no, deaths, damage_usd FROM game.historical_disaster ORDER BY dis_no")
        disasters = [tuple(row) for row in cur.fetchall()]
        cur.execute("SELECT DISTINCT country FROM game.asteroid_scenario WHERE country IS NOT NULL ORDER BY country")
        countries = [row[0] for row in cur.fetchall()]
    return Candidates(scenarios, disasters, countries)


def pick_probability(level: str, gap: float) -> float:
    """Chance of answering "Asteroid", for an asteroid `gap` orders of magnitude worse than the disaster."""
    return 1 / (1 + math.exp(-(SENSITIVITY * gap + BIAS[level])))


def _gap(asteroid_value: int, disaster_value: int) -> float:
    # +1 as in the game's fairness rule, so a harmless asteroid has a finite gap.
    return math.log10((asteroid_value + 1) / (disaster_value + 1))


def _is_guessable(asteroid_value: int, disaster_value: int) -> bool:
    if asteroid_value == disaster_value:
        return False
    return max(asteroid_value, disaster_value) + 1 <= MAX_RATIO * (min(asteroid_value, disaster_value) + 1)


class _Pairs:
    """Draws fair pairs with the game's balance: the asteroid causes more deaths in half the rounds."""

    def __init__(self, candidates: Candidates):
        self.deadly = [s for s in candidates.scenarios if s[2] > 0]
        self.harmless = [s for s in candidates.scenarios if s[2] == 0]
        self.disasters = sorted(candidates.disasters, key=lambda d: (d[1], d[0]))
        self.disaster_deaths = [d[1] for d in self.disasters]

    def _disaster_range(self, asteroid_deaths: int, asteroid_worse: bool) -> tuple[int, int]:
        if asteroid_worse:
            fewest = -(-(asteroid_deaths + 1) // MAX_RATIO) - 1
            return bisect_left(self.disaster_deaths, fewest), bisect_left(self.disaster_deaths, asteroid_deaths)
        most = MAX_RATIO * (asteroid_deaths + 1) - 1
        return bisect_right(self.disaster_deaths, asteroid_deaths), bisect_right(self.disaster_deaths, most)

    def draw(self, rng: random.Random) -> tuple[tuple, tuple]:
        for _ in range(DRAW_ATTEMPTS):
            plan = rng.random()
            asteroid_worse = plan >= 0.5
            pool = self.harmless if plan < HARMLESS_SHARE else self.deadly
            if not pool:
                continue
            scenario = rng.choice(pool)
            low, high = self._disaster_range(scenario[2], asteroid_worse)
            if low >= high:
                continue
            for _ in range(PAIR_TRIES):
                disaster = self.disasters[rng.randrange(low, high)]
                if disaster[2] is None or _is_guessable(scenario[3], disaster[2]):
                    return scenario, disaster
        raise RuntimeError("no fair pair of events: run the pipeline up to game_views first")


def _players(rng: random.Random, candidates: Candidates, count: int) -> list[dict]:
    last_signup = (END - START).days - SIGNUP_BEFORE_END
    return [{"player_id": str(uuid.UUID(int=rng.getrandbits(128), version=4)),
             "player_country": rng.choice(candidates.countries),
             "player_signup_date": START + timedelta(days=rng.randrange(last_signup)),
             "activity": rng.expovariate(1.0)} for _ in range(count)]


def _schedule(rng: random.Random, players: list[dict], rounds: int) -> list[tuple[datetime, dict, str]]:
    """(played_at, player, level) of every round. A level is set at the start of a day, from the rounds
    played on earlier days, so dim_player's daily versions are never ambiguous."""
    owners = list(range(len(players)))  # every player plays at least once
    owners += rng.choices(range(len(players)), weights=[p["activity"] for p in players], k=rounds - len(players))
    end = datetime.combine(END, datetime.min.time())
    times = {index: [] for index in range(len(players))}
    for index in owners:
        signup = datetime.combine(players[index]["player_signup_date"], datetime.min.time())
        times[index].append((signup + rng.random() * (end - signup)).replace(microsecond=0))
    schedule = []
    for index, played in times.items():
        played.sort()
        level, day, earlier_rounds = LEVELS[0], None, 0
        for count, played_at in enumerate(played):
            if played_at.date() != day:
                day, earlier_rounds = played_at.date(), count
                level = max((lvl for lvl in LEVELS if ROUNDS_TO_REACH[lvl] <= earlier_rounds), key=LEVELS.index)
            schedule.append((played_at, players[index], level))
    schedule.sort(key=lambda entry: (entry[0], entry[1]["player_id"]))
    return schedule


def _answer(rng: random.Random, level: str, asteroid_value: int, disaster_value: int) -> tuple[bool, bool]:
    chose_asteroid = rng.random() < pick_probability(level, _gap(asteroid_value, disaster_value))
    return chose_asteroid, chose_asteroid == (asteroid_value > disaster_value)


def generate_rounds(candidates: Candidates, seed: int, rounds: int, players: int) -> list[dict]:
    if rounds < players:
        raise ValueError(f"{rounds} rounds for {players} players: at least one round per player")
    rng = random.Random(seed)
    pairs = _Pairs(candidates)
    documents = []
    for round_id, (played_at, player, level) in enumerate(_schedule(rng, _players(rng, candidates, players), rounds), 1):
        (des, geonameid, asteroid_deaths, asteroid_damage), (dis_no, disaster_deaths, disaster_damage) = pairs.draw(rng)
        chose_asteroid_deaths, correct_deaths = _answer(rng, level, asteroid_deaths, disaster_deaths)
        chose_asteroid_damage = correct_damage = None
        if disaster_damage is not None:
            chose_asteroid_damage, correct_damage = _answer(rng, level, asteroid_damage, disaster_damage)
        documents.append({
            "round_id": round_id,
            "player_id": player["player_id"],
            "player_country": player["player_country"],
            "player_level": level,
            "player_signup_date": player["player_signup_date"].isoformat(),
            "played_at": played_at,
            "asteroid_des": des,
            "geonameid": geonameid,
            "dis_no": dis_no,
            "chose_asteroid_deaths": chose_asteroid_deaths,
            "correct_deaths": correct_deaths,
            "chose_asteroid_damage": chose_asteroid_damage,
            "correct_damage": correct_damage,
            "response_time_s": max(0.5, round(rng.lognormvariate(math.log(7), 0.5), 1)),
        })
    return documents
