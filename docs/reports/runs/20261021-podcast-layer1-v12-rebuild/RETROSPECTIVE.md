# 复盘：20261021-podcast-layer1-v12-rebuild

数据见同目录 INDEX.md 和 manifest.json。承接 [20261021-podcast-layer1-mfa-judge](../20261021-podcast-layer1-mfa-judge/RETROSPECTIVE.md)（v1–v9）。

## 结论先行

- **交付类型**：`four_layer_release` 的 Layer 1 前置（双讲员播客《If I Had More Time | Jesus sends and resurrects His own》，YouTube `AKY0k5KiKns`，周日 2026-10-18，批准窗口 0:05.5–40:06）。
- **最终状态**：v10 `blocked` / `source_machine_judge_rejected`（709 句中 4 句高风险边界）；v11 重建在锚点阶段被拒（`Boundary override lacks a safe clause split`）；v12 重建在第一批裁判调用就停（`claude_language_model_identity_missing`），没有 `machine-judge.json`。候选包仍是 v10 的 `blocked` 候选，`humanApproval=false`，没有任何人工批准。
- **根因（v10 的 4 句）**：上一提交 `b2d3f355` 把"优先可听停顿、引号内逗号不切"的规则改在 v1 拆分函数 `_split_long_sentence`，而生产入口 `unified_stage` 用的是 v2 `_split_clause_stable`，规则从未生效。4 句分别是：逗号后是填充词（`who's, I mean,`）、否定句在 `yes,` 处被切、`the whole | sort of` 把修饰语和中心词切开、攻击者列表在 `by Nero,` 处被切。
- **根因（v12 的失败）**：本会话里调用 Claude CLI 时，`modelUsage` 多出一条 `claude-haiku-4-5-20251001`（输入 3697、输出 14 token，辅助调用），结构化答案仍由 `claude-opus-5-5` 产出（输出 2616 token，含思考 886）。传输层要求 `set(modelUsage) == {requested}`，因此拒收；6 次调用的 CLI 结果都是 `is_error=false`、`subtype=success`、schema 合法，但账本记为 `started_response_unconfirmed`，v12 预算根关闭。
- **证据边界**：以上都是机器判定和代码事实，不是人工审核；没有产生 `ready_for_translation`。

## 总时间

- v10（旧会话）：17:11:11Z → 17:19:40Z，508.8 s 计算：ASR 14 块 4 并发约 30 s，Spark MFA 约 90 s，裁判 121 次调用 6 并发约 5 分钟。
- v11（旧会话）：10:50 本地，重建在锚点阶段即失败，0 次模型调用。
- v12（本会话）：18:08:50Z → 18:09:13Z，23 s；6 次 CLI 调用全部被传输层拒收。
- 本会话代码与离线验证（规则重写、裁判缓存改造、139 个定向测试、用 v10 对齐离线重建锚点）约 2 小时，其中没有付费调用。

## 各层模型、耗时与速度

| 层／阶段 | 模型或后端 | 推理强度／tier | 调用次数 | 计算耗时 | token 或音频秒数 | 速度 | 费用 | 证据 |
|---|---|---|---|---|---|---|---|---|
| L1 来源 ASR | `gpt-transcribe`（OpenAI dev 项目） | default | v10：14 | 约 30 s | 2400.5 s 音频 | — | 约 USD 0.18（估） | `output-v10/accounting/summary.json` |
| L1 词级对齐（MFA） | DGX Spark MFA 3.4.2，beam 100 / retry 400 | — | v10：14 块 | 约 90 s | 7303 词 | 约 26× 实时 | 本地算力 | `output-v10/alignment-receipt.json` |
| L1 英文机器评审 | `claude-opus-5-5`（订阅 CLI） | high | v10：121；v12：6（拒收） | v10 约 5 分钟（记录合计 38m08s，6 并发） | v10 输出 271,382 token | 118.6 token/s | 订阅列价等价，v10 预留内 | `output-v10/machine-judge.json`、`output-v12/judge-requests/claude-cli-calls/*` |
| L1 锚点（v12 规则，离线） | 本地确定性 | — | 0 | 秒级 | 709 句 → 768 单元 | — | 0 | 本会话离线重建，未进入产物 |
| L2–L4 | not_run | | | | | | | Layer 1 未放行 |

## 错误

| 层／阶段 | 现象 | 原因 | 发现时机 | 处理 | 回归测试 | 提交或 PR |
|---|---|---|---|---|---|---|
| L1 锚点（v10） | 裁判拒 4/709 句，全部是高风险边界 | 规则改在 v1 函数，v2 生产路径未改 | 占用资源后（裁判跑完） | 规则移入 `_split_clause_stable` 并按四句真实模式收紧 | `tests/test_anchor_unit_splitting.py` 新增 6 例 | `869cb15b`，PR #1237 |
| L1 锚点（v11） | 重建拒绝操作者覆盖 `chunk-0007-w0234` | 覆盖点无标点也无停顿，代码不接受 | 预检（锚点阶段） | 放弃逐句覆盖，改规则 | — | — |
| L1 裁判（v12） | 6 次调用 `claude_language_model_identity_missing` | CLI 结果多出一条 haiku 辅助用量 | 占用资源后（首批） | 待修：传输层只要求请求模型产出答案并记录辅助模型；清理继承的 `CLAUDE_CODE_*` 环境变量 | 待补 | 待提交 |
| L1 预算 | v12 预算根 6 条 unknown，账本关闭 | 传输层拒收后无对账路径 | 占用资源后 | 下一轮开新身份（v13） | — | — |
| 报告导出 | 整个 `layer1` 目录超 2 MB 上限 | 12 轮输出累积 | 导出时 | 只导出 v10、v12 与一个小的上下文目录 | — | — |

## 可以改进的地方

| 类别 | 改进 | 依据（本报告的数值或错误） | 预期收益 | 负责人 | 跟踪 |
|---|---|---|---|---|---|
| 速度 | 裁判缓存按内容寻址并共享 `judgeCacheRoot` | v10→v12 边界只改 42 句，旧缓存键含 manifest 哈希只能整批重判 | 重建只重判改动批次，约 5 分钟降到 1–2 分钟 | 本会话 | `869cb15b` |
| 速度 | 单元 ID 按块顺序编号，一句多拆一个单元会让后面句子的单元 ID 全部顺延 | 测试 `test_shared_cache_root_replays_unchanged_batches_after_a_boundary_rebuild` | 稳定单元 ID 后重判范围再缩小 | 待排 | backlog 待建 |
| 质量 | v2 拆分：虚词结尾、填充词后逗号、修饰语与中心词、列表中逗号都不再作为切点 | v10 的 4 句 | 裁判高风险边界减少 | 本会话 | `869cb15b` |
| 预检 | 传输层对辅助模型用量的处理和环境清理 | v12 的 6 次拒收 | 不再因宿主环境差异整轮停下 | 本会话 | 待提交 |
| 流程 | 预算授权绑定代码身份，每次改代码都要重签 | v10–v12 各一份授权 | 授权绑定 run 与上限、代码身份只作证据 | 待讨论 | backlog 待建 |

## 实际覆盖范围

- **L1**：v10 执行 ASR、MFA、锚点、裁判（blocked）；v12 重建复用 v10 对齐，只到裁判首批即停；新拆分规则只有离线重建结果（709 句 768 单元，20 句保持完整 8.7–13.1 s，4 句问题边界消除），尚未经过裁判。
- **L2–L4**：not_run。

## 遗留状态

- 本地 `layer1/output-v12/` 无 `machine-judge.json`；`.output-v12.judge-budget` 有 6 条 unknown，不能再派发。
- `layer1/.judge-cache/` 为空（v12 没有成功返回）。
- 旧会话的 iOS 工程文件改动仍在工作区，未提交、未触碰。

## 外部可见的变化

- PR #1237 分支新增提交 `869cb15b`（规则、缓存、测试）。
- Dev 发布、TestFlight、受保护分支：not_run。

## 后续：v13–v20（另一 agent 并行完成，本节于 20:00Z 补记）

- 同一 `layer1/` 目录里，另一个 agent 在本地 10:57–12:20（17:57–19:20Z）连续做了 v13、v17、v18、v20 重建，用的是本会话当时未提交的拆分规则加它自己的提交 `6b3045fd`（操作者可接受无停顿的依赖边界）。v13 裁判 708/709（只剩 `is primarily, | if not …`）；决定记录 18:34Z 冻结 v13 转人工；v20 把 `maxUnitSeconds` 调到 10.0、对 `chunk-0010-s002` 写一条三段覆盖，裁判 709/709 通过、7 条清单问题、746 单元，19:19Z 人工四项批准，19:20Z 决定放行，`output-v20/english-source-package-reviewed.json` 为 `ready_for_translation`、`translationEligible=true`。
- 本会话 12:36 本地的 v13 准备文件覆盖了对方同名的 v13 配置和授权（已改名为 `*-v13-overwritten-by-this-session-1936Z.json` 留证，原件无法恢复），随后的 v13 重建在已冻结的 `anchor-manifest.json` 处停下，没有新调用。
- 用分支头 `3683539b`（含系动词后副词规则）离线重建 v20 的锚点：与已发布的 v20 清单 **0 句差异**，v20 可由当前代码复现。
- 传输层修复（`000656ba`）在本会话环境下尚未经过真实裁判调用验证；v20 是在对方环境跑的，没有出现辅助模型用量。
- 教训：两个 agent 共享一个 checkout 和 `artifacts/`，未提交的包代码对所有进程即时生效，版本后缀是唯一的命名空间。写运行文件前先看目录里比自己上一步更新的文件和 `decisions.ndjson` 末尾，并让准备脚本拒绝覆盖已存在的版本。
