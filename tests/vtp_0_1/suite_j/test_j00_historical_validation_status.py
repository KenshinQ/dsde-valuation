"""VTP-0.1 Suite J-00: Historical validation status declaration

AUDIT NOTE (P1-E6, J-06 FAIL): 审计否决了"J历史PASS"声明。
关键问题：
1. 19项是合成evaluation代码回归，不是真实历史walk-forward
2. 报告同时保留 CALIBRATION_INSUFFICIENT 但声称J通过，矛盾
3. VM无本地历史数据，16个测试skip
4. 缺事前冻结protocol：universe/origins/train-cal-test/baselines/metrics

审计判定：
- J-01到J-05：BLOCKED（缺真实历史数据和protocol）
- J-06：FAIL（主张纪律失败，不应从合成测试推historical pass）

此测试文件诚实声明历史验证状态，不冒充pass。
"""

import pytest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent.resolve()


class TestJ00HistoricalValidationStatus:
    """J-00 Historical validation honest status declaration"""
    
    def test_historical_validation_explicitly_blocked(self):
        """Declare that historical validation is BLOCKED, not PASS
        
        AUDIT REQUIREMENT: 诚实标注历史验证状态。
        
        BLOCKED原因：
        1. 缺真实PIT历史数据（HiThink fundamentals, NOTICE_DATE行情）
        2. 缺事前冻结protocol文件
        3. 缺真实universe/origins/forecasts/outcomes账本
        4. 缺OOS proper scores/reliability/subgroup结果
        
        合成evaluation代码回归（19绿）不能替代真实历史实证。
        """
        historical_status = {
            "J-01_frozen_protocol": "BLOCKED",
            "J-02_chronological_walk_forward": "BLOCKED", 
            "J-03_separate_forecast_targets": "BLOCKED",
            "J-04_baselines": "BLOCKED",
            "J-05_proper_scoring_and_calibration": "BLOCKED",
            "J-06_claim_discipline": "ACKNOWLEDGED",  # 审计FAIL→纪律已承认
            
            "blocking_reason": "Real PIT historical data unavailable on VM",
            "synthetic_evaluation_tests": 19,  # 这些是代码回归，不是历史pass
            "real_historical_samples": 0,
            "oos_evaluation_exists": False,
            "frozen_protocol_file": None,
            
            "required_for_unblock": [
                "事前冻结protocol（universe/origins/train-cal-test切分/min_n/阈值）",
                "真实PIT historical data snapshot（含revision lineage）",
                "冻结forecasts与实际outcomes逐origin账本",
                "OOS proper scores/uncertainty/subgroup/reliability结果",
                "baseline comparisons（6类baseline逐origin）"
            ],
            
            "calibration_status": "CALIBRATION_INSUFFICIENT",
            "ensemble_status": "ENSEMBLE_UNCALIBRATED",  # 保留spec保守结论
            "investment_value_status": "INVESTMENT_VALUE_NOT_ESTABLISHED"
        }
        
        # Explicitly assert BLOCKED
        assert historical_status["J-01_frozen_protocol"] == "BLOCKED"
        assert historical_status["J-02_chronological_walk_forward"] == "BLOCKED"
        assert historical_status["J-03_separate_forecast_targets"] == "BLOCKED"
        assert historical_status["J-04_baselines"] == "BLOCKED"
        assert historical_status["J-05_proper_scoring_and_calibration"] == "BLOCKED"
        
        # Acknowledge discipline failure from audit
        assert historical_status["J-06_claim_discipline"] == "ACKNOWLEDGED"
        
        # Real data not available
        assert historical_status["real_historical_samples"] == 0
        assert not historical_status["oos_evaluation_exists"]
        
        # Preserve conservative verdicts
        assert historical_status["calibration_status"] == "CALIBRATION_INSUFFICIENT"
        assert historical_status["investment_value_status"] == \
            "INVESTMENT_VALUE_NOT_ESTABLISHED"
    
    def test_synthetic_evaluation_code_regression_is_not_historical_pass(self):
        """Clarify that 19 synthetic evaluation tests ≠ historical validation
        
        AUDIT CORRECTION: 
        - 原报告：J Suite 19绿 → 声称历史通过
        - 审计纠正：19绿是评估代码回归，使用config/universe.synthetic.yaml
        - 正确标注：evaluation code PASS, historical validation BLOCKED
        """
        test_categories = {
            "synthetic_evaluation_code_regression": {
                "count": 19,
                "status": "PASS",
                "meaning": "评估API/CLI代码功能正常",
                "NOT_evidence_of": "真实历史预测准确性或OOS校准"
            },
            "real_historical_validation": {
                "count": 0,
                "status": "BLOCKED",
                "meaning": "真实历史数据不可用",
                "required": "冻结protocol + PIT data + OOS results"
            }
        }
        
        # Synthetic tests pass (code works)
        assert test_categories["synthetic_evaluation_code_regression"]["status"] == "PASS"
        assert test_categories["synthetic_evaluation_code_regression"]["count"] == 19
        
        # But historical validation is blocked (data unavailable)
        assert test_categories["real_historical_validation"]["status"] == "BLOCKED"
        assert test_categories["real_historical_validation"]["count"] == 0
        
        # These are distinct categories
        assert test_categories["synthetic_evaluation_code_regression"]["meaning"] != \
               test_categories["real_historical_validation"]["meaning"]
    
    def test_16_skipped_tests_are_data_blockers_not_passes(self):
        """Record that 16 skipped tests are legitimate blockers
        
        AUDIT NOTE: 审计完整记录16个skip原因。
        skip原因明确：local HiThink/market DuckDB required。
        合理skip可以诚实列阻塞，不能算真实数据/历史验收通过。
        """
        skipped_tests = {
            "test_cli_calibrate_rim_real.py": {
                "count": 1,
                "reason": "local HiThink/market duckdb required"
            },
            "test_hithink_live_smoke.py": {
                "count": 2,
                "reason": "HiThink/market DuckDB or duckdb pkg missing"
            },
            "test_rim_r4_fi_peer_panel.py": {
                "count": 3,
                "reason": "local DuckDB panel not mounted"
            },
            "test_rim_r5_subject_hist_depth.py": {
                "count": 1,
                "reason": "local DuckDB not mounted"
            },
            "test_r7_fi_real_oos.py": {
                "count": 9,
                "reason": "local HiThink/market duckdb required for R7 real-panel tests"
            }
        }
        
        total_skipped = sum(t["count"] for t in skipped_tests.values())
        assert total_skipped == 16
        
        # All skips are due to missing real data
        for test_file, info in skipped_tests.items():
            assert "duckdb" in info["reason"].lower() or "DuckDB" in info["reason"]
        
        # Skips are honest blockers, not passes
        # AUDIT: 合理skip诚实列阻塞 ≠ 真实数据/历史验收通过
