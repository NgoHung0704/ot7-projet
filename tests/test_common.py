from datetime import UTC, datetime

from ingestion.common import batch_id_for, new_load_id


def test_batch_id_is_year_month():
    assert batch_id_for(datetime(2026, 11, 1, 0, 3, tzinfo=UTC)) == "2026-11"


def test_load_id_is_unique_per_write():
    now = datetime(2026, 11, 1, 0, 3, 12, 123456, tzinfo=UTC)
    assert new_load_id("sentry_objects", "2026-11", now) == "sentry_objects/2026-11/20261101T000312123456Z"
