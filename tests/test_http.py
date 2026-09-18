"""Real HTTP contract smoke test for a running GridWise service."""

import copy
import json
import os
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.schemas import OptimizeEnergyResponse


BASE_URL = os.getenv("GRIDWISE_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
SAMPLE_FILE = os.getenv(
    "GRIDWISE_HTTP_SAMPLE_FILE",
    str(Path(__file__).parent / "samples" / "sample_request.json"),
)


def run_tests() -> int:
    with open(SAMPLE_FILE) as stream:
        sample = json.load(stream)

    health = requests.get(f"{BASE_URL}/health", timeout=5)
    assert health.status_code == 200
    assert health.json() == {"status": "ok"}

    malformed = requests.post(
        f"{BASE_URL}/optimize-energy",
        data="{",
        headers={"Content-Type": "application/json"},
        timeout=5,
    )
    assert malformed.status_code == 400
    assert malformed.headers["content-type"].startswith("application/json")

    extra = copy.deepcopy(sample)
    extra["unexpected"] = True
    rejected = requests.post(f"{BASE_URL}/optimize-energy", json=extra, timeout=5)
    assert rejected.status_code == 400

    response = requests.post(f"{BASE_URL}/optimize-energy", json=sample, timeout=30)
    assert response.status_code == 200, response.text
    validated = OptimizeEnergyResponse.model_validate(response.json())
    assert validated.scenario_id == sample["scenario_id"]
    assert len(validated.hourly_plan) == 24
    print("Real HTTP health, malformed-input, strict-schema, and optimization checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_tests())
