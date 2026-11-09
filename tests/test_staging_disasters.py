from datetime import date

from staging.disasters import build_disasters, start_date

ROW = {
    "DisNo": "2020-0432-LBN", "Event Name": "Beirut explosion", "Disaster Group": "Technological",
    "Disaster Subgroup": "Industrial accident", "Disaster Type": "Explosion (Industrial)", "Disaster Subtype": None,
    "ISO": "LBN", "Country": "Lebanon", "Subregion": "Western Asia", "Region": "Asia",
    "Start Year": 2020, "Start Month": 8, "Start Day": 4,
    "Total Deaths": 218.0, "Total Damage ('000 US$)": 1500, "Total Damage, Adjusted ('000 US$)": 1500.4,
    "Magnitude": None, "Magnitude Scale": None, "Latitude": "33.9", "Longitude": None,
}


def test_start_date_precision():
    assert start_date(2020, 8, 4) == (date(2020, 8, 4), "day")
    assert start_date(2020, 8, None) == (date(2020, 8, 1), "month")
    assert start_date(1931, None, None) == (date(1931, 1, 1), "year")
    assert start_date(None, 8, 4) == (None, None)


def test_deaths_and_damage():
    rows, rejects = build_disasters([ROW, ROW | {"DisNo": "x", "Total Deaths": None, "Total Damage ('000 US$)": None}])

    assert rejects == []
    beirut, unknown = rows
    assert beirut["deaths"] == 218
    assert beirut["damage_usd"] == 1_500_000
    assert beirut["damage_adjusted_usd"] == 1_500_400
    assert beirut["start_date"] == date(2020, 8, 4) and beirut["date_precision"] == "day"
    assert beirut["latitude"] == 33.9 and beirut["longitude"] is None
    assert unknown["deaths"] is None and unknown["damage_usd"] is None


def test_historical_country_kept():
    rows, _ = build_disasters([ROW | {"DisNo": "1986-0001-SUN", "ISO": "SUN", "Country": "Soviet Union"}])
    assert (rows[0]["iso3"], rows[0]["country"]) == ("SUN", "Soviet Union")


def test_missing_year_is_quarantined():
    rows, rejects = build_disasters([ROW | {"Start Year": None}])
    assert rows == []
    assert [(r["natural_key"], r["check_name"]) for r in rejects] == [("2020-0432-LBN", "conversion")]
