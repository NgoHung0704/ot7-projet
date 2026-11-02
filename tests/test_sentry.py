from datetime import UTC, datetime

import mongomock
import pytest
import requests
import responses
from responses import matchers

from ingestion.sentry import SENTRY_URL, SentryFormatError, ingest_sentry
from ingestion.store import CATALOG, RawStore

NOW = datetime(2026, 11, 1, 0, 3, 12, tzinfo=UTC)
SIGNATURE = {"source": "NASA/JPL Sentry Data API", "version": "2.0"}
REMOVED = {"signature": SIGNATURE, "count": "1", "data": [{"des": "2026 VA", "removed": "2026-11-02 14:22:18"}]}


def listing(*designations, signature=SIGNATURE):
    data = [{"des": des, "ip": "1.4e-05", "v_inf": "10.1"} for des in designations]
    return {"signature": signature, "count": str(len(data)), "data": data}


def detail(des):
    return {
        "signature": SIGNATURE,
        "summary": {"des": des, "mass": "1.2e9", "v_imp": "20.1", "energy": "3.4"},
        "data": [{"date": "2090-01-01.12", "ip": "1e-06", "energy": "3.4"}],
    }


def mock_api(rsps, designations, details, signature=SIGNATURE):
    rsps.add(responses.GET, SENTRY_URL, match=[matchers.query_param_matcher({})],
             json=listing(*designations, signature=signature))
    rsps.add(responses.GET, SENTRY_URL, match=[matchers.query_param_matcher({"removed": "1"})], json=REMOVED)
    for des, (status, body) in details.items():
        rsps.add(responses.GET, SENTRY_URL, match=[matchers.query_param_matcher({"des": des})],
                 json=body, status=status)


def run(store):
    return ingest_sentry(store, requests.Session(), "2026-11", "manual__1", NOW, pause_s=0)


@pytest.fixture
def store():
    return RawStore(mongomock.MongoClient()["raw"])


def test_ingest_writes_three_collections(store):
    with responses.RequestsMock() as rsps:
        mock_api(rsps, ["2011 TO", "29075"], {"2011 TO": (200, detail("2011 TO")), "29075": (200, detail("29075"))})
        counts = run(store)

    assert counts == {"sentry_objects": 2, "sentry_removed": 1, "sentry_details": 2, "removed_during_run": 0}
    assert {doc["des"] for doc in store.read_latest("sentry_objects")} == {"2011 TO", "29075"}
    assert store.read_latest("sentry_removed")[0]["removed"] == "2026-11-02 14:22:18"
    detail_doc = next(d for d in store.read_latest("sentry_details") if d["summary"]["des"] == "2011 TO")
    assert detail_doc["summary"]["mass"] == "1.2e9"
    assert detail_doc["data"][0]["date"] == "2090-01-01.12"
    assert detail_doc["_meta"]["dataset_version"] == "2.0"
    assert "des=2011" in detail_doc["_meta"]["url"]


def test_object_removed_between_calls_is_skipped(store):
    gone = {"signature": SIGNATURE, "error": "specified object removed", "removed": "2026-11-02 14:22:18"}
    with responses.RequestsMock() as rsps:
        mock_api(rsps, ["2011 TO", "2026 VA"], {"2011 TO": (200, detail("2011 TO")), "2026 VA": (200, gone)})
        counts = run(store)

    assert counts["sentry_details"] == 1
    assert counts["removed_during_run"] == 1
    assert [d["summary"]["des"] for d in store.read_latest("sentry_details")] == ["2011 TO"]


def test_unknown_major_version_fails(store):
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        mock_api(rsps, ["2011 TO"], {"2011 TO": (200, detail("2011 TO"))},
                 signature={"source": "NASA/JPL Sentry Data API", "version": "3.0"})
        with pytest.raises(SentryFormatError):
            run(store)

    assert store.db[CATALOG].count_documents({}) == 0


def test_network_failure_keeps_previous_details(store):
    with responses.RequestsMock() as rsps:
        mock_api(rsps, ["2011 TO", "29075"], {"2011 TO": (200, detail("2011 TO")), "29075": (200, detail("29075"))})
        run(store)
    first_load = store.latest_complete("sentry_details")["load_id"]

    with responses.RequestsMock() as rsps:
        mock_api(rsps, ["2011 TO", "29075"], {"2011 TO": (200, detail("2011 TO")), "29075": (503, {})})
        with pytest.raises(requests.HTTPError):
            run(store)

    assert store.latest_complete("sentry_details")["load_id"] == first_load
    assert len(store.read_latest("sentry_details")) == 2
