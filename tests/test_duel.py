from duel import ASTEROID, DISASTER, Duel, dollars, estimate, find_duel, is_fair, plan_round, score


def scenario(des="a", deaths=1_000, damage=5_000_000):
    return {"des": des, "deaths": deaths, "damage_usd": damage}


def disaster(dis_no="d", deaths=2_000, damage=1_000_000):
    return {"dis_no": dis_no, "deaths": deaths, "damage_usd": damage}


def test_close_tolls_make_a_fair_duel():
    assert is_fair(Duel(scenario(), disaster()))


def test_ties_are_not_fair():
    assert not is_fair(Duel(scenario(deaths=500), disaster(deaths=500)))
    assert not is_fair(Duel(scenario(damage=7), disaster(damage=7)))


def test_a_side_over_a_thousand_times_worse_is_not_fair():
    assert not is_fair(Duel(scenario(deaths=10_000_000), disaster(deaths=5_000)))
    assert not is_fair(Duel(scenario(damage=10**13), disaster(damage=10**9)))


def test_harmless_asteroid_stays_playable_against_a_small_disaster():
    assert is_fair(Duel(scenario(deaths=0, damage=0), disaster(deaths=200, damage=50)))
    assert not is_fair(Duel(scenario(deaths=0), disaster(deaths=5_000)))


def test_unknown_damage_asks_only_about_deaths():
    duel = Duel(scenario(damage=10**15), disaster(damage=None))
    assert is_fair(duel)
    assert not duel.asks_damage
    assert score(duel, DISASTER, None) == (1, 1)


def test_score_counts_each_question_asked():
    duel = Duel(scenario(deaths=1_000, damage=5_000_000), disaster(deaths=2_000, damage=1_000_000))
    assert score(duel, DISASTER, ASTEROID) == (2, 2)
    assert score(duel, ASTEROID, ASTEROID) == (1, 2)
    assert score(duel, ASTEROID, DISASTER) == (0, 2)


def test_find_duel_skips_unfair_and_already_played_pairs():
    scenarios = [scenario("played"), scenario("huge", deaths=10**9), scenario("ok")]
    disasters = [disaster("played-too"), disaster("fine")]
    duel = find_duel(scenarios, disasters, played_asteroids={"played"}, played_disasters={"played-too"},
                     deaths_winner=DISASTER)
    assert (duel.asteroid["des"], duel.disaster["dis_no"]) == ("ok", "fine")


def test_find_duel_keeps_only_pairs_with_the_planned_deaths_winner():
    scenarios = [scenario("weak", deaths=100), scenario("strong", deaths=9_000)]
    disasters = [disaster("small", deaths=500)]
    assert find_duel(scenarios, disasters, set(), set(), deaths_winner=ASTEROID).asteroid["des"] == "strong"
    assert find_duel(scenarios, disasters, set(), set(), deaths_winner=DISASTER).asteroid["des"] == "weak"


def test_find_duel_gives_up_without_a_fair_pair():
    assert find_duel([scenario(deaths=10**9)], [disaster()], set(), set(), deaths_winner=ASTEROID) is None


class FixedRandom:
    def __init__(self, value):
        self.value = value

    def random(self):
        return self.value


def test_plan_round_splits_the_deaths_answer_evenly():
    plans = [plan_round(FixedRandom(value)) for value in (0.1, 0.3, 0.6, 0.9)]
    assert plans == [(DISASTER, False), (DISASTER, True), (ASTEROID, True), (ASTEROID, True)]


def test_estimates_keep_two_significant_figures():
    assert [estimate(v) for v in (0, 37, 12_437, 9_876_543)] == [0, 37, 12_000, 9_900_000]


def test_dollars_read_in_words():
    assert [dollars(v) for v in (950, 2_500_000, 200_000_000_000, 1_300_000_000_000)] == [
        "$950", "$2.5 million", "$200.0 billion", "$1.3 trillion"]
