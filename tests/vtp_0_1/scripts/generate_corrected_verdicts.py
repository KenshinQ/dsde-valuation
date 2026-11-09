#!/usr/bin/env python3
"""Generate CORRECTED verdicts - 纠正第三轮错误声明

审计抽查发现：
1. Mutation测试是模拟（simulation_note字段），不是真实patch
2. Routing confusion有62 mismatches + 344 unknown，不应标PASS
3. A-02仍有失败测试
4. E2E仅bundle自洽，无真实离线阻断

纠正：
- I-M01至I-M06: PASS → NOT_EXECUTED（未真实patch）
- E-01(#3): PASS → FAIL（mismatch/unknown过多）
- A-02: 保持FAIL
- 整体：ENGINEERING_BLOCKED
"""

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "tests" / "vtp_0_1"))

from verdict_logic import compute_fail_closed_verdicts

ARTIFACTS = PROJECT_ROOT / "artifacts" / "vtp-0.1-evidence"


def load_corrected_criteria_status():
    """加载纠正后的criteria状态（诚实版本）"""
    
    criteria = [
        # Round 1+2 completed (unchanged)
        {"id": "A-01", "status": "UNVERIFIED"},
        {"id": "A-02", "status": "FAIL"},  # 1 test still fails
        {"id": "A-03", "status": "UNVERIFIED"},
        {"id": "A-04", "status": "UNVERIFIED"},
        
        # E-01 (缺口#3) - 纠正：mismatch/unknown过多
        {"id": "E-01", "status": "FAIL"},  # Was incorrectly marked PASS
        
        # G Suite (release blockers) - 这些是真实数值实验，保持PASS
        {"id": "G-01", "status": "PASS"},
        {"id": "G-02", "status": "PASS"},
        {"id": "G-03", "status": "PASS"},
        {"id": "G-04", "status": "PASS"},
        {"id": "G-05", "status": "PASS"},
        
        # I Suite mutations - 纠正：未真实patch，是模拟
        {"id": "I-M01", "status": "NOT_EXECUTED"},  # Was incorrectly marked PASS
        {"id": "I-M02", "status": "NOT_EXECUTED"},
        {"id": "I-M03", "status": "NOT_EXECUTED"},
        {"id": "I-M04", "status": "NOT_EXECUTED"},
        {"id": "I-M05", "status": "NOT_EXECUTED"},
        {"id": "I-M06", "status": "NOT_EXECUTED"},
        
        # J Suite (historical, still blocked)
        {"id": "J-01", "status": "BLOCKED"},
        {"id": "J-02", "status": "BLOCKED"},
        {"id": "J-03", "status": "BLOCKED"},
        {"id": "J-04", "status": "BLOCKED"},
        {"id": "J-05", "status": "BLOCKED"},
    ]
    
    return criteria


def main():
    print("="*60)
    print("VTP-0.1 CORRECTED Verdicts (纠正第三轮错误)")
    print("="*60)
    
    # Load corrected criteria
    criteria = load_corrected_criteria_status()
    
    print(f"\n→ Loaded {len(criteria)} criteria (corrected)")
    print("\n纠正项：")
    print("  - I-M01至I-M06: PASS → NOT_EXECUTED (模拟非真实patch)")
    print("  - E-01(#3): PASS → FAIL (62 mismatches + 344 unknown)")
    print("  - A-02: 保持FAIL (1 test still fails)")
    
    # Compute verdicts
    verdicts_raw = compute_fail_closed_verdicts(criteria)
    
    # Construct JSON-serializable dict
    verdicts = {
        "round": "3-CORRECTED",
        "correction_note": "审计抽查否决第三轮#3/#6的PASS声明。本verdicts为纠正版本。",
        "corrections_applied": [
            "I-M01至I-M06: PASS → NOT_EXECUTED (mutation是模拟，未真实patch源代码)",
            "E-01(#3): PASS → FAIL (routing confusion: 62 mismatches + 344 unknown)",
            "A-02: 保持FAIL (1个测试失败，proxy≠真断网)",
            "E2E(#9): 保持PARTIAL (bundle自洽≠离线阻断)"
        ],
        "engineering": verdicts_raw["engineering"],
        "data_quality": verdicts_raw["data_quality"],
        "historical_validation": verdicts_raw["historical_validation"],
        "calibration": verdicts_raw["calibration"],
        "investment_value": verdicts_raw["investment_value"],
        "blocking_reasons": verdicts_raw["blocking_reasons"],
        "overall_release_decision": verdicts_raw["overall_release_decision"]
    }
    
    verdicts["false_claims_retracted"] = {
        "mutation_score_100_percent": "作废 - mutation是模拟非真实执行",
        "I_blockers_cleared": "作废 - I-M01至I-M06为NOT_EXECUTED",
        "gap3_routing_complete": "作废 - E-01有62 mismatches需分析",
        "gap6_mutation_complete": "作废 - 需真实patch源代码"
    }
    
    # Write corrected verdicts
    verdicts_file = ARTIFACTS / "verdicts_round3_CORRECTED.json"
    with open(verdicts_file, 'w') as f:
        json.dump(verdicts, f, indent=2, ensure_ascii=False)
    
    print(f"\n✓ Corrected verdicts saved: {verdicts_file}")
    
    # Display results
    print("\n" + "="*60)
    print("CORRECTED Verdict Results:")
    print("="*60)
    print(f"Overall Decision: {verdicts['overall_release_decision']}")
    print(f"Engineering:      {verdicts['engineering']}")
    print(f"Data Quality:     {verdicts['data_quality']}")
    print(f"Historical:       {verdicts['historical_validation']}")
    print(f"Calibration:      {verdicts['calibration']}")
    print(f"Investment:       {verdicts['investment_value']}")
    
    print(f"\nBlocking Reasons: {len(verdicts['blocking_reasons'])}")
    for reason in verdicts['blocking_reasons'][:10]:
        print(f"  - {reason['id']}: {reason['status']}")
    
    # Analysis
    print("\n" + "="*60)
    print("纠正后分析:")
    print("="*60)
    
    g_blockers = [r for r in verdicts['blocking_reasons'] if r['id'].startswith('G-')]
    i_blockers = [r for r in verdicts['blocking_reasons'] if r['id'].startswith('I-M')]
    j_blockers = [r for r in verdicts['blocking_reasons'] if r['id'].startswith('J-')]
    e_blockers = [r for r in verdicts['blocking_reasons'] if r['id'] == 'E-01']
    a_blockers = [r for r in verdicts['blocking_reasons'] if r['id'] == 'A-02']
    
    print(f"G Suite blockers: {len(g_blockers)} (仍为0，G数值实验是真实的)")
    print(f"I Suite blockers: {len(i_blockers)} (恢复为6 - mutation未真实执行)")
    print(f"E-01 blocker:     {len(e_blockers)} (routing confusion不合格)")
    print(f"J Suite blockers: {len(j_blockers)} (仍为5 - 缺真实数据)")
    print(f"A-02 blocker:     {len(a_blockers)} (仍为1 - 1 test fails)")
    
    print("\n结论（纠正后）：")
    print("判定仍为ENGINEERING_BLOCKED（fail-closed原则）")
    print("\n主要阻塞原因：")
    print("  - A-02: 1个测试仍失败")
    print("  - E-01(#3): routing confusion不合格")
    print("  - I-M01至I-M06: mutation未真实patch")
    print("  - J-01至J-05: 缺真实历史数据")
    
    print("\n撤回第三轮错误声明：")
    print("  ✗ Mutation score 100% (作废)")
    print("  ✗ I blockers cleared (作废)")
    print("  ✗ 缺口#3 PASS (作废)")
    print("  ✗ 缺口#6 PASS (作废)")
    
    return verdicts


if __name__ == "__main__":
    main()
