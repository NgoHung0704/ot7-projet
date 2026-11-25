"""GEM Global Exposure Model: building occupants and replacement cost per admin-1 region, one CSV per country."""

import csv
import io
import logging
from datetime import datetime

import requests

from ingestion.common import clean_record, sha256_hex
from ingestion.store import RawStore

API_URL = "https://api.github.com/repos/gem/global_exposure_model"
RAW_URL = "https://raw.githubusercontent.com/gem/global_exposure_model"
COLLECTION = "gem_exposure_adm1"
ADM1_SUFFIX = "summaries/Exposure_Summary_Adm1.csv"
WORLD_PREFIX = "World/"  # aggregate of every country: its regions are already in the country files

log = logging.getLogger(__name__)


def latest_commit(session: requests.Session) -> str:
    response = session.get(f"{API_URL}/commits/main", timeout=60)
    response.raise_for_status()
    return response.json()["sha"]


def adm1_paths(session: requests.Session, sha: str) -> list[str]:
    response = session.get(f"{API_URL}/git/trees/{sha}", params={"recursive": "1"}, timeout=60)
    response.raise_for_status()
    tree = response.json()
    if tree.get("truncated"):
        raise RuntimeError(f"gem/global_exposure_model@{sha}: file tree truncated by GitHub")
    paths = sorted(
        entry["path"] for entry in tree["tree"]
        if entry["type"] == "blob" and entry["path"].endswith(ADM1_SUFFIX) and not entry["path"].startswith(WORLD_PREFIX)
    )
    if not paths:
        raise RuntimeError(f"no {ADM1_SUFFIX} in gem/global_exposure_model@{sha}: repository layout changed?")
    return paths


def parse_csv(text: str) -> list[dict]:
    return [clean_record(row) for row in csv.DictReader(io.StringIO(text))]


def ingest_gem(store: RawStore, session: requests.Session, batch_id: str, run_id: str, now: datetime) -> int | None:
    """Returns the document count, or None when the repository has not changed since the last batch."""
    sha = latest_commit(session)
    previous = store.latest_complete(COLLECTION)
    if previous and previous["dataset_version"] == sha:
        log.info("GEM unchanged since batch %s (commit %s)", previous["batch_id"], sha[:10])
        return None

    paths = adm1_paths(session, sha)
    log.info("GEM commit %s: downloading %d admin-1 files", sha[:10], len(paths))
    docs = []
    for path in paths:
        response = session.get(f"{RAW_URL}/{sha}/{path}", timeout=60)
        response.raise_for_status()
        meta = {"url": response.url, "sha256": sha256_hex(response.content)}
        docs.extend({**row, "_meta": meta} for row in parse_csv(response.content.decode("utf-8-sig")))
    store.write_batch(COLLECTION, batch_id, docs, {"dataset_version": sha}, run_id, now)
    return len(docs)
