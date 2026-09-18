import json
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.schemas import OptimizeEnergyRequest
from app.main import optimize_energy
from app.utils.replay import replay_and_verify_schedule

SAMPLE_FILE = "/home/mehedi/Videos/BUP_CSE_FEST_2026_Participant_Docs/BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json"

def run_tests():
    if not os.path.exists(SAMPLE_FILE):
        print(f"Sample file not found at {SAMPLE_FILE}")
        return

    with open(SAMPLE_FILE) as f:
        data = json.load(f)

    cases = data.get("cases", [])
    print(f"\n========================================================")
    print(f"RUNNING GRIDWISE LLM VALIDATION ON ALL {len(cases)} SAMPLE CASES")
    print(f"========================================================\n")

    total_cases = len(cases)
    passed_cases = 0

    for i, c in enumerate(cases):
        case_id = c["input"]["scenario_id"]
        label = c.get("label", "")
        print(f"--- Case {i+1}/{total_cases}: {case_id} ({label}) ---")

        req = OptimizeEnergyRequest(**c["input"])
        resp = optimize_energy(req)

        # 1. Check Directive Interpretation
        exp_dirs = c["expected_output"]["directive_interpretation"]
        act_dirs = resp.directive_interpretation

        dir_match = True
        if len(act_dirs) != len(exp_dirs):
            print(f"  [FAIL] Expected {len(exp_dirs)} directives, got {len(act_dirs)}")
            dir_match = False
        else:
            for d_exp, d_act in zip(exp_dirs, act_dirs):
                if d_act.note_index != d_exp["note_index"]:
                    print(f"  [FAIL] Note index mismatch: expected {d_exp['note_index']}, got {d_act.note_index}")
                    dir_match = False
                if d_act.applies != d_exp["applies"]:
                    print(f"  [FAIL] applies mismatch on note {d_act.note_index}: expected {d_exp['applies']}, got {d_act.applies}")
                    dir_match = False
                if d_act.directive_type != d_exp["directive_type"]:
                    print(f"  [FAIL] directive_type mismatch on note {d_act.note_index}: expected {d_exp['directive_type']}, got {d_act.directive_type}")
                    dir_match = False
                if d_exp["structured_adjustment"] is not None:
                    exp_adj = d_exp["structured_adjustment"]
                    act_adj = d_act.structured_adjustment or {}
                    if act_adj.get("hours") != exp_adj.get("hours"):
                        print(f"  [FAIL] hours mismatch: expected {exp_adj.get('hours')}, got {act_adj.get('hours')}")
                        dir_match = False
                    for key in ["factor", "minimum_energy_kwh", "max_grid_kwh"]:
                        if key in exp_adj:
                            exp_v = exp_adj[key]
                            act_v = act_adj.get(key)
                            if act_v is None or abs(float(act_v) - float(exp_v)) > 0.02:
                                print(f"  [FAIL] {key} mismatch: expected {exp_v}, got {act_v}")
                                dir_match = False

        # 2. Check Replay Validity
        is_valid, errors = replay_and_verify_schedule(
            hours=req.hours,
            battery=req.battery,
            directives=act_dirs,
            hourly_plan=resp.hourly_plan,
            total_grid_kwh=resp.total_grid_kwh,
            total_cost_bdt=resp.total_cost_bdt,
            peak_grid_kwh=resp.peak_grid_kwh
        )

        # 3. Check Optimal Cost
        exp_cost = c["expected_output"]["total_cost_bdt"]
        act_cost = resp.total_cost_bdt
        cost_diff = abs(act_cost - exp_cost)
        cost_ok = cost_diff < 0.05

        if dir_match and is_valid and cost_ok:
            passed_cases += 1
            print(f"  [PASS] Directives Match | Schedule Valid | Cost: {act_cost:.2f} BDT (exp: {exp_cost:.2f})")
        else:
            print(f"  [FAIL] Directives Match: {dir_match} | Schedule Valid: {is_valid} | Cost Diff: {cost_diff:.2f}")
            if errors:
                for err in errors:
                    print(f"    - Error: {err}")

    print(f"\n========================================================")
    print(f"RESULTS: {passed_cases}/{total_cases} CASES PASSED")
    print(f"========================================================\n")

if __name__ == "__main__":
    run_tests()
