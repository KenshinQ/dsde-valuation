"""VTP-0.1 Suite E-01: Ten-company routing truth table

AUDIT NOTE (P1-E2): 审计指出原交付只有YAML设计草稿，未真正执行。
缺口：
1. synthetic_companies.yaml 无消费者
2. 缺完整PIT/单位/报表/method决策表
3. 未交10×method×target实测矩阵
4. 未交routing confusion表

此测试实现基础routing验证框架。
真正的完整E-01需要：事前approved完整method×fixture×target真值矩阵。
"""

import json
import yaml
from pathlib import Path
import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent.resolve()
FIXTURES = PROJECT_ROOT / "tests" / "vtp_0_1" / "fixtures" / "synthetic_companies.yaml"


class TestE01TenCompanyRouting:
    """E-01 Routing truth table tests"""
    
    @pytest.fixture
    def synthetic_companies(self):
        """Load the 10 synthetic companies from YAML"""
        with open(FIXTURES) as f:
            data = yaml.safe_load(f)
        return data.get("companies", {})
    
    def test_all_ten_companies_loaded(self, synthetic_companies):
        """Verify all 10 companies are defined in fixture
        
        AUDIT NOTE: 此测试仅验证YAML可读，不是实际路由执行。
        """
        expected_companies = [
            "SYN-MATURE",
            "SYN-GROWTH", 
            "SYN-BANK",
            "SYN-CYCLICAL",
            "SYN-ASSET",
            "SYN-HOLDCO",
            "SYN-DISTRESSED",
            "SYN-BAD-DATA",
            "SYN-HYBRID",
            "SYN-NO-PEERS"
        ]
        
        actual_companies = list(synthetic_companies.keys())
        
        # Check all expected companies exist
        missing = set(expected_companies) - set(actual_companies)
        assert not missing, f"Missing companies: {missing}"
        
        # Each company should have description and expected_routes
        for company_id in expected_companies:
            company = synthetic_companies[company_id]
            assert "description" in company, f"{company_id} missing description"
            assert "expected_routes" in company, f"{company_id} missing expected_routes"
    
    def test_expected_routes_documented(self, synthetic_companies):
        """Verify each company documents expected routing outcomes
        
        AUDIT NOTE: 此测试验证期望路由已声明，但未执行实际routing。
        实际执行需要完整PIT数据+method实现。
        """
        for company_id, company in synthetic_companies.items():
            expected_routes = company.get("expected_routes", {})
            assert len(expected_routes) > 0, \
                f"{company_id} has no expected routing outcomes"
            
            # Each route should specify expected status
            for method, status in expected_routes.items():
                assert status in ["ELIGIBLE", "INELIGIBLE", "WARN", "CONDITIONAL"], \
                    f"{company_id}.{method} has invalid status: {status}"
    
    def test_routing_matrix_structure_exists(self, synthetic_companies):
        """Verify we can construct a method×company routing matrix structure
        
        AUDIT NOTE: 此测试构造空矩阵结构，不填充实测结果。
        真正的E-01需要：每个cell运行路由并记录actual status+reason codes。
        """
        # Collect all methods mentioned across all companies
        all_methods = set()
        for company in synthetic_companies.values():
            all_methods.update(company.get("expected_routes", {}).keys())
        
        # Construct matrix skeleton
        matrix = {
            "companies": list(synthetic_companies.keys()),
            "methods": sorted(all_methods),
            "targets": ["FUNDAMENTAL_VALUE_CURRENT", "MARKET_EXIT_PRICE", 
                       "ASSET_NAV", "TOTAL_RETURN"],
            "cells": {}
        }
        
        # For each company×method, we would run actual routing here
        for company_id in matrix["companies"]:
            for method in matrix["methods"]:
                for target in matrix["targets"]:
                    cell_key = f"{company_id}_{method}_{target}"
                    # AUDIT: 实际执行应在此处调用routing，记录：
                    # - actual_status: ELIGIBLE/INELIGIBLE/WARN
                    # - reason_codes: 具体拒绝原因
                    # - expected_status: 来自YAML
                    # - match: actual == expected
                    matrix["cells"][cell_key] = {
                        "company": company_id,
                        "method": method,
                        "target": target,
                        "expected_status": synthetic_companies[company_id]
                            .get("expected_routes", {}).get(method, "UNKNOWN"),
                        "actual_status": "NOT_EXECUTED",  # 待实现
                        "reason_codes": [],
                        "execution_timestamp": None
                    }
        
        # Matrix structure is valid
        assert len(matrix["companies"]) == 10
        assert len(matrix["methods"]) > 5  # Should have multiple methods
        assert len(matrix["targets"]) == 4
        
        # AUDIT NOTE: 审计要求交付此matrix填充实测结果。
        # 当前状态：NOT_EXECUTED（结构已建，实测待补）。
    
    def test_routing_confusion_table_placeholder(self, synthetic_companies):
        """Placeholder for routing confusion matrix
        
        AUDIT NOTE: 审计要求routing confusion表（预期vs实测不一致汇总）。
        真正实现需要：
        1. 执行所有company×method×target
        2. 对比expected vs actual
        3. 统计：true positives, false positives, false negatives, true negatives
        """
        # Expected format:
        confusion = {
            "true_positive": 0,   # expected ELIGIBLE, actual ELIGIBLE
            "false_positive": 0,  # expected INELIGIBLE, actual ELIGIBLE
            "false_negative": 0,  # expected ELIGIBLE, actual INELIGIBLE
            "true_negative": 0,   # expected INELIGIBLE, actual INELIGIBLE
            "warn_matches": 0,
            "conditional_resolved": 0,
            "not_executed": 0  # 当前状态
        }
        
        # Count total expected routes
        total_expected = sum(
            len(c.get("expected_routes", {})) 
            for c in synthetic_companies.values()
        )
        
        confusion["not_executed"] = total_expected * 4  # 4 targets each
        
        # AUDIT: 真正的confusion需要实测后填充
        assert confusion["not_executed"] > 0, "Matrix has expected routes"
