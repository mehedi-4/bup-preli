from typing import List, Dict, Any, Optional
from app.schemas import DirectiveInterpretationEntry, BatteryInput

ALLOWED_DIRECTIVES = {
    "solar_reduction",
    "minimum_battery_reserve",
    "no_charge_window",
    "no_discharge_window",
    "max_grid_window",
    "no_op"
}

def clean_and_validate_hours(raw_hours: Any) -> List[int]:
    """Ensure hours are unique integers from 0 to 23 in ascending order."""
    if not isinstance(raw_hours, list):
        return []
    valid = []
    for h in raw_hours:
        try:
            h_int = int(h)
            if 0 <= h_int <= 23 and h_int not in valid:
                valid.append(h_int)
        except (ValueError, TypeError):
            continue
    valid.sort()
    return valid

def validate_and_sanitize_directive(
    raw_entry: Dict[str, Any],
    note_idx: int,
    battery: BatteryInput
) -> DirectiveInterpretationEntry:
    """
    Validates a raw directive dictionary against Problem Statement guardrails (Section 08 & 04).
    Sanitizes keys to ensure exact required shapes.
    Safely falls back to no_op if structure is invalid.
    """
    raw_type = str(raw_entry.get("directive_type", "")).strip().lower()
    explanation = str(raw_entry.get("explanation", "")).strip() or "Operator note interpretation."

    if raw_type not in ALLOWED_DIRECTIVES:
        # Unsupported type -> safe failure downgrade to no_op
        return DirectiveInterpretationEntry(
            note_index=note_idx,
            applies=False,
            directive_type="no_op",
            structured_adjustment=None,
            explanation=f"Safely handled unsupported directive type: {raw_type}"
        )

    if raw_type == "no_op":
        return DirectiveInterpretationEntry(
            note_index=note_idx,
            applies=False,
            directive_type="no_op",
            structured_adjustment=None,
            explanation=explanation
        )

    raw_adj = raw_entry.get("structured_adjustment") or {}
    hours = clean_and_validate_hours(raw_adj.get("hours"))

    if not hours:
        # Directive without valid hours cannot be applied -> downgrade to no_op
        return DirectiveInterpretationEntry(
            note_index=note_idx,
            applies=False,
            directive_type="no_op",
            structured_adjustment=None,
            explanation=f"No valid hours specified; defaulting to no_op."
        )

    sanitized_adj: Dict[str, Any] = {"hours": hours}

    if raw_type == "solar_reduction":
        try:
            factor = float(raw_adj.get("factor", 1.0))
            # Clamp factor between 0.0 and 1.0
            factor = max(0.0, min(1.0, factor))
            sanitized_adj["factor"] = factor
        except (ValueError, TypeError):
            return DirectiveInterpretationEntry(
                note_index=note_idx,
                applies=False,
                directive_type="no_op",
                structured_adjustment=None,
                explanation="Invalid solar factor; defaulting to no_op."
            )

    elif raw_type == "minimum_battery_reserve":
        try:
            min_energy = float(raw_adj.get("minimum_energy_kwh", battery.minimum_energy_kwh))
            min_energy = max(0.0, min(battery.capacity_kwh, min_energy))
            sanitized_adj["minimum_energy_kwh"] = min_energy
        except (ValueError, TypeError):
            return DirectiveInterpretationEntry(
                note_index=note_idx,
                applies=False,
                directive_type="no_op",
                structured_adjustment=None,
                explanation="Invalid minimum energy reserve; defaulting to no_op."
            )

    elif raw_type in ("no_charge_window", "no_discharge_window"):
        # Section 04: shape is strictly {"hours": [...]}
        pass

    elif raw_type == "max_grid_window":
        try:
            max_grid = float(raw_adj.get("max_grid_kwh", 0.0))
            sanitized_adj["max_grid_kwh"] = max(0.0, max_grid)
        except (ValueError, TypeError):
            return DirectiveInterpretationEntry(
                note_index=note_idx,
                applies=False,
                directive_type="no_op",
                structured_adjustment=None,
                explanation="Invalid max grid limit; defaulting to no_op."
            )

    return DirectiveInterpretationEntry(
        note_index=note_idx,
        applies=True,
        directive_type=raw_type,  # type: ignore
        structured_adjustment=sanitized_adj,
        explanation=explanation
    )

def validate_interpretations_list(
    raw_directives: List[Dict[str, Any]],
    operator_notes: List[str],
    battery: BatteryInput
) -> List[DirectiveInterpretationEntry]:
    """
    Validates that every operator note has exactly one directive entry in note_index order.
    """
    num_notes = len(operator_notes)
    by_index: Dict[int, Dict[str, Any]] = {}

    for d in raw_directives:
        try:
            idx = int(d.get("note_index", -1))
            if 0 <= idx < num_notes and idx not in by_index:
                by_index[idx] = d
        except (ValueError, TypeError):
            continue

    validated: List[DirectiveInterpretationEntry] = []
    for idx in range(num_notes):
        raw = by_index.get(idx, {
            "note_index": idx,
            "applies": False,
            "directive_type": "no_op",
            "structured_adjustment": None,
            "explanation": "No directive generated; defaulted to no_op."
        })
        entry = validate_and_sanitize_directive(raw, idx, battery)
        validated.append(entry)

    return validated
