import json
import shutil

import pytest
from fastapi.testclient import TestClient

from suspension_predictor import billing
from suspension_predictor.api.main import app

client = TestClient(app)
HEADERS = {"X-API-Key": "demo-key-123"}


@pytest.fixture(autouse=True)
def isolated_api_keys(tmp_path, monkeypatch):
    """Redirect the billing store to a throwaway copy so tests never mutate
    the shipped data/api_keys.json (and each test starts with a full quota)."""
    tmp_file = tmp_path / "api_keys.json"
    shutil.copy(billing._DATA_PATH, tmp_file)
    monkeypatch.setattr(billing, "_DATA_PATH", tmp_file)
    yield

PAYLOAD = {
    "front": {
        "left": {"camber": -1.6, "caster": 4.4, "sai": 13.4, "toe": 0.05},
        "right": {"camber": -0.3, "caster": 4.5, "sai": 13.5, "toe": 0.02},
    },
    "front_spec": {
        "camber": {"min": -1.0, "max": 0.5},
        "caster": {"min": 3.7, "max": 5.2},
        "sai": {"min": 12.5, "max": 14.5},
        "toe": {"min": -0.08, "max": 0.08},
    },
}


def test_health():
    assert client.get("/health").json() == {"status": "ok"}


def test_predict_requires_api_key():
    resp = client.post("/v1/predict", json=PAYLOAD)
    assert resp.status_code == 401


def test_predict_rejects_bad_api_key():
    resp = client.post("/v1/predict", json=PAYLOAD, headers={"X-API-Key": "nope"})
    assert resp.status_code == 401


def test_predict_happy_path():
    resp = client.post("/v1/predict", json=PAYLOAD, headers=HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert body["findings"]
    assert body["findings"][0]["parameter"] == "camber"
    assert "disclaimer" in body


def test_predict_missing_spec_and_no_vehicle_match_400():
    bad_payload = {"front": PAYLOAD["front"]}
    resp = client.post("/v1/predict", json=bad_payload, headers=HEADERS)
    assert resp.status_code == 400


def test_predict_spec_autofill_from_vehicle():
    payload = {"front": PAYLOAD["front"], "vehicle": {"year": 2022, "make": "Toyota", "model": "Camry"}}
    resp = client.post("/v1/predict", json=payload, headers=HEADERS)
    assert resp.status_code == 200


def test_vehicles_list():
    resp = client.get("/v1/vehicles", headers=HEADERS)
    assert resp.status_code == 200
    assert len(resp.json()["vehicles"]) > 0
