from datetime import UTC, datetime

from ingestion.common import (
    USER_AGENT,
    batch_id_for,
    clean_record,
    make_session,
    new_load_id,
    sha256_hex,
)


def test_batch_id_is_year_month():
    assert batch_id_for(datetime(2026, 11, 1, 0, 3, tzinfo=UTC)) == "2026-11"


def test_load_id_is_unique_per_write():
    now = datetime(2026, 11, 1, 0, 3, 12, 123456, tzinfo=UTC)
    assert new_load_id("sentry_objects", "2026-11", now) == "sentry_objects/2026-11/20261101T000312123456Z"


def test_sha256_hex():
    assert sha256_hex(b"abc") == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


def test_clean_record_removes_dots_and_empty_strings():
    record = {"DisNo.": "2026-0153-KEN", "No. Injured": "", "Total Deaths": 59}
    assert clean_record(record) == {"DisNo": "2026-0153-KEN", "No Injured": None, "Total Deaths": 59}


def test_session_has_user_agent_and_retries():
    session = make_session()
    assert session.headers["User-Agent"] == USER_AGENT
    assert session.get_adapter("https://example.org").max_retries.total == 5
