# E-01 离线端到端 smoke（清单第 6 项 / Gap #9）

- 日期：2026-11-27 Asia/Shanghai（CST, UTC+8）
- 仓库：KenshinQ/dsde-valuation
- 本文件只服务清单第 6 项。不开始第 7 项及以后。
- **禁止把 A-02 PASS 改口成本项关闭。**
- 权威 fail-closed 判定仍是 `verdicts_final_failclosed.json`。仓库继续 `ENGINEERING_BLOCKED` / `DO_NOT_MERGE` / `INVESTMENT_VALUE_NOT_ESTABLISHED`。本项 PASS 不解除 I-M04 / Suite G / Suite J 等阻塞。

## 1. 名称碰撞：三个容易混在一起的「E-01」

必须分开写，不能互相顶替。

| 名称 | 出处 | 真实验收标准 | 与本项关系 |
|------|------|----------------|------------|
| **VTP 准则 E-01 Routing truth table** | `vtp_criteria_mapping.json` / original_spec.md:215；`tests/vtp_0_1/suite_e/test_e01_ten_company_routing.py` | 用事先批准的期望路由矩阵跑全部合成 fixture。Pass：每个 method 决策符合 ELIGIBLE / INELIGIBLE / WARN/QUALIFIED / UNSUPPORTED，并带 reason codes。 | **不是本项。** 对应清单第 9 项（生产 10×12×4）。测例仍是框架，本轮未做，保持未关闭。 |
| **A-02 Offline synthetic run** | 同一 mapping；PR #35 | 网络不可用下跑**最小完整**合成公司工作流，产出版本化 bundle：profile、routing、methods、exit-price、returns、diagnostics、provenance。已用 `phase12 --pattern mature_operating` + `unshare -r --net` 于 2026-11-27 有依据地标 PASS。 | **前置/相邻，但更窄。** 一次 phase12 编排 ≠ 官方多步生产路径，也没有「从已保存 request/data/config 重放」。 |
| **清单第 6 项 / verdicts Suite E「E-01」/ gap_items.9** | backlog 2026-11-27；HONEST_GAP「#9 Offline E2E + Replay」；审计 P1-E7 | 在可复现的**真隔离**下，跑通**真实生产路径** smoke，保存产物；并从已保存输入 replay（K-02）。不是手写 JSON，不是代理。 | **本项。** |

历史伪关闭：`tests/vtp_0_1/scripts/offline_e2e_replay.py` 手写 bundle、把 `intrinsic_value=14500` 写死在 generate 与 replay 里、只用 proxy 当离线。审计结论是 **BLOCKED（bundle 自洽演示 ≠ 真 E2E）**。本轮不使用该脚本。

HONEST_GAP 曾写「需要 root（unshare -n / iptables）」——本机已证实 **`unshare -r --net` 无需 root**（A-02 已用）。环境不再构成阻塞；本项按原标准执行，不降级。

## 2. 本项相对 A-02 多出来的要求

A-02 已证明：在 user+net namespace 里，生产 `phase12 mature_operating` 能在无网条件下给出完整 bundle。那不够关闭本项，因为：

1. **路径不同**：A-02 是 phase12 单模式编排器（内部自己生成 fixture）。本项是官方 `scripts/e2e_offline_demo.sh`（SPEC §18 / §21 DoD）的多步**生产 CLI**：`validate-data` → `build-snapshot` → `estimate` → `simulate` → `project-paths` → `value` → `returns` → `sensitivity` → `evaluate`，数据来自已写出的 canonical 目录。
2. **Replay（K-02）**：从**已保存** data（及同一 seed / as-of / ticker / 配置默认值）再跑一遍 valuation→exit/returns 链，对照哈希；非确定性字段必须点名隔离。A-02 没有做从冻结 snapshot 的重放（同 seed 再跑 phase12 只是再生成）。
3. **完整命令与产物保留**：本项保存逐步 stdout、全量 SHA、隔离自检与宿主对照。

未把「干净 checkout + 全新 venv + pip install」并入本项关闭条件（那是历史 Gap #9 里的 ENV-CLEAN，另项）。本项使用已有可复现 venv，跑的是生产 CLI，不宣称 ENV-CLEAN。

## 3. 执行与证据（2026-11-27 Asia/Shanghai）

测例 PR：[PR #36](https://github.com/KenshinQ/dsde-valuation/pull/36)，提交 `cd3384e8f2612c773ac16af37be52a428e05e993`（从 master `dd84fc16…`）。无 `src/vms` 改动。

文件 SHA256：

- `tests/integration/e01_isolated_netns_runner.py` `2ea637ee5420afbd18befdc1d1d09cddc7d73cd67828609b1bbed73d9c3bfe4a`
- `tests/integration/e01_offline_e2e_smoke.py` `51e0b281fae90fb7a50a5c1250db34b7aed40a613a3d3db0536832330989f5b1`
- `tests/integration/test_e01_offline_e2e_smoke.py` `90d9299012af0394a8927009f86c9ed868e73230c2b39793487ea56b944eed2c`

隔离：`unshare -r --net`；白名单环境；无 proxy、无凭据类变量。自检见 `e01_offline_e2e/isolation_self_check.json`（仅 lo，空路由，`1.1.1.1:443` 与 `8.8.8.8:53` 均为 errno 101）。宿主对照：两条均能连接（`host_contrast.json`）。未使用代理。

命令见 `e01_offline_e2e/COMMANDS.txt`。

pytest 9.2.0 / Python 3.13.5：

```
cd /workspace/dsde-valuation-e01
export PYTHONPATH=/workspace/dsde-valuation-e01/src:/workspace/dsde-valuation-e01
/workspace/dsde-valuation/.venv/bin/python -m pytest \
  tests/integration/test_e01_offline_e2e_smoke.py -v --tb=short
```

- **1 passed**，exit 0，34.97s
- junit：`e01_offline_e2e/junit_e01_isolated.xml`，timestamp `2026-11-27T01:50:47.463894+08:00`

生产路径（与官方脚本一致；demo 显式 `--paths 40`，因官方脚本省略该参数时会落到 `default_paths=10000`；后续 40/30/30/30/20 与脚本相同）：

`demo` → `validate-data` → `build-snapshot` → `estimate` → `simulate` → `project-paths` → `value` → `returns` → `sensitivity` → `evaluate`

`vms value` 按官方脚本保留。其 CLI 帮助写明是 legacy 0.1 FCFF（prefer phase4）。本项不因此改口关闭生产路由矩阵。

`evaluate` 使用 `config/universe.synthetic.yaml`（`data_dir: null`），与官方脚本相同——它不读取 demo 写出的 data，而是评价器自己的合成宇宙。这是官方路径的一部分，已如实记录。

## 4. Replay 结果（K-02）

从冻结的 `run1/demo/data` 重跑 post-demo 步骤到 `run2`。

| 部分 | 哈希对照 |
|------|----------|
| snap, est, sim, fp, val, ret, sens | 全部文件 bit-identical（0 differed） |
| eval / `evaluation_report.json` 及 data、frozen_weights、origin_records、simulation_metadata | 哈希一致 |
| eval / `forecasts/**/_h1.json`（8 个文件） | 哈希不同；逐字段对照后**唯一**差异是 `outcomes.evaluation_as_of` 墙钟时间戳 |

非确定性已隔离到该时间戳字段，符合 K-02「任何非确定性分量须被识别并隔离」。完整对照：`e01_offline_e2e/replay_comparison.json`、`run1_sha256.json`、`run2_sha256.json`。完整大 bundle 未入库（约 20MB），以哈希与关键 JSON 为准。

产物标签：`investment_value = INVESTMENT_VALUE_NOT_ESTABLISHED`，`pass_claim_authorized = false`，`CALIBRATION_INSUFFICIENT`。`evaluation_report` 中 run-level `ENGINEERING_PASS: true` **只描述本次合成 evaluate 产物，不是仓库 ENGINEERING_ACCEPTED**。

## 5. 最终判词

**清单第 6 项（verdicts 中的 Suite E / E-01 离线端到端 smoke / gap_items.9）：PASS**（有依据）。

仍保持：

- 仓库 `ENGINEERING_BLOCKED` / `RELEASE_BLOCKED` / `DO_NOT_MERGE` / `INVESTMENT_VALUE_NOT_ESTABLISHED`
- **VTP 准则 E-01 路由真值表 / 清单第 9 项未关闭**
- A-02 仍是单独的 PASS，不是本项的证据替代
- I-M04 `NOT_EXECUTED`；Suite G、Suite J 仍阻塞
- Suite I 仍为 5/5 executed KILLED，不是 6/6
- PR #33 / #34 / #35 / #36 均不合入，除非用户明确说「合入」

## 6. 证据路径

- 本报告：`artifacts/vtp-0.1-evidence/E_01_OFFLINE_E2E_SMOKE.md`
- 目录：`artifacts/vtp-0.1-evidence/e01_offline_e2e/`
- 测例 PR：https://github.com/KenshinQ/dsde-valuation/pull/36
- 证据/判词 PR：https://github.com/KenshinQ/dsde-valuation/pull/33
