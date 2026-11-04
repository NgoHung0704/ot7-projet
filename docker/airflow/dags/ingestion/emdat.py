"""EM-DAT: the Excel export is downloaded by hand (an account is required) and dropped in a folder."""

import logging
import os
from datetime import datetime
from pathlib import Path

import openpyxl

from ingestion.common import clean_record, sha256_hex
from ingestion.store import RawStore

COLLECTION = "emdat_events"
DEFAULT_DIR = "/opt/airflow/data/landing/emdat"
DATA_SHEET = "EM-DAT Data"
INFO_SHEET = "EM-DAT Info"

log = logging.getLogger(__name__)


class EmdatShrinkError(RuntimeError):
    pass


def emdat_dir() -> Path:
    return Path(os.environ.get("EMDAT_DIR", DEFAULT_DIR))


def find_latest_file(directory: Path) -> Path | None:
    """Newest .xlsx; `~$…` files are Excel lock files left while the export is open."""
    if not directory.is_dir():
        return None
    files = [path for path in directory.glob("*.xlsx") if not path.name.startswith("~$")]
    return max(files, key=lambda path: path.stat().st_mtime, default=None)


def read_workbook(path: Path) -> tuple[list[dict], str]:
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        if DATA_SHEET not in workbook.sheetnames:
            raise RuntimeError(f"{path.name}: no sheet {DATA_SHEET!r} (sheets: {workbook.sheetnames})")
        sheet = workbook[DATA_SHEET]
        sheet.reset_dimensions()  # the real export declares a 1x1 sheet
        rows = sheet.iter_rows(values_only=True)
        header = next(rows)
        records = [
            clean_record({key: value for key, value in zip(header, row) if key is not None})
            for row in rows
            if any(value not in (None, "") for value in row)
        ]

        version = path.name
        if INFO_SHEET in workbook.sheetnames:
            info = workbook[INFO_SHEET]
            info.reset_dimensions()
            for row in info.iter_rows(values_only=True):
                if len(row) > 1 and isinstance(row[0], str) and row[0].strip() == "Version:" and row[1]:
                    version = str(row[1])
                    break
        return records, version
    finally:
        workbook.close()


def check_not_shrunk(new_count: int, previous_count: int | None) -> None:
    """A filtered export (some years or types only) would silently shrink EM-DAT for staging."""
    if previous_count and new_count < previous_count / 2:
        raise EmdatShrinkError(
            f"EM-DAT export has {new_count} rows, previous batch had {previous_count}: "
            "filtered export? Download the full table again."
        )


def ingest_emdat(store: RawStore, directory: Path, batch_id: str, run_id: str, now: datetime) -> dict | None:
    path = find_latest_file(directory)
    if path is None:
        log.info("No EM-DAT export in %s: download it by hand and drop the .xlsx there", directory)
        return None

    digest = sha256_hex(path.read_bytes())
    previous = store.latest_complete(COLLECTION)
    if previous and previous["sha256"] == digest:
        log.info("EM-DAT export %s already ingested in batch %s", path.name, previous["batch_id"])
        return None

    records, version = read_workbook(path)
    log.info("EM-DAT export %s: version %s, %d rows", path.name, version, len(records))
    check_not_shrunk(len(records), previous["n_docs"] if previous else None)
    meta = {"url": path.resolve().as_uri(), "dataset_version": version, "sha256": digest}
    return store.write_batch(COLLECTION, batch_id, records, meta, run_id, now)
