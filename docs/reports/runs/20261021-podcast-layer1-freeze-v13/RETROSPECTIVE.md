# 复盘：20261021-podcast-layer1-freeze-v13

数据见同目录 INDEX.md 和 manifest.json。

## 结论先行

- **交付类型**：`four_layer_release` 的 Layer 1 前置（双讲员播客《If I Had More Time | Jesus sends and resurrects His own》，YouTube `AKY0k5KiKns`，周日 2026-10-18，批准窗口 0:05.5–40:06）。
- **最终状态**：Layer 1 候选**冻结但未获机器放行**：`blocked` / `source_machine_judge_rejected`。选中 v13（Claude 裁判）：709 句中 708 通过、0 高风险、1 中风险、0 manifest 问题。`translationEligible=false`、`humanApproval=false`，Layer 2 需先做人工源审核。
- **为什么冻结**：v10（8 秒目标）4 句失败；v13（9.3 秒目标 + 3 处切点覆盖）只剩 1 句；v16 换 OpenAI `gpt-6.1-sol` 裁判后，同一份对齐被标出**另一句**高风险并带 11 个 manifest 问题。两个模型对边界的判定不一致，说明剩余差距在启发式切分器，而不是某个单点缺陷；继续调切点是打地鼠。选择收据见 `layer1/layer1-candidate-selection-v13.json`，决定记录见 `layer1/decisions.ndjson`。
- **证据边界**：机器裁判是模型判定，不是人工审核；本报告不构成任何人工批准，也未创建 `humanApproval=true`。

## 总时间

- 2026-10-21 本地 07:46 → 11:34，约 3 小时 50 分（含等待 Spark 准入、两次 Claude 登录、一次会话配额耗尽）。
- 主要返工来自身份重置：每次配置/代码变化都要重跑 ASR（14 次调用）与 MFA（约 90 秒）。

## 各层模型、耗时与速度

| 层／阶段 | 模型或后端 | 推理强度／tier | 调用次数 | 计算耗时 | 费用 | 证据 |
|---|---|---|---|---|---|---|
| L1 来源 ASR | `gpt-transcribe` | default | 14／轮，共 11 轮 | ~40 s／轮 | 约 USD 0.18／轮 | `layer1/output-v10/chunks/*.asr-final.json` |
| L1 词级对齐（MFA） | DGX Spark MFA 3.4.2 | beam 100 / retry 400 | 14 chunk | ~90 s | 本地算力 | `layer1/output-v10/aligned-segments.json` |
| L1 英文机器评审（v13） | `claude-opus-5-5`（订阅 CLI） | high | 119 批 | ~6 min | 订阅 | `layer1/output-v13/machine-judge.json` |
| L1 英文机器评审（v16） | `gpt-6.1-sol`（OpenAI） | high | 119 批 | ~5 min | 实测结算约 USD 2.09 | `layer1/output-v16/machine-judge.json` |
| L2 初译／审核／回译 | not_run | — | — | — | — | 需先人工源审核 |
| L3 配音／质检 | not_run | — | — | — | — | — |
| L4 构建与发布 | not_run | — | — | — | — | — |

## 错误与修复

1. **MFA `NoAlignmentsError`（已修，PR #1237）**：506 词／180 秒块在默认 beam 下无路径；改为 `--beam 100 --retry_beam 400`，本地 21.7 秒验证。
2. **Claude CLI 401 OAuth 过期**：两次需要操作者重新登录；失败调用记为 `started_response_unconfirmed`，按设计阻断该账本后续派发，只能开新身份。
3. **裁判输入上限 `source_judge_input_bound_exceeded`（已修）**：冻结上限 16384，批次 10/8/6 曾先后超限；根因是每轮 ASR 导致句子长度漂移，改为对超限批次二分拆分。
4. **`claude_language_unexpected_turn_count`（已修）**：CLI 把 schema 修复轮计入 turn，放宽到 3。
5. **Claude 订阅会话配额耗尽**：v15 在第 35 次调用后返回 "You've hit your session limit · resets 12:30pm"；改走 OpenAI 裁判完成 v16。
6. **锚点切分**：缩写年份（`A.D. 70`）、引语列表、`yes,` 否定句、名单切分等 9 处被裁判标出；句子切分加缩写表、长单元切分优先可听停顿/强标点、引号内不切（PR #1237），剩余问题用 `boundaryOverrides` 定点修。

## 费用

- 实际付费：ASR 约 **USD 1.80**（11 轮 × 14 次）+ OpenAI 裁判 **USD 2.09**（119 次，token 实测结算）≈ **USD 3.9**，远低于 USD 25 授权。
- 预留最坏值：v13 订阅预留 USD 20.17、v16 预留 USD 8.13（不是扣费）。
- 所有 ASR 行仍为 `costStatus=unknown`（供应商无 token 用量），`invoiceVerified=false`。

## 下一步

1. **人工源审核**（blocking）：审核冻结候选 `output-v13/english-source-candidate.json`，重点看 `chunk-0004-s031`（中风险，系动词与补语被切开），记录人工决定后 Layer 2 才能启动。
2. **切分器升级**：用双讲员 diarization 的 turn 边界或语义切分替代标点/停顿启发式，可根治本轮的边界争议。
3. **跨配置 ASR 复用**：给该 producer 接上预算账本已有的 `reuseBudgetRoots`，避免每轮重转。
