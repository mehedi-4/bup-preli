import math
from typing import List, Tuple
from app.schemas import HourInput, BatteryInput, DirectiveInterpretationEntry, HourlyPlanEntry

TOLERANCE = 0.02  # Problem statement specifies 0.01 kWh / 0.01 BDT

def replay_and_verify_schedule(
    hours: List[HourInput],
    battery: BatteryInput,
    directives: List[DirectiveInterpretationEntry],
    hourly_plan: List[HourlyPlanEntry],
    total_grid_kwh: float,
    total_cost_bdt: float,
    peak_grid_kwh: float
) -> Tuple[bool, List[str]]:
    """
    Independently replays the schedule against the exact Problem Statement Section 09 & 11 rules:
    - 24 consecutive hours (0..23)
    - Non-negative finite values
    - Energy balance: grid + solar_used + discharge = demand + charge
    - Solar usage <= effective solar
    - Battery capacity & active minimum reserve limits
    - Max charge/discharge rate limits
    - Directive compliance (no charge, no discharge, max grid)
    - End-of-day battery neutrality
    - Summary recalculations
    """
    errors: List[str] = []

    if len(hourly_plan) != 24:
        errors.append(f"hourly_plan must contain 24 entries, got {len(hourly_plan)}")
        return False, errors

    # Compute effective solar and active constraints
    eff_solar = [h.solar_kwh for h in hours]
    min_res = [battery.minimum_energy_kwh] * 24
    no_charge_hrs = set()
    no_discharge_hrs = set()
    max_grid_limits = [float("inf")] * 24

    for d in directives:
        if not d.applies or not d.structured_adjustment:
            continue
        d_hours = d.structured_adjustment.get("hours", [])
        if d.directive_type == "solar_reduction":
            factor = float(d.structured_adjustment.get("factor", 1.0))
            for h in d_hours:
                eff_solar[h] = eff_solar[h] * factor
        elif d.directive_type == "minimum_battery_reserve":
            m = float(d.structured_adjustment.get("minimum_energy_kwh", battery.minimum_energy_kwh))
            for h in d_hours:
                min_res[h] = max(min_res[h], m)
        elif d.directive_type == "no_charge_window":
            for h in d_hours:
                no_charge_hrs.add(h)
        elif d.directive_type == "no_discharge_window":
            for h in d_hours:
                no_discharge_hrs.add(h)
        elif d.directive_type == "max_grid_window":
            mg = float(d.structured_adjustment.get("max_grid_kwh", float("inf")))
            for h in d_hours:
                max_grid_limits[h] = min(max_grid_limits[h], mg)

    current_battery = battery.initial_energy_kwh

    for h, p in enumerate(hourly_plan):
        if p.hour != h:
            errors.append(f"Hour mismatch at index {h}: plan hour is {p.hour}")

        # Non-negative checks
        for name, val in [
            ("grid_kwh", p.grid_kwh),
            ("solar_used_kwh", p.solar_used_kwh),
            ("battery_kwh", p.battery_kwh),
            ("battery_energy_after_kwh", p.battery_energy_after_kwh),
        ]:
            if math.isnan(val) or math.isinf(val) or val < -1e-5:
                errors.append(f"Hour {h}: {name} must be non-negative and finite, got {val}")

        # Solar limit check
        if p.solar_used_kwh > eff_solar[h] + TOLERANCE:
            errors.append(f"Hour {h}: solar_used_kwh ({p.solar_used_kwh}) exceeds effective solar ({eff_solar[h]})")

        # Battery action checks
        charge_amt = p.battery_kwh if p.battery_action == "charge" else 0.0
        discharge_amt = p.battery_kwh if p.battery_action == "discharge" else 0.0

        if p.battery_action == "idle" and p.battery_kwh > 1e-4:
            errors.append(f"Hour {h}: battery_kwh must be 0 when idle, got {p.battery_kwh}")

        # Rate limits
        if charge_amt > battery.max_charge_kwh_per_hour + TOLERANCE:
            errors.append(f"Hour {h}: charge amount exceeds max_charge_kwh_per_hour")
        if discharge_amt > battery.max_discharge_kwh_per_hour + TOLERANCE:
            errors.append(f"Hour {h}: discharge amount exceeds max_discharge_kwh_per_hour")

        # Directive constraints
        if h in no_charge_hrs and charge_amt > 1e-4:
            errors.append(f"Hour {h}: charging violates active no_charge_window")
        if h in no_discharge_hrs and discharge_amt > 1e-4:
            errors.append(f"Hour {h}: discharging violates active no_discharge_window")
        if p.grid_kwh > max_grid_limits[h] + TOLERANCE:
            errors.append(f"Hour {h}: grid import ({p.grid_kwh}) violates max_grid_window limit ({max_grid_limits[h]})")

        # Energy balance check: grid + solar_used + discharge = demand + charge
        supply = p.grid_kwh + p.solar_used_kwh + discharge_amt
        demand = hours[h].demand_kwh + charge_amt
        if abs(supply - demand) > TOLERANCE:
            errors.append(f"Hour {h}: energy balance violated (supply={supply:.3f}, demand={demand:.3f})")

        # Battery transition check
        expected_e = current_battery + charge_amt - discharge_amt
        if abs(p.battery_energy_after_kwh - expected_e) > TOLERANCE:
            errors.append(f"Hour {h}: battery state transition mismatch (got {p.battery_energy_after_kwh}, expected {expected_e})")

        # Battery reserve & capacity bounds
        if p.battery_energy_after_kwh < min_res[h] - TOLERANCE:
            errors.append(f"Hour {h}: battery energy ({p.battery_energy_after_kwh}) below active reserve ({min_res[h]})")
        if p.battery_energy_after_kwh > battery.capacity_kwh + TOLERANCE:
            errors.append(f"Hour {h}: battery energy ({p.battery_energy_after_kwh}) exceeds capacity ({battery.capacity_kwh})")

        current_battery = p.battery_energy_after_kwh

    # End-of-day battery neutrality
    if abs(current_battery - battery.initial_energy_kwh) > TOLERANCE:
        errors.append(f"End-of-day neutrality violated: final {current_battery:.3f} != initial {battery.initial_energy_kwh:.3f}")

    # Summary verification
    recalc_grid = sum(p.grid_kwh for p in hourly_plan)
    recalc_cost = sum(p.grid_kwh * hours[h].tariff_bdt_per_kwh for h, p in enumerate(hourly_plan))
    recalc_peak = max(p.grid_kwh for p in hourly_plan)

    if abs(total_grid_kwh - recalc_grid) > TOLERANCE:
        errors.append(f"total_grid_kwh ({total_grid_kwh}) does not match recalculated ({recalc_grid})")
    if abs(total_cost_bdt - recalc_cost) > TOLERANCE:
        errors.append(f"total_cost_bdt ({total_cost_bdt}) does not match recalculated ({recalc_cost})")
    if abs(peak_grid_kwh - recalc_peak) > TOLERANCE:
        errors.append(f"peak_grid_kwh ({peak_grid_kwh}) does not match recalculated ({recalc_peak})")

    return len(errors) == 0, errors
