# VTP-0.1 诚实缺口状态（最终诚实版）

**生成时间**: 2026-11-09 16:53 UTC  
**审计抽查**: 独立第三轮审计否决#3/#5/#6假关闭  
**硬约束遵守**: 生产API需完整环境；做不到则标BLOCKED/UNVERIFIED

---

## 硬约束执行结果

### #6 Mutation Testing

**硬约束**：必须对真实源码打patch，跑会失败的property/unit suite，再还原。

**实际情况**：
- 第三轮交付：模拟执行（`simulation_note: real patch not applied`）
- 硬编码所有mutation为KILLED
- 未修改任何源文件
- 未运行detector tests

**生产要求**：
```python
# 需要：
1. 临时修改src/vms/projection.py等源文件
2. 清除Python import缓存
3. 运行detector tests (pytest)
4. 记录exit code
5. 恢复源文件
6. 重复6次（6个mutation）
```

**技术阻塞**：
- 需要隔离test runner以避免import缓存污染
- 需要处理并发pytest session
- 需要1-2小时实现+验证

**诚实状态**：**NOT_EXECUTED / BLOCKED**

**I-M01至I-M06状态**：**NOT_EXECUTED**（非PASS）

**Mutation score**：**N/A**（未真实执行，100%作废）

---

### #3 Ten-Company Routing

**硬约束**：调用生产路由/方法选择API（vms 现有 Adaptive Multi-Method / phase routing），禁止SimplifiedRoutingEngine。

**实际情况**：
- 第三轮交付：`SimplifiedRoutingEngine`自实现
- 脚本注释：「不调用完整VMS pipeline；不是production-grade」
- Confusion：74 matches, **62 mismatches**, **344 unknown**
- 仅15.4% match rate

**生产要求**：
```python
from vms.router.route import route_methods
from vms.methods.registry import MethodRegistry

# 需要：
1. 完整PITSnapshot（数据库）
2. LoadedConfig（配置文件）
3. ValuationContext（wacc/tv假设）
4. ProfileReport（分类结果）
5. 调用registry.evaluate_all(context)
6. route_methods()返回RouteReport
```

**技术阻塞**：
- 生产routing需要完整数据库setup
- 需要真实equity snapshot数据
- 需要完整配置加载
- synthetic_companies.yaml不提供所需数据结构

**诚实状态**：**BLOCKED / UNVERIFIED**

**E-01状态**：**FAIL**（有矩阵但quality不足）

---

### #5 Suite G Counterfactuals

**硬约束**：必须调用生产 exit_price / intrinsic / fundamental-vs-market 分离 API，禁止SimpleValuationModel / Gordon玩具DCF。

**实际情况**：
- 第三轮交付：`SimpleValuationModel` Gordon Growth + rng.uniform multiple
- 无import `vms.market_pricing.exit_prices`
- 无import `vms.methods`任何valuation plugin
- 年化return≈489.7%（荒谬）

**生产要求**：
```python
from vms.market_pricing.exit_prices import estimate_exit_prices
from vms.market_pricing.convergence import ConvergenceScenario
from vms.methods.cash_flow.fcff_plugin import FcffDcfMethod

# 需要：
1. 完整ProjectionResult（phase 4 output）
2. MarketPricingConfig
3. ConvergenceScenario参数
4. 运行estimate_exit_prices()
5. 分离intrinsic vs terminal regime
```

**技术阻塞**：
- 生产exit pricing需要projection bundle
- 需要market_pricing.config配置
- 需要regimes/transitions参数
- 简化场景无法调用production pipeline

**诚实状态**：**BLOCKED / UNVERIFIED**

**G-01至G-05状态**：**UNVERIFIED**（有数值但非生产API）

---

### #9 Offline E2E + Replay

**硬约束**：真隔离（network namespace / 断网自检可证明），干净checkout生成或重放生产VMS pipeline bundle。

**实际情况**：
- 第三轮交付：手写bundle JSON，自重放常数
- intrinsic_value=14500硬编码在generate和replay
- proxy设置（非真断网）
- 无network namespace / unshare

**生产要求**：
```bash
# 真隔离：
unshare -n python3 -m pytest tests/offline_e2e.py

# 或
iptables -A OUTPUT -j REJECT
python3 -m pytest tests/offline_e2e.py
iptables -D OUTPUT -j REJECT

# 生产bundle：
vms-cli phase12 --input snapshot.json --output bundle.json
vms-cli replay bundle.json --verify
```

**技术阻塞**：
- 需要root权限（unshare -n / iptables）
- 需要VMS CLI完整setup
- 需要真实snapshot数据
- 云环境无root

**诚实状态**：**BLOCKED**（bundle自洽演示≠真E2E）

**K-02状态**：**UNVERIFIED**

---

### #2 A-02 Offline Synthetic Run

**硬约束**：重新跑测试，提交新鲜junit；离线语义不够则标PARTIAL/BLOCKED。

**实际情况**：
- 源码已修改：`synthetic.generate()`正确导入
- Committed junit：2026-11-07（过期）
- 当前测试状态：未运行（pytest未安装）
- proxy设置≠真断网

**诚实状态**：**PARTIAL**（源码修复✓，证据过期✗，离线不足✗）

**A-02状态**：**FAIL / PARTIAL**

---

## 真关闭缺口（仅2个）

| 缺口 | 状态 | 证据 |
|------|------|------|
| #1 venv污染清理 | **TRUE_CLOSE** | 6454文件移除，树内无venv |
| #7 Suite J诚实标注 | **TRUE_CLOSE** | J-01至J-05明确BLOCKED，19绿≠历史 |

---

## 假关闭缺口（4个）

| 缺口 | 第三轮声称 | 审计纠正 | 诚实状态 |
|------|-----------|---------|---------|
| #3 Routing | PASS | FALSE_CLOSE | **BLOCKED** (需生产API+完整环境) |
| #5 Suite G | PASS | FALSE_CLOSE | **UNVERIFIED** (需生产API+完整环境) |
| #6 Mutation | PASS (100%) | FALSE_CLOSE | **NOT_EXECUTED** (需真实patch) |
| #9 E2E Replay | PARTIAL | FALSE_CLOSE | **BLOCKED** (需真隔离+生产bundle) |

---

## 部分完成缺口（3个）

| 缺口 | 状态 | 说明 |
|------|------|------|
| #2 A-02 | **PARTIAL** | 源码修复✓，证据过期✗，离线不足✗ |
| #8 100项映射 | **PARTIAL** | 映射加载✓，执行回填✗ |
| #10 判定引擎 | **PARTIAL** | 引擎存在✓，错误清除fake blocker✗ |

---

## Release Blockers 状态（诚实版）

**仍阻塞（18个）**：

| Blocker | 状态 | 理由 |
|---------|------|------|
| A-02 | FAIL/PARTIAL | 证据过期，离线不足 |
| E-01(#3) | BLOCKED | 需生产routing API |
| G-01 | UNVERIFIED | 需生产API |
| G-02 | UNVERIFIED | 需生产API |
| G-03 | UNVERIFIED | 需生产API |
| G-04 | UNVERIFIED | 需生产API |
| G-05 | UNVERIFIED | 需生产API |
| I-M01 | NOT_EXECUTED | 未真实patch |
| I-M02 | NOT_EXECUTED | 未真实patch |
| I-M03 | NOT_EXECUTED | 未真实patch |
| I-M04 | NOT_EXECUTED | 未真实patch |
| I-M05 | NOT_EXECUTED | 未真实patch |
| I-M06 | NOT_EXECUTED | 未真实patch |
| J-01 | BLOCKED | 无真实历史数据 |
| J-02 | BLOCKED | 无真实历史数据 |
| J-03 | BLOCKED | 无真实历史数据 |
| J-04 | BLOCKED | 无真实历史数据 |
| J-05 | BLOCKED | 无真实历史数据 |

**清除的blocker（0个）**：无

---

## 判定（诚实版）

**工程**：**ENGINEERING_BLOCKED**

**阻塞原因**：
- G Suite: 5个UNVERIFIED（需生产API+完整环境）
- I Suite: 6个NOT_EXECUTED（需真实patch源码）
- J Suite: 5个BLOCKED（需真实历史数据）
- A-02: 1个FAIL/PARTIAL（证据过期+离线不足）
- E-01(#3): 1个BLOCKED（需生产routing API）

**数据质量**：**UNVERIFIED**（合成≠真实）

**历史验证**：**BLOCKED**（real_samples=0）

**校准**：**INSUFFICIENT**（保持保守，无OOS）

**投资价值**：**NOT_ESTABLISHED**（保持保守）

**发布**：**RELEASE_BLOCKED**

---

## 为何生产API做不到

### 技术依赖链

生产routing需要：
```
PITSnapshot → 需要数据库连接
LoadedConfig → 需要完整配置文件树
ValuationContext → 需要loaded WACC/TV假设
ProfileReport → 需要profile classification
MethodRegistry → 需要router.yaml配置
```

生产exit pricing需要：
```
ProjectionResult → 需要phase4 simulation bundle
MarketPricingConfig → 需要convergence/regime配置
ConvergenceScenario → 需要market参数
```

生产mutation需要：
```
临时修改源文件 → 需要git worktree或备份
清除import缓存 → 需要隔离test runner
运行detector tests → 需要完整test环境
```

### 在测试/CI环境的阻塞

- **无数据库**：synthetic fixture不提供PITSnapshot格式
- **无配置树**：缺router.yaml、market_pricing.config等
- **无权限**：unshare需要root，云环境无root
- **时间成本**：真实mutation需要1-2小时实现+验证

### 选择：诚实 vs 造假

按硬约束：**做不到则标BLOCKED/UNVERIFIED，不造假证据**。

---

## 撤回第三轮声明

**作废**：
- ✗ 缺口#3 PASS / routing完整关闭
- ✗ 缺口#5 PASS / G blockers cleared
- ✗ 缺口#6 PASS / mutation score 100%
- ✗ 「G/I blockers全部cleared」
- ✗ 「9个完整关闭」

**保留**：
- ✓ 缺口#1 venv清理（真关闭）
- ✓ 缺口#7 J诚实标注（真关闭）
- ✓ routing框架演示（非validation）
- ✓ G框架演示（非production）
- ✓ mutation框架演示（非真实执行）

---

## 结论

**诚实fail-closed判定**：

- **完整关闭：2个**（#1, #7）
- **部分完成：3个**（#2, #8, #10）
- **BLOCKED/UNVERIFIED：5个**（#3, #5, #6, #9, 及多个子项）

**Release blockers：18个**（未清零）

**Overall：RELEASE_BLOCKED**

**不从框架演示、玩具模型、模拟执行推导PASS**。

**硬约束遵守：生产API需完整环境；做不到则诚实标BLOCKED/UNVERIFIED**。

---

**不建议合入PR #33。不建议再发「9缺口已关闭」类报告。**
