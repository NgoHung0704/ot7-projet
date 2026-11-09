"""GeoNames cities + GEM admin-1 summaries → stg_city rows (the impact cities of the game)."""

import logging
import re
import unicodedata
from collections import defaultdict

from staging.convert import to_float, to_int
from staging.quality import reject

SOURCE = "cities"
CONTINENTS = ("EU", "AS", "NA", "SA", "AF", "OC")
CITY_COLUMNS = [
    "geonameid", "name", "ascii_name", "country_iso2", "country_iso3", "country_name", "continent",
    "latitude", "longitude", "population", "is_capital", "admin1_code", "admin1_name",
    "gem_level", "gem_id_1", "occupants", "buildings", "repl_cost_usd", "repl_cost_per_occupant_usd",
]
# Words GeoNames and GEM add or drop around the same region name ("State of Berlin" / "Berlin")
GENERIC_WORDS = {
    "city", "state", "of", "province", "region", "oblast", "governorate", "division", "district", "prefecture",
    "municipality", "capital", "metropolitan", "federal", "the", "special", "administrative",
    "ciudad", "autonoma", "de",
}
GEM_SUMS = {"occupants": "OCCUPANTS_TOTAL", "buildings": "BUILDINGS", "repl_cost_usd": "TOTAL_REPL_COST_USD"}
# GEM's World file repeats every country's regions; raw batches ingested before it was excluded still hold it
GEM_WORLD_FILE = "/World/summaries/"

log = logging.getLogger(__name__)


def normalize_region(name: str | None) -> str:
    ascii_name = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower()
    return "".join(word for word in re.split(r"[^a-z0-9]+", ascii_name) if word and word not in GENERIC_WORDS)


def match_gem_region(candidates: list[str | None], regions: dict[str, str]) -> str | None:
    """GEM region ID_1 matching the first candidate that matches anything (region names before the city name).

    Equal names first, then one name containing the other. When several GEM regions match, the name is
    ambiguous ("Mexico City": "Ciudad de México" and the State of "México") and None is returned, so the city
    falls back to its country rather than to the wrong region.
    """
    gem = {id_1: normalize_region(name) for id_1, name in regions.items()}
    for candidate in candidates:
        name = normalize_region(candidate)
        if not name:
            continue
        equal = [id_1 for id_1, gem_name in gem.items() if gem_name == name]
        contained = [
            id_1 for id_1, gem_name in gem.items()
            if gem_name and len(min(name, gem_name, key=len)) >= 4 and (name in gem_name or gem_name in name)
        ]
        found = equal or contained
        if found:
            return found[0] if len(found) == 1 else None
    return None


def select_cities(cities: list[dict], countries: list[dict], per_continent: int,
                  capital_min_population: int) -> list[dict]:
    """The most populous cities of each continent, plus the large capitals."""
    continent = {c["ISO"]: c["Continent"] for c in countries}
    by_population = sorted(cities, key=lambda c: -(to_int(c.get("population")) or 0))
    selected = []
    for code in CONTINENTS:
        selected += [c for c in by_population if continent.get(c["country code"]) == code][:per_continent]
    chosen = {c["geonameid"] for c in selected}
    selected += [
        c for c in by_population
        if c.get("feature code") == "PPLC" and (to_int(c.get("population")) or 0) >= capital_min_population
        and c["geonameid"] not in chosen
    ]
    return selected


def _gem_totals(gem_rows: list[dict]):
    regions = defaultdict(dict)
    region_totals = defaultdict(lambda: dict.fromkeys(GEM_SUMS, 0.0))
    country_totals = defaultdict(lambda: dict.fromkeys(GEM_SUMS, 0.0))
    for row in gem_rows:
        if GEM_WORLD_FILE in str(row.get("_meta", {}).get("url", "")):
            continue
        iso3, id_1 = row["ID_0"], row["ID_1"]
        regions[iso3][id_1] = row["NAME_1"]
        for key, field in GEM_SUMS.items():
            value = to_float(row.get(field)) or 0.0
            region_totals[(iso3, id_1)][key] += value
            country_totals[iso3][key] += value
    return regions, region_totals, country_totals


def _per_occupant(totals: dict) -> float | None:
    return totals["repl_cost_usd"] / totals["occupants"] if totals["occupants"] else None


def build_cities(cities: list[dict], countries: list[dict], admin1: list[dict], gem_rows: list[dict],
                 per_continent: int, capital_min_population: int) -> tuple[list[dict], list[dict]]:
    country_by_iso2 = {c["ISO"]: c for c in countries}
    admin1_by_code = {a["code"]: a for a in admin1}
    regions, region_totals, country_totals = _gem_totals(gem_rows)

    rows, rejects = [], []
    for city in select_cities(cities, countries, per_continent, capital_min_population):
        country = country_by_iso2.get(city["country code"])
        iso3 = country["ISO3"] if country else None
        if iso3 not in country_totals:
            rejects.append(reject(SOURCE, city["geonameid"], "no_gem_exposure", f"no GEM exposure for {iso3}", city))
            continue
        admin1_code = f"{city['country code']}.{city.get('admin1 code')}"
        region = admin1_by_code.get(admin1_code, {})
        id_1 = match_gem_region([region.get("asciiname"), region.get("name"), city["name"]], regions[iso3])
        totals = region_totals[(iso3, id_1)] if id_1 else None
        rows.append({
            "geonameid": int(city["geonameid"]),
            "name": city["name"],
            "ascii_name": city.get("asciiname"),
            "country_iso2": city["country code"],
            "country_iso3": iso3,
            "country_name": country.get("Country"),
            "continent": country.get("Continent"),
            "latitude": to_float(city["latitude"]),
            "longitude": to_float(city["longitude"]),
            "population": to_int(city.get("population")),
            "is_capital": city.get("feature code") == "PPLC",
            "admin1_code": admin1_code if region else None,
            "admin1_name": region.get("name"),
            "gem_level": "region" if id_1 else "country",
            "gem_id_1": id_1,
            # A whole country's totals would mislead (all of India for Delhi): only per-occupant values fall back
            **({key: totals[key] for key in GEM_SUMS} if totals else dict.fromkeys(GEM_SUMS)),
            "repl_cost_per_occupant_usd": _per_occupant(totals or country_totals[iso3]),
        })
    fallback = [row["name"] for row in rows if row["gem_level"] == "country"]
    log.info("GEM region found for %d of %d cities; country average for: %s",
             len(rows) - len(fallback), len(rows), ", ".join(fallback) or "none")
    return rows, rejects
