"""Rejected rows and the reject-rate guard."""

import json


class StagingQualityError(RuntimeError):
    pass


def reject(source: str, natural_key: str, check_name: str, reason: str, payload: dict) -> dict:
    """A quarantine row; the raw document is kept as JSON (without MongoDB's _id)."""
    body = {key: value for key, value in payload.items() if key != "_id"}
    return {
        "source": source,
        "natural_key": natural_key,
        "check_name": check_name,
        "reason": reason,
        "raw_payload": json.dumps(body, default=str),
    }


def check_reject_rate(source: str, n_ok: int, n_rejected: int, max_rate: float) -> None:
    """So many rejects means the raw format changed: fail instead of loading a shrunken table."""
    total = n_ok + n_rejected
    if total and n_rejected / total > max_rate:
        raise StagingQualityError(
            f"{source}: {n_rejected} of {total} rows rejected (more than {max_rate:.0%}): has the raw format changed?"
        )
