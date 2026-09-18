"""Adversarial checks for LLM authority and deterministic guardrails."""

import sys
from pathlib import Path
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config import settings
from app.interpreter.guardrails import validate_and_sanitize_directive
from app.interpreter.llm_service import LLMService
from app.schemas import BatteryInput, DirectiveInterpretationEntry


BATTERY = BatteryInput(
    capacity_kwh=100,
    initial_energy_kwh=50,
    minimum_energy_kwh=10,
    max_charge_kwh_per_hour=20,
    max_discharge_kwh_per_hour=20,
)


def test_valid_model_no_op_is_authoritative():
    note = (
        "A training seminar from noon until 2 PM discusses how solar output "
        "can drop to 25%; no operational change is planned today."
    )
    service = LLMService()
    original = (settings.OPENAI_API_KEY, settings.GEMINI_API_KEY, settings.PRIMARY_PROVIDER)
    try:
        settings.OPENAI_API_KEY = "test-only"
        settings.GEMINI_API_KEY = ""
        settings.PRIMARY_PROVIDER = "openai"
        service._call_openai = lambda prompt, battery: [{
            "note_index": 0,
            "applies": False,
            "directive_type": "no_op",
            "structured_adjustment": None,
            "explanation": "Informational seminar; no operational directive.",
        }]
        result = service.interpret_notes([note], BATTERY)[0]
    finally:
        settings.OPENAI_API_KEY, settings.GEMINI_API_KEY, settings.PRIMARY_PROVIDER = original

    assert result.directive_type == "no_op"
    assert result.applies is False
    assert result.structured_adjustment is None


def test_multiple_windows_preserve_model_selected_window():
    note = (
        "The briefing runs from 9 AM to 10 AM; usable solar will then be "
        "limited to 50% from noon until 2 PM."
    )
    raw = {
        "note_index": 0,
        "applies": True,
        "directive_type": "solar_reduction",
        "structured_adjustment": {"hours": [12, 13], "factor": 0.5},
        "explanation": "Solar reduction from noon until 2 PM.",
    }
    result = validate_and_sanitize_directive(raw, 0, BATTERY, note)
    assert result.directive_type == "solar_reduction"
    assert result.structured_adjustment == {"hours": [12, 13], "factor": 0.5}


def test_single_window_is_canonicalized_end_exclusive():
    note = "Do not discharge the battery from 6 PM until 9 PM."
    raw = {
        "note_index": 0,
        "applies": True,
        "directive_type": "no_discharge_window",
        "structured_adjustment": {"hours": [18, 19, 20, 21]},
        "explanation": "No discharge during the stated window.",
    }
    result = validate_and_sanitize_directive(raw, 0, BATTERY, note)
    assert result.structured_adjustment == {"hours": [18, 19, 20]}


def test_directive_response_shapes_are_exact():
    try:
        DirectiveInterpretationEntry(
            note_index=0,
            applies=True,
            directive_type="no_charge_window",
            structured_adjustment={"hours": [2, 3], "factor": 0.5},
            explanation="Invalid extra field.",
        )
    except ValidationError:
        pass
    else:
        raise AssertionError("directive adjustment accepted an unknown field")

    try:
        DirectiveInterpretationEntry(
            note_index=0,
            applies=True,
            directive_type="no_op",
            structured_adjustment=None,
            explanation="Invalid no_op consistency.",
        )
    except ValidationError:
        pass
    else:
        raise AssertionError("no_op accepted applies=true")


if __name__ == "__main__":
    test_valid_model_no_op_is_authoritative()
    test_multiple_windows_preserve_model_selected_window()
    test_single_window_is_canonicalized_end_exclusive()
    test_directive_response_shapes_are_exact()
    print("LLM authority and adversarial time-window checks passed")
