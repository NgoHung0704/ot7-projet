import logging
from datetime import UTC, datetime

import mongomock
import pytest

from ingestion.store import CATALOG, RawStore

NOW = datetime(2026, 11, 1, 0, 3, 12, tzinfo=UTC)
META = {"url": "https://example.org/api", "dataset_version": "2.0", "sha256": "abc"}


@pytest.fixture
def store():
    return RawStore(mongomock.MongoClient()["raw"])


def write(store, docs, batch_id="2026-11", now=NOW):
    return store.write_batch("sentry_objects", batch_id, docs, META, run_id="manual__1", now=now)


def test_write_batch_stores_docs_with_meta_and_catalog(store):
    entry = write(store, [{"des": "a"}, {"des": "b"}])

    docs = store.read_latest("sentry_objects")
    assert sorted(doc["des"] for doc in docs) == ["a", "b"]
    meta = docs[0]["_meta"]
    assert meta["source"] == "sentry_objects"
    assert meta["batch_id"] == "2026-11"
    assert meta["run_id"] == "manual__1"
    assert meta["url"] == META["url"]
    assert meta["load_id"] == entry["load_id"]
    assert entry["_id"] == "sentry_objects/2026-11"
    assert entry["status"] == "complete"
    assert entry["n_docs"] == 2
    assert store.db[CATALOG].find_one({"_id": "sentry_objects/2026-11"})["load_id"] == entry["load_id"]


def test_rewrite_same_month_replaces_without_duplicates(store, caplog):
    caplog.set_level(logging.INFO, logger="ingestion")
    write(store, [{"des": "a"}, {"des": "b"}])
    entry = write(store, [{"des": "a"}, {"des": "b"}, {"des": "c"}], now=NOW.replace(minute=4))

    assert store.db["sentry_objects"].count_documents({}) == 3
    assert len(store.read_latest("sentry_objects")) == 3
    assert entry["n_docs"] == 3
    assert "sentry_objects 2026-11: wrote 3 docs, removed 2 superseded" in caplog.text


def test_other_months_are_kept(store):
    write(store, [{"des": "a"}], batch_id="2026-10")
    write(store, [{"des": "a"}], batch_id="2026-11")

    assert store.db["sentry_objects"].count_documents({}) == 2
    assert store.latest_complete("sentry_objects")["batch_id"] == "2026-11"


def test_doc_meta_overrides_common_meta_without_mutating_input(store):
    doc = {"des": "a", "_meta": {"url": "u1", "sha256": "s1"}}
    write(store, [doc])

    meta = store.read_latest("sentry_objects")[0]["_meta"]
    assert (meta["url"], meta["sha256"], meta["dataset_version"]) == ("u1", "s1", "2.0")
    assert doc == {"des": "a", "_meta": {"url": "u1", "sha256": "s1"}}


def test_crash_after_insert_keeps_previous_load_visible(store, monkeypatch):
    first = write(store, [{"des": "a"}])
    original = mongomock.collection.Collection.insert_many

    def insert_then_crash(self, documents, *args, **kwargs):
        original(self, documents, *args, **kwargs)
        raise RuntimeError("crash after insert")

    monkeypatch.setattr(mongomock.collection.Collection, "insert_many", insert_then_crash)
    with pytest.raises(RuntimeError):
        write(store, [{"des": "b"}], now=NOW.replace(minute=5))
    monkeypatch.undo()

    assert [doc["des"] for doc in store.read_latest("sentry_objects")] == ["a"]
    assert store.latest_complete("sentry_objects")["load_id"] == first["load_id"]
