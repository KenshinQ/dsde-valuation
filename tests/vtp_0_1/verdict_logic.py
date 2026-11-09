"""VTP-0.1 Fail-closed verdict logic

AUDIT REQUIREMENT (缺口#10): 实现release blocker未全绿则BLOCKED的判定逻辑。

判定原则：
1. 工程：release blocker未全绿 → ENGINEERING_BLOCKED
2. 数据质量：合成质量门禁 ≠ 真实数据验收 → UNVERIFIED
3. 历史：real_samples=0 → BLOCKED
4. 不从部分进展推导ACCEPTED

Spec明确的release blockers:
- A-02 Offline synthetic run (失败则阻塞)
- G Suite (Market-pricing separation, spec:271 明确release blocker)
- Suite I Properties/mutations (spec:339/448/561)
- Suite J Historical validation (缺真实数据则BLOCKED)
"""

from typing import Dict, Any, List
from enum import Enum


class VerdictStatus(Enum):
    """Verdict status values"""
    ENGINEERING_ACCEPTED = "ENGINEERING_ACCEPTED"
    ENGINEERING_BLOCKED = "ENGINEERING_BLOCKED"
    
    DATA_QUALITY_PASS = "DATA_QUALITY_PASS"
    DATA_QUALITY_UNVERIFIED = "DATA_QUALITY_UNVERIFIED"
    
    HISTORICAL_VALIDATION_PASS = "HISTORICAL_VALIDATION_PASS"
    HISTORICAL_VALIDATION_BLOCKED = "HISTORICAL_VALIDATION_BLOCKED"
    
    CALIBRATION_PASS = "CALIBRATION_PASS"
    CALIBRATION_INSUFFICIENT = "CALIBRATION_INSUFFICIENT"
    
    INVESTMENT_VALUE_ESTABLISHED = "INVESTMENT_VALUE_ESTABLISHED"
    INVESTMENT_VALUE_NOT_ESTABLISHED = "INVESTMENT_VALUE_NOT_ESTABLISHED"


class FailClosedVerdictEngine:
    """Fail-closed verdict engine per audit requirements"""
    
    RELEASE_BLOCKERS = {
        "A-02": "Offline synthetic run must pass",
        "G-01": "Intrinsic/market separation (release blocker per spec:271)",
        "G-02": "Fixed intrinsic vary multiple",
        "G-03": "Fixed multiple vary financial",
        "G-04": "Fundamental/market independence",
        "G-05": "Explicit convergence scenarios",
        "I-M01": "Mutation: debt sign reversal",
        "I-M02": "Mutation: bypass hard gates",
        "I-M03": "Mutation: post-as_of inclusion",
        "I-M04": "Mutation: mixture→mean averaging",
        "I-M05": "Mutation: exit forced intrinsic",
        "I-M06": "Mutation: drop failed paths",
        "J-01": "Frozen historical protocol",
        "J-02": "Chronological walk-forward",
        "J-03": "Separate forecast targets",
        "J-04": "Baseline comparisons",
        "J-05": "Proper scoring and calibration"
    }
    
    def __init__(self, criteria_results: List[Dict[str, Any]]):
        """Initialize with criteria results
        
        Args:
            criteria_results: List of dicts with keys: id, status, ...
        """
        self.criteria = {c["id"]: c for c in criteria_results}
        self.verdicts = {}
        self.blocking_reasons = []
    
    def evaluate_engineering(self) -> VerdictStatus:
        """Evaluate engineering verdict (fail-closed)
        
        Returns ACCEPTED only if ALL release blockers pass.
        """
        blocking_failures = []
        
        for blocker_id, reason in self.RELEASE_BLOCKERS.items():
            criterion = self.criteria.get(blocker_id, {})
            status = criterion.get("status", "NOT_EXECUTED")
            
            # Fail-closed: anything except PASS blocks
            if status != "PASS":
                blocking_failures.append({
                    "id": blocker_id,
                    "status": status,
                    "reason": reason
                })
        
        if blocking_failures:
            self.blocking_reasons.extend(blocking_failures)
            self.verdicts["engineering"] = VerdictStatus.ENGINEERING_BLOCKED
            self.verdicts["engineering_blockers"] = blocking_failures
            return VerdictStatus.ENGINEERING_BLOCKED
        else:
            self.verdicts["engineering"] = VerdictStatus.ENGINEERING_ACCEPTED
            return VerdictStatus.ENGINEERING_ACCEPTED
    
    def evaluate_data_quality(self) -> VerdictStatus:
        """Evaluate data quality verdict (fail-closed)
        
        Synthetic quality gates ≠ real data validation.
        """
        # Check if we have real data tests
        real_data_tests = [
            c for c in self.criteria.values()
            if "real" in c.get("id", "").lower() or "historical" in c.get("id", "").lower()
        ]
        
        real_data_passed = sum(1 for t in real_data_tests if t.get("status") == "PASS")
        
        if real_data_passed == 0:
            # No real data tests passed → UNVERIFIED
            self.verdicts["data_quality"] = VerdictStatus.DATA_QUALITY_UNVERIFIED
            self.verdicts["data_quality_reason"] = "合成质量门禁回归 ≠ 真实数据验收"
            return VerdictStatus.DATA_QUALITY_UNVERIFIED
        else:
            # Some real data validation exists
            self.verdicts["data_quality"] = VerdictStatus.DATA_QUALITY_PASS
            return VerdictStatus.DATA_QUALITY_PASS
    
    def evaluate_historical_validation(self) -> VerdictStatus:
        """Evaluate historical validation verdict (fail-closed)
        
        Requires real PIT historical data and walk-forward execution.
        """
        # Check J-01 through J-05
        j_criteria = [f"J-{i:02d}" for i in range(1, 6)]
        j_blocked = sum(
            1 for jid in j_criteria
            if self.criteria.get(jid, {}).get("status") in ["BLOCKED", "NOT_EXECUTED", "FAIL"]
        )
        
        if j_blocked > 0:
            self.verdicts["historical"] = VerdictStatus.HISTORICAL_VALIDATION_BLOCKED
            self.verdicts["historical_reason"] = f"{j_blocked}/5 J criteria BLOCKED (real data unavailable)"
            return VerdictStatus.HISTORICAL_VALIDATION_BLOCKED
        else:
            self.verdicts["historical"] = VerdictStatus.HISTORICAL_VALIDATION_PASS
            return VerdictStatus.HISTORICAL_VALIDATION_PASS
    
    def evaluate_calibration(self) -> VerdictStatus:
        """Evaluate calibration verdict (always INSUFFICIENT unless proven)
        
        Conservative: keep INSUFFICIENT unless OOS validation exists.
        """
        # Default to INSUFFICIENT (conservative)
        self.verdicts["calibration"] = VerdictStatus.CALIBRATION_INSUFFICIENT
        self.verdicts["calibration_reason"] = "No OOS evaluation with real data (spec保守默认)"
        return VerdictStatus.CALIBRATION_INSUFFICIENT
    
    def evaluate_investment_value(self) -> VerdictStatus:
        """Evaluate investment value verdict (always NOT_ESTABLISHED)
        
        Conservative: do not infer from software tests.
        """
        # Default to NOT_ESTABLISHED (conservative)
        self.verdicts["investment"] = VerdictStatus.INVESTMENT_VALUE_NOT_ESTABLISHED
        self.verdicts["investment_reason"] = "不从软件测试推导投资边界 (spec保守默认)"
        return VerdictStatus.INVESTMENT_VALUE_NOT_ESTABLISHED
    
    def evaluate_all(self) -> Dict[str, Any]:
        """Evaluate all verdicts (fail-closed)
        
        Returns:
            Dict with all verdicts and blocking reasons
        """
        results = {
            "engineering": self.evaluate_engineering().value,
            "data_quality": self.evaluate_data_quality().value,
            "historical_validation": self.evaluate_historical_validation().value,
            "calibration": self.evaluate_calibration().value,
            "investment_value": self.evaluate_investment_value().value,
            
            "verdict_details": self.verdicts,
            "blocking_reasons": self.blocking_reasons,
            
            "overall_release_decision": self._overall_decision()
        }
        
        return results
    
    def _overall_decision(self) -> str:
        """Overall release decision
        
        Returns:
            "RELEASE_BLOCKED" or "RELEASE_APPROVED"
        """
        engineering = self.verdicts.get("engineering")
        
        if engineering == VerdictStatus.ENGINEERING_BLOCKED:
            return "RELEASE_BLOCKED"
        elif len(self.blocking_reasons) > 0:
            return "RELEASE_BLOCKED"
        else:
            # Even if engineering passes, be conservative
            return "RELEASE_APPROVED_WITH_CAVEATS"


def compute_fail_closed_verdicts(criteria_results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute fail-closed verdicts from criteria results
    
    Args:
        criteria_results: List of criterion dicts with id and status
        
    Returns:
        Dict with all verdicts
    """
    engine = FailClosedVerdictEngine(criteria_results)
    return engine.evaluate_all()


if __name__ == "__main__":
    # Example usage with mock data
    mock_criteria = [
        {"id": "A-01", "status": "UNVERIFIED"},
        {"id": "A-02", "status": "FAIL"},  # Release blocker fails
        {"id": "G-01", "status": "UNVERIFIED"},  # Release blocker not done
        {"id": "I-M01", "status": "NOT_EXECUTED"},  # Mutation not run
        {"id": "J-01", "status": "BLOCKED"},  # Historical blocked
    ]
    
    verdicts = compute_fail_closed_verdicts(mock_criteria)
    
    print(f"{'='*60}")
    print(f"Overall Decision: {verdicts['overall_release_decision']}")
    print(f"Engineering: {verdicts['engineering']}")
    print(f"Data Quality: {verdicts['data_quality']}")
    print(f"Historical: {verdicts['historical_validation']}")
    print(f"Calibration: {verdicts['calibration']}")
    print(f"Investment: {verdicts['investment_value']}")
    print(f"\nBlocking Reasons: {len(verdicts['blocking_reasons'])}")
    for reason in verdicts['blocking_reasons'][:5]:
        print(f"  - {reason['id']}: {reason['status']}")
