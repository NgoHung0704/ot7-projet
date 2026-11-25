"""Simulation contracts: units, exposure limits and overlapping hazard bands."""

import math
import json
from pathlib import Path

import pytest

from simulation.intensity import historical_intensity, shaking_class, wind_class
from simulation.model import Band, band_losses, simulate
from simulation.physics import effects, profile


@pytest.mark.parametrize("magnitude,expected", [(None, "Not applicable"), (float("nan"), "Not applicable"),
    (-1, "<4"), (3.999, "<4"), (4, "4-5"), (4.999, "4-5"), (5, "5-6"),
    (6, "6-7"), (7, "7-8"), (8, "8-9"), (8.999, "8-9"), (9, "9+"), (10, "9+")])
def test_shaking_boundaries(magnitude, expected):
    assert shaking_class(magnitude) == expected


@pytest.mark.parametrize("speed,expected", [(None, "Not applicable"), (-1, "Not applicable"),
    (float("inf"), "Not applicable"), (0, "<119 km/h"), (118.999, "<119 km/h"),
    (119, "119-154 km/h"), (153.999, "119-154 km/h"), (154, "154-178 km/h"),
    (177.999, "154-178 km/h"), (178, "178-209 km/h"), (208.999, "178-209 km/h"),
    (209, "209-252 km/h"), (251.999, "209-252 km/h"), (252, "252+ km/h")])
def test_wind_boundaries(speed, expected):
    assert wind_class(speed) == expected


@pytest.mark.parametrize("scale", ["Moment Magnitude", "Richter"])
def test_historical_seismic_scales(scale):
    assert historical_intensity(6.5, scale) == {
        "magnitude": 6.5, "max_wind_kmh": None, "shaking_class": "6-7", "wind_class": "Not applicable"}


def test_historical_wind_scale():
    assert historical_intensity(180, "Kph") == {
        "magnitude": None, "max_wind_kmh": 180, "shaking_class": "Not applicable", "wind_class": "178-209 km/h"}


@pytest.mark.parametrize("scale", [None, "Km2", "m3", "°C", "Vaccinated", "unknown"])
def test_other_scales_are_not_seismic_or_wind(scale):
    result = historical_intensity(7, scale)
    assert result["magnitude"] is None
    assert result["max_wind_kmh"] is None
    assert result["shaking_class"] == result["wind_class"] == "Not applicable"


def test_nested_bands_use_annular_area_not_repeated_population():
    deaths, damage = band_losses(1000, 100, 10, [Band(5, .5, .8), Band(10, .1, .2)], [])
    assert deaths == pytest.approx(200)
    assert damage == pytest.approx(35000)


def test_overlapping_effects_combine_survival_and_cap_asset_loss():
    deaths, damage = band_losses(1000, 100, 10, [Band(10, .5, .8)], [Band(10, .5, .6)])
    assert deaths == 750
    assert damage == 80000


def test_bands_bigger_than_disc_never_exceed_exposure():
    assert band_losses(1000, 100, 10, [Band(100, 1, 1)], []) == (1000, 100000)


def test_no_affected_radius_means_zero_loss():
    assert band_losses(1000, 100, 10, [], []) == (0, 0)


@pytest.fixture
def city():
    return {"population": 1_000_000, "gem_level": "region", "occupants": 2_000_000,
            "repl_cost_per_occupant_usd": 50_000}


@pytest.mark.parametrize("diameter", [1., 20., 140., 1000.])
def test_real_physics_energy_and_limits(diameter, city):
    asteroid = {"diameter_m": diameter, "entry_speed_kms": 20.}
    result = simulate(asteroid, city)
    expected_mt = .5 * (math.pi / 6 * 2600 * diameter**3) * 20000**2 / 4.184e15
    assert result["energy_mt"] == pytest.approx(expected_mt, rel=.001)
    assert 0 <= result["deaths"] <= 2_000_000
    assert 0 <= result["damage_usd"] <= 100_000_000_000
    assert result["exposed_population"] == 2_000_000
    assert math.isfinite(result["peak_wind_kmh"])


def test_airburst_has_no_ground_seismic_magnitude_or_surface_fireball():
    result = profile(20., 20.)
    assert result.burst_altitude_m > 20_000
    assert result.magnitude is None
    assert result.thermal == ()
    assert result.peak_wind_kmh == pytest.approx(17.5391207531)


def test_thermal_beyond_horizon_is_zero():
    assert effects(140., 20., 2000.)[2] == 0


def test_country_exposure_uses_city_population(city):
    city.update(gem_level="country", occupants=None)
    result = simulate({"diameter_m": 1000., "entry_speed_kms": 20.}, city)
    assert result["exposed_population"] == 1_000_000
    assert result["deaths"] <= 1_000_000


@pytest.mark.parametrize("field,value", [("occupants", None), ("occupants", -1),
    ("occupants", float("nan")), ("repl_cost_per_occupant_usd", None), ("population", -1)])
def test_invalid_exposure_is_rejected(city, field, value):
    city[field] = value
    with pytest.raises(ValueError):
        simulate({"diameter_m": 140., "entry_speed_kms": 20.}, city)


@pytest.mark.parametrize("diameter,speed", [(0,20), (-1,20), (20,0), (float("nan"),20)])
def test_invalid_physics_inputs_are_rejected(diameter, speed, city):
    with pytest.raises(ValueError):
        simulate({"diameter_m": diameter, "entry_speed_kms": speed}, city)


def test_zero_population_has_zero_losses(city):
    city.update(gem_level="country", occupants=None, population=0)
    result = simulate({"diameter_m": 140., "entry_speed_kms": 20.}, city)
    assert result["deaths"] == result["damage_usd"] == 0


def test_probability_does_not_scale_conditional_losses(city):
    asteroid = {"diameter_m": 140., "entry_speed_kms": 20., "impact_probability": 1e-9}
    first = simulate(asteroid, city)
    asteroid["impact_probability"] = 1
    assert simulate(asteroid, city) == first


@pytest.mark.parametrize("asteroid", json.loads(
    (Path(__file__).parent / "fixtures" / "sentry_reference.json").read_text(encoding="utf-8"))["asteroids"])
def test_energy_matches_independent_sentry_reference(asteroid, city):
    ratio = simulate(asteroid, city)["energy_mt"] / asteroid["energy_mt"]
    assert .5 <= ratio <= 2


def test_fractional_gem_occupants_are_never_rounded_up(city):
    city["occupants"] = .8
    assert simulate({"diameter_m": 1000., "entry_speed_kms": 20.}, city)["deaths"] == 0
