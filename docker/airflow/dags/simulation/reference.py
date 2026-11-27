"""Print reproducible reference cases and optionally time a synthetic full-size workload."""

import argparse
import json
import math
from time import perf_counter

from simulation.model import simulate
from simulation.physics import profile


def reference_cases() -> list[dict]:
    city = {"population": 1_000_000, "gem_level": "country", "occupants": None,
            "repl_cost_per_occupant_usd": 50_000}
    return [{"diameter_m": diameter, "entry_speed_kms": 20.,
             **simulate({"diameter_m": diameter, "entry_speed_kms": 20.}, city)}
            for diameter in (20., 140., 1000.)]


def benchmark(asteroids: int = 2200, cities: int = 100) -> dict:
    profile.cache_clear()
    started = perf_counter()
    checksum = 0
    for index in range(asteroids):
        asteroid = {"diameter_m": math.exp(math.log(.5) + math.log(2400) * index / max(1, asteroids - 1)),
                    "entry_speed_kms": 11.2 + 20 * index / max(1, asteroids - 1)}
        for city_index in range(cities):
            city = {"population": 100_000 + 100_000 * city_index, "gem_level": "country", "occupants": None,
                    "repl_cost_per_occupant_usd": 50_000}
            checksum += simulate(asteroid, city)["deaths"]
    return {"asteroids": asteroids, "cities": cities, "pairs": asteroids * cities,
            "seconds": round(perf_counter() - started, 3), "deaths_checksum": checksum,
            "physics_cache": str(profile.cache_info())}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark", action="store_true")
    args = parser.parse_args()
    output = {"reference_cases": reference_cases()}
    if args.benchmark:
        output["benchmark"] = benchmark()
    print(json.dumps(output, indent=2, allow_nan=False))
