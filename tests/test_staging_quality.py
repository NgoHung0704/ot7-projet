import json
from datetime import datetime

import pytest

from staging.quality import StagingQualityError, check_reject_rate, reject


def test_reject_rate():
    check_reject_rate("emdat", 9, 1, 0.10)
    with pytest.raises(StagingQualityError):
        check_reject_rate("emdat", 8, 2, 0.10)
    check_reject_rate("emdat", 0, 0, 0.10)


def test_reject_payload_is_json():
    payload = {"_id": object(), "des": "a", "_meta": {"retrieved_at": datetime(2026, 11, 1, 0, 3)}}
    row = reject("sentry", "a", "missing_data", "no mass", payload)

    assert {k: v for k, v in row.items() if k != "raw_payload"} == {
        "source": "sentry", "natural_key": "a", "check_name": "missing_data", "reason": "no mass",
    }
    stored = json.loads(row["raw_payload"])
    assert "_id" not in stored
    assert stored["_meta"]["retrieved_at"].startswith("2026-11-01")
