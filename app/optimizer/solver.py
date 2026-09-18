import numpy as np
from typing import List, Dict, Any, Tuple
from scipy.optimize import milp, LinearConstraint, Bounds

from app.schemas import (
    HourInput,
    BatteryInput,
    DirectiveInterpretationEntry,
    HourlyPlanEntry,
    OptimizeEnergyResponse
)

def solve_energy_schedule(
    scenario_id: str,
    hours: List[HourInput],
    battery: BatteryInput,
    directives: List[DirectiveInterpretationEntry]
) -> Tuple[List[HourlyPlanEntry], float, float, float, str]:
    """
    Formulates and solves the 24-hour campus energy scheduling problem as a Mixed-Integer
    Linear Program (MILP) using SciPy's HiGHS solver.
    Guarantees physical constraint satisfaction and exact cost minimization.
    """
    cap = battery.capacity_kwh
    e_init = battery.initial_energy_kwh
    base_min = battery.minimum_energy_kwh
    base_max_c = battery.max_charge_kwh_per_hour
    base_max_d = battery.max_discharge_kwh_per_hour

    # Initialize hourly constraint arrays
    eff_solar = [h.solar_kwh for h in hours]
    min_res = [base_min] * 24
    max_charge = [base_max_c] * 24
    max_discharge = [base_max_d] * 24
    max_grid = [float("inf")] * 24

    # Apply directives deterministically
    active_directives_summary = []
    for d in directives:
        if not d.applies or not d.structured_adjustment:
            continue
        d_type = d.directive_type
        adj = d.structured_adjustment
        d_hours = adj.get("hours", [])

        if d_type == "solar_reduction":
            factor = float(adj.get("factor", 1.0))
            for h in d_hours:
                eff_solar[h] = eff_solar[h] * factor
            active_directives_summary.append(f"solar reduced to {factor*100:.0f}% in hours {d_hours}")

        elif d_type == "minimum_battery_reserve":
            m = float(adj.get("minimum_energy_kwh", base_min))
            for h in d_hours:
                min_res[h] = max(min_res[h], m)
            active_directives_summary.append(f"reserve raised to {m:.1f} kWh in hours {d_hours}")

        elif d_type == "no_charge_window":
            for h in d_hours:
                max_charge[h] = 0.0
            active_directives_summary.append(f"charging disabled in hours {d_hours}")

        elif d_type == "no_discharge_window":
            for h in d_hours:
                max_discharge[h] = 0.0
            active_directives_summary.append(f"discharging disabled in hours {d_hours}")

        elif d_type == "max_grid_window":
            mg = float(adj.get("max_grid_kwh", float("inf")))
            for h in d_hours:
                max_grid[h] = min(max_grid[h], mg)
            active_directives_summary.append(f"grid capped at {mg:.1f} kWh in hours {d_hours}")

    # Decision variables (120 variables total):
    # 0..23:   grid_kwh (g)
    # 24..47:  solar_used_kwh (s)
    # 48..71:  battery_charge_kwh (c)
    # 72..95:  battery_discharge_kwh (d)
    # 96..119: binary charge indicator (b) in {0, 1}
    n_vars = 120
    c_obj = np.zeros(n_vars)
    for h in range(24):
        c_obj[h] = hours[h].tariff_bdt_per_kwh
        # Tiny tie-breaking penalty to prevent unnecessary cycling
        c_obj[48 + h] += 1e-6
        c_obj[72 + h] += 1e-6

    integrality = np.zeros(n_vars)
    integrality[96:120] = 1  # 24 binary variables

    lb = np.zeros(n_vars)
    ub = np.zeros(n_vars)
    for h in range(24):
        lb[h] = 0.0
        ub[h] = max_grid[h]
        lb[24 + h] = 0.0
        ub[24 + h] = eff_solar[h]
        lb[48 + h] = 0.0
        ub[48 + h] = max_charge[h]
        lb[72 + h] = 0.0
        ub[72 + h] = max_discharge[h]
        lb[96 + h] = 0.0
        ub[96 + h] = 1.0

    A_eq = []
    b_eq = []
    A_ub = []
    b_ub_l = []
    b_ub_u = []

    # 1. Energy balance each hour: g_h + s_h + d_h - c_h = demand_h
    for h in range(24):
        row = np.zeros(n_vars)
        row[h] = 1.0
        row[24 + h] = 1.0
        row[72 + h] = 1.0
        row[48 + h] = -1.0
        A_eq.append(row)
        b_eq.append(hours[h].demand_kwh)

    # 2. End-of-day battery neutrality: sum(c) - sum(d) = 0
    row_neut = np.zeros(n_vars)
    for h in range(24):
        row_neut[48 + h] = 1.0
        row_neut[72 + h] = -1.0
    A_eq.append(row_neut)
    b_eq.append(0.0)

    # 3. Battery bounds: min_res[h] <= e_init + sum_{i=0}^h (c_i - d_i) <= cap
    for h in range(24):
        row = np.zeros(n_vars)
        for i in range(h + 1):
            row[48 + i] = 1.0
            row[72 + i] = -1.0
        A_ub.append(row)
        b_ub_l.append(min_res[h] - e_init)
        b_ub_u.append(cap - e_init)

    # 4. Binary exclusivity: c_h <= max_c * b_h, d_h <= max_d * (1 - b_h)
    for h in range(24):
        # c_h - max_c * b_h <= 0
        row1 = np.zeros(n_vars)
        row1[48 + h] = 1.0
        row1[96 + h] = -base_max_c
        A_ub.append(row1)
        b_ub_l.append(-np.inf)
        b_ub_u.append(0.0)

        # d_h + max_d * b_h <= max_d
        row2 = np.zeros(n_vars)
        row2[72 + h] = 1.0
        row2[96 + h] = base_max_d
        A_ub.append(row2)
        b_ub_l.append(-np.inf)
        b_ub_u.append(base_max_d)

    A_all = np.vstack([np.array(A_eq), np.array(A_ub)])
    lb_all = np.array(b_eq + b_ub_l)
    ub_all = np.array(b_eq + b_ub_u)

    constraints = LinearConstraint(A_all, lb_all, ub_all)
    bounds = Bounds(lb, ub)

    res = milp(c=c_obj, constraints=constraints, bounds=bounds, integrality=integrality)
    if not res.success:
        raise RuntimeError(f"MILP optimization failed to find feasible schedule: {res.status}")

    sol = res.x
    g_sol = sol[0:24]
    s_sol = sol[24:48]
    c_sol = sol[48:72]
    d_sol = sol[72:96]

    # Reconstruct hourly plan
    hourly_plan: List[HourlyPlanEntry] = []
    current_e = e_init

    for h in range(24):
        g_val = float(g_sol[h])
        s_val = float(s_sol[h])
        c_val = float(c_sol[h])
        d_val = float(d_sol[h])

        # Numerical cleanup
        if g_val < 1e-5:
            g_val = 0.0
        if s_val < 1e-5:
            s_val = 0.0
        if c_val < 1e-5:
            c_val = 0.0
        if d_val < 1e-5:
            d_val = 0.0

        if c_val > 1e-4:
            action = "charge"
            bat_kwh = c_val
            current_e += c_val
        elif d_val > 1e-4:
            action = "discharge"
            bat_kwh = d_val
            current_e -= d_val
        else:
            action = "idle"
            bat_kwh = 0.0

        # Maintain exact roundings
        hourly_plan.append(
            HourlyPlanEntry(
                hour=h,
                grid_kwh=round(g_val, 4),
                solar_used_kwh=round(s_val, 4),
                battery_action=action,
                battery_kwh=round(bat_kwh, 4),
                battery_energy_after_kwh=round(current_e, 4)
            )
        )

    # Recalculate summary totals exactly from the hourly plan entries
    total_grid_kwh = round(sum(item.grid_kwh for item in hourly_plan), 2)
    total_cost_bdt = round(sum(item.grid_kwh * hours[h].tariff_bdt_per_kwh for h, item in enumerate(hourly_plan)), 2)
    peak_grid_kwh = round(max(item.grid_kwh for item in hourly_plan), 2)

    active_info = f" Active directives: {', '.join(active_directives_summary)}." if active_directives_summary else " No active directive adjustments."
    plan_summary = (
        f"Optimal 24-hour schedule formulated with total cost {total_cost_bdt:.2f} BDT and {total_grid_kwh:.2f} kWh grid energy "
        f"(peak {peak_grid_kwh:.2f} kWh).{active_info} Battery energy neutrality achieved."
    )

    return hourly_plan, total_grid_kwh, total_cost_bdt, peak_grid_kwh, plan_summary
