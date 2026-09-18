"""Deterministic fallback interpretation for provider outages.

The configured language model remains the primary interpreter. This module is
deliberately conservative: it emits an actionable directive only when the note
contains enough information to satisfy the public contract.
"""

import re
from typing import Any, Dict, List, Optional

from app.schemas import BatteryInput


_NUMBER_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4,
    "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
    "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30,
    "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
    "eighty": 80, "ninety": 90,
}
_TIME_WORDS = {key: value for key, value in _NUMBER_WORDS.items() if value <= 19 or value in {20, 30}}
_TIME_ATOM = (
    r"(?:\d{1,2}(?::\d{2})?\s*(?:a\.?m\.?|p\.?m\.?)?"
    r"|noon|midnight|" + "|".join(sorted(_TIME_WORDS, key=len, reverse=True)) + r")"
)


def _normalise_text(text: str) -> str:
    return (
        text.lower()
        .replace("–", "-")
        .replace("—", "-")
        .replace("−", "-")
        .replace("a.m.", "am")
        .replace("p.m.", "pm")
    )


def _contains_meridiem(value: str) -> bool:
    return bool(re.search(r"(?:am|pm)$", value.strip()))


def _parse_time_str(value: str, default_meridiem: Optional[str] = None) -> Optional[int]:
    value = value.strip().replace(".", "")
    if value in {"noon", "12 noon", "12 pm"}:
        return 12
    if value in {"midnight", "12 am"}:
        return 0

    match = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", value)
    if match:
        hour = int(match.group(1))
        minutes = match.group(2)
        explicit_meridiem = match.group(3)
        if hour == 24:
            return 24 if minutes == "00" and explicit_meridiem is None else None
        # 13:00 is an unambiguous 24-hour time even when the surrounding note
        # contains a daytime context that would otherwise imply PM.
        meridiem = explicit_meridiem or (None if ":" in value and hour > 12 else default_meridiem)
    else:
        word_match = re.fullmatch(r"([a-z]+)", value)
        if not word_match or word_match.group(1) not in _TIME_WORDS:
            return None
        hour = _TIME_WORDS[word_match.group(1)]
        meridiem = default_meridiem

    if meridiem:
        if hour < 1 or hour > 12:
            return None
        if meridiem == "pm" and hour < 12:
            hour += 12
        elif meridiem == "am" and hour == 12:
            hour = 0
    return hour if 0 <= hour <= 23 else None


def parse_time_windows(text: str) -> List[List[int]]:
    """Extract all distinct start-inclusive, end-exclusive hour windows.

    Supports numeric, 24-hour, noon/midnight, and number-word forms. Bare
    o'clock expressions in solar/afternoon contexts are interpreted as PM;
    explicit AM/PM and 24-hour forms always take precedence.
    """

    normalised = _normalise_text(text)
    patterns = [
        rf"(?:from|between)\s+({_TIME_ATOM})\s+(?:until|to|and|through)\s+({_TIME_ATOM})",
        rf"({_TIME_ATOM})\s*(?:-|to|until|through)\s*({_TIME_ATOM})",
    ]

    context_meridiem: Optional[str] = None
    if re.search(r"\b(?:afternoon|evening|tonight|solar|pv|photovoltaic|panel|inverter)\b", normalised):
        context_meridiem = "pm"
    elif re.search(r"\b(?:morning|dawn)\b", normalised):
        context_meridiem = "am"

    matches = []
    for pattern in patterns:
        for match in re.finditer(pattern, normalised):
            start_raw, end_raw = match.group(1).strip(), match.group(2).strip()
            start_has_meridiem = _contains_meridiem(start_raw)
            end_has_meridiem = _contains_meridiem(end_raw)

            propagated = None
            if end_has_meridiem and not start_has_meridiem:
                propagated = "pm" if "pm" in end_raw else "am"
            elif start_raw in {"noon", "12 noon"} and not end_has_meridiem:
                propagated = "pm"
            elif start_raw in {"midnight", "12 am"} and not end_has_meridiem:
                propagated = "am"
            elif not start_has_meridiem and not end_has_meridiem:
                propagated = context_meridiem

            start = _parse_time_str(start_raw, propagated)
            end = _parse_time_str(end_raw, propagated)
            # In an interval such as 10 PM until midnight, midnight is the
            # exclusive end of the same day (24), not hour 0 of the next day.
            if end_raw in {"midnight", "12 am"} and start is not None and start > 0:
                end = 24
            if start is None or end is None or start >= end:
                continue
            matches.append((match.start(), tuple(range(start, end))))

    # Both regexes can discover the same textual range. Preserve text order
    # while deduplicating equivalent windows.
    windows: List[List[int]] = []
    seen = set()
    for _, hours in sorted(matches, key=lambda item: item[0]):
        if hours in seen:
            continue
        seen.add(hours)
        windows.append(list(hours))
    return windows


def parse_time_window(text: str) -> List[int]:
    """Return the first canonical window for the emergency parser."""

    windows = parse_time_windows(text)
    return windows[0] if windows else []


def _extract_percent(text: str) -> Optional[float]:
    match = re.search(r"(\d+(?:\.\d+)?)\s*(?:%|percent)", text)
    return float(match.group(1)) / 100.0 if match else None


def _extract_fraction(text: str) -> Optional[float]:
    fractions = {
        "half": 0.5, "one-half": 0.5, "one half": 0.5,
        "quarter": 0.25, "one-quarter": 0.25, "one quarter": 0.25,
        "one-fifth": 0.2, "one fifth": 0.2, "fifth": 0.2,
        "one-third": 1 / 3, "one third": 1 / 3,
        "three-quarters": 0.75, "three quarters": 0.75,
    }
    for phrase, value in fractions.items():
        if phrase in text:
            return value
    return None


def _extract_solar_factor(text: str) -> Optional[float]:
    percent = _extract_percent(text)
    fraction = _extract_fraction(text)
    if fraction is not None:
        return fraction
    if percent is None:
        return None

    # "drop/reduce to 25%" and "25% of normal" describe what remains.
    if re.search(r"(?:drop|fall|reduce|reduced|cut|leave|remain|only|limit|limited).*?\b(?:to|at|about|roughly|around)\s+\d+(?:\.\d+)?\s*(?:%|percent)", text):
        return percent
    if re.search(r"\d+(?:\.\d+)?\s*(?:%|percent)\s+(?:of|remaining|usable|available|output)", text):
        return percent

    # "80% reduction", "reduced by 30%", and "drop by 30%" describe the loss.
    if re.search(r"\d+(?:\.\d+)?\s*(?:%|percent)\s+(?:reduction|drop|decrease|loss)", text):
        return 1.0 - percent
    if re.search(r"(?:reduce|reduced|drop|drops|fall|cut|decrease|decreased|curtail|curtailed|limit|limited).*?\bby\s+\d+(?:\.\d+)?\s*(?:%|percent)", text):
        return 1.0 - percent
    return percent


def _extract_kwh(text: str) -> Optional[float]:
    match = re.search(r"(\d+(?:\.\d+)?)\s*(?:kwh|kw\s*h|kilowatt(?:\s|-)*hours?)\b", text)
    if match:
        return float(match.group(1))
    for word, value in sorted(_NUMBER_WORDS.items(), key=lambda item: -len(item[0])):
        if re.search(rf"\b{re.escape(word)}\s*(?:kwh|kilowatt(?:\s|-)*hours?)\b", text):
            return float(value)
    return None


def _no_op(note_idx: int, reason: str) -> Dict[str, Any]:
    return {
        "note_index": note_idx,
        "applies": False,
        "directive_type": "no_op",
        "structured_adjustment": None,
        "explanation": reason,
    }


def fallback_heuristic_parse(note: str, note_idx: int, battery: BatteryInput) -> Dict[str, Any]:
    """Conservative emergency parser used only when all configured LLMs fail."""

    lower = _normalise_text(note)
    hours = parse_time_window(lower)
    if not hours:
        return _no_op(note_idx, "No complete energy directive window was identified.")

    # Check discharging before charging: the word "discharge" contains
    # "charge", so the order is semantically significant.
    discharge_intent = re.search(
        r"\b(?:discharg(?:e|ing|ed)|draw\s+from\s+(?:the\s+)?battery|battery\s+(?:output|supply|delivery))\b",
        lower,
    )
    if discharge_intent:
        if re.search(r"\b(?:no|not|do not|don't|must not|cannot|can't|unable|unavailable|disabled|prohibited)\b", lower) or re.search(r"\b(?:protection|relay)\s+test", lower):
            return {
                "note_index": note_idx,
                "applies": True,
                "directive_type": "no_discharge_window",
                "structured_adjustment": {"hours": hours},
                "explanation": "Battery discharge is unavailable during the stated window.",
            }

    if re.search(r"\b(?:(?:re)?charg(?:e|er|ing|ed)|charging\s+circuit)\b", lower):
        if re.search(r"\b(?:no|not|do not|don't|must not|cannot|can't|unable|unavailable|disabled|isolated|offline|maintenance|outage|prohibited)\b", lower):
            return {
                "note_index": note_idx,
                "applies": True,
                "directive_type": "no_charge_window",
                "structured_adjustment": {"hours": hours},
                "explanation": "Battery charging is unavailable during the stated window.",
            }

    if re.search(r"\b(?:solar|pv|photovoltaic|rooftop|panel|inverter)\b", lower):
        factor = _extract_solar_factor(lower)
        if factor is not None and 0 <= factor <= 1:
            return {
                "note_index": note_idx,
                "applies": True,
                "directive_type": "solar_reduction",
                "structured_adjustment": {"hours": hours, "factor": factor},
                "explanation": f"Usable solar is reduced to {factor:g} of forecast during the stated window.",
            }

    if re.search(r"\b(?:reserve|at least|remain in the battery|stored in the battery|state of charge|backup|maintain|retain|keep)\b", lower) and re.search(r"\b(?:battery|storage|stored|energy)\b", lower):
        reserve = _extract_kwh(lower)
        percent = _extract_percent(lower)
        if percent is not None:
            reserve = percent * battery.capacity_kwh
        if reserve is not None and 0 <= reserve <= battery.capacity_kwh:
            return {
                "note_index": note_idx,
                "applies": True,
                "directive_type": "minimum_battery_reserve",
                "structured_adjustment": {"hours": hours, "minimum_energy_kwh": reserve},
                "explanation": f"Battery energy must remain at or above {reserve:g} kWh during the stated window.",
            }

    if re.search(r"\b(?:grid|feeder|transformer|substation)\b", lower):
        cap = _extract_kwh(lower)
        if cap is not None and cap >= 0 and re.search(r"\b(?:cap|capped|limit|limited|below|under|above|at or below|not exceed|must stay|intake|import)\b", lower):
            return {
                "note_index": note_idx,
                "applies": True,
                "directive_type": "max_grid_window",
                "structured_adjustment": {"hours": hours, "max_grid_kwh": cap},
                "explanation": f"Grid import is capped at {cap:g} kWh during the stated window.",
            }

    return _no_op(note_idx, "The note does not contain a supported actionable energy directive.")
