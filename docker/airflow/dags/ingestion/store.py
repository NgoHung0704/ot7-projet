"""Batch writes into the raw MongoDB database, tracked by the ingest_catalog collection."""

from datetime import UTC, datetime

from pymongo.database import Database

from ingestion.common import new_load_id

CATALOG = "ingest_catalog"


class RawStore:
    def __init__(self, db: Database):
        self.db = db

    def latest_complete(self, collection: str) -> dict | None:
        return self.db[CATALOG].find_one(
            {"collection": collection, "status": "complete"}, sort=[("batch_id", -1)]
        )

    def read_latest(self, collection: str) -> list[dict]:
        """The read rule for staging: the documents of the latest complete write."""
        entry = self.latest_complete(collection)
        if entry is None:
            return []
        return list(self.db[collection].find({"_meta.load_id": entry["load_id"]}))

    def write_batch(
        self, collection: str, batch_id: str, docs: list[dict], meta: dict, run_id: str, now: datetime
    ) -> dict:
        """Write first, then switch the catalog, then delete the superseded writes of this batch.

        A reader that follows the catalog never sees a half-written batch. A doc's own `_meta`
        (url, sha256, retrieved_at of a re-used document…) overrides the common `meta`.
        """
        load_id = new_load_id(collection, batch_id, now)
        defaults = {key: meta.get(key) for key in ("url", "dataset_version", "sha256")}
        defaults["retrieved_at"] = now
        fixed = {"source": collection, "batch_id": batch_id, "run_id": run_id, "load_id": load_id}
        stored = [{**doc, "_meta": {**defaults, **doc.get("_meta", {}), **fixed}} for doc in docs]

        target = self.db[collection]
        target.create_index("_meta.load_id")
        if stored:
            target.insert_many(stored)

        entry = {
            "_id": f"{collection}/{batch_id}",
            "collection": collection,
            "batch_id": batch_id,
            "status": "complete",
            "load_id": load_id,
            "n_docs": len(stored),
            "dataset_version": defaults["dataset_version"],
            "sha256": defaults["sha256"],
            "run_id": run_id,
            "started_at": now,
            "finished_at": datetime.now(UTC),
        }
        self.db[CATALOG].replace_one({"_id": entry["_id"]}, entry, upsert=True)
        target.delete_many({"_meta.batch_id": batch_id, "_meta.load_id": {"$ne": load_id}})
        return entry
