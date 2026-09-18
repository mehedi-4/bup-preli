"""Deterministic validation for untrusted model interpretations."""

import math
from typing import Any, Dict, List, Optional

from app.interpreter.heuristics import parse_time_windows
from app.schemas import BatteryInput, DirectiveInterpretationEntry


ALLOWED_DIRECTIVES = {
    "solar_reduction",
    "minimum_battery_reserve",
    "no_charge_window",
    "no_discharge_window",
    "max_grid_window",
    "no_op",
}


def clean_and_validate_hours(raw_hours: Any) -> Optional[List[int]]:
    """Return hours only when they exactly satisfy the canonical hour rules."""

    if not isinstance(raw_hours, list) or not raw_hours:
        return None
    if any(isinstance(hour, bool) or not isinstance(hour, int) for hour in raw_hours):
        return None
    if len(set(raw_hours)) != len(raw_hours):
        return None
    if any(hour < 0 or hour > 23 for hour in raw_hours):
        return None
    if raw_hours != sorted(raw_hours):
        return None
    return list(raw_hours)


def _finite_number(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _safe_no_op(note_idx: int, explanation: str) -> DirectiveInterpretationEntry:
    return DirectiveInterpretationEntry(
        note_index=note_idx,
        applies=False,
        directive_type="no_op",
        structured_adjustment=None,
        explanation=explanation,
    )


def validate_and_sanitize_directive(
    raw_entry: Dict[str, Any],
    note_idx: int,
    battery: BatteryInput,
    note_text: Optional[str] = None,
) -> DirectiveInterpretationEntry:
    """Validate one model result without inventing or clamping constraints."""

    if not isinstance(raw_entry, dict):
        return _safe_no_op(note_idx, "Malformed model output was safely ignored.")

    raw_type = str(raw_entry.get("directive_type", "")).strip().lower()
    explanation = str(raw_entry.get("explanation", "")).strip() or "Operator note interpretation."

    if raw_type not in ALLOWED_DIRECTIVES:
        return _safe_no_op(note_idx, "Unsupported model directive was safely ignored.")
    if raw_type == "no_op":
        return _safe_no_op(note_idx, explanation)

    raw_adj = raw_entry.get("structured_adjustment")
    if not isinstance(raw_adj, dict):
        return _safe_no_op(note_idx, "Malformed directive parameters were safely ignored.")

    # Canonicalize a single unambiguous range. When a note contains multiple
    # ranges, retain the model-selected range only if it matches one of them;
    # blindly selecting the first range can apply the directive to unrelated
    # contextual times.
    canonical_windows = parse_time_windows(note_text or "")
    raw_hours = clean_and_validate_hours(raw_adj.get("hours"))
    if len(canonical_windows) == 1:
        hours = canonical_windows[0]
    elif len(canonical_windows) > 1:
        if raw_hours is None or raw_hours not in canonical_windows:
            return _safe_no_op(note_idx, "Directive hours were ambiguous and the directive was safely ignored.")
        hours = raw_hours
    elif raw_hours is not None:
        hours = raw_hours
    else:
        return _safe_no_op(note_idx, "Directive hours were invalid and the directive was ignored.")

    sanitized: Dict[str, Any] = {"hours": hours}

    if raw_type == "solar_reduction":
        factor = _finite_number(raw_adj.get("factor"))
        if factor is None or not 0.0 <= factor <= 1.0:
            return _safe_no_op(note_idx, "Solar factor was outside the allowed range and was ignored.")
        sanitized["factor"] = factor
    elif raw_type == "minimum_battery_reserve":
        reserve = _finite_number(raw_adj.get("minimum_energy_kwh"))
        if reserve is None or not 0.0 <= reserve <= battery.capacity_kwh:
            return _safe_no_op(note_idx, "Battery reserve was outside the allowed range and was ignored.")
        sanitized["minimum_energy_kwh"] = reserve
    elif raw_type == "max_grid_window":
        grid_cap = _finite_number(raw_adj.get("max_grid_kwh"))
        if grid_cap is None or grid_cap < 0.0:
            return _safe_no_op(note_idx, "Grid cap was outside the allowed range and was ignored.")
        sanitized["max_grid_kwh"] = grid_cap
    # no_charge_window and no_discharge_window require only {"hours": [...]}.

    return DirectiveInterpretationEntry(
        note_index=note_idx,
        applies=True,
        directive_type=raw_type,  # type: ignore[arg-type]
        structured_adjustment=sanitized,
        explanation=explanation,
    )


def validate_interpretations_list(
    raw_directives: Any,
    operator_notes: List[str],
    battery: BatteryInput,
) -> List[DirectiveInterpretationEntry]:
    """Return exactly one ordered, guardrailed entry per operator note."""

    if not isinstance(raw_directives, list):
        raw_directives = []

    by_index: Dict[int, Dict[str, Any]] = {}
    for raw in raw_directives:
        if not isinstance(raw, dict):
            continue
        index = raw.get("note_index", -1)
        if isinstance(index, bool) or not isinstance(index, int):
            continue
        if 0 <= index < len(operator_notes) and index not in by_index:
            by_index[index] = raw

    validated: List[DirectiveInterpretationEntry] = []
    for index, note in enumerate(operator_notes):
        raw = by_index.get(index)
        if raw is None:
            validated.append(_safe_no_op(index, "No valid model interpretation was returned."))
        else:
            validated.append(validate_and_sanitize_directive(raw, index, battery, note_text=note))
    return validated
