"""NASA/JPL Sentry API: asteroid list (mode S), removed objects (mode R) and one detail call per asteroid (mode O)."""

import json
import logging
from datetime import datetime

import requests

from ingestion.common import sha256_hex
from ingestion.store import RawStore

SENTRY_URL = "https://ssd-api.jpl.nasa.gov/sentry.api"
EXPECTED_MAJOR = "2"
REUSED_META = ("url", "sha256", "retrieved_at", "listing_sha256")

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


def listing_fingerprint(record: dict) -> str:
    """Hash of an asteroid's list record: its details are fetched again only when this changes."""
    return sha256_hex(json.dumps(record, sort_keys=True).encode())


def _get(session: requests.Session, params: dict) -> tuple[dict, str, str]:
    response = session.get(SENTRY_URL, params=params, timeout=60)
    response.raise_for_status()
    return response.json(), response.url, sha256_hex(response.content)


def _reuse(doc: dict) -> dict:
    """A detail document from the previous batch, keeping where and when it was fetched."""
    body = {key: value for key, value in doc.items() if key not in ("_id", "_meta")}
    return {**body, "_meta": {key: doc["_meta"][key] for key in REUSED_META}}


def ingest_sentry(
    store: RawStore, session: requests.Session, batch_id: str, run_id: str, now: datetime
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

    # One call at a time (JPL asks clients not to send parallel requests), and only for the
    # asteroids whose list record changed: a few dozen a month instead of ~2,200.
    previous = {doc["_meta"].get("listing_sha256"): doc for doc in store.read_latest("sentry_details")}
    details, fetched, reused, removed_during_run = [], 0, 0, 0
    for obj in listing["data"]:
        fingerprint = listing_fingerprint(obj)
        if fingerprint in previous:
            details.append(_reuse(previous[fingerprint]))
            reused += 1
            continue
        payload, url, digest = _get(session, {"des": obj["des"]})
        if "error" in payload:
            log.warning("Sentry object %s skipped: %s", obj["des"], payload["error"])
            removed_during_run += 1
            continue
        details.append({**payload, "_meta": {"url": url, "sha256": digest, "listing_sha256": fingerprint}})
        fetched += 1
    store.write_batch("sentry_details", batch_id, details, {"dataset_version": version}, run_id, now)
    log.info("Sentry details: %d fetched, %d re-used from the previous batch", fetched, reused)

    return {
        "sentry_objects": len(listing["data"]),
        "sentry_removed": len(removed["data"]),
        "sentry_details": len(details),
        "details_fetched": fetched,
        "details_reused": reused,
        "removed_during_run": removed_during_run,
    }
