from datetime import UTC, datetime

import mongomock
import pytest
import requests
import responses
from responses import matchers
from responses.registries import OrderedRegistry

from ingestion.common import make_session
from ingestion.sentry import SENTRY_URL, SentryFormatError, ingest_sentry
from ingestion.store import CATALOG, RawStore

NOW = datetime(2026, 11, 1, 0, 3, 12, tzinfo=UTC)
SIGNATURE = {"source": "NASA/JPL Sentry Data API", "version": "2.0"}
REMOVED = {"signature": SIGNATURE, "count": "1", "data": [{"des": "2026 VA", "removed": "2026-11-02 14:22:18"}]}


def listing(*designations, signature=SIGNATURE, changed=()):
    data = [{"des": des, "ip": "9.9e-04" if des in changed else "1.4e-05", "v_inf": "10.1"} for des in designations]
    return {"signature": signature, "count": str(len(data)), "data": data}


def detail(des):
    return {
        "signature": SIGNATURE,
        "summary": {"des": des, "mass": "1.2e9", "v_imp": "20.1", "energy": "3.4"},
        "data": [{"date": "2090-01-01.12", "ip": "1e-06", "energy": "3.4"}],
    }


def mock_api(rsps, designations, details, signature=SIGNATURE, changed=()):
    rsps.add(responses.GET, SENTRY_URL, match=[matchers.query_param_matcher({})],
             json=listing(*designations, signature=signature, changed=changed))
    rsps.add(responses.GET, SENTRY_URL, match=[matchers.query_param_matcher({"removed": "1"})], json=REMOVED)
    for des, (status, body) in details.items():
        rsps.add(responses.GET, SENTRY_URL, match=[matchers.query_param_matcher({"des": des})],
                 json=body, status=status)


def run(store, now=NOW, min_interval_s=0.0):
    return ingest_sentry(store, requests.Session(), "2026-11", "manual__1", now, min_interval_s=min_interval_s)


@pytest.fixture
def sleeps(monkeypatch):
    calls = []
    monkeypatch.setattr("ingestion.sentry.time.sleep", calls.append)
    return calls


@pytest.fixture
def store():
    return RawStore(mongomock.MongoClient()["raw"])


def test_ingest_writes_three_collections(store):
    with responses.RequestsMock() as rsps:
        mock_api(rsps, ["2011 TO", "29075"], {"2011 TO": (200, detail("2011 TO")), "29075": (200, detail("29075"))})
        counts = run(store)

    assert counts == {
        "sentry_objects": 2,
        "sentry_removed": 1,
        "sentry_details": 2,
        "details_fetched": 2,
        "details_reused": 0,
        "removed_during_run": 0,
    }
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


def test_unchanged_objects_reuse_previous_details(store):
    with responses.RequestsMock() as rsps:
        mock_api(rsps, ["2011 TO", "29075"], {"2011 TO": (200, detail("2011 TO")), "29075": (200, detail("29075"))})
        run(store)
    first = {d["summary"]["des"]: d["_meta"] for d in store.read_latest("sentry_details")}

    # "2011 TO" unchanged: no detail call registered for it, so fetching it would fail the test
    with responses.RequestsMock() as rsps:
        mock_api(rsps, ["2011 TO", "29075", "2026 AB"],
                 {"29075": (200, detail("29075")), "2026 AB": (200, detail("2026 AB"))}, changed={"29075"})
        counts = run(store, now=NOW.replace(day=2))

    assert (counts["sentry_details"], counts["details_fetched"], counts["details_reused"]) == (3, 2, 1)
    reused = next(d for d in store.read_latest("sentry_details") if d["summary"]["des"] == "2011 TO")
    assert reused["data"][0]["date"] == "2090-01-01.12"
    assert reused["_meta"]["url"] == first["2011 TO"]["url"]
    assert reused["_meta"]["retrieved_at"] == first["2011 TO"]["retrieved_at"]
    assert reused["_meta"]["load_id"] != first["2011 TO"]["load_id"]


def test_details_lost_in_a_failed_run_are_fetched_again(store):
    with responses.RequestsMock() as rsps:
        mock_api(rsps, ["2011 TO", "29075"], {"2011 TO": (200, detail("2011 TO")), "29075": (200, detail("29075"))})
        run(store)
    with responses.RequestsMock() as rsps:
        mock_api(rsps, ["2011 TO", "29075"], {"29075": (503, {})}, changed={"29075"})
        with pytest.raises(requests.HTTPError):
            run(store)

    with responses.RequestsMock() as rsps:
        mock_api(rsps, ["2011 TO", "29075"], {"29075": (200, detail("29075"))}, changed={"29075"})
        counts = run(store)

    assert (counts["details_fetched"], counts["details_reused"]) == (1, 1)


def test_detail_calls_are_spaced(store, sleeps):
    with responses.RequestsMock() as rsps:
        mock_api(rsps, ["a", "b", "c"], {des: (200, detail(des)) for des in ["a", "b", "c"]})
        run(store, min_interval_s=0.5)

    assert len(sleeps) == 2
    assert all(0.4 < wait <= 0.5 for wait in sleeps)


def test_blocked_call_waits_then_resumes(store, sleeps):
    with responses.RequestsMock(registry=OrderedRegistry) as rsps:
        mock_api(rsps, ["a", "b"], {"a": (200, detail("a")), "b": (403, {})})
        rsps.add(responses.GET, SENTRY_URL, match=[matchers.query_param_matcher({"des": "b"})], json=detail("b"))
        counts = run(store)

    assert sleeps == [60]
    assert counts["details_fetched"] == 2


def test_sustained_429_through_the_real_session_waits_minutes(store, sleeps):
    with responses.RequestsMock(registry=OrderedRegistry) as rsps:
        mock_api(rsps, ["a"], {"a": (429, {})})
        for _ in range(2):
            rsps.add(responses.GET, SENTRY_URL, match=[matchers.query_param_matcher({"des": "a"})],
                     status=429, json={})
        rsps.add(responses.GET, SENTRY_URL, match=[matchers.query_param_matcher({"des": "a"})], json=detail("a"))
        counts = ingest_sentry(store, make_session(), "2026-11", "manual__1", NOW, min_interval_s=0)

    assert sleeps == [60, 120, 300]
    assert counts["details_fetched"] == 1


def test_still_blocked_after_every_wait_fails(store, sleeps):
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        mock_api(rsps, ["a"], {"a": (403, {})})
        with pytest.raises(requests.HTTPError):
            run(store)

    assert sleeps == [60, 120, 300, 600]


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
    first_loads = {c: store.latest_complete(c)["load_id"] for c in ("sentry_objects", "sentry_removed", "sentry_details")}

    with responses.RequestsMock() as rsps:
        mock_api(rsps, ["2011 TO", "29075"], {"29075": (503, {})}, changed={"29075"})
        with pytest.raises(requests.HTTPError):
            run(store, now=NOW.replace(day=2))

    # The list and the details stay consistent: nothing of the failed run becomes visible
    assert {c: store.latest_complete(c)["load_id"] for c in first_loads} == first_loads
    assert len(store.read_latest("sentry_details")) == 2
