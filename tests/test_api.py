import json
import os
import copy
import sys
from pathlib import Path
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.main import health_check, optimize_energy
from app.schemas import OptimizeEnergyRequest, OptimizeEnergyResponse

def test_health_endpoint():
    assert health_check().model_dump() == {"status": "ok"}
    print("Health response contract passed: {'status': 'ok'}")

def test_malformed_request():
    try:
        OptimizeEnergyRequest(scenario_id="BAD-REQ")
    except ValidationError:
        pass
    else:
        raise AssertionError("malformed input was accepted")
    print("Malformed request schema rejection passed")

def _load_sample_input():
    supplied_pack = os.getenv("GRIDWISE_SAMPLE_FILE")
    default_pack = "/home/mehedi/Videos/BUP_CSE_FEST_2026_Participant_Docs/BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json"
    sample_file = supplied_pack or (default_pack if os.path.exists(default_pack) else str(Path(__file__).parent / "samples" / "sample_request.json"))
    with open(sample_file) as f:
        data = json.load(f)
    return data["cases"][0]["input"] if "cases" in data else data

def test_request_normalization_and_strictness():
    sample = _load_sample_input()
    reversed_hours = copy.deepcopy(sample)
    reversed_hours["hours"].reverse()
    normalized = OptimizeEnergyRequest(**reversed_hours)
    assert [hour.hour for hour in normalized.hours] == list(range(24))

    extra_root = copy.deepcopy(sample)
    extra_root["unexpected"] = True
    try:
        OptimizeEnergyRequest(**extra_root)
    except ValidationError:
        pass
    else:
        raise AssertionError("unknown root request field was accepted")

    extra_hour = copy.deepcopy(sample)
    extra_hour["hours"][0]["unexpected"] = True
    try:
        OptimizeEnergyRequest(**extra_hour)
    except ValidationError:
        pass
    else:
        raise AssertionError("unknown hourly request field was accepted")
    print("Request ordering normalization and unknown-field rejection passed")

def test_sample_case_api():
    case0 = _load_sample_input()
    body = optimize_energy(OptimizeEnergyRequest(**case0)).model_dump()

    assert body["scenario_id"] == case0["scenario_id"]
    assert len(body["hourly_plan"]) == 24
    assert len(body["directive_interpretation"]) == len(case0["operator_notes"])
    if case0["scenario_id"] == "SAMPLE-01":
        assert body["total_cost_bdt"] == 38365.0
    assert set(body) == {
        "scenario_id", "directive_interpretation", "hourly_plan",
        "total_grid_kwh", "total_cost_bdt", "peak_grid_kwh", "plan_summary",
    }
    print("Sample optimization service contract passed")

def test_documented_sample_response():
    response_file = Path(__file__).parent / "samples" / "sample_response.json"
    with open(response_file) as f:
        documented = json.load(f)
    validated = OptimizeEnergyResponse.model_validate(documented)
    assert len(validated.hourly_plan) == 24
    assert [entry.hour for entry in validated.hourly_plan] == list(range(24))
    assert validated.plan_summary
    print("Documented complete sample response validation passed")

if __name__ == "__main__":
    test_health_endpoint()
    test_malformed_request()
    test_request_normalization_and_strictness()
    test_sample_case_api()
    test_documented_sample_response()
