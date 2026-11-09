"""One staging step: read the latest raw batches, rebuild the tables in one transaction, or say why not."""

import logging
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field

from ingestion.store import RawStore
from staging.asteroids import ASTEROID_COLUMNS, REMOVED_COLUMNS, build_asteroids, build_removed
from staging.cities import CITY_COLUMNS, build_cities
from staging.disasters import DISASTER_COLUMNS, build_disasters
from staging.quality import check_reject_rate
from staging.warehouse import (
    ensure_schema,
    last_inputs,
    record_inputs,
    replace_quarantine,
    replace_table,
    transaction,
)

# Table whose row count the reject rate of each source is measured against
CHECKED_TABLE = {"sentry": "stg_asteroid", "emdat": "stg_disaster", "cities": "stg_city"}

log = logging.getLogger(__name__)

Tables = dict[str, tuple[list[str], list[dict]]]
Build = Callable[[dict[str, list[dict]]], tuple[Tables, dict[str, list[dict]]]]


@dataclass
class StageResult:
    status: str  # built | unchanged | waiting
    detail: str
    counts: dict[str, int] = field(default_factory=dict)


def asteroid_tables(data: dict[str, list[dict]]):
    rows, rejects = build_asteroids(data["sentry_objects"], data["sentry_details"])
    removed = build_removed(data["sentry_removed"])
    return {"stg_asteroid": (ASTEROID_COLUMNS, rows), "stg_asteroid_removed": (REMOVED_COLUMNS, removed)}, {
        "sentry": rejects}


def disaster_tables(data: dict[str, list[dict]]):
    rows, rejects = build_disasters(data["emdat_events"])
    return {"stg_disaster": (DISASTER_COLUMNS, rows)}, {"emdat": rejects}


def city_tables(data: dict[str, list[dict]], per_continent: int, capital_min_population: int):
    rows, rejects = build_cities(data["geonames_cities"], data["geonames_countries"], data["geonames_admin1"],
                                 data["gem_exposure_adm1"], per_continent, capital_min_population)
    return {"stg_city": (CITY_COLUMNS, rows)}, {"cities": rejects}


def stage(conn, store: RawStore, task: str, inputs: list[str], build: Build, run_id: str,
          max_reject_rate: float, force: bool = False) -> StageResult:
    """`force` rebuilds even when the raw inputs did not change (after a fix in the staging code)."""
    entries = {collection: store.latest_complete(collection) for collection in inputs}
    missing = [collection for collection, entry in entries.items() if entry is None]
    if missing:
        return StageResult("waiting", f"waiting for raw {', '.join(missing)}: no complete batch yet")

    # An empty batch (an API answering []) must not wipe a table and wake up the steps downstream
    empty = [f"{collection} (batch {entry['batch_id']})" for collection, entry in entries.items() if not entry["n_docs"]]
    if empty:
        return StageResult("waiting", f"raw {', '.join(empty)} is empty: nothing to build")

    load_ids = {collection: entry["load_id"] for collection, entry in entries.items()}
    if not force and last_inputs(conn, task) == load_ids:
        return StageResult("unchanged", f"raw inputs unchanged since the last build: {', '.join(inputs)}")

    data = {}
    for collection, entry in entries.items():
        data[collection] = store.read_latest(collection)
        log.info("Read %s batch %s: %d docs", collection, entry["batch_id"], len(data[collection]))

    tables, rejects_by_source = build(data)
    for source, rejects in rejects_by_source.items():
        check_reject_rate(source, len(tables[CHECKED_TABLE[source]][1]), len(rejects), max_reject_rate)

    with transaction(conn):
        ensure_schema(conn)
        counts = {table: replace_table(conn, table, columns, rows) for table, (columns, rows) in tables.items()}
        for source, rejects in rejects_by_source.items():
            replace_quarantine(conn, source, rejects, run_id)
        record_inputs(conn, task, load_ids)

    for table, count in counts.items():
        log.info("staging.%s: wrote %d rows", table, count)
    for source, rejects in rejects_by_source.items():
        log.info("%s: %d rows quarantined %s", source, len(rejects), dict(Counter(r["check_name"] for r in rejects)))
    return StageResult("built", f"built {', '.join(counts)}", counts)
