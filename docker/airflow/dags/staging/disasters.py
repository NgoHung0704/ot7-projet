"""EM-DAT raw rows → stg_disaster rows."""

from datetime import date

from staging.convert import to_float, to_int
from staging.quality import reject

SOURCE = "emdat"
DISASTER_COLUMNS = [
    "dis_no", "event_name", "disaster_group", "disaster_subgroup", "disaster_type", "disaster_subtype",
    "iso3", "country", "subregion", "region", "start_date", "date_precision",
    "deaths", "damage_usd", "damage_adjusted_usd", "magnitude", "magnitude_scale", "latitude", "longitude",
]
# stg_disaster column → EM-DAT column, copied as they are
TEXT_FIELDS = {
    "event_name": "Event Name", "disaster_group": "Disaster Group", "disaster_subgroup": "Disaster Subgroup",
    "disaster_type": "Disaster Type", "disaster_subtype": "Disaster Subtype", "iso3": "ISO", "country": "Country",
    "subregion": "Subregion", "region": "Region", "magnitude_scale": "Magnitude Scale",
}


def start_date(year, month, day) -> tuple[date | None, str | None]:
    """EM-DAT often lacks the day or the month: use the 1st and say how precise the date really is."""
    year, month, day = to_int(year), to_int(month), to_int(day)
    for value, precision in ((year, month, day), "day"), ((year, month, 1), "month"), ((year, 1, 1), "year"):
        if None in value:
            continue
        try:
            return date(*value), precision
        except ValueError:
            continue
    return None, None


def thousands(value) -> int | None:
    """EM-DAT damage is in thousands of US$."""
    amount = to_float(value)
    return None if amount is None else round(amount * 1000)


def build_disasters(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    disasters, rejects = [], []
    for row in rows:
        when, precision = start_date(row.get("Start Year"), row.get("Start Month"), row.get("Start Day"))
        if when is None:
            rejects.append(reject(SOURCE, row.get("DisNo"), "conversion", "no readable start year", row))
            continue
        disasters.append({
            "dis_no": row["DisNo"],
            **{column: row.get(field) for column, field in TEXT_FIELDS.items()},
            "start_date": when,
            "date_precision": precision,
            "deaths": to_int(row.get("Total Deaths")),
            "damage_usd": thousands(row.get("Total Damage ('000 US$)")),
            "damage_adjusted_usd": thousands(row.get("Total Damage, Adjusted ('000 US$)")),
            "magnitude": to_float(row.get("Magnitude")),
            "latitude": to_float(row.get("Latitude")),
            "longitude": to_float(row.get("Longitude")),
        })
    return disasters, rejects
