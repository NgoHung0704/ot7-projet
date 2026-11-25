"""Adapt ImpactEffect's units and tuple outputs for repeatable dry-land scenarios."""

import math
from dataclasses import dataclass
from functools import lru_cache

import numpy

# ImpactEffect 1.0.0 imports NumPy's removed Inf alias; retain NumPy 2 for the Airflow dependency tree.
if not hasattr(numpy, "Inf"):
    numpy.Inf = numpy.inf

from impactEffects.functions.function import (
    airburst_altitude, cal_energy_surface, cal_magnitude, cal_themal, cal_velocity, cal_vmax, kinetic_energy,
)
from impactEffects.instances.ImpactorClass import Impactor
from impactEffects.instances.TargetClass import Target

DENSITY_KGM3 = 2600.
ANGLE_DEG = 45.
TARGET_DENSITY_KGM3 = 2500.
MIN_DISTANCE_KM = .001
MAX_DISTANCE_KM = 20_000.
PRESSURE_BANDS = ((20_000., .01, .1), (50_000., .1, .5), (100_000., .5, 1.), (200_000., .95, 1.))
THERMAL_BANDS = ((100_000., .01, .05), (300_000., .1, .2), (1_000_000., .5, .7))


@dataclass(frozen=True)
class Band:
    radius_km: float
    fatality_rate: float
    damage_ratio: float


@dataclass(frozen=True)
class Profile:
    energy_mt: float
    burst_altitude_m: float
    magnitude: float | None
    peak_wind_kmh: float
    pressure: tuple[Band, ...]
    thermal: tuple[Band, ...]


def positive(value, name: str, *, allow_zero: bool = False) -> float:
    if value is None:
        raise ValueError(f"{name} is missing")
    number = float(value)
    if not math.isfinite(number) or number < 0 or (number == 0 and not allow_zero):
        raise ValueError(f"{name} must be finite and {'nonnegative' if allow_zero else 'positive'}")
    return number


def effects(diameter_m: float, speed_kms: float, distance_km: float) -> tuple[float, float, float]:
    impactor = Impactor(positive(diameter_m, "diameter_m"), DENSITY_KGM3,
                        positive(speed_kms, "entry_speed_kms"), ANGLE_DEG)
    target = Target(depth=0, distance=positive(distance_km, "distance_km"), density=TARGET_DENSITY_KGM3)
    burst = airburst_altitude(impactor, target)
    wind_ms, pressure_pa = cal_vmax(impactor, target)
    thermal_jm2 = 0.
    if burst == 0 and cal_velocity(impactor, target) >= 15:
        energy_surface = cal_energy_surface(impactor, target)
        fireball_radius_km = 2e-6 * energy_surface ** (1 / 3)
        horizon_height_km = (1 - math.cos(distance_km / target.R_earth)) * target.R_earth
        # ImpactEffect calls acos before checking the horizon, raising outside its domain.
        if horizon_height_km < fireball_radius_km:
            thermal = cal_themal(impactor, target, energy_surface=energy_surface)
            thermal_jm2 = thermal[2] * 10. ** thermal[7]
    values = (pressure_pa, wind_ms * 3.6, thermal_jm2)
    if any(not math.isfinite(value) or value < 0 for value in values):
        raise ValueError("ImpactEffect returned invalid physical effects")
    return values


def _radius(effect, threshold: float) -> float:
    if effect(MIN_DISTANCE_KM) < threshold:
        return 0.
    low, high = MIN_DISTANCE_KM, MAX_DISTANCE_KM
    if effect(high) >= threshold:
        raise ValueError("effect radius exceeds the regional model domain")
    for _ in range(32):
        middle = (low + high) / 2
        if effect(middle) >= threshold:
            low = middle
        else:
            high = middle
    return (low + high) / 2


@lru_cache(maxsize=4096)
def profile(diameter_m: float, speed_kms: float) -> Profile:
    impactor = Impactor(positive(diameter_m, "diameter_m"), DENSITY_KGM3,
                        positive(speed_kms, "entry_speed_kms"), ANGLE_DEG)
    target = Target(depth=0, distance=1., density=TARGET_DENSITY_KGM3)
    burst = airburst_altitude(impactor, target)
    magnitude = float(cal_magnitude(impactor, target)) if burst == 0 else None
    samples = {}

    def at(distance):
        if distance not in samples:
            samples[distance] = effects(diameter_m, speed_kms, distance)
        return samples[distance]

    pressure = tuple(Band(_radius(lambda r: at(r)[0], threshold), fatality, damage)
                     for threshold, fatality, damage in PRESSURE_BANDS)
    thermal = tuple(Band(_radius(lambda r: at(r)[2], threshold), fatality, damage)
                    for threshold, fatality, damage in THERMAL_BANDS) if burst == 0 else ()
    return Profile(kinetic_energy(impactor) / 4.184e15, burst, magnitude, at(1.)[1], pressure, thermal)
