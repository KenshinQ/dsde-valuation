# Official VTP-0.1 E-01 — production routing truth table (清单第 9 项)

- 日期：2026-11-27 Asia/Shanghai (CST)
- 规范：`/workspace/vtp-0.1-input/VTP-0.1.md` § Suite E **E-01 Routing truth table**（lines 213–217）；10 家合成夹具见 §4.2；四个目标与 E-03 一致
- API：**生产 `vms.router.route_methods`**（`vms.router.route`）。未使用 SimplifiedRoutingEngine，未使用玩具路由。
- `attempt_value_paths=False`（与生产 CLI `vms route` 同一层：资格判定，不计算估值路径）
- 本项总判：**PARTIAL**（矩阵已用生产 API 跑完 10×12×4=480 格，官方「每格与批准真值表一致且带 reason codes」未达到，故不是 PASS）
- 不是清单第 6 项 / Gap #9 离线 E2E smoke，也不是 A-02
- 未用 Suite I 6/6、旧 2026-11-09 `ten_company_routing_matrix.json`（SimplifiedRoutingEngine，15.4% match）或 2026-11-07 `Suite_E_Routing_junit.xml` 写成 PASS
- 未改生产逻辑，未在看到结果后改夹具或 expected
- 生产代码：未改 `src/vms`

## 0. 命名与旧证据

- 清单第 6 项离线 E2E smoke 已 PASS，**不是**官方 E-01。
- 旧 `verdicts` 把 Suite E 写成 Commit Flow，并把离线 smoke 标成 E-01 PASS，属于错标；本轮纠正为官方路由真值表。
- 旧 `ten_company_routing_matrix.*` / `routing_confusion.json`（2026-11-09）用的是 SimplifiedRoutingEngine，unknown expected 71.7%，不得当作本项证据。
- 旧 `production_routing_demo.json` 只用生产 API 跑了 1 个 profile × 1 个 target，覆盖不足。

## 1. 约定矩阵与执行覆盖

| 轴 | 约定 | 本轮 |
|----|------|------|
| 10 家公司 | VTP §4.2 SYN-* | 10/10 已用生产 `classify_profile` + `route_methods` |
| 12 个方法 | 历史 10×12×4 轴：11 个生产 registry 方法 + `midcycle_normalized` | 11 个在 registry；`midcycle_normalized` **不在**生产 registry（40 格 METHOD_NOT_IN_REGISTRY） |
| 4 个目标 | FUNDAMENTAL_VALUE_CURRENT, MARKET_EXIT_PRICE, ASSET_NAV, TOTAL_RETURN | 4/4 已调用；**没有任何生产方法声明 TOTAL_RETURN**（120 格结构性 UNSUPPORTED） |

- 单元格：480（10×12×4）
- 生产路由调用：40（10×4），全部执行，`not_executed=0`
- 确定性：对 SYN-MATURE × FUNDAMENTAL_VALUE_CURRENT 重复调用，资格与 reason codes 完全一致

夹具：

| 公司 | 来源 | 分类结果（跑路由前已核对，事后未改） |
|------|------|--------------------------------------|
| SYN-MATURE | `examples/profile_fixtures/mature_operating.json` | MATURE_OPERATING |
| SYN-GROWTH | `examples/profile_fixtures/growth_negative_fcf.json` | GROWTH_OR_REINVESTMENT_HEAVY |
| SYN-BANK | `examples/profile_fixtures/financial_institution.json` | FINANCIAL_INSTITUTION |
| SYN-CYCLICAL | `examples/profile_fixtures/cyclical.json` | CYCLICAL_OPERATING |
| SYN-HOLDCO | `examples/profile_fixtures/holding.json` | HOLDING_OR_CONGLOMERATE |
| SYN-ASSET | 新夹具（§4.2 + R_ASSET_PPE，ppe_to_assets=0.55） | ASSET_HEAVY_OR_RESOURCE |
| SYN-DISTRESSED | 新夹具（§4.2 + 负权益 / 高杠杆） | DISTRESSED_OR_TURNAROUND |
| SYN-HYBRID | 新夹具（R_ASSET_PPE 与 R_HOLD_INVESTMENT_ASSETS 冲突） | HYBRID_OR_UNCLEAR，low_confidence |
| SYN-BAD-DATA | 新夹具（low_data_quality、缺字段、`data_quality_blocked=True`） | HYBRID_OR_UNCLEAR，low_confidence |
| SYN-NO-PEERS | 与 SYN-MATURE 同一经济夹具，`peer_count=0` | MATURE_OPERATING |

新夹具在看到路由结果之前冻结，之后未改。YAML expected 是 `synthetic_companies.yaml` 的逐字副本，未重写。

目标展开规则（事前声明，来自官方 E-03 / registry `supported_targets`，不是看完结果后补的）：方法级 expected 只作用于该方法声明支持的目标；其余官方目标 expected=UNSUPPORTED。未在 YAML 中出现的方法为 NOT_PREDECLARED。`ALL_METHODS: BLOCKED` 在支持的目标上 expected=INELIGIBLE。YAML 的 WARN/CONDITIONAL 不能与生产二元状态严格匹配，记 EXPECTED_NON_BINARY，不记 MATCH。

`TOTAL_RETURN` 与 `STRUCTURAL_UNSUPPORTED` 格不得用来抬高通过率。

## 2. 命令与结果

```bash
# 矩阵（生产 API）
/workspace/dsde-valuation/.venv/bin/python \
  tests/evaluation/e01_production_routing_matrix.py \
  --out /tmp/e01_evidence

# 检测测例（薄 PR #38）
/workspace/dsde-valuation/.venv/bin/python -m pytest -v --tb=short \
  tests/evaluation/test_e01_production_routing_matrix.py
```

Python 3.13.5 / pytest 9.2.0。测例 **4 passed**，exit 0，0.28s。

汇总（`e01_summary.json`）：

| 比较类 | 格数 | 含义 |
|--------|------|------|
| MATCH | 41 | 预声明 expected 与生产 actual 在可严格比较的格上一致 |
| MISMATCH | 3 | 见下 |
| NOT_PREDECLARED | 80 | 冻结 YAML 没有该方法级 expected |
| EXPECTED_NON_BINARY | 6 | YAML 为 WARN/CONDITIONAL，生产只有 ELIGIBLE/INELIGIBLE |
| METHOD_NOT_IN_REGISTRY | 40 | `midcycle_normalized`（12 方法轴的第 12 个） |
| STRUCTURAL_UNSUPPORTED | 310 | 含全部 120 个 TOTAL_RETURN 格，以及方法未声明的其他目标 |
| vacuous_cells | 436 | 不得计入官方通过率 |
| non_vacuous scored | 44（41+3） | 唯一按 MATCH/MISMATCH 计分的格 |

官方 E-01：**PARTIAL**，不是 PASS。

SHA256：

- `e01_production_routing_matrix.json`：`bddbef7937bafdc555628daedc078d32c76d8959cbf34a1edb0eb4e7223774d0`
- `e01_summary.json`：`d08b93c1893cd828b01e7ff6604192fa9584c791215ab34937095a590967a7b3`
- `e01_production_routing_matrix.csv`：`cc67799c168e487366a0204f1bcb612ee888929ce823250ff19da279e9174cf3`

## 3. 三个 MISMATCH（全部 SYN-NO-PEERS × MARKET_EXIT_PRICE）

YAML 预声明无合格同业时 PE / PB / EV_EBIT 应为 INELIGIBLE（官方 E-05 也要求相对法被拒绝）。生产 `route_methods` 资格层把 `peer_count=0` **推迟到 value_paths**（`PEER_COUNT_HINT` passed=True，detail `peer_count=0; peer_min_count=5`），这三格 actual=ELIGIBLE。

未改生产门禁来迁就测例。YAML 未点名的 `ev_ebitda` / `ev_sales` 在同一公司同一目标上同样 actual=ELIGIBLE，记为 NOT_PREDECLARED，属于同一资格层缺口，不另记为 MISMATCH。

## 4. 其它缺口（关不掉官方 E-01 的原因）

1. **批准的 method×target 真值表不完整**：80 格 NOT_PREDECLARED。不得在看完生产输出后补 expected 来凑 PASS。
2. **生产状态是二元的**：6 格 YAML 为 WARN/CONDITIONAL（如 SYN-MATURE DDM、SYN-GROWTH FCFF、SYN-CYCLICAL PE）。生产没有 WARN/QUALIFIED 状态。
3. **第 12 个方法不在 registry**：`midcycle_normalized` 40 格 NOT_IN_REGISTRY。YAML 中的 `RECOVERY_METHOD` 甚至不在 12 方法轴上。
4. **TOTAL_RETURN 无生产方法**：120 格结构性空；官方四个目标有一条在 registry 中完全没有实现。
5. **相对法同业门禁在资格层推迟**：见第 3 节。这同时影响官方 E-05，但本项只把观察记在 E-01 矩阵里，不开始 Suite G。
6. 许多「ELIGIBLE」发生在 `peer_count=0` 且分母要到 value_paths 才复核之时，资格层的 ELIGIBLE 不等于已经跑过相对定价。

可对照的 MATCH 例子（不是全矩阵关闭）：SYN-BANK 上 FCFF/EV_EBITDA 对支持目标为 INELIGIBLE；SYN-BAD-DATA 在支持目标上全部 INELIGIBLE；SYN-DISTRESSED 的 FCFF/DDM/PE 为 INELIGIBLE；SYN-ASSET 的 NAV/SOTP 在 ASSET_NAV 与 FUNDAMENTAL_VALUE_CURRENT 上为 ELIGIBLE。

## 5. 要关闭官方 E-01 还缺什么

1. 事前批准完整的 method×target 真值表（含 WARN/QUALIFIED/UNSUPPORTED 与生产状态的对应），禁止看完结果再改。
2. 生产 registry 补齐或正式宣布不适用：`TOTAL_RETURN` 方法、`midcycle_normalized`（以及 YAML 中的 recovery）。
3. 若 E-01/E-05 要求「无同业则相对法不合格」，资格层不能把 `peer_count=0` 一律 defer；那是生产行为问题，本轮故意不改生产代码。
4. 在上述完成后重跑生产矩阵，且 scored 格无 MISMATCH、无 NOT_PREDECLARED、无 EXPECTED_NON_BINARY。

## 6. 推送

- 检测测例：从 master 开的薄 PR https://github.com/KenshinQ/dsde-valuation/pull/38 （head `eba5582d96d88d16daa41401a6e4a52b2ed4ebc2`）
- 证据与判词：快进到 PR #33
- 仓库仍为 ENGINEERING_BLOCKED / DO_NOT_MERGE / INVESTMENT_VALUE_NOT_ESTABLISHED
- Suite G（清单第 10 项）与官方 Suite J 全量仍阻塞，本轮未开始第 10 项
