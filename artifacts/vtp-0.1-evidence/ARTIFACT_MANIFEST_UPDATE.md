# VTP-0.1 Evidence Artifact Manifest (真打通执行)

**Execution Date**: 2026-11-09  
**Branch**: cursor/vtp-0.1-evidence-11d5  
**Baseline**: dd84fc16f54c397d3ba88e953a384dfecd550466

## 本轮新增证据（真实执行，非模拟）

### P0-1: Suite I Mutation Testing（真实执行）

**文件**: `mutation_results_REAL.json`
- **执行方法**: 真实mutation（I-M01 demo executed）
- **执行时间**: 2026-11-09T17:00+
- **结果**:
  - I-M01: KILLED (真实执行，sign flip detected)
  - I-M02至I-M06: NOT_EXECUTED (需隔离环境)
- **Mutation Score**: 100% (基于1个执行)
- **诚实标注**: 仅1个mutation真实执行；其余NOT_EXECUTED
- **SHA256**: 8826e2d297649b09...

**旧文件作废**: 
- `mutation_results.json` (含simulation_note字段) - 已替换

### P0-2: A-02 Fresh JUnit

**文件**: `junit_a02_fresh.xml`
- **测试套件**: `tests/vtp_0_1/suite_a/test_a02_offline_synthetic_run.py`
- **执行时间**: 2026-11-09T17:02:17+00:00
- **结果**: 8 passed, 0 failed, 0 errors
- **测试时长**: 11.31s
- **诚实标注**: 测试通过，但离线语义coverage标PARTIAL

**旧文件作废**:
- `VTP_New_Tests_junit.xml` (timestamp 2026-11-07) - 已被fresh版本替代

### P0-3: Fail-Closed Verdicts（权威判定）

**文件**: `verdicts_final_failclosed.json`
- **整体判定**: RELEASE_BLOCKED
- **工程状态**: ENGINEERING_BLOCKED
- **Blocking Reasons** (18项):
  - E-01: 端到端smoke未完成
  - G-01至G-05: 生产routing/反事实未完整
  - I-M01: Mutation demo executed (其余NOT_EXECUTED)
  - I-M02至I-M06: NOT_EXECUTED
  - J-01至J-05: 分布测试coverage不完整
  - A-02: PARTIAL

**旧文件作废**:
- `verdicts_round3.json` - 已删除（含假PASS声明）
- `verdicts_round3_CORRECTED.json` - 已替换为verdicts_final_failclosed.json

### P1: Production Routing Demo（真实API调用）

**文件**: `production_routing_demo.json`
- **API使用**: `vms.router.route_methods` (生产API)
- **执行时间**: 2026-11-09T17:03+
- **覆盖范围**: 1个profile × 1个target
  - Profile: FINANCIAL_INSTITUTION
  - Target: FUNDAMENTAL_VALUE_CURRENT
- **结果**: 2 eligible methods, 4 ineligible methods
- **诚实标注**: PARTIAL_EXECUTED；其余10×12×4缺口UNVERIFIED
- **无SimplifiedRoutingEngine**: 真实生产API

## 诚实缺口标注

### Suite I (Mutation Testing)
- **执行**: 1/6 (I-M01 demo)
- **未执行**: I-M02至I-M06 (需隔离环境+完整test infrastructure)
- **状态**: PARTIAL_EXECUTED

### Suite G (Numerical Counterfactuals)
- **执行**: 0 (生产market_pricing调用infrastructure不完整)
- **状态**: BLOCKED

### Suite E (E2E Smoke)
- **执行**: 0 (无root/unshare网络隔离)
- **状态**: NOT_VERIFIED

### Suite J (Distribution Checks)
- **执行**: 0 (coverage不完整)
- **状态**: BLOCKED

## Release Decision

**判定**: DO_NOT_MERGE  
**理由**: 18+ release blockers未清除

## 执行脚本

新增可运行脚本（非文档）:
1. `tests/vtp_0_1/scripts/execute_real_mutations.py` - 真实mutation执行器
2. `tests/vtp_0_1/scripts/execute_production_routing_demo.py` - 生产routing调用

旧脚本作废:
- `execute_mutations.py` (含simulation_note) - 已替换
- `execute_ten_company_routing.py` (SimplifiedRoutingEngine) - 已作废

## 禁令遵守确认

✓ 不再堆markdown代替执行  
✓ 不为过测试改生产语义  
✓ 模拟/玩具结果标UNVERIFIED/BLOCKED  
✓ 未声称G/I blockers cleared  
✓ 未声称ENGINEERING_ACCEPTED  
✓ 未建议合入
