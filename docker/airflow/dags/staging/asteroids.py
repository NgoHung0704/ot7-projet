"""Sentry raw documents → stg_asteroid and stg_asteroid_removed rows."""

from datetime import date, datetime

from staging.convert import to_float, to_int
from staging.quality import reject

SOURCE = "sentry"
ASTEROID_COLUMNS = [
    "des", "fullname", "diameter_m", "mass_kg", "entry_speed_kms", "energy_mt",
    "impact_probability", "impact_date", "n_impacts", "last_obs",
]
REMOVED_COLUMNS = ["des", "removed_at"]


def parse_sentry_date(value: str | None) -> date | None:
    """Sentry dates carry a fraction of day: "2090-01-01.12" → 2090-01-01."""
    try:
        return datetime.strptime(str(value).split(".")[0], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def most_probable_impact(vis: list[dict]) -> dict | None:
    candidates = [vi for vi in vis if to_float(vi.get("ip")) is not None]
    return max(candidates, key=lambda vi: to_float(vi["ip"]), default=None)


def build_asteroids(objects: list[dict], details: list[dict]) -> tuple[list[dict], list[dict]]:
    by_des = {doc["summary"]["des"]: doc for doc in details if "summary" in doc}
    rows, rejects = [], []
    for obj in objects:
        des = obj["des"]
        detail = by_des.get(des)
        if detail is None:
            rejects.append(reject(SOURCE, des, "missing_data", "no detail document (removed during ingestion?)", obj))
            continue
        summary = detail["summary"]
        diameter_km, mass, speed = (to_float(summary.get(key)) for key in ("diameter", "mass", "v_imp"))
        if None in (diameter_km, mass, speed):
            rejects.append(reject(SOURCE, des, "missing_data", "diameter, mass or v_imp missing", detail))
            continue
        impact = most_probable_impact(detail.get("data", []))
        impact_date = parse_sentry_date(impact["date"]) if impact else None
        if impact_date is None:
            rejects.append(reject(SOURCE, des, "conversion", "no readable impact date", detail))
            continue
        rows.append({
            "des": des,
            "fullname": " ".join(str(obj.get("fullname") or des).split()),
            "diameter_m": diameter_km * 1000,
            "mass_kg": mass,
            "entry_speed_kms": speed,
            "energy_mt": to_float(summary.get("energy")),
            "impact_probability": to_float(obj.get("ip")),
            "impact_date": impact_date,
            "n_impacts": to_int(obj.get("n_imp")),
            "last_obs": parse_sentry_date(obj.get("last_obs")),
        })
    return rows, rejects


def build_removed(removed: list[dict]) -> list[dict]:
    return [
        {"des": doc["des"], "removed_at": datetime.strptime(doc["removed"], "%Y-%m-%d %H:%M:%S")}
        for doc in removed
    ]
