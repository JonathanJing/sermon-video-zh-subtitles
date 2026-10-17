# 复盘：G1 开窗只读预检（2026-10-17 18:13–18:21 UTC）

## 结论先行

测试／预检交付，结果 **未满足开窗排空条件**。本机全 `artifacts/` 的 `check_run_start.check_drain` 返回 fail：85 项未确认调用结果。三机进程采样未见当前 QC、校准、Layer 2、统一运行、Prefect pilot 或 mock DAG；Spark 固定独占会话已 closed。进程采样只说明检查时刻，不能抵消历史未知结果，也不能保证随后没有新派发。本轮只读，无生产执行、付费调用或状态修复。

## 总时间

检查从 18:12:53 到 18:21:18 UTC，约 8 分 25 秒。仅计本次检查墙钟；没有模型计算、服务等待或返工统计。

## 各层模型、耗时与速度

L1–L4 均为 `not_run`；调用数和费用均为 0，无模型速度数据。

## 错误／阻断

| 证据 | 数量与时间 | 判断 |
|---|---|---|
| Layer 2 `*.started.json` 且无同 stem `.raw.json` | 78；marker 状态均为 `started_response_unconfirmed`。其中 57 个只有 policy-preview，同 stem 其余 21 个没有附件。 | 本地没有同尝试终局收据。旧运行停止或后续尝试成功，不能结算这些请求。原供应商／CLI 响应仍需对账。 |
| Codex call `identity.json` 与 `started.json` 且无 `outcome.json` | 7，均在 `artifacts/weekend-live/text-qc-54475d42/state/codex-calls/`。 | 原 callId 的终局未由本地收据证明。 |
| Layer 2 预算 reservation | 在 43 个 budget state、11,303 条 reservation 中，4 条仍为 `request`，均为 `artifacts/weekend-live/layer2-54475d42/` 的 zh-Hans r7、r8、r9、r10。 | 相应 durable job 均记录 `failed/command_completed`，这不等于供应商请求已结算。 |

85 个标记的 mtime 范围为 2026-09-27 04:15:52 至 2026-10-14 21:14:27 UTC，按顶层根：`next-concurrency-605s-20261005-r13-gemini` 31、`weekend-live` 19、`post-live-runs` 18、`clip-e2e-20261004-opus-n` 8、`clip-test-20261012` 3、`drive-source-20260926-1730` 3、`layer2-api-test-20261010-clip` 2、`clip-e2e-dev216-20261014-c` 1。它们是历史目录，当前没有同名运行进程；其中 marker 是调用状态，不宜归作纯本地 fixture。没有取得原 provider 的同请求终局证明。

10/14 两个相关 clip 根的 `summary.json` 都记 `failed_durable_job` 而停止；`start-check-layer2.json` 分别记录旧 commit `74ecf747` 与 `c82e2d83`。这证明两次运行未继续活动，不证明它们的 9 个未知调用已结算。其他根的固定 checkout 和远端请求身份未逐一证明，因此不能整体排除出 G1。

## 可以改进的地方

先按原请求身份逐项对账：78 个 Layer 2 marker 的原 API/CLI 返回，7 个 Codex call 的原 callId 返回，尤其 zh-Hans r7–r10 的 4 条 reservation。若把历史运行隔离在旧 checkout，不再经 dev 续跑，需要留下可审计的明确范围与负责人决定；本预检不代替这个决定。重新检查排空后，再做开窗判断。

## 实际覆盖范围

本机整个 `artifacts/` 的 `check_drain`、43 个 Layer 2 budget state、312 个 `state.json`、52 个 Spark dispatcher started/result 对、`opus-e2e-dev216-20261014-g` 的 locale 产物、三机进程采样、Spark 固定独占状态与 GPU PID。312 个 state 中 136 个 workflow job 均终态（73 succeeded、63 failed）；52 个 Spark dispatcher result 均为 `known_terminal`。Spark 独占 `session.json` 为 closed、1 job terminal、10 operations verified、0 active/unknown jobs、0 unknown operations；常驻 GPU 进程为 llama-server。Mac mini checkout 的 artifacts 最近四天没有 state 或 started marker。

`check_drain` 本身不检查预算、Spark dispatcher 和当前进程；上述项目分别补查。未核验每个历史请求的供应商后台状态，也未把静态状态当成未来无活动保证。

## 遗留状态

用户已选择 G1 先行，之后重做 es、ko、zh-Hans。`artifacts/opus-e2e-dev216-20261014-g/` 三个 locale 均有文字和音频 waiver，但目录没有可见 seal 文件；其 `stages.json` 的 Layer 4/report 为 done，只代表该旧运行的阶段记录。开窗后这些 locale 要以新身份重新校准、筛查和签发。G1 首个合并应等待未知结果的可审计处理和临开窗进程复查。

## 外部可见的变化

无代码、账本、Spark 服务、远端作业或公开页面变更。本地仅生成本脱敏报告，交由主 Agent 审阅后决定是否公开。
