import json
import logging
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

from app.config import settings
from app.schemas import BatteryInput, DirectiveInterpretationEntry
from app.interpreter.guardrails import validate_interpretations_list
from app.interpreter.heuristics import fallback_heuristic_parse

logger = logging.getLogger("gridwise.llm")

# Pydantic schemas for LLM structured output
class LLMDirectiveAdjustment(BaseModel):
    hours: Optional[List[int]] = None
    factor: Optional[float] = None
    minimum_energy_kwh: Optional[float] = None
    max_grid_kwh: Optional[float] = None

class LLMDirectiveItem(BaseModel):
    note_index: int
    applies: bool
    directive_type: str
    structured_adjustment: Optional[LLMDirectiveAdjustment] = None
    explanation: str

class LLMInterpretationEnvelope(BaseModel):
    directives: List[LLMDirectiveItem]

SYSTEM_PROMPT = """You are an expert energy scheduling assistant for the BUP Smart Campus Energy Optimization Challenge.
Your task is to interpret 1 to 3 campus operator notes into machine-checkable structured directives.

Each scenario has:
- Battery capacity: {capacity_kwh} kWh
- Battery initial energy: {initial_energy_kwh} kWh
- Base minimum reserve: {minimum_energy_kwh} kWh

DIRECTIVE RULES:
1. Supported directive_type values:
   - "solar_reduction": Usable solar is reduced. Requires: "hours" (list of ints), "factor" (usable fraction remaining, 0 to 1). E.g. "80% reduction" means factor = 0.2; "drops to 25%" means factor = 0.25; "half" means factor = 0.5.
   - "minimum_battery_reserve": Battery energy must stay at or above a level. Requires: "hours", "minimum_energy_kwh". If given as percentage of capacity (e.g. 50%), calculate value: (pct/100) * capacity_kwh.
   - "no_charge_window": Battery charging is disabled/isolated. Requires: "hours".
   - "no_discharge_window": Battery discharging is disabled/testing. Requires: "hours".
   - "max_grid_window": Grid import capped. Requires: "hours", "max_grid_kwh".
   - "no_op": Note does NOT affect today's energy schedule (distractors, cafeteria menus, sports registration, library hours, next week notices). For no_op: applies MUST be false, structured_adjustment MUST be null.

2. TIME WINDOW RULES:
   - Time ranges are start-inclusive and end-exclusive!
   - Examples:
     "noon until 2 PM" -> [12, 13]
     "1 PM to 3 PM" -> [13, 14]
     "2 AM until 5 AM" -> [2, 3, 4]
     "6 PM until 9 PM" -> [18, 19, 20]
     "6 PM until 10 PM" -> [18, 19, 20, 21]
     "7 PM until 9 PM" -> [19, 20]
     "10 AM until noon" -> [10, 11]
     "11 AM until 1 PM" -> [11, 12]
     "11 AM until 2 PM" -> [11, 12, 13]
     "5 PM until 7 PM" -> [17, 18]
   - "hours" must be unique integers from 0 through 23 in ascending order.

3. MAPPING RULES:
   - Return exactly one entry for each note in note_index order (0, 1, ...).
   - If a note is not an energy directive, set directive_type="no_op", applies=false, structured_adjustment=null.
   - For all non-no_op directives, applies MUST be true.
"""

class LLMService:
    def __init__(self):
        self._openai_client = None
        self._gemini_client = None
        self._cache: Dict[str, List[DirectiveInterpretationEntry]] = {}

    def _get_openai_client(self):
        if self._openai_client is None and settings.OPENAI_API_KEY:
            try:
                from openai import OpenAI
                self._openai_client = OpenAI(api_key=settings.OPENAI_API_KEY)
            except Exception as e:
                logger.error(f"Failed to initialize OpenAI client: {e}")
        return self._openai_client

    def _get_gemini_client(self):
        if self._gemini_client is None and settings.GEMINI_API_KEY:
            try:
                from google import genai
                self._gemini_client = genai.Client(api_key=settings.GEMINI_API_KEY)
            except Exception as e:
                logger.error(f"Failed to initialize Gemini client: {e}")
        return self._gemini_client

    def _call_openai(self, prompt: str, battery: BatteryInput) -> List[Dict[str, Any]]:
        client = self._get_openai_client()
        if not client:
            raise RuntimeError("OpenAI client not configured or missing API key.")

        formatted_system = SYSTEM_PROMPT.format(
            capacity_kwh=battery.capacity_kwh,
            initial_energy_kwh=battery.initial_energy_kwh,
            minimum_energy_kwh=battery.minimum_energy_kwh
        )

        response = client.beta.chat.completions.parse(
            model=settings.OPENAI_MODEL,
            messages=[
                {"role": "system", "content": formatted_system},
                {"role": "user", "content": prompt}
            ],
            response_format=LLMInterpretationEnvelope,
            temperature=0.0
        )
        parsed = response.choices[0].message.parsed
        return [item.model_dump() for item in parsed.directives]

    def _call_gemini(self, prompt: str, battery: BatteryInput) -> List[Dict[str, Any]]:
        client = self._get_gemini_client()
        if not client:
            raise RuntimeError("Gemini client not configured or missing API key.")

        from google.genai import types

        formatted_system = SYSTEM_PROMPT.format(
            capacity_kwh=battery.capacity_kwh,
            initial_energy_kwh=battery.initial_energy_kwh,
            minimum_energy_kwh=battery.minimum_energy_kwh
        )

        full_prompt = f"{formatted_system}\n\nOPERATOR NOTES TO INTERPRET:\n{prompt}"

        response = client.models.generate_content(
            model=settings.GEMINI_MODEL,
            contents=full_prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=LLMInterpretationEnvelope,
                temperature=0.0
            )
        )
        data = json.loads(response.text)
        return data.get("directives", [])

    def interpret_notes(
        self,
        operator_notes: List[str],
        battery: BatteryInput
    ) -> List[DirectiveInterpretationEntry]:
        """
        Interprets notes using LLM with dual-provider fallback and deterministic guardrails.
        """
        # Cache check
        cache_key = f"{tuple(operator_notes)}_{battery.capacity_kwh}_{battery.minimum_energy_kwh}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        user_prompt_lines = [f"Note {idx}: {note}" for idx, note in enumerate(operator_notes)]
        prompt = "\n".join(user_prompt_lines)

        raw_directives: Optional[List[Dict[str, Any]]] = None

        # Determine order of provider execution
        providers = ["openai", "gemini"] if settings.PRIMARY_PROVIDER == "openai" else ["gemini", "openai"]

        for provider in providers:
            try:
                if provider == "openai" and settings.OPENAI_API_KEY:
                    logger.info(f"Interpreting notes using OpenAI ({settings.OPENAI_MODEL})...")
                    raw_directives = self._call_openai(prompt, battery)
                    break
                elif provider == "gemini" and settings.GEMINI_API_KEY:
                    logger.info(f"Interpreting notes using Gemini ({settings.GEMINI_MODEL})...")
                    raw_directives = self._call_gemini(prompt, battery)
                    break
            except Exception as err:
                logger.warning(f"Provider {provider} failed: {err}. Attempting fallback...")

        # If all LLMs failed, use safe heuristic fallback
        if raw_directives is None:
            logger.warning("All LLM providers unavailable. Falling back to heuristic parsing.")
            raw_directives = [
                fallback_heuristic_parse(note, idx, battery)
                for idx, note in enumerate(operator_notes)
            ]

        # Apply deterministic guardrails to clean, validate, and ensure Section 04/08 compliance
        validated = validate_interpretations_list(raw_directives, operator_notes, battery)

        self._cache[cache_key] = validated
        return validated

llm_service = LLMService()
