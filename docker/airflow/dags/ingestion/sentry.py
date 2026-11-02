"""NASA/JPL Sentry API: asteroid list (mode S), removed objects (mode R) and one detail call per asteroid (mode O)."""

import logging
import time
from datetime import datetime

import requests

from ingestion.common import sha256_hex
from ingestion.store import RawStore

SENTRY_URL = "https://ssd-api.jpl.nasa.gov/sentry.api"
EXPECTED_MAJOR = "2"

log = logging.getLogger(__name__)


class SentryFormatError(RuntimeError):
    pass


def check_version(payload: dict) -> str:
    """The API says its format can change at any time: stop on a new major version."""
    version = str(payload.get("signature", {}).get("version", ""))
    if version.split(".")[0] != EXPECTED_MAJOR:
        raise SentryFormatError(
            f"Sentry API version {version!r}, expected {EXPECTED_MAJOR}.x: check the format before ingesting"
        )
    return version


def _get(session: requests.Session, params: dict) -> tuple[dict, str, str]:
    response = session.get(SENTRY_URL, params=params, timeout=60)
    response.raise_for_status()
    return response.json(), response.url, sha256_hex(response.content)


def ingest_sentry(
    store: RawStore, session: requests.Session, batch_id: str, run_id: str, now: datetime, pause_s: float = 0.1
) -> dict[str, int]:
    listing, url, digest = _get(session, {})
    version = check_version(listing)
    store.write_batch(
        "sentry_objects", batch_id, listing["data"],
        {"url": url, "dataset_version": version, "sha256": digest}, run_id, now,
    )

    removed, url, digest = _get(session, {"removed": "1"})
    check_version(removed)
    store.write_batch(
        "sentry_removed", batch_id, removed["data"],
        {"url": url, "dataset_version": version, "sha256": digest}, run_id, now,
    )

    # One call at a time: JPL asks clients not to send parallel requests.
    details, removed_during_run = [], 0
    for index, obj in enumerate(listing["data"]):
        if index and pause_s:
            time.sleep(pause_s)
        payload, url, digest = _get(session, {"des": obj["des"]})
        if "error" in payload:
            log.warning("Sentry object %s skipped: %s", obj["des"], payload["error"])
            removed_during_run += 1
            continue
        details.append({**payload, "_meta": {"url": url, "sha256": digest}})
    store.write_batch("sentry_details", batch_id, details, {"dataset_version": version}, run_id, now)

    return {
        "sentry_objects": len(listing["data"]),
        "sentry_removed": len(removed["data"]),
        "sentry_details": len(details),
        "removed_during_run": removed_during_run,
    }
