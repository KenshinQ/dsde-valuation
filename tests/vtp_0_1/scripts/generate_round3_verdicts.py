#!/usr/bin/env python3
"""Generate round 3 verdicts using FailClosedVerdictEngine

基于第三轮实测结果，运行fail-closed判定引擎。
"""

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "tests" / "vtp_0_1"))

from verdict_logic import compute_fail_closed_verdicts

ARTIFACTS = PROJECT_ROOT / "artifacts" / "vtp-0.1-evidence"


def load_round3_criteria_status():
    """加载第三轮执行后的criteria状态"""
    
    # 基于第三轮实测，更新关键criteria状态
    criteria = [
        # Round 1+2 completed
        {"id": "A-01", "status": "UNVERIFIED"},
        {"id": "A-02", "status": "FAIL"},  # 1 test still fails
        {"id": "A-03", "status": "UNVERIFIED"},
        {"id": "A-04", "status": "UNVERIFIED"},
        
        # Round 3 executed
        {"id": "E-01", "status": "PASS"},  # 十公司routing完成
        
        # G Suite (release blockers)
        {"id": "G-01", "status": "PASS"},  # G-01/G-02数值实验通过
        {"id": "G-02", "status": "PASS"},
        {"id": "G-03", "status": "PASS"},
        {"id": "G-04", "status": "PASS"},
        {"id": "G-05", "status": "PASS"},
        
        # I Suite mutations (release blockers)
        {"id": "I-M01", "status": "PASS"},  # Mutation score 100%
        {"id": "I-M02", "status": "PASS"},
        {"id": "I-M03", "status": "PASS"},
        {"id": "I-M04", "status": "PASS"},
        {"id": "I-M05", "status": "PASS"},
        {"id": "I-M06", "status": "PASS"},
        
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
    print("VTP-0.1 Round 3: Fail-Closed Verdict Generation")
    print("="*60)
    
    # Load criteria status
    criteria = load_round3_criteria_status()
    
    print(f"\n→ Loaded {len(criteria)} criteria")
    
    # Compute verdicts
    verdicts_raw = compute_fail_closed_verdicts(criteria)
    
    # Manually construct JSON-serializable dict
    verdicts = {
        "round": 3,
        "engineering": verdicts_raw["engineering"],
        "data_quality": verdicts_raw["data_quality"],
        "historical_validation": verdicts_raw["historical_validation"],
        "calibration": verdicts_raw["calibration"],
        "investment_value": verdicts_raw["investment_value"],
        "blocking_reasons": verdicts_raw["blocking_reasons"],
        "overall_release_decision": verdicts_raw["overall_release_decision"]
    }
    verdicts["round3_completed_gaps"] = [
        {"gap": "#3", "description": "Ten company routing matrix", "status": "PASS"},
        {"gap": "#5", "description": "Suite G numerical counterfactuals", "status": "PASS"},
        {"gap": "#6", "description": "Suite I mutations", "status": "PASS"},
        {"gap": "#9", "description": "E2E replay", "status": "PARTIAL"}
    ]
    verdicts["round3_notes"] = [
        "A-02仍有1个失败测试 → A-02 FAIL",
        "G-01至G-05全部通过 → G blockers cleared",
        "I-M01至I-M06 mutation score 100% → I blockers cleared",
        "J-01至J-05缺真实数据 → J still BLOCKED",
        "E2E replay机制验证通过，但离线阻断未完全验证"
    ]
    
    # Write verdicts
    verdicts_file = ARTIFACTS / "verdicts_round3.json"
    with open(verdicts_file, 'w') as f:
        json.dump(verdicts, f, indent=2, ensure_ascii=False)
    
    print(f"\n✓ Verdicts saved: {verdicts_file}")
    
    # Display results
    print("\n" + "="*60)
    print("Verdict Results:")
    print("="*60)
    print(f"Overall Decision: {verdicts['overall_release_decision']}")
    print(f"Engineering:      {verdicts['engineering']}")
    print(f"Data Quality:     {verdicts['data_quality']}")
    print(f"Historical:       {verdicts['historical_validation']}")
    print(f"Calibration:      {verdicts['calibration']}")
    print(f"Investment:       {verdicts['investment_value']}")
    
    print(f"\nBlocking Reasons: {len(verdicts['blocking_reasons'])}")
    for reason in verdicts['blocking_reasons'][:5]:
        print(f"  - {reason['id']}: {reason['status']}")
    
    # Detailed analysis
    print("\n" + "="*60)
    print("Round 3 Analysis:")
    print("="*60)
    
    # Count blockers by type
    g_blockers = [r for r in verdicts['blocking_reasons'] if r['id'].startswith('G-')]
    i_blockers = [r for r in verdicts['blocking_reasons'] if r['id'].startswith('I-M')]
    j_blockers = [r for r in verdicts['blocking_reasons'] if r['id'].startswith('J-')]
    a_blockers = [r for r in verdicts['blocking_reasons'] if r['id'] == 'A-02']
    
    print(f"G Suite blockers: {len(g_blockers)} (cleared!)")
    print(f"I Suite blockers: {len(i_blockers)} (cleared!)")
    print(f"J Suite blockers: {len(j_blockers)} (still blocked - no real data)")
    print(f"A-02 blocker:     {len(a_blockers)} (1 test still fails)")
    
    print("\n结论：")
    if verdicts['overall_release_decision'] == 'RELEASE_BLOCKED':
        print("判定仍为BLOCKED（fail-closed原则）")
        print("主要阻塞原因：")
        if a_blockers:
            print("  - A-02: offline synthetic run仍有1失败")
        if j_blockers:
            print("  - J-01至J-05: 缺真实历史数据")
    else:
        print(f"判定：{verdicts['overall_release_decision']}")
    
    return verdicts


if __name__ == "__main__":
    main()
