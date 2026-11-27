"""Rules of an Impact Duel round, kept apart from Streamlit and the database so they can be tested alone."""

from dataclasses import dataclass

ROUNDS_PER_GAME = 10
MAX_RATIO = 1000
ASTEROID = "Asteroid"
DISASTER = "Disaster"


@dataclass(frozen=True)
class Duel:
    asteroid: dict
    disaster: dict

    @property
    def asks_damage(self) -> bool:
        return self.disaster["damage_usd"] is not None


def _is_guessable(asteroid_value: int, disaster_value: int) -> bool:
    if asteroid_value == disaster_value:
        return False
    # +1 keeps a harmless asteroid playable against a small disaster instead of an infinite ratio.
    return max(asteroid_value, disaster_value) + 1 <= MAX_RATIO * (min(asteroid_value, disaster_value) + 1)


def is_fair(duel: Duel) -> bool:
    if not _is_guessable(duel.asteroid["deaths"], duel.disaster["deaths"]):
        return False
    return not duel.asks_damage or _is_guessable(duel.asteroid["damage_usd"], duel.disaster["damage_usd"])


def find_duel(scenarios: list[dict], disasters: list[dict],
              played_asteroids: set[str], played_disasters: set[str]) -> Duel | None:
    """First fair pair of the shuffled candidates, never replaying an asteroid or a disaster of the game."""
    for scenario in scenarios:
        if scenario["des"] in played_asteroids:
            continue
        for disaster in disasters:
            if disaster["dis_no"] in played_disasters:
                continue
            duel = Duel(scenario, disaster)
            if is_fair(duel):
                return duel
    return None


def worse(asteroid_value: int, disaster_value: int) -> str:
    return ASTEROID if asteroid_value > disaster_value else DISASTER


def score(duel: Duel, deaths_pick: str, damage_pick: str | None) -> tuple[int, int]:
    """Points earned and questions asked in the round."""
    points = int(deaths_pick == worse(duel.asteroid["deaths"], duel.disaster["deaths"]))
    if not duel.asks_damage:
        return points, 1
    return points + int(damage_pick == worse(duel.asteroid["damage_usd"], duel.disaster["damage_usd"])), 2


def estimate(value: int) -> int:
    """Two significant figures: the simulation gives orders of magnitude, not exact tolls."""
    return int(float(f"{value:.2g}")) if value else 0


def people(value: int) -> str:
    return f"{value:,}"


def dollars(value: int) -> str:
    if value >= 1_000_000_000_000:
        return f"${value / 1_000_000_000_000:,.1f} trillion"
    if value >= 1_000_000_000:
        return f"${value / 1_000_000_000:,.1f} billion"
    if value >= 1_000_000:
        return f"${value / 1_000_000:,.1f} million"
    return f"${value:,}"
