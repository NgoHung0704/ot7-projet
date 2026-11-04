import logging
import os
from datetime import UTC, datetime

import mongomock
import openpyxl
import pytest

from ingestion.emdat import EmdatShrinkError, find_latest_file, ingest_emdat, read_workbook
from ingestion.store import CATALOG, RawStore

NOW = datetime(2026, 11, 1, 0, 3, 12, tzinfo=UTC)
HEADER = ["DisNo.", "Country", "Total Deaths", "No. Injured", "Start Year"]
ROWS = [
    ["2026-0153-KEN", "Kenya", 59, "", 2026],
    ["2020-0432-LBN", "Lebanon", 218, 7000, 2020],
    ["2004-0659-IDN", "Indonesia", 165708, "", 2004],
    ["2010-0017-HTI", "Haiti", 222570, 300000, 2010],
]


def make_workbook(path, rows=ROWS, info=True):
    workbook = openpyxl.Workbook()
    data = workbook.active
    data.title = "EM-DAT Data"
    data.append(HEADER)
    for row in rows:
        data.append(row)
    data.append(["", "", "", "", ""])
    if info:
        sheet = workbook.create_sheet("EM-DAT Info")
        sheet.append(["Source:", "EM-DAT, CRED / UCLouvain, Brussels, Belgium"])
        sheet.append(["Version:", "2026-11-01"])
    workbook.save(path)
    return path


def ingest(store, directory):
    return ingest_emdat(store, directory, "2026-11", "manual__1", NOW)


@pytest.fixture
def store():
    return RawStore(mongomock.MongoClient()["raw"])


def test_read_workbook_cleans_keys_and_empties(tmp_path):
    rows, version = read_workbook(make_workbook(tmp_path / "public_emdat_2026-11-02.xlsx"))

    assert version == "2026-11-01"
    assert len(rows) == 4
    assert rows[0]["DisNo"] == "2026-0153-KEN"
    assert rows[0]["No Injured"] is None
    assert rows[1]["Total Deaths"] == 218


def test_version_falls_back_to_file_name_without_info_sheet(tmp_path):
    _, version = read_workbook(make_workbook(tmp_path / "export.xlsx", info=False))
    assert version == "export.xlsx"


def test_newest_file_wins_and_lock_file_is_ignored(tmp_path):
    old = make_workbook(tmp_path / "a.xlsx")
    new = make_workbook(tmp_path / "b.xlsx")
    lock = tmp_path / "~$b.xlsx"
    lock.write_bytes(b"lock")
    os.utime(old, (1_000, 1_000))
    os.utime(new, (2_000, 2_000))
    os.utime(lock, (3_000, 3_000))

    assert find_latest_file(tmp_path) == new


def test_no_file_skips(store, tmp_path):
    assert ingest(store, tmp_path) is None
    assert ingest(store, tmp_path / "missing") is None
    assert store.db[CATALOG].count_documents({}) == 0


def test_same_file_twice_skips_second_time(store, tmp_path, caplog):
    caplog.set_level(logging.INFO, logger="ingestion")
    make_workbook(tmp_path / "public_emdat.xlsx")

    entry = ingest(store, tmp_path)
    assert entry["n_docs"] == 4
    assert "EM-DAT export public_emdat.xlsx: version 2026-11-01, 4 rows" in caplog.text
    assert entry["dataset_version"] == "2026-11-01"
    assert ingest(store, tmp_path) is None
    assert store.db["emdat_events"].count_documents({}) == 4


def test_much_smaller_export_fails(store, tmp_path):
    make_workbook(tmp_path / "public_emdat.xlsx")
    ingest(store, tmp_path)
    make_workbook(tmp_path / "public_emdat.xlsx", rows=ROWS[:1])

    with pytest.raises(EmdatShrinkError):
        ingest(store, tmp_path)
    assert len(store.read_latest("emdat_events")) == 4
