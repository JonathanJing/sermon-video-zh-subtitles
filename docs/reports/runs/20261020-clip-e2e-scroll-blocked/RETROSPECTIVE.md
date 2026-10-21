# 复盘：20261020-clip-e2e-scroll-blocked

数据见同目录 INDEX.md 和 manifest.json。未填写的小节删掉前请写明原因。

## 结论先行

<!-- 交付类型（dual_pdf／live_session／four_layer_release／测试）、最终状态和结束信号（outcome.json；独占 Spark 以 round: 行为准）、证据边界。模拟审核和诊断级结果原样写出。 -->
**交付类型：测试运行；结果：失败（门禁按预期阻断，未发布）。最终状态 `four_layer_release=not_run`，Dev 测试页未创建。**

目标是从 2026-10-18 resi-15030286 证道截取 7 分钟片段（英语单元 127–215，启示录 10:8–11），按四层流程跑到 Dev 隔离测试页。本次只完成 Layer 1 输入构建与 Layer 2 策略冻结，被 Layer 2 的源绑定门禁阻断，未产出任何 Target-Language Candidate，因此 Layer 3、Layer 4 都未执行，页面未发布（404 已核验）。

已付费调用 96 次、全部 `succeeded`、无未知结果，合计 **$0.645419**，输出 26,250 token。金额已按实际结算记录计入后续预算的 `settledUsdBefore`。

**证据边界：** 这不是四层生产完成，也不证明片段流程可用；它证明的是片段作用域的源绑定在现有插件架构下无法满足。机器审核不是人工批准。

## 总时间

<!-- 从开始到结束的墙钟时间，拆成计算、等待（人、服务、凭据）和返工；与上一轮同类运行比较。 -->
自动汇总（核对后保留）：

- `clip-e2e-15030286-20261020-scroll`：没有 journal、outcome 起止时间或 timings.tsv，无法自动计算
- `clip-e2e-15030286-20261020-scroll-b`：没有 journal、outcome 起止时间或 timings.tsv，无法自动计算

## 各层模型、耗时与速度

<!-- 每层写模型或后端、推理强度和 tier、调用次数、计算耗时、token 或音频秒数、速度（输出 token/s 或 ×实时）、费用。没执行的层写 not_run，复用的写 reused 和来源。 -->
| 层／阶段 | 模型或后端 | 推理强度／tier | 调用次数 | 计算耗时 | token 或音频秒数 | 速度 | 费用 | 证据 |
|---|---|---|---|---|---|---|---|---|
| L1 来源 ASR | 复用源周次 gpt-transcribe 冻结结果 | — | not_run（本片段） | — | — | — | reused | `layer1-15030286-20261017/formal-v3` |
| L1 词级对齐（MFA） | 复用源周次 MFA 对齐 | — | not_run（本片段） | — | — | — | reused | `output-rebuild-v3/anchor-manifest.json` |
| L1 英文机器评审 | 复用源周次人工审核收据 | — | — | — | — | — | reused | `formal-v3/english-source-review.json` |
| L2 初译 | `gpt-6.1-sol` | `high` / `default` | 48 | 约 13 分钟（含重试） | 26,250 输出 token | 约 33 token/s | 计入下方合计 | 96 条 `*.result.json` |
| L2 独立审核 | `gpt-6.1-sol` | `medium` / `default` | 48 | 同上 | 含在上行 | 同上 | 同上 | 同上 |
| 文本质检（回译） | not_run | — | 0 | — | — | — | 0 | 未到达（Layer 2 未产出候选） |
| L3 配音（TTS） | not_run | — | 0 | — | — | — | 0 | 未到达（Layer 2 未产出候选） |
| L3 回转写筛查（ASR） | not_run | — | 0 | — | — | — | 0 | 未到达（Layer 2 未产出候选） |
| 音频质检 | not_run | — | 0 | — | — | — | 0 | 未到达（Layer 2 未产出候选） |
| L4 构建与发布 | not_run | — | 0 | — | — | — | 0 | 未到达（Layer 2 未产出候选） |

已复制收据里出现的模型（自动汇总，按层归入上表）：

| 模型 | 推理强度 | tier | 调用记录 | 输出 token | 计时 | 输出 token/s | 来源文件 |
|---|---|---|---|---|---|---|---|
| `gpt-6.1-sol` | ? | ? | 108 | 26250 | 11m39s | 37.6 | `clip-e2e-15030286-20261020-scroll-b/l2/text/es/accounting/summary.json`, `clip-e2e-15030286-20261020-scroll-b/l2/text/zh-Hans/accounting/summary.json`, `clip-e2e-15030286-20261020-scroll/l2/attempt-1-week-plugins/text/es/accounting/summary.json` 等 6 个 |

同一次调用可能在请求和响应两处各记一次；速度只用同一记录里同时有输出 token 和耗时的部分。

## 错误

<!-- 每个错误一行：发现时机分预检／占用资源后／发布后；占用资源后才发现的，写要补的预检。 -->
| 层／阶段 | 现象 | 原因 | 发现时机 | 处理 | 回归测试 | 提交或 PR |
|---|---|---|---|---|---|---|
| Layer 2 预算规划 | `layer2 cap cannot cover even the initial 176 calls` | 88 组片段远超 profile 的 16 组 clip 校准（每语初始预留 $10.813 vs $2.00 上限） | 预检 | 经用户批准改用 `seven-minute-run-profile.json`（只放大计数与每语 cap） | `tests/test_clip_real_e2e.py` 的 budgetProfile 用例 | 分支 `fde95b9b` |
| Layer 2 插件校验（3 轮） | `15030286 plugin source package differs` | 插件把 `SOURCE_SHA256` 硬绑整周源包；片段必有新源包 | 占用资源后（已付费） | 生成 clip 作用域变体；三次尝试均未让变体在 worker 进程中生效 | 变体构建器有单行 diff 校验与导入校验 | 分支 `fde95b9b` |
| 编排器参数 | `--out: expected one argument` | `argv` 插入位置错一 | 预检 | 修正为 `argv[:2]` 并加两条回归测试 | `tests/test_clip_real_e2e.py` | `fde95b9b` |
| 运行目录复用 | `Layer 2 budget identity changed` | 归档 attempt 后 plan 授权与账本 authority 不再一致 | 预检（阻断派发） | 未强行续跑，另起干净 run 目录 `-b` | — | 待补：归档后应禁止复用 |

## 可以改进的地方

<!-- 按速度、成本、预检、质量、流程分类；每条写预期收益、负责人和跟踪的 PR 或 backlog 条目。 -->
| 类别 | 改进 | 依据（本报告的数值或错误） | 预期收益 | 负责人 | 跟踪 |
|---|---|---|---|---|---|
| 预检 | 片段开工前应检查“插件是否绑定整周源包”，并给出明确阻断，而不是在付费后才失败 | 本次 96 次付费调用全部浪费 | 每次片段运行省下约 $0.65 与 13 分钟 | 待定 | 建议新增 backlog 条目 |
| 流程 | 归档 Layer 2 attempt 时不应同时移动 budget root 与 plan 授权；或应提供官方归档命令 | `budget identity changed` | 避免必须新建 run 目录 | 待定 | 待定 |
| 质量 | 片段插件需要显式的源作用域绑定机制（读策略 `sourceScope`，而非硬编码整周哈希） | 8 条人工批准校正落在本片段内，放弃插件会静默降质 | 片段可复用周次校正 | 待定 | 需用户决策 |

## 实际覆盖范围

<!-- 按 L1–L4 写本轮执行、复用和未执行的部分。 -->
- **L1：** 复用源周次（resi-15030286）已人工审校的英文来源包、锚点与对齐；片段输入由 `inputs` 阶段裁出 88 个单元（424.7 秒）。
- **L2：** 策略已冻结（Sol 6.1 high 初译 / medium 复核、三语插件变体绑定），预算与开工检查通过，实际派发 96 次调用后于插件源校验处失败；**0 个 candidate**。
- **L3 / L4：** not_run。

**实际覆盖范围：** `inputs`、`layer2-setup` 完成；`layer2` 未完成。

## 遗留状态

<!-- Dev 上无引用的文件、未结束的 job hold、已用构建号、待删除的本地产物。 -->
- 本地产物：`artifacts/clip-e2e-15030286-20261020-scroll`（attempt 1–3）与 `-scroll-b`（attempt 1）；均未发布、无外部引用。
- Dev：无新增文件，测试页 `mockup-dev-clip-20261018-scroll-b-20261020` 仍为 404。
- 未结束的 Spark 会话与 job hold：无（本次未进入 GPU 阶段）。
- 已结算 $0.645419 需计入后续运行 `settledUsdBefore`。

## 外部可见的变化

<!-- Dev 发布、TestFlight、受保护分支推送各自的证据；没做的验收写 not_run。 -->
- Dev 发布：not_run。
- 受保护分支推送：分支 `codex/clip-e2e-15030286-7min-20261020` 与其运行报告 PR 已推送；未合并到 `dev`。
- TestFlight / 设备 / 现场：not_run。
