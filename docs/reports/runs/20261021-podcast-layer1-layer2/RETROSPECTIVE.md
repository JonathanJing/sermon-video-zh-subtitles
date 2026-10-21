# 复盘：2026-10-18 播客 Layer 1 + Layer 2 zh-Hans（2026-10-21 运行）

- 来源：YouTube `AKY0k5KiKns`，主日 2026-10-18，批准窗口 `0:05.5–40:06`
- 交付类型：`four_layer_release` 的前两层（Layer 3／4 未运行）
- 状态：Layer 1 **放行**（`ready_for_translation`）；Layer 2 zh-Hans 多轮重跑中，r11 后仅剩 2 组失败，已按人工译本例外重跑 r12

## 结论先行

1. Layer 1 已走完全部机器门 + 人审门：709/709 句通过（`gpt-6.1-sol` high），0 高风险，候选包 `translationEligible: true`。
2. Layer 2 的正确路径是 **execution v3 自动修复**：r11 的 round-001 全量 746 组用 1471 次调用，round-002 修复轮**只新增 20 次调用**——它复用缓存、只重跑失败组。因此"修复轮全量重跑"是误解。
3. 真正的浪费来自**跨运行整轮重启**：r5–r10 因配置/插件/上限问题各重启一次，累计约 $14，其中 r10 单次 $13.21 停在 75%。
4. 本轮真正需要根治的是**派发前预检**与**跨运行续跑**，而不是继续加人工重试。

## 花费（按 token 实测结算，估算 $3/M 输入、$15/M 输出）

| 运行 | 调用 | 输入 tokens | 输出 tokens | 估算 USD | 结果 |
|---|---|---|---|---|---|
| r5 | 2 | 4,485 | 478 | $0.02 | 插件绑定上一集源包，停 |
| r6 | 2 | 4,485 | 466 | $0.02 | 插件补丁缺变量，停 |
| r7 | 16 | 36,990 | 4,744 | $0.18 | 复核改写 `Called Thrice`，停 |
| r8 | 16 | 37,790 | 4,166 | $0.18 | 纯英文名单单元无汉字，停 |
| r9 | 29 | 68,530 | 8,192 | $0.33 | 模型返回空 `targetUtterances`，停 |
| r10 | 1,114 | 2,675,539 | 345,472 | $13.21 | 输出上限 1024，第 564 组截断，停 |
| r11 | 1,491 | 3,585,327 | 466,106 | $17.75 | 全量完成，修后 2 组仍失败 |
| **合计** | **2,670** | | | **≈ $31.7** | |

Layer 1 另计 ≈ $8.05。全局累计 ≈ **$39.7**。

## 根因与代价（每一条都导致过一次整轮重启）

| # | 根因 | 触发轮次 | 代价 |
|---|---|---|---|
| 1 | 语言插件硬编码上一集的 `SOURCE_PACKAGE_SHA` / `ANCHOR_SHA` / `QUOTE_UNIT` | r5、r6 | 2 次重启（$0.04） |
| 2 | 固定译名（`Called Thrice`、`Rooted Week`）被独立复核改写为自然语序 | r7、r8、r11 | 3 次停（其中 r11 已完成 744 组） |
| 3 | 纯英文名单元（`Called Thrice。`）没有汉字，被 `spoken_chinese` 拒 | r8 | 1 次停 |
| 4 | `maxCompletionTokens=1024` 不足，长单元响应截断 | r10 | $13.21，停在 75% |
| 5 | 偶发 `malformed_model_output`（空 `targetUtterances`） | r9、r11 | 2 次停 |
| 6 | 预算规划器用 1 MiB **配置**上限读取 1.6 MiB 锚点 | 规划阶段 | 无法规划（PR #1242 修复） |
| 7 | 单次输入上限 3072 / 8192 小于真实载荷 | r5、r6 | 派发前失败 |

## 如何避免重复：不在问题区块之外重跑

### A. 派发前预检（零付费，最高优先）
1. **插件常量校验**：`rule_preflight` 在派发前比对插件的 `SOURCE_PACKAGE_SHA`、`ANCHOR_SHA` 与本次包/锚点；`QUOTE_UNIT` 必须存在于本次 source。可拦掉根因 1、3 的全部重启。
2. **术语预扫**：把 policy 的 `seriesNames` / `properNames` 与英文单元逐条比对，输出"文本出现但未批准"清单；对"保留英文"的条目自动生成 register rule，避免复核改写成中文（根因 2）。
3. **上限自检**：用最长单元与模板估算输入/输出 token，若接近 `maxCompletionTokens` 就先调高（根因 4 可在派发前发现）。
4. **插件身份一致性**：`plugin_implementation_sha256` 与 policy 的记录值在冻结时就比对（当前是在 worker 准入时才发现）。

### B. 跨运行续跑（避免整轮重跑）
- 现状：`text.models` 在 bound 模式下明确拒绝 `--resume-cache-from` / `--reuse-from`，导致每次重启都从第 1 组开始。
- 建议 P0：在 canonical 控制器允许 `--resume-cache-from`（复用上次运行的已验证组，只付缺失组）；或新增 `text.controller resume`：读取停止 job 的 round 缓存，生成只含缺失组的 job。
- 这样 r10 之后的修复只需为 183 组付费，而不是 746 组。

### C. 一次冻结"每轮都会变的东西"
- 人工译本（本次 `现在是 Rooted 的第九周。`）应写入 policy 的术语批准或 register rule，而不是散落在插件常量里；插件只保留实现，不承载内容决定。
- 每轮换 `jobRoot` 会丢缓存：只在配置身份确实变化时换根；纯预算/上限调整应复用同一 job root。

### D. 失败分类与有界重试
- `malformed_model_output`（空输出/格式错）与内容质量无关，应在 runner 内做 **1 次**有界重试，而不是停下整轮（根因 5）。
- 内容类失败（译名、语义）继续走自动修复链，不自动重试。

### E. 运行身份与预算
- 预算规划器应把 source/anchor 当包产物读取（已修，PR #1242）。
- 运行级 profile 的 `requestLimits` 应由实测载荷推导，而不是固定猜值。

## 本次已落地的改动

- PR #1237：MFA beam、裁判 turn、裁判批次自适应拆分、锚点切分与"操作员接受切点"
- PR #1242：预算规划器读取包产物（1.6 MiB 锚点不再被 1 MiB 配置上限拒绝）
- 决策记录：`layer2/zh-Hans/decisions.ndjson`（含人工译本 `Rooted` 决定，artifact-bound 到插件）
- 插件 r4：`HUMAN_APPROVED_UNIT_TEXT` 精确放行 `chunk-0002-u040`

## 待办（按优先级）

1. P0 `rule_preflight`：插件常量 + 术语预扫 + 输出上限自检（零付费，能避免本轮 4 次无效重启）
2. P0 canonical 路径放开跨运行续跑，只重跑缺失组
3. P1 policy 增加 fixed-form / keep-in-English 字段，prompt 与插件共用同一来源
4. P1 `malformed_model_output` 有界重试一次
5. P2 运行级 requestLimits 自动测量
