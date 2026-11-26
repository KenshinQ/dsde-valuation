# A-02 离线语义：相对新鲜 junit 的缺口与关闭记录

- 日期：2026-11-27 Asia/Shanghai（CST, UTC+8）
- 仓库：KenshinQ/dsde-valuation
- 本文件只服务清单第 5 项（A-02）。不开始第 6 项及以后。
- 权威 fail-closed 判定仍是 `verdicts_final_failclosed.json`。仓库继续 `ENGINEERING_BLOCKED` / `DO_NOT_MERGE` / `INVESTMENT_VALUE_NOT_ESTABLISHED`。A-02 单项 PASS 不解除整仓库 BLOCKED。

## 1. 现有新鲜 junit 是什么

`artifacts/vtp-0.1-evidence/junit_a02_fresh.xml`

- 时间戳：`2026-11-09T17:02:17.393184+00:00`（2026-11-10 01:02 Asia/Shanghai）
- pytest：8 tests, 0 failed, 0 errors, 0 skipped，约 11.311s
- 全部 8 项 PASS：
  - `test_phase0_runs_offline`
  - `test_phase0_produces_versioned_bundle`
  - `test_phase4_runs_offline`
  - `test_phase12_five_patterns_offline`
  - `test_offline_no_network_dependency`
  - `test_bundle_contains_provenance`
  - `test_routing_decision_recorded`
  - `test_investment_value_not_established_label`
- 对应测例：`tests/vtp_0_1/suite_a/test_a02_offline_synthetic_run.py`（仅在 PR #33 证据分支，不在 master）
- 该文件自身 docstring 已写明：修复后可运行，但不足以证明 spec A-02 完整离线要求。

先前把 A-02 标为 **PARTIAL** 是正确的：8/8 green ≠ 完整离线语义。本轮不改写、不丢弃这份 junit，也不把它单独升级为 PASS。

## 2. 官方 A-02 通过标准（`vtp_criteria_mapping.json`）

> Run the smallest complete synthetic-company workflow with **network access unavailable**.
>
> **Pass:** a versioned result bundle is produced with profile, routing decision, method results, market exit-price distribution, return distribution, diagnostics and provenance.

## 3. 「完整离线语义」相对该新鲜 junit 还缺什么（本轮开始时）

| 缺口 | 新鲜 8/8 junit 的情况 | 为何不够 |
|------|----------------------|----------|
| G1 真正的网络不可用 | 只设置低优先级 `http_proxy`/`https_proxy` 到 `http://0.0.0.0:1` 或 `http://localhost:9999` | 审计 P1-E1 已否决「代理 = 离线」。无效代理不能阻止直连 socket，也不能证明无默认路由。 |
| G2 阻断自检 | 无 | 没有在同一运行里对外部地址做连接并期望失败；没有记录 errno / 路由表 / 接口。 |
| G3 干净环境 / 无凭据 | `env={**os.environ, ...}` 继承全部环境 | 可能带入其他代理、`NO_PROXY` 例外、API key / token。没有无凭据环境证据。 |
| G4 最小完整工作流的 bundle 字段 | phase0 测例无法产出 method results / exit-price / returns；`test_phase12_five_patterns_offline` 只断言 returncode==0 且输出目录存在 | 通过标准要求 profile、routing、methods、exit、returns、diagnostics、provenance 都在版本化 bundle 里。 |
| G5 非空断言 | `test_phase0_produces_versioned_bundle`、`test_bundle_contains_provenance`、`test_routing_decision_recorded` 使用 `if file.exists(): ...` | 文件缺失时断言被跳过，测试仍为绿。 |
| G6 投资价值标签 | `test_investment_value_not_established_label` 只检查未出现 `INVESTMENT_ADVICE` 字符串 | 弱于显式 `INVESTMENT_VALUE_NOT_ESTABLISHED`。测例自己的 AUDIT NOTE 已承认。 |
| G7 产物保留 | TemporaryDirectory 在测试结束时删除 | mapping 已记录「TemporaryDirectory输出未保存」，无法复核 bundle。 |

这些缺口在 8/8 green 之后仍然成立。因此本轮若只重跑同一套代理测例，A-02 必须继续诚实 PARTIAL。

## 4. 本轮补测（新测例落在 master 薄 PR，不堆进 #33/#34）

- 测例 PR：[PR #35](https://github.com/KenshinQ/dsde-valuation/pull/35)
- 分支：`test/a02-isolated-offline-synthetic-run`
- 提交：`0ce82c69abaa38319fa49ed6e3e69d127bb071b0`（从 `master` @ `dd84fc16f54c397d3ba88e953a384dfecd550466` 快进）
- 文件（无 `src/vms` 改动）：
  - `tests/integration/a02_isolated_netns_runner.py` SHA256 `62b67afae02f6e799ba0454db0b1fc2ca97184692347c2f1b407007c11445822`
  - `tests/integration/test_a02_isolated_offline_synthetic_run.py` SHA256 `9941202ad518ee1296f4f9e0754ecaec319ebfb333243501fc4706f3dc397594`

机制：`unshare -r --net`（无特权 user + network namespace）。本机探测：

- `unshare -r --net true` 与 `unshare --user --net true`：exit 0
- `unshare --net true`（不带 user ns）：Operation not permitted
- 不是 iptables，不是 root `ip netns add`，**也不是代理**

自检权威视图：`ip link` / `/proc/net/dev` / `/proc/net/route` 与 socket。本环境 `/sys/class/net` 在新 netns 内仍可能列出宿主机网卡（sysfs 未随 netns 重挂）；自检不把宿主 sysfs 泄漏当作通过或失败依据，并在报告里如实记录 `sysfs_interfaces_may_be_host_view`。

Fail-closed：无法创建 namespace 或自检不能证明网络不可用则测试失败（不 skip）。

命令与原始输出见 `a02_isolated/COMMANDS.txt`、`a02_isolated/a02_isolated_pytest_stdout.txt`、`a02_isolated/junit_a02_isolated.xml`。

## 5. 新证据结果（2026-11-27 Asia/Shanghai）

### 5.1 pytest

```
/workspace/dsde-valuation/.venv/bin/python -m pytest \
  tests/integration/test_a02_isolated_offline_synthetic_run.py -v --tb=short
```

- 在 master 工作树 `/workspace/dsde-valuation-a02` 上运行，`PYTHONPATH` 指向该工作树 `src`（与 master 的 phase12/reporting/cli 一致）
- **2 passed**，exit 0，2.91s
- junit：`a02_isolated/junit_a02_isolated.xml`，timestamp `2026-11-27T01:36:46.193709+08:00`，hostname `grok-bot-vm-154033825`
  - PASS `test_isolated_netns_blocks_outbound_without_proxy` (0.042s)
  - PASS `test_a02_smallest_complete_synthetic_workflow_network_unavailable` (2.726s)

### 5.2 同一隔离下的生产 phase12（复核用，exit 0）

宿主对比（`a02_isolated/host_contrast.json`）：宿主机可连接 `1.1.1.1:443` 与 `8.8.8.8:53`。

隔离自检（`a02_isolated/isolation_self_check.json`）：

- `isolation_mechanism`: `unshare -r --net (user + network namespace)`
- `proxy_used`: false；`env_proxy_keys_present`: []；`credential_like_keys_present`: []
- `interfaces`: ["lo"]；`non_loopback_interfaces`: []；`ip_route`: ""；`default_route_present`: false
- `1.1.1.1:443` 与 `8.8.8.8:53`：`OSError` errno 101 `Network is unreachable`
- `network_unavailable`: true

生产 CLI 在**同一次** namespace 调用里、自检通过之后运行：`vms.cli.main phase12 --pattern mature_operating --seed 42 --paths 10 --years 2 --spot 10.0`。stdout 见 `a02_isolated/phase12_isolated_stdout.json`（`validation_ok: true`，`investment_value: INVESTMENT_VALUE_NOT_ESTABLISHED`，`validation_subset: phase12_mature_full`）。

保留的产物摘要（完整大文件未入库，避免把 262KB 级 return distribution 推进证据分支；全量 sha256 见 `a02_isolated/artifact_sha256sums.txt`）：

- `phase12_summary.json`、`validation_report.json`（`ok: true`，`subset: phase12_mature_full`，`missing: []`）
- `profile_report.json`（`primary_profile: MATURE_OPERATING`）
- `simulation_metadata.json`（`schema_version: vms-0.2.phase12`，`seed: 42`，含 `run_id` 与 `config_hash`）
- `request.json`、`diagnostics.json`

## 6. 缺口关闭对照

| 缺口 | 关闭？ | 依据 |
|------|--------|------|
| G1 真正网络不可用 | 是 | user+net ns，空路由，仅 lo，直连 ENETUNREACH；宿主机同时可连，证明阻断来自 ns 而非网卡坏掉。未使用代理。 |
| G2 阻断自检 | 是 | runner 在同一 ns、运行 phase12 之前写入 `isolation_self_check.json`。 |
| G3 干净环境 | 是（本次工作流） | 白名单 env，无 proxy、无凭据类键。不把全仓库 `ENV-OFFLINE` 准则一并标 PASS。 |
| G4 完整 bundle 字段 | 是（相对 A-02 标准） | 非空文件 + 生产 `phase12_mature_full` 校验 + 字段断言。未宣称 K-01 / 完整 §16.3 全量产物。 |
| G5 非空断言 | 是 | 新测例对缺失文件直接失败，不用 `if exists`。 |
| G6 投资价值标签 | 是（相对 A-02） | 显式 `INVESTMENT_VALUE_NOT_ESTABLISHED`，且 `INVESTMENT_VALUE_SUPPORTED` 为 false。不宣称投资价值成立。 |
| G7 产物保留 | 是（摘要 + 全量哈希） | 见 `a02_isolated/`。完整 TemporaryDirectory 仍不入库。 |

## 7. 最终判词

**A-02：PASS**（有依据，不是把旧 8/8 代理 junit 改口）。

仍保持：

- 仓库 `ENGINEERING_BLOCKED` / `RELEASE_BLOCKED` / `DO_NOT_MERGE` / `INVESTMENT_VALUE_NOT_ESTABLISHED`
- 清单第 6 项（离线端到端 smoke；PR #33 中 Suite E / `gap_items.9`）**未做**，保持 `NOT_VERIFIED`。更正一处过时环境描述：本机已能使用 `unshare -r --net`，不再写「无 unshare」；但第 6 项本身未执行，不降级标准，不标 PASS。
- 不把 `ENV-OFFLINE` 全仓库环境准则悄悄改成 PASS
- Suite I 仍为 5/5 executed KILLED，仅 I-M04 `NOT_EXECUTED`，不是 6/6
- PR #33、#34、#35 均不合入，除非用户明确说「合入」

## 8. 证据路径

- 本报告：`artifacts/vtp-0.1-evidence/A_02_OFFLINE_SEMANTICS_GAP_AND_CLOSURE.md`
- 新测例与命令/junit/自检：`artifacts/vtp-0.1-evidence/a02_isolated/`
- 旧新鲜 junit（仍不足单独作为 PASS）：`artifacts/vtp-0.1-evidence/junit_a02_fresh.xml`
- 测例 PR：https://github.com/KenshinQ/dsde-valuation/pull/35
- 证据/判词 PR：https://github.com/KenshinQ/dsde-valuation/pull/33
