"""Estimate conditional immediate fatalities and direct building replacement losses."""

import math

from simulation.intensity import shaking_class, wind_class
from simulation.physics import Band, positive, profile

MODEL_VERSION = "educational_bands_v1"
POPULATION_DENSITY_KM2 = 3000.


def band_losses(population: float, cost_per_occupant: float, disc_radius_km: float,
                pressure: list[Band] | tuple[Band, ...], thermal: list[Band] | tuple[Band, ...]) -> tuple[float, float]:
    boundaries = sorted({0., disc_radius_km, *(min(b.radius_km, disc_radius_km) for b in (*pressure, *thermal))})
    deaths = damage = 0.
    for inner, outer in zip(boundaries, boundaries[1:]):
        distance = (inner + outer) / 2
        pressure_fatality = max((b.fatality_rate for b in pressure if distance < b.radius_km), default=0.)
        thermal_fatality = max((b.fatality_rate for b in thermal if distance < b.radius_km), default=0.)
        loss_ratio = max((b.damage_ratio for b in (*pressure, *thermal) if distance < b.radius_km), default=0.)
        exposed = population * (outer**2 - inner**2) / disc_radius_km**2
        deaths += exposed * (1 - (1 - pressure_fatality) * (1 - thermal_fatality))
        damage += exposed * cost_per_occupant * loss_ratio
    return min(deaths, population), min(damage, population * cost_per_occupant)


def simulate(asteroid: dict, city: dict) -> dict:
    population = positive(city.get("population"), "population", allow_zero=True)
    if city.get("gem_level") == "region":
        exposed = positive(city.get("occupants"), "occupants", allow_zero=True)
    elif city.get("gem_level") == "country":
        exposed = population
    else:
        raise ValueError("gem_level must be region or country")
    cost = positive(city.get("repl_cost_per_occupant_usd"), "repl_cost_per_occupant_usd", allow_zero=True)
    physics = profile(float(positive(asteroid.get("diameter_m"), "diameter_m")),
                      float(positive(asteroid.get("entry_speed_kms"), "entry_speed_kms")))
    radius = math.sqrt(exposed / (math.pi * POPULATION_DENSITY_KM2))
    deaths, damage = band_losses(exposed, cost, radius, physics.pressure, physics.thermal) if exposed else (0., 0.)
    return {"deaths": min(round(deaths), math.floor(exposed)), "damage_usd": math.floor(damage),
            "magnitude": physics.magnitude, "peak_wind_kmh": physics.peak_wind_kmh,
            "shaking_class": shaking_class(physics.magnitude), "wind_class": wind_class(physics.peak_wind_kmh),
            "energy_mt": physics.energy_mt, "burst_altitude_m": physics.burst_altitude_m,
            "exposed_population": exposed, "disc_radius_km": radius, "model_version": MODEL_VERSION}
