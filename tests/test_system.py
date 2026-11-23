import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from threadpoolctl import threadpool_limits

from api.main import app, engine
from src.rules import CATALOG, after

ROOT = Path(__file__).resolve().parents[1]
DEMOS = {case["id"]: case["payload"] for case in json.loads((ROOT / "data" / "demo_cases.json").read_text())}
BASE = DEMOS["normal"]


@pytest.fixture(scope="session", autouse=True)
def deterministic_threads():
    with threadpool_limits(limits=2):
        yield


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("FRAUD_LOG", str(tmp_path / "decisions.sqlite"))
    return TestClient(app)


def rules(response):
    return {rule["id"] for rule in response.json()["rules"]}


def test_catalog_groups():
    assert len(CATALOG) >= 15
    assert {item[0] for item in CATALOG.values()} == {"validation", "hard", "post"}


@pytest.mark.parametrize(("name", "status", "expected_rule"), [
    ("normal", "clear", "R15"), ("borderline", "review", "R13"), ("fraud", "flagged", "R14"),
])
def test_real_demos(client, name, status, expected_rule):
    response = client.post("/predict", json=DEMOS[name])
    assert response.status_code == 200
    assert response.json()["status"] == status
    assert expected_rule in rules(response)
    assert 0 <= response.json()["probability"] <= 1


@pytest.mark.parametrize(("payload", "rule"), [
    ({}, "R2"), (dict(BASE, amount=-1), "R2"), (dict(BASE, amount="12"), "R2"),
    (dict(BASE, time=-1), "R3"), (dict(BASE, time=0.5), "R3"),
    (dict(BASE, components=[0]), "R4"), (dict(BASE, components=["x"] + [0] * 27), "R8"),
    (dict(BASE, count_10m=0), "R5"), (dict(BASE, seconds_since_previous=-1), "R6"),
    (dict(BASE, count_10m=2, seconds_since_previous=601), "R7"),
])
def test_invalid_requests(client, payload, rule):
    response = client.post("/predict", json=payload)
    assert response.status_code == 422
    assert response.json()["status"] == "invalid"
    assert rule in rules(response)


@pytest.mark.parametrize(("changes", "status", "rule"), [
    ({"watchlist_match": True}, "flagged", "R9"),
    ({"count_10m": 8, "seconds_since_previous": 5}, "flagged", "R10"),
    ({"count_10m": 8, "amount": 100000}, "flagged", "R11"),
    ({"components": None}, "review", "R12"),
])
def test_hard_rules_stop_model(client, changes, status, rule):
    response = client.post("/predict", json=dict(BASE, **changes))
    assert response.json()["status"] == status
    assert response.json()["probability"] is None
    assert rule in rules(response)


def test_missing_component_uses_imputer(client):
    response = client.post("/predict", json=dict(BASE, components=[None] + BASE["components"][1:]))
    assert response.json()["probability"] is not None
    assert "R20" in rules(response)


def test_large_amount_and_time_raise_review():
    stats = engine().stats
    payload = dict(BASE, amount=stats["high_amount"] + 1, time=200000, count_10m=5, seconds_since_previous=9)
    status, trace = after(payload, 0.0, stats)
    assert status == "review"
    assert {item["id"] for item in trace} == {"R16", "R17", "R18", "R19"}


def test_predict_explain_and_health(client):
    prediction = client.post("/predict", json=BASE).json()
    explanation = client.post("/explain", json=BASE).json()
    assert prediction == explanation
    assert len(explanation["top_features"]) == 5
    assert client.get("/health").json()["model"] == "Histogram gradient boosting"
    assert client.get("/").status_code == 200
    assert client.get("/assets/site.js").status_code == 200
    assert len(client.get("/examples").json()) == 4


def test_log_keeps_rejected_values_out(client, tmp_path):
    client.post("/predict", json=BASE)
    client.post("/predict", json=dict(BASE, unrecognized="test-private-value"))
    with sqlite3.connect(tmp_path / "decisions.sqlite") as connection:
        records = connection.execute("SELECT status, source, input FROM decisions ORDER BY id").fetchall()
    assert records[0][:2] == ("clear", "hybrid")
    assert records[1][:2] == ("invalid", "validation")
    assert "test-private-value" not in records[1][2]


def test_data_and_threshold_quality(client):
    report = client.get("/metrics").json()
    assert report["dataset"]["rows"] == 284807 and report["dataset"]["fraud"] == 492
    assert report["test"]["tn"] + report["test"]["fp"] + report["test"]["fn"] + report["test"]["tp"] == report["splits"]["test"]["rows"]
    assert report["test"]["average_precision"] > 100 * report["test_prevalence"]
    assert 0 < report["threshold"] < 0.5
    windows = [report["splits"][name] for name in ("train", "calibration", "validation", "test")]
    assert all(left["max_time"] < right["min_time"] for left, right in zip(windows, windows[1:]))
