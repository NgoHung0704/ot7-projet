import io
import zipfile
from datetime import UTC, datetime

import mongomock
import pytest
import requests
import responses

from ingestion.geonames import BASE_URL, CITY_COLUMNS, ingest_geonames, parse_country_info, parse_tsv
from ingestion.store import RawStore

NOW = datetime(2026, 11, 1, 0, 3, 12, tzinfo=UTC)
LAST_MODIFIED = "Sun, 01 Nov 2026 01:00:00 GMT"
CITIES_TXT = (
    "2988507\tParis\tParis\tLutece,Paris\t48.85341\t2.3488\tP\tPPLC\tFR\t\t11\t75\t751\t75056"
    "\t2133111\t\t42\tEurope/Paris\t2024-06-01\n"
    "2643743\tLondon\tLondon\t\t51.50853\t-0.12574\tP\tPPLC\tGB\t\tENG\tGLA\t\t"
    "\t8961989\t\t25\tEurope/London\t2024-01-01\n"
)
COUNTRY_TXT = "# GeoNames country info\n#\n#ISO\tISO3\tISO-Numeric\tfips\tCountry\nAD\tAND\t020\tAN\tAndorra\n"
ADMIN1_TXT = "AD.06\tSant Julià de Loria\tSant Julia de Loria\t3039162\nAD.05\tOrdino\tOrdino\t3039676\n"


def cities_zip():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("cities15000.txt", CITIES_TXT)
    return buffer.getvalue()


def mock_files(rsps):
    for name, body in (
        ("cities15000.zip", cities_zip()),
        ("countryInfo.txt", COUNTRY_TXT.encode()),
        ("admin1CodesASCII.txt", ADMIN1_TXT.encode()),
    ):
        rsps.add(responses.GET, BASE_URL + name, body=body, headers={"Last-Modified": LAST_MODIFIED})


def run(store):
    return ingest_geonames(store, requests.Session(), "2026-11", "manual__1", NOW)


@pytest.fixture
def store():
    return RawStore(mongomock.MongoClient()["raw"])


def test_parse_tsv_names_columns_and_nulls():
    rows = parse_tsv(CITIES_TXT, CITY_COLUMNS)

    assert len(rows) == 2
    assert rows[0]["geonameid"] == "2988507"
    assert rows[0]["feature code"] == "PPLC"
    assert rows[0]["population"] == "2133111"
    assert rows[0]["cc2"] is None


def test_parse_tsv_rejects_wrong_column_count():
    with pytest.raises(ValueError):
        parse_tsv("2988507\tParis\n", CITY_COLUMNS)


def test_parse_country_info_uses_file_header():
    assert parse_country_info(COUNTRY_TXT) == [
        {"ISO": "AD", "ISO3": "AND", "ISO-Numeric": "020", "fips": "AN", "Country": "Andorra"}
    ]


def test_ingest_writes_three_collections(store):
    with responses.RequestsMock() as rsps:
        mock_files(rsps)
        counts = run(store)

    assert counts == {"geonames_cities": 2, "geonames_countries": 1, "geonames_admin1": 2}
    admin1 = store.read_latest("geonames_admin1")
    assert {row["code"] for row in admin1} == {"AD.06", "AD.05"}
    assert admin1[0]["_meta"]["dataset_version"] == LAST_MODIFIED


def test_unchanged_files_are_skipped(store):
    with responses.RequestsMock() as rsps:
        mock_files(rsps)
        run(store)
    with responses.RequestsMock() as rsps:
        mock_files(rsps)
        assert run(store) == {}

    assert store.db["geonames_cities"].count_documents({}) == 2
