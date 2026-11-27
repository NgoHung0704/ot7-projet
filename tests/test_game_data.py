"""Needs a PostgreSQL: the `conn` fixture (conftest.py) reads WAREHOUSE_TEST_DSN."""

from urllib.parse import urlparse

import pytest

import game_data
from conftest import DSN
from game.publish import publish
from test_game_views import PASSWORD, warehouse  # noqa: F401  (fixture)


@pytest.fixture
def reader(warehouse, monkeypatch):  # noqa: F811
    publish(warehouse, PASSWORD)
    url = urlparse(DSN)
    monkeypatch.setenv("GAME_DB_HOST", url.hostname)
    monkeypatch.setenv("GAME_DB_PORT", str(url.port))
    monkeypatch.setenv("GAME_DB_NAME", url.path.lstrip("/"))
    monkeypatch.setenv("GAME_READER_PASSWORD", PASSWORD)
    with game_data.connect() as connection:
        yield connection


def test_candidates_come_from_the_game_views(reader):
    assert [row["des"] for row in game_data.shuffled_scenarios(reader)] == ["kept"]
    assert sorted(row["dis_no"] for row in game_data.shuffled_disasters(reader)) == ["blast", "quake"]


def test_similar_events_share_the_class_and_skip_the_current_disaster(reader):
    assert [row["dis_no"] for row in game_data.similar_events(reader, "shaking_class", "6-7", "blast")] == ["quake"]
    assert game_data.similar_events(reader, "shaking_class", "6-7", "quake") == []
    assert game_data.similar_events(reader, "wind_class", "Not applicable", "quake") == []
