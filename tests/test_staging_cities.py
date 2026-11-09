import logging

import pytest

from staging.cities import build_cities, match_gem_region, normalize_region, select_cities

COUNTRIES = [
    {"ISO": "FR", "ISO3": "FRA", "Country": "France", "Continent": "EU"},
    {"ISO": "DE", "ISO3": "DEU", "Country": "Germany", "Continent": "EU"},
    {"ISO": "JP", "ISO3": "JPN", "Country": "Japan", "Continent": "AS"},
    {"ISO": "IS", "ISO3": "ISL", "Country": "Iceland", "Continent": "EU"},
]
ADMIN1 = [
    {"code": "FR.11", "name": "Île-de-France", "asciiname": "Ile-de-France", "geonameid": "3012874"},
    {"code": "DE.16", "name": "Land Berlin", "asciiname": "State of Berlin", "geonameid": "2950157"},
]


def city(geonameid, name, country, population, admin1="00", feature="PPL"):
    return {"geonameid": str(geonameid), "name": name, "asciiname": name, "country code": country,
            "admin1 code": admin1, "population": str(population), "feature code": feature,
            "latitude": "48.85", "longitude": "2.35"}


def gem(iso3, id_1, name_1, occupancy, occupants, buildings, cost):
    return {"ID_0": iso3, "ID_1": id_1, "NAME_1": name_1, "OCCUPANCY": occupancy,
            "OCCUPANTS_TOTAL": str(occupants), "BUILDINGS": str(buildings), "TOTAL_REPL_COST_USD": str(cost)}


GEM = [
    gem("FRA", "FR-IDF", "Ile-de-France", "RES", 2500, 100, 5_000_000.0),
    gem("FRA", "FR-IDF", "Ile-de-France", "COM", 1200, 20, 3_000_000.0),
    gem("FRA", "FR-ARA", "Auvergne-Rhone-Alpes", "RES", 1000, 50, 1_000_000.0),
    gem("DEU", "DE-BY", "Bayern", "RES", 4000, 200, 2_000_000.0),
]


def build(cities):
    return build_cities(cities, COUNTRIES, ADMIN1, GEM, per_continent=15, capital_min_population=1_000_000)


def test_normalize_drops_generic_whole_words():
    assert normalize_region("State of Berlin") == "berlin"
    assert normalize_region("Île-de-France") == "ilefrance"
    assert normalize_region("Athens") == "athens"
    assert normalize_region(None) == ""


def test_match_by_containment():
    assert match_gem_region(["Moscow"], {"RU-MOW": "Moscow City", "RU-MOS": "Moskovskaya"}) == "RU-MOW"
    assert match_gem_region(["Mazovia"], {"PL-MZ": "Mazowieckie"}) is None
    assert match_gem_region([None, "Greater Tokyo"], {"JP-13": "Tokyo"}) == "JP-13"


def test_capital_district_never_gets_the_province_of_the_same_name():
    # Real GEM names: the city district and the surrounding province normalize alike -> ambiguous -> country
    mexico = {"MX-CMX": "Ciudad de México", "MX-MEX": "México"}
    assert match_gem_region(["Mexico City", "Mexico City", "Mexico City"], mexico) is None
    argentina = {"AR-C": "Ciudad Autónoma de Buenos Aires", "AR-B": "Buenos Aires"}
    assert match_gem_region(["Buenos Aires F.D.", "Buenos Aires F.D.", "Buenos Aires"], argentina) is None


def test_region_name_is_tried_before_the_city_name():
    dominican = {"DO-01": "Distrito Nacional", "DO-32": "Santo Domingo"}
    assert match_gem_region(["Nacional", "Nacional", "Santo Domingo"], dominican) == "DO-01"


def test_match_rate_is_logged(caplog):
    caplog.set_level(logging.INFO, logger="staging")
    build([city(1, "Paris", "FR", 2_100_000, admin1="11"), city(3, "Berlin", "DE", 3_400_000, admin1="16")])
    assert "GEM region found for 1 of 2 cities; country average for: Berlin" in caplog.text


def test_select_cities_per_continent_and_capitals():
    cities = [
        city(1, "Paris", "FR", 2_100_000), city(2, "Lyon", "FR", 500_000), city(3, "Berlin", "DE", 3_400_000),
        city(4, "Tokyo", "JP", 8_300_000), city(5, "Osaka", "JP", 2_600_000), city(6, "Kobe", "JP", 1_500_000),
        city(7, "Reykjavik", "IS", 1_200_000, feature="PPLC"),
    ]
    selected = select_cities(cities, COUNTRIES, per_continent=2, capital_min_population=1_000_000)
    assert [c["name"] for c in selected] == ["Berlin", "Paris", "Tokyo", "Osaka", "Reykjavik"]


def test_region_match_fills_totals():
    rows, rejects = build([city(1, "Paris", "FR", 2_100_000, admin1="11", feature="PPLC")])

    assert rejects == []
    paris = rows[0]
    assert (paris["gem_level"], paris["gem_id_1"]) == ("region", "FR-IDF")
    assert (paris["occupants"], paris["buildings"], paris["repl_cost_usd"]) == (3700, 120, 8_000_000.0)
    assert paris["repl_cost_per_occupant_usd"] == pytest.approx(8_000_000 / 3700)
    assert (paris["admin1_code"], paris["admin1_name"]) == ("FR.11", "Île-de-France")
    assert paris["is_capital"] is True and paris["country_iso3"] == "FRA" and paris["continent"] == "EU"


def test_world_aggregate_rows_are_ignored():
    world = [row | {"_meta": {"url": "https://raw.githubusercontent.com/gem/x/World/summaries/Exposure_Summary_Adm1.csv"}}
             for row in GEM]
    rows, _ = build_cities([city(1, "Paris", "FR", 2_100_000, admin1="11")], COUNTRIES, ADMIN1, GEM + world,
                           per_continent=15, capital_min_population=1_000_000)
    assert rows[0]["occupants"] == 3700


def test_country_fallback_keeps_only_per_capita():
    rows, _ = build([city(3, "Berlin", "DE", 3_400_000, admin1="16")])

    berlin = rows[0]
    assert berlin["gem_level"] == "country"
    assert (berlin["gem_id_1"], berlin["occupants"], berlin["buildings"], berlin["repl_cost_usd"]) == (None,) * 4
    assert berlin["repl_cost_per_occupant_usd"] == pytest.approx(2_000_000 / 4000)


def test_country_absent_from_gem_is_quarantined():
    rows, rejects = build([city(4, "Tokyo", "JP", 8_300_000)])
    assert rows == []
    assert [(r["natural_key"], r["check_name"]) for r in rejects] == [("4", "no_gem_exposure")]
