from datetime import date, datetime

from staging.asteroids import build_asteroids, build_removed, most_probable_impact, parse_sentry_date

OBJ = {"des": "2011 TO", "fullname": "  2011 TO", "ip": "1.4e-05", "n_imp": 2, "last_obs": "2026-10-12"}
DETAIL = {
    "summary": {"des": "2011 TO", "diameter": "0.018", "mass": "1.2e9", "v_imp": "20.1", "v_inf": "16.5",
                "energy": "3.4"},
    "data": [{"date": "2101-05-03.40", "ip": "1.4e-06"}, {"date": "2090-01-01.12", "ip": "9.9e-06"}],
}


def test_parse_sentry_date():
    assert parse_sentry_date("2090-01-01.12") == date(2090, 1, 1)
    assert parse_sentry_date("not a date") is None
    assert parse_sentry_date(None) is None


def test_most_probable_impact_compares_numbers():
    vis = [{"ip": "9.9e-04", "date": "a"}, {"ip": "1.4e-05", "date": "b"}]
    assert most_probable_impact(vis)["date"] == "a"
    assert most_probable_impact([]) is None


def test_build_asteroids_converts_units():
    rows, rejects = build_asteroids([OBJ], [DETAIL])

    assert rejects == []
    row = rows[0]
    assert row["diameter_m"] == 18.0
    assert row["mass_kg"] == 1.2e9
    assert row["entry_speed_kms"] == 20.1
    assert row["energy_mt"] == 3.4
    assert row["impact_probability"] == 1.4e-05
    assert row["impact_date"] == date(2090, 1, 1)
    assert row["fullname"] == "2011 TO"
    assert row["n_impacts"] == 2
    assert row["last_obs"] == date(2026, 10, 12)


def test_asteroid_without_detail_or_mass_is_quarantined():
    no_mass = {**DETAIL, "summary": {**DETAIL["summary"], "des": "29075", "mass": None}}
    rows, rejects = build_asteroids([OBJ | {"des": "gone"}, OBJ | {"des": "29075"}], [no_mass])

    assert rows == []
    assert [(r["natural_key"], r["check_name"]) for r in rejects] == [("gone", "missing_data"), ("29075", "missing_data")]


def test_build_removed():
    assert build_removed([{"des": "2026 VA", "removed": "2026-11-02 14:22:18"}]) == [
        {"des": "2026 VA", "removed_at": datetime(2026, 11, 2, 14, 22, 18)}
    ]
