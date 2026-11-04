import logging
from datetime import UTC, datetime

import mongomock
import pytest
import requests
import responses
from responses import matchers

from ingestion.gem import API_URL, RAW_URL, ingest_gem
from ingestion.store import RawStore

NOW = datetime(2026, 11, 1, 0, 3, 12, tzinfo=UTC)
SHA = "e2a74b9ff5" + "0" * 30
FRANCE_PATH = "Europe/France/summaries/Exposure_Summary_Adm1.csv"
LEBANON_PATH = "Middle_East/Lebanon/summaries/Exposure_Summary_Adm1.csv"
TREE = {
    "sha": SHA,
    "truncated": False,
    "tree": [
        {"path": "Europe/France/README.md", "type": "blob"},
        {"path": "Europe/France/summaries", "type": "tree"},
        {"path": "Europe/France/summaries/Exposure_Summary_Adm0.csv", "type": "blob"},
        {"path": FRANCE_PATH, "type": "blob"},
        {"path": LEBANON_PATH, "type": "blob"},
    ],
}
HEADER = "ID_0,NAME_0,ID_1,NAME_1,OCCUPANCY,BUILDINGS,OCCUPANTS_TOTAL\n"
FRANCE = HEADER + "FRA,France,FR-ARA,Auvergne-Rhône-Alpes,RES,1000,2500\nFRA,France,FR-ARA,Auvergne-Rhône-Alpes,COM,10,\n"
LEBANON = "﻿" + HEADER + "LBN,Lebanon,LB-BA,Beirut,RES,500,1200\nLBN,Lebanon,LB-BA,Beirut,COM,50,300\n"


def mock_commit(rsps):
    rsps.add(responses.GET, f"{API_URL}/commits/main", json={"sha": SHA})


def mock_repo(rsps, tree=TREE):
    mock_commit(rsps)
    rsps.add(responses.GET, f"{API_URL}/git/trees/{SHA}",
             match=[matchers.query_param_matcher({"recursive": "1"})], json=tree)
    for path, body in ((FRANCE_PATH, FRANCE), (LEBANON_PATH, LEBANON)):
        rsps.add(responses.GET, f"{RAW_URL}/{SHA}/{path}", body=body.encode("utf-8"))


def run(store):
    return ingest_gem(store, requests.Session(), "2026-11", "manual__1", NOW)


@pytest.fixture
def store():
    return RawStore(mongomock.MongoClient()["raw"])


def test_ingest_downloads_all_adm1_files(store, caplog):
    caplog.set_level(logging.INFO, logger="ingestion")
    with responses.RequestsMock() as rsps:
        mock_repo(rsps)
        assert run(store) == 4

    assert "GEM commit e2a74b9ff5: downloading 2 admin-1 files" in caplog.text
    docs = store.read_latest("gem_exposure_adm1")
    france_res = next(d for d in docs if d["ID_1"] == "FR-ARA" and d["OCCUPANCY"] == "RES")
    assert france_res["OCCUPANTS_TOTAL"] == "2500"
    assert france_res["_meta"]["dataset_version"] == SHA
    assert france_res["_meta"]["url"].endswith(FRANCE_PATH)
    assert next(d for d in docs if d["OCCUPANCY"] == "COM" and d["ID_0"] == "FRA")["OCCUPANTS_TOTAL"] is None
    assert {d["ID_0"] for d in docs} == {"FRA", "LBN"}


def test_same_commit_is_skipped(store):
    with responses.RequestsMock() as rsps:
        mock_repo(rsps)
        run(store)
    with responses.RequestsMock() as rsps:
        mock_commit(rsps)
        assert run(store) is None

    assert store.db["gem_exposure_adm1"].count_documents({}) == 4


def test_no_adm1_file_fails(store):
    tree = {"sha": SHA, "truncated": False, "tree": [{"path": "README.md", "type": "blob"}]}
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        mock_repo(rsps, tree=tree)
        with pytest.raises(RuntimeError):
            run(store)
