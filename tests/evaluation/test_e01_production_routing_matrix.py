"""Official VTP-0.1 E-01: production route_methods 10×12×4 truth table.

These tests call ``vms.router.route_methods`` (no toy / SimplifiedRoutingEngine).
They do not retune fixtures or expected routes after seeing results.
Official E-01 is not PASS while gaps, vacuous/structural cells, or mismatches remain.
"""

from __future__ import annotations

from vms.router import route_methods
from vms.schemas.contracts import ValuationTarget

from tests.evaluation.e01_production_routing_matrix import (
    COMPANIES,
    MATRIX_METHODS,
    OFFICIAL_TARGETS,
    build_matrix,
    official_e01_status,
)


def test_route_methods_is_the_production_symbol():
    assert route_methods.__module__ == "vms.router.route"
    assert "Simplified" not in route_methods.__module__


def test_official_e01_helper_fail_closed_on_gaps():
    blocked = official_e01_status({
        "mismatches": 0,
        "not_predeclared": 1,
        "expected_non_binary": 0,
        "method_not_in_registry": 0,
        "structural_unsupported_total_return": 0,
        "not_executed": 0,
        "executed_route_calls": 40,
    })
    assert blocked == "PARTIAL"
    perfect = official_e01_status({
        "mismatches": 0,
        "not_predeclared": 0,
        "expected_non_binary": 0,
        "method_not_in_registry": 0,
        "structural_unsupported_total_return": 0,
        "not_executed": 0,
        "executed_route_calls": 40,
    })
    assert perfect == "PASS"
    empty = official_e01_status({
        "mismatches": 0,
        "not_predeclared": 0,
        "expected_non_binary": 0,
        "method_not_in_registry": 0,
        "structural_unsupported_total_return": 0,
        "not_executed": 1,
        "executed_route_calls": 0,
    })
    assert empty == "BLOCKED"


def test_production_10x12x4_matrix_executes_and_is_not_official_pass():
    bundle = build_matrix()
    summary = bundle["summary"]
    assert bundle["api"] == "vms.router.route_methods"
    assert summary["toy_router_used"] is False
    assert summary["total_cells"] == 10 * 12 * 4 == 480
    assert summary["executed_route_calls"] == 10 * 4 == 40
    assert summary["not_executed"] == 0
    assert list(bundle["companies"]) == list(COMPANIES)
    assert list(bundle["methods"]) == list(MATRIX_METHODS)
    assert bundle["targets"] == [t.value for t in OFFICIAL_TARGETS]
    assert "midcycle_normalized" in bundle["methods"]
    assert "midcycle_normalized" not in summary["production_methods_in_registry"]
    assert summary["method_not_in_registry"] == 40
    assert summary["no_production_method_supports_total_return"] is True
    assert summary["structural_unsupported_total_return"] == 120
    assert summary["determinism_repeat_ok"] is True
    assert official_e01_status(summary) == summary["official_e01"]
    assert summary["official_e01"] != "PASS"
    # Routing decisions carry reason codes on considered methods
    considered = [
        c for c in bundle["cells"]
        if c["actual_status"] in {"ELIGIBLE", "INELIGIBLE"}
    ]
    assert considered
    assert all(c["reasons"] for c in considered)


def test_syn_no_peers_relative_methods_deferred_peer_gate_is_recorded():
    """E-05 / YAML expect relative methods ineligible without peers.

    Production ``route_methods`` eligibility currently defers peer_count=0
    (PEER_COUNT_HINT passed). This test records that gap; it does not change
    production gates.
    """
    bundle = build_matrix()
    cells = {
        (c["company_id"], c["method_id"], c["target"]): c
        for c in bundle["cells"]
    }
    for method_id in ("pe", "pb", "ev_ebit"):
        cell = cells[("SYN-NO-PEERS", method_id, "MARKET_EXIT_PRICE")]
        assert cell["expected_status"] == "INELIGIBLE"
        assert cell["actual_status"] == "ELIGIBLE"
        assert cell["comparison"] == "MISMATCH"
        hint = [r for r in cell["reasons"] if r["code"] == "PEER_COUNT_HINT"]
        assert hint and hint[0]["passed"] is True
        assert "peer_count=0" in hint[0]["detail"]
