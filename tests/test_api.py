import json
import sys
from pathlib import Path
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.main import app

client = TestClient(app)

def test_health_endpoint():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
    print("Health check endpoint test passed: GET /health -> 200 {'status': 'ok'}")

def test_malformed_request():
    # Sending missing required fields
    resp = client.post("/optimize-energy", json={"scenario_id": "BAD-REQ"})
    assert resp.status_code == 400
    print("Malformed input test passed: POST /optimize-energy -> 400 Bad Request")

def test_sample_case_api():
    sample_file = "/home/mehedi/Videos/BUP_CSE_FEST_2026_Participant_Docs/BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json"
    with open(sample_file) as f:
        data = json.load(f)

    case0 = data["cases"][0]
    resp = client.post("/optimize-energy", json=case0["input"])
    assert resp.status_code == 200
    body = resp.json()

    assert body["scenario_id"] == "SAMPLE-01"
    assert len(body["hourly_plan"]) == 24
    assert len(body["directive_interpretation"]) == 2
    assert body["total_cost_bdt"] == 38365.0
    print("Sample 01 API integration test passed: POST /optimize-energy -> 200 OK")

if __name__ == "__main__":
    test_health_endpoint()
    test_malformed_request()
    test_sample_case_api()
