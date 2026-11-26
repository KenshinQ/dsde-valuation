# Suite J — official historical walk-forward (清单第 8 项)

- 日期：2026-11-27 Asia/Shanghai (CST)
- 规范：`/workspace/vtp-0.1-input/VTP-0.1.md` § Suite J (lines 341–385)
- 运行时所在分支：PR #33 `dea7173e338620c0c07925b43a198b7e005bc264`（证据提交会再前移）
- master 基准：`dd84fc16f54c397d3ba88e953a384dfecd550466`
- Python 3.13.5 / pytest 9.2.0
- 生产代码：未改 `src/vms`
- 未使用 6/6 mutation 顶替 Suite J
- 未把 2026-11-07 旧 `Suite_J_Historical_junit.xml`（19 passed）写成 PASS
- 未削弱测例或生产逻辑

## 0. 准则对照（先读官方，再对照 backlog / verdicts）

官方 VTP-0.1 Suite J 是 **Historical walk-forward evaluation**：

| ID | 官方准则 |
|----|----------|
| J-01 | Frozen protocol：跑窗口前事先冻结 universe / PIT 成员规则、decision timestamps、horizons、coverage、train/cal/test、方法与 baseline、指标与切片、缺失政策、最小样本、校准阈值 |
| J-02 | No random row split：时间顺序 walk-forward；变换与校准器只在允许的过去数据上拟合 |
| J-03 | Separate forecast targets：收入/EBIT/ROE/FCF、peer multiples、未来市场价格、总回报与事件概率、ensemble 对其声明目标的校准，分别评分 |
| J-04 | Baselines：历史 driver 均值/中位数、合格画像的确定性中枢 DCF、简单倍数、no-regime、退出价的 current-multiple persistence、画像适配基准 |
| J-05 | Proper scoring and calibration：连续预测用 MAE/RMSE（或 scaled error），分位数用 pinball/区间覆盖，正确实现时用 CRPS/log，事件概率用 Brier/reliability；并按 profile / sector / fundamental state / market-pricing state 报告不确定性与子群 |
| J-06 | Claim discipline：ENGINEERING / DATA_QUALITY / CALIBRATION / ENSEMBLE / 投资价值分列；样本或 PIT 不足则 `CALIBRATION_INSUFFICIENT`，不得从合成或 in-sample 声称 alpha |

清单第 8 项与 `verdicts_final_failclosed.json` 此前把 Suite J 写成「Distribution Checks」，阻塞文案是「真实分布 / sanity / edge / intrinsic / 联合分布」。那是对官方准则的**错标**。分布单元测试属于 VTP 执行序列 L3/L4，不能用来关闭 Suite J。本轮按官方历史前向准则清点与取证；错标已在判词中纠正。

已有 `tests/unit/test_distributions.py`（mixture 分位数、regime 条件、边界单调、pinball 等）仍是工程回归，**不是** J-01..J-05 的关闭证据。

## 1. 本轮新跑证据（不是旧 junit）

| 批次 | 命令见 `commands.txt` | 结果 | 路径 |
|------|------------------------|------|------|
| 合成 evaluation 代码回归 + 旧 j00 声明 + live smoke | 24 passed，exit 0，14.99s | `junit_synth_eval_and_j00.xml`，`synth_eval_and_j00_stdout.txt` |
| R7 真实 OOS 测例 + CLI smoke（过去因缺 DuckDB 被 skip） | 14 passed，exit 0，47.35s | `junit_r7_real_oos.xml`，`r7_real_oos_stdout.txt` |
| 耐久 CLI：`vms calibrate-rim` 预声明 R7 窗口 | exit 0，REST=0 | `r7_calibrate_rim_out/`，`r7_calibrate_rim_stdout.txt` |
| R4/R5 本地 panel（过去 skip） | 25 passed，exit 0，43.41s | `junit_r4_r5_local.xml`，`r4_r5_stdout.txt` |
| 官方关闭准则新测例（薄 PR #37） | 11 passed，exit 0，0.17s | PR #37；测例在 master 分支上 |

本地数据（本机已有，不是本轮新造的历史库）：

- `/workspace/data/hithink_fundamentals.duckdb`（约 195MB）
- `/workspace/data/market.duckdb`（约 555MB，mtime 2026-11-26 16:57 CST）

CLI 为 `--prefer_local` 默认路径，`fi_real_rest_calls=0`，未 `--refresh`。DuckDB 可能在只读打开时更新 fundamentals 文件 mtime（本轮跑完后 fundamentals 文件 mtime 为 2026-11-27 02:09 CST）；未改生产代码，未做增量同步。

旧声明 `real_historical_samples=0` /「VM 无本地历史数据」已被本机数据与 R7 执行推翻。`tests/vtp_0_1/suite_j/test_j00_historical_validation_status.py` 仍硬编码 `real_historical_samples == 0`（只存在于 PR #33 证据分支，不在 master）。本轮不把该过时声明测例堆进 #33 当作新检测；替换口径在 PR #37。

## 2. 预声明 R7 切片（不是本轮看完结果后补协议）

已在仓库中的协议（先于本轮执行）：

- Assumption：`EVAL-RIM-FI-DEPOSIT-REAL-OOS-v1`
- Universe：`config/universe.fi_deposit_lean_real.yaml`（`fi_deposit_lean_r7_v1`，3 家存款类银行，`split_mode=chronological`，`forbid_random_splits=true`，horizon=1y，`min_history_years=3`，as_of `2025-06-30T15:00:00+08:00`）
- 窗口：`--start 2016-01-01 --end 2022-12-31 --seed 42`
- 文档：`docs/calibration_protocol.md`
- 冻结权重：`frozen_weights.json`（`frozen_before_test=true`，`test_window_start=2016-01-01`，`min_oos_for_calibration=5`，`min_hist_pb_points=12`，`brier_pass_max=0.35`）

这是存款类银行 RIM 精简切片，不是官方 Suite J 要求的全方法 / 全目标 / 全基线 / 全画像历史评价。

## 3. 耐久 CLI 结果要点

出处：`r7_calibrate_rim_out/calibrate_rim_summary.json` 与 `rim_calibration_report.json`。

| 项 | 值 |
|----|----|
| universe / data_label | `fi_deposit_lean_r7_v1` / `HITHINK_EM_LEAN_FI`（不含 SYNTHETIC） |
| split_mode | chronological |
| n_origins_attempted / n_forecasts_persisted / n_scored | 15 / 15 / 15 |
| n_pit_assumed | 15（全部 `pit_complete=false`，`pit_policy=PIT_ASSUMED`） |
| n_unbiased_pit_complete | **0** |
| n_pending_outcomes | 0 |
| Track B | 0 eligible / 15 skipped（`INSUFFICIENT_OWN_PB_HISTORY`，hist_n 约 1–6，下限 12 未下调） |
| REST | 0 |
| 声明目标 | `driver_roe`, `intrinsic_value`, `market_price` |
| 出现的 baseline | `central_rim`, `fi_note`, `historical_roe_median` |
| calibration_claim | `CALIBRATION_INSUFFICIENT` |
| ensemble | `ENSEMBLE_UNCALIBRATED` |
| investment_value | `INVESTMENT_VALUE_NOT_ESTABLISHED` |
| pass_claim | `authorized=false`，`reason=NO_ARTIFACT`，`run_n_unbiased=0` |
| 预测先于结果 | `persisted_before_outcomes=true`（账本与单份 forecast JSON） |

评分（研究口径，**不是** PIT-complete unbiased 样本）：

- `driver_roe`：MAE 0.013621，RMSE 0.015695，n=14
- 与 `historical_roe_median` 的 baseline 误差**数值相同**（不能声称打败基准；至少部分 origin 的 historical median 样本很薄，例如 2018-03-15 的 `n_years=1`）
- `intrinsic_value` 只报 later-origin 稳定性及「与市价的 association」；`price_mae_as_iv_truth_forbidden=true`
- `market_price`：MAE 4.3427，RMSE 7.0745，n=15
- 无 pinball / CRPS / log score / Brier / reliability
- subgroup：仅 `FINANCIAL_INSTITUTION` 与 `fundamental_regime=UNKNOWN`；`tsr_point_errors.n=0`

运行级标签里的 `ENGINEERING_PASS` / `DATA_QUALITY_PASS` **不是**仓库 `ENGINEERING_ACCEPTED`。

关键 SHA256：

- `calibrate_rim_summary.json`：`8c1fdf6458aef7509d56efd166849aeab9143d9a279969eac81d923e76658d40`
- `rim_calibration_report.json`：`0a091ab1f4a54a0cb986bdadf42feaf41ac13c544749a43bb99614373830eb61`
- `frozen_weights.json`：`0f9b20f866e69ce3a36aeed27b276459a2d90ad8f3e6f209c228789eda19f50f`
- `origin_records.json`：`ce81d35de0d6de6a4484e30f698b1d1c55172413dfc72c476bea5c9f2a96b43d`
- `fi_real_materialize.json`：`1e1cbf61788d26432557a882e020ab8aef7114ad58371c78c4a30f624bca42df`
- `pass_claim_decision.json`：`f84b82966fdcb7de0549ff6cef0c224c513aaea5dee9ce303e26ebe7c94178a3`

完整文件清单哈希见 `r7_calibrate_rim_sha256.txt`。

## 4. 官方 J-01 至 J-05 逐项判定

**总判：Suite J 仍为 BLOCKED。** 本轮把「无真实数据 / 未执行」推进到「预声明 R7 切片已在真实本地 PIT 面板上跑通，但官方全量准则未关闭」。单项如下。

### J-01 Frozen protocol — PARTIAL

已有并已按该协议执行：R7 universe、窗口、horizon、min history、RIM 方法、部分 baseline、最小样本、冻结权重/阈值、缺失政策（`PIT_ASSUMED` / `LATEST_ONLY`）。协议写在仓库里，不是看完本次数字后补的。

仍缺，故不能 PASS：

- 官方建议的 `tests/evaluation/walk_forward_config.yaml` / `baseline_definitions.yaml` 全量协议文件不存在
- universe 是 3 只股票的精简名单，不是一般 PIT 成员规则
- train / calibration / test 没有事先分开的三段窗口（只有 2016–2022 walk-forward + evaluation_as_of 2025-06-30）
- 未覆盖官方要求的全部方法、目标、baseline 与子群切片
- 未为最终 holdout 预注册可关闭校准的表现阈值（保持保守是对的，但不能据此宣布 J-01 全关闭）

### J-02 No random row split — PARTIAL

引擎拒绝随机切分（新鲜 19 项合成回归仍绿）。本轮 R7 运行为 `split_mode=chronological`，预测先于结果，REST=0，权重在窗口前冻结。

不能 PASS 的原因：全部 15 个 origin 都是 `PIT_ASSUMED` / `pit_complete=false`（vendor `LATEST_ONLY`）。官方第二句「变换与校准器只在允许的过去数据上拟合」在完整 PIT 意义上未被证明。政策已事先声明，没有隐瞒，但不足以把 J-02 写成 PASS。

### J-03 Separate forecast targets — PARTIAL

已分离评分：`driver_roe`、`intrinsic_value`（稳定性，不以未来市价为内在真值）、`market_price`。

仍缺官方清单：收入/EBIT/FCF（只有 ROE）、peer multiple behavior、总回报与事件概率（账本有 TSR 字段但 `tsr_point_errors.n=0`）、ensemble 声明目标的校准（本路径明确 `ENSEMBLE_UNCALIBRATED`）。

### J-04 Baselines — PARTIAL

已出现：`historical_roe_median`、`central_rim`、`fi_note`（工业 FCFF/DCF 对存款类 FI 标明不可用，不是偷偷缺失）。

仍缺：simple multiple、no-regime、current-multiple persistence（Track B 15/15 SKIP，没有退出持久化基线）。driver ROE 预测误差与历史中位数基准相同，不声称超额。

### J-05 Proper scoring and calibration — BLOCKED

- `n_unbiased_pit_complete=0`，不能把 `PIT_ASSUMED` 研究分写成无偏 OOS 校准 PASS
- 本 run 只有 MAE/RMSE；无 pinball、区间覆盖、CRPS/log、Brier、reliability
- subgroup 近乎空：单一 profile、regime=UNKNOWN、TSR n=0，没有 sector / market-pricing state 切片
- 报告自身为 `CALIBRATION_INSUFFICIENT`；`MIN_UNBIASED_FOR_PASS=5` 未满足
- 不把 vacuous / assumed-only 结果写成 PASS

### J-06 Claim discipline — 保持诚实（ACKNOWLEDGED / 本轮未改口）

标签仍为 `CALIBRATION_INSUFFICIENT`、`ENSEMBLE_UNCALIBRATED`、`INVESTMENT_VALUE_NOT_ESTABLISHED`。pass-claim 无 artifact，未授权。官方 J-06 不是清单第 8 项的关闭对象，但纪律仍然成立。这不能把 J-01..J-05 抬成 PASS。

## 5. 要关闭官方 Suite J 还缺什么

1. 针对官方全量目标/基线/切片事先冻结协议（或明确记录为何某条不适用），而不是只有 R7 银行 RIM 切片。
2. 完整 PIT（`pit_complete=true`）或达到预声明最小样本的无偏样本：`n_unbiased_pit_complete >= min_oos`，而不是 15 条全是 `PIT_ASSUMED`。
3. 分别评分官方 J-03 其余目标（经营预测全套、peer multiples、TSR 与事件概率、ensemble 校准目标）。
4. 补齐并记录 J-04 其余 baseline；Track B 在 `hist_n>=12` 时才能评退出持久化，禁止为凑数下调下限。
5. J-05：在无偏样本上给出适当的 pinball/CRPS/Brier 与非空子群，并保持 fail-closed 的校准声明。
6. 不得用合成 19 绿、分布单元测试、或 Suite I 6/6 KILLED 顶替上述任何一项。

## 6. 推送

- 证据与判词：快进到 PR #33（不 force-push）。
- 新检测测例：从 master 开薄 PR https://github.com/KenshinQ/dsde-valuation/pull/37 （head `bd6e9c876eb70efa4ca4b1ddef1f10247ad77f03`）。
- 仓库仍为 ENGINEERING_BLOCKED / DO_NOT_MERGE / INVESTMENT_VALUE_NOT_ESTABLISHED。Suite G 与生产路由 10×12×4 未开始。
