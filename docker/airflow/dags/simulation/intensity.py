"""Keep historical and simulated events comparable without confusing EM-DAT units."""

import math

NOT_APPLICABLE = "Not applicable"


def shaking_class(magnitude: float | None) -> str:
    if magnitude is None or not math.isfinite(magnitude):
        return NOT_APPLICABLE
    if magnitude < 4:
        return "<4"
    if magnitude >= 9:
        return "9+"
    lower = math.floor(magnitude)
    return f"{lower}-{lower + 1}"


def wind_class(kmh: float | None) -> str:
    if kmh is None or not math.isfinite(kmh) or kmh < 0:
        return NOT_APPLICABLE
    for upper, label in [(119, "<119 km/h"), (154, "119-154 km/h"), (178, "154-178 km/h"),
                         (209, "178-209 km/h"), (252, "209-252 km/h")]:
        if kmh < upper:
            return label
    return "252+ km/h"


def historical_intensity(value: float | None, scale: str | None) -> dict:
    valid = value is not None and math.isfinite(value)
    magnitude = value if valid and scale in ("Moment Magnitude", "Richter") else None
    wind = value if valid and value >= 0 and scale == "Kph" else None
    return {"magnitude": magnitude, "max_wind_kmh": wind,
            "shaking_class": shaking_class(magnitude), "wind_class": wind_class(wind)}
