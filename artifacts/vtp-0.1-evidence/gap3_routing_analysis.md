# 缺口#3 Routing矩阵问题分析

## 审计抽查结果

Routing confusion统计（来自`routing_confusion.json`）：
- Total decisions: 480
- **Matches**: 74 (15.4%)
- **Mismatches**: 62 (12.9%)
- **Unknown expected**: 344 (71.7%)

## 问题诊断

### 问题1：Unknown Expected占比过高（71.7%）

**根因**：`synthetic_companies.yaml`中expected_routes仅记录method-level期望（如"FCFF_DCF: ELIGIBLE"），未展开到method×target组合。

**示例**：
- YAML声明：`FCFF_DCF: ELIGIBLE`
- 实际执行：`FCFF_DCF × FUNDAMENTAL_VALUE_CURRENT`, `FCFF_DCF × MARKET_EXIT_PRICE`等4个target
- 结果：仅第1个target匹配，其余3个无expected → 标为UNKNOWN

**影响**：344个决策无法判定正确性。

### 问题2：Mismatch 62项（12.9%）

**可能原因**：
1. **简化routing引擎**：当前使用`SimplifiedRoutingEngine`基于financial_data判定，不是完整VMS routing
2. **Expected定义粗糙**：YAML中expected未考虑target compatibility
3. **Method-target兼容性**：
   - DCF methods主要用于FUNDAMENTAL_VALUE_CURRENT
   - Multiple methods主要用于MARKET_EXIT_PRICE
   - Asset methods主要用于ASSET_NAV
   - 但YAML未区分这些

**示例mismatch场景**：
- Expected: `PE_MULTIPLE: ELIGIBLE`（method-level）
- Actual: `PE_MULTIPLE × ASSET_NAV: INELIGIBLE`（PE不适用于NAV target）
- 判定：MISMATCH（但可能是expected定义问题）

## 为何不应标PASS

1. **71.7% unknown**：大部分决策无法验证
2. **12.9% mismatch**：存在不一致需要分析
3. **仅15.4% match**：太低无法支撑"routing正确"声明

## 纠正动作

**缺口#3状态**：PASS → **FAIL**

**理由**：
- Routing矩阵已生成（432行） ✓
- 但confusion统计显示质量不足 ✗
- Unknown/mismatch过多，无法支撑验收

## 补齐路径（未执行）

### 选项A：修正expected（推荐）
1. 扩展`synthetic_companies.yaml`：为每个method×target组合定义expected
2. 区分target compatibility规则
3. 重新运行routing并验证

### 选项B：接受当前状态并说明
1. 文档化SimplifiedRoutingEngine局限性
2. 说明这是routing框架演示，不是完整验证
3. 标记为PARTIAL而非PASS

### 选项C：完整VMS routing
1. 集成真实VMS routing引擎
2. 加载完整peer set和数据质量检查
3. 生成production-grade routing矩阵

**当前选择**：选项B（诚实标注局限性）

## 结论

缺口#3状态：**FAIL**（矩阵已生成，但质量不足以支撑PASS）

需要：
1. 修正expected定义，或
2. 说明当前是routing框架演示（PARTIAL），或
3. 集成完整VMS routing（完整解决方案）

**不得用15.4% match率声称routing验证通过。**
