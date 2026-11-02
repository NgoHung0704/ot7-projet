"""Helpers shared by every source: batch and load ids, hashing, record cleaning, HTTP session."""

import hashlib
from datetime import datetime

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

USER_AGENT = "ot7-projet-ingestion (+https://github.com/NgoHung0704/ot7-projet)"


def batch_id_for(when: datetime) -> str:
    """A batch is one collection month: 2026-11."""
    return when.strftime("%Y-%m")


def new_load_id(collection: str, batch_id: str, now: datetime) -> str:
    """Identifies one write of a batch; changes on every re-run, even within the same Airflow run."""
    return f"{collection}/{batch_id}/{now:%Y%m%dT%H%M%S%f}Z"


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def clean_record(record: dict) -> dict:
    """File rows only: MongoDB handles dots in field names badly, and empty cells mean no value."""
    return {key.replace(".", ""): (None if value == "" else value) for key, value in record.items()}


def make_session() -> requests.Session:
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    # Server errors only: a rate-limit answer (403/429) needs minutes, not seconds, and is
    # handled by the caller (see ingestion.sentry).
    retry = Retry(
        total=5,
        backoff_factor=1,
        status_forcelist=(500, 502, 503, 504),
        allowed_methods=("GET",),
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session
