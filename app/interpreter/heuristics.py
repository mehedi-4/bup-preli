import re
from typing import List, Dict, Any, Tuple, Optional
from app.schemas import BatteryInput

def parse_time_window(text: str) -> List[int]:
    """
    Extracts start-inclusive, end-exclusive hours from natural text expressions.
    e.g. 'from noon until 2 PM' -> [12, 13]
         'between 13:00 and 15:00' -> [13, 14]
         'from 6 PM until 9 PM' -> [18, 19, 20]
    """
    text = text.lower()

    def parse_time_str(t_str: str) -> Optional[int]:
        t_str = t_str.strip()
        if t_str in ("noon", "12 noon", "12 pm"):
            return 12
        if t_str in ("midnight", "12 am"):
            return 0
        m = re.match(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", t_str)
        if not m:
            return None
        hr = int(m.group(1))
        meridiem = m.group(3)
        if meridiem == "pm" and hr < 12:
            hr += 12
        elif meridiem == "am" and hr == 12:
            hr = 0
        return hr if 0 <= hr <= 24 else None

    # Time window extraction patterns
    patterns = [
        r"(?:from|between)\s+([0-9]{1,2}(?::[0-9]{2})?\s*(?:am|pm)?|noon|midnight)\s+(?:until|to|and)\s+([0-9]{1,2}(?::[0-9]{2})?\s*(?:am|pm)?|noon|midnight)",
        r"([0-9]{1,2}(?::[0-9]{2})?\s*(?:am|pm)?)\s*(?:-|to|until)\s*([0-9]{1,2}(?::[0-9]{2})?\s*(?:am|pm)?)"
    ]

    for pat in patterns:
        m = re.search(pat, text)
        if m:
            start_str, end_str = m.group(1).strip(), m.group(2).strip()
            # If end has am/pm but start does not (and is not noon/midnight), propagate meridiem
            if start_str not in ("noon", "midnight") and ("pm" in end_str or "am" in end_str) and not ("pm" in start_str or "am" in start_str):
                meridiem = "pm" if "pm" in end_str else "am"
                start_str = f"{start_str} {meridiem}"
            start_h = parse_time_str(start_str)
            end_h = parse_time_str(end_str)
            if start_h is not None and end_h is not None and start_h < end_h:
                return list(range(start_h, end_h))

    return []

def fallback_heuristic_parse(note: str, note_idx: int, battery: BatteryInput) -> Dict[str, Any]:
    """
    Emergency rule-based interpreter used strictly when external model APIs fail.
    """
    lower = note.lower()
    hours = parse_time_window(note)

    # 1. Distractor / No-Op checks
    distractor_keywords = [
        "cafeteria", "menu", "sports", "registration", "deadline", 
        "library", "book", "club", "seminar", "notices", "tomorrow", "next week", "next month"
    ]
    if any(k in lower for k in distractor_keywords) and not any(k in lower for k in ["solar", "battery", "charge", "grid"]):
        return {
            "note_index": note_idx,
            "applies": False,
            "directive_type": "no_op",
            "structured_adjustment": None,
            "explanation": "Heuristic fallback: identified as campus schedule distractor."
        }

    # 2. Solar reduction
    if "solar" in lower or "pv" in lower or "panel" in lower:
        factor = 0.5 # default
        m_pct = re.search(r"(\d+)%", lower)
        if "drop to" in lower or "leave" in lower or "roughly" in lower:
            if m_pct:
                factor = float(m_pct.group(1)) / 100.0
            elif "one-fifth" in lower or "1/5" in lower:
                factor = 0.2
            elif "one-quarter" in lower or "1/4" in lower or "quarter" in lower:
                factor = 0.25
            elif "half" in lower:
                factor = 0.5
        elif "reduction" in lower:
            if m_pct:
                factor = 1.0 - (float(m_pct.group(1)) / 100.0)
        
        return {
            "note_index": note_idx,
            "applies": bool(hours),
            "directive_type": "solar_reduction" if hours else "no_op",
            "structured_adjustment": {"hours": hours, "factor": factor} if hours else None,
            "explanation": f"Heuristic fallback: solar reduction factor {factor} during window."
        }

    # 3. No charge window
    if ("charge" in lower or "charging" in lower) and ("not" in lower or "do not" in lower or "isolated" in lower or "unavailable" in lower or "disabled" in lower):
        return {
            "note_index": note_idx,
            "applies": bool(hours),
            "directive_type": "no_charge_window" if hours else "no_op",
            "structured_adjustment": {"hours": hours} if hours else None,
            "explanation": "Heuristic fallback: battery charging prohibited during window."
        }

    # 4. No discharge window
    if ("discharge" in lower or "discharging" in lower) and ("not" in lower or "do not" in lower or "disabled" in lower or "testing" in lower):
        return {
            "note_index": note_idx,
            "applies": bool(hours),
            "directive_type": "no_discharge_window" if hours else "no_op",
            "structured_adjustment": {"hours": hours} if hours else None,
            "explanation": "Heuristic fallback: battery discharging prohibited during window."
        }

    # 5. Minimum battery reserve
    if "reserve" in lower or "remain in the battery" in lower or "stored in the battery" in lower or "at least" in lower:
        m_pct = re.search(r"(\d+)%", lower)
        m_kwh = re.search(r"(\d+(?:\.\d+)?)\s*kwh", lower)
        min_kwh = battery.minimum_energy_kwh
        if m_pct:
            pct = float(m_pct.group(1)) / 100.0
            min_kwh = pct * battery.capacity_kwh
        elif m_kwh:
            min_kwh = float(m_kwh.group(1))

        return {
            "note_index": note_idx,
            "applies": bool(hours),
            "directive_type": "minimum_battery_reserve" if hours else "no_op",
            "structured_adjustment": {"hours": hours, "minimum_energy_kwh": min_kwh} if hours else None,
            "explanation": f"Heuristic fallback: minimum reserve {min_kwh} kWh required."
        }

    # 6. Max grid window
    if "grid" in lower or "feeder" in lower or "transformer" in lower or "substation" in lower:
        m_kwh = re.search(r"(\d+(?:\.\d+)?)\s*kwh", lower)
        grid_kwh = 0.0
        if m_kwh:
            grid_kwh = float(m_kwh.group(1))
        return {
            "note_index": note_idx,
            "applies": bool(hours),
            "directive_type": "max_grid_window" if hours else "no_op",
            "structured_adjustment": {"hours": hours, "max_grid_kwh": grid_kwh} if hours else None,
            "explanation": f"Heuristic fallback: grid import capped at {grid_kwh} kWh."
        }

    # Default to no_op
    return {
        "note_index": note_idx,
        "applies": False,
        "directive_type": "no_op",
        "structured_adjustment": None,
        "explanation": "Heuristic fallback: no applicable energy directive identified."
    }
