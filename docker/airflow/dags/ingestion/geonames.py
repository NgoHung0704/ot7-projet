"""GeoNames: cities over 15,000 inhabitants, countries, and admin-1 region names (to link cities to GEM regions)."""

import io
import logging
import zipfile
from datetime import datetime

import requests

from ingestion.common import clean_record, sha256_hex
from ingestion.store import RawStore

BASE_URL = "https://download.geonames.org/export/dump/"
# The files have no header row: names from the GeoNames readme.txt
CITY_COLUMNS = [
    "geonameid", "name", "asciiname", "alternatenames", "latitude", "longitude",
    "feature class", "feature code", "country code", "cc2", "admin1 code", "admin2 code",
    "admin3 code", "admin4 code", "population", "elevation", "dem", "timezone", "modification date",
]
ADMIN1_COLUMNS = ["code", "name", "asciiname", "geonameid"]

log = logging.getLogger(__name__)


def parse_tsv(text: str, columns: list[str]) -> list[dict]:
    records = []
    for line in text.splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        fields = line.split("\t")
        if len(fields) != len(columns):
            raise ValueError(f"expected {len(columns)} columns, got {len(fields)}: {line[:80]!r}")
        records.append(clean_record(dict(zip(columns, fields))))
    return records


def parse_country_info(text: str) -> list[dict]:
    """countryInfo.txt carries its header as its last comment line: #ISO, ISO3, …"""
    header = [line for line in text.splitlines() if line.startswith("#ISO")][-1]
    return parse_tsv(text, header.lstrip("#").split("\t"))


def cities_from_zip(blob: bytes) -> list[dict]:
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        return parse_tsv(archive.read("cities15000.txt").decode("utf-8"), CITY_COLUMNS)


def _countries(blob: bytes) -> list[dict]:
    return parse_country_info(blob.decode("utf-8"))


def _admin1(blob: bytes) -> list[dict]:
    return parse_tsv(blob.decode("utf-8"), ADMIN1_COLUMNS)


FILES = (
    ("geonames_cities", "cities15000.zip", cities_from_zip),
    ("geonames_countries", "countryInfo.txt", _countries),
    ("geonames_admin1", "admin1CodesASCII.txt", _admin1),
)


def ingest_geonames(
    store: RawStore, session: requests.Session, batch_id: str, run_id: str, now: datetime
) -> dict[str, int]:
    """Returns the document count of each collection written; {} when no file changed."""
    written = {}
    for collection, name, parse in FILES:
        response = session.get(BASE_URL + name, timeout=120)
        response.raise_for_status()
        digest = sha256_hex(response.content)
        previous = store.latest_complete(collection)
        if previous and previous["sha256"] == digest:
            log.info("GeoNames %s unchanged since batch %s", name, previous["batch_id"])
            continue
        records = parse(response.content)
        meta = {"url": response.url, "dataset_version": response.headers.get("Last-Modified"), "sha256": digest}
        store.write_batch(collection, batch_id, records, meta, run_id, now)
        written[collection] = len(records)
    return written
