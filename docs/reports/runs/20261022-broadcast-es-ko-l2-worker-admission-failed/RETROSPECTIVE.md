# 复盘：20261022-broadcast-es-ko-l2-worker-admission-failed

数据见同目录 INDEX.md 和 manifest.json。未填写的小节删掉前请写明原因。

## 结论先行

<!-- 交付类型（dual_pdf／live_session／four_layer_release／测试）、最终状态和结束信号（outcome.json；独占 Spark 以 round: 行为准）、证据边界。模拟审核和诊断级结果原样写出。 -->
交付类型为 `four_layer_release`。本轮只进入 ES 的 Layer 2 worker admission；job `a7131092…17fea` 以 `failed` 结束，候选未生成。账本可读且收据一致，API 请求 0、费用估算 0、未结算／未知结果 0。Layer 2 初始预算计划上限为 $102.24（两语言合计），但预算授权没有传入 worker，因此付费阶段未开始。来源包与英文锚点通过只读门禁；未发生发布或页面变更。

## 总时间

<!-- 从开始到结束的墙钟时间，拆成计算、等待（人、服务、凭据）和返工；与上一轮同类运行比较。 -->
自动汇总（核对后保留）：

- `a7131092cf4d5be8edbbdc31a3251100f59ccaa4393b5921fde8a8b457b17fea`：worker accounting 记录 0.166 秒，其中本地 admission 0.163 秒；没有 run-level journal，无法拆分完整轮次墙钟和等待

## 各层模型、耗时与速度

<!-- 每层写模型或后端、推理强度和 tier、调用次数、计算耗时、token 或音频秒数、速度（输出 token/s 或 ×实时）、费用。没执行的层写 not_run，复用的写 reused 和来源。 -->
| 层／阶段 | 模型或后端 | 推理强度／tier | 调用次数 | 计算耗时 | token 或音频秒数 | 速度 | 费用 | 证据 |
|---|---|---|---|---|---|---|---|---|
| L1 来源 ASR | reused；本次未调用 | | 0 | not_run | — | — | $0 新增 | 已复用源包，416 个锚点通过来源门禁 |
| L1 词级对齐（MFA） | reused；本次未运行 | | 0 | not_run | — | — | $0 新增 | 现有源包 |
| L1 英文机器评审 | reused；本次未运行 | | 0 | not_run | — | — | $0 新增 | 现有源包 |
| L2 初译 | gpt-6.1-sol（冻结策略；未调用） | high / default | 0 API | not_run；worker admission 0.163 秒 | 0 tokens | — | $0 估算 | summary.json；budget plan |
| L2 独立审核 | gpt-6.1-sol（冻结策略；未调用） | medium / default | 0 API | not_run | 0 tokens | — | $0 估算 | summary.json；budget plan |
| 文本质检（回译） | not_run | — | 0 | not_run | — | — | $0 新增 | 未进入 QC |
| L3 配音（TTS） | not_run | — | 0 | not_run | — | — | $0 新增 | 未启动 Spark 会话 |
| L3 回转写筛查（ASR） | not_run | — | 0 | not_run | — | — | $0 新增 | 未进入 L3 |
| 音频质检 | not_run | — | 0 | not_run | — | — | $0 新增 | 未进入 QC |
| L4 构建与发布 | not_run | — | 0 | not_run | — | — | $0 新增 | 公共目录未改动 |

已复制收据里出现的模型（自动汇总，按层归入上表）：

已复制的收据里没有模型身份；按各层的预算账本或收据手工填写。

## 错误

<!-- 每个错误一行：发现时机分预检／占用资源后／发布后；占用资源后才发现的，写要补的预检。 -->
| 层／阶段 | 现象 | 原因 | 发现时机 | 处理 | 回归测试 | 提交或 PR |
|---|---|---|---|---|---|---|
| L2 worker admission | `bound_budget_authorization_required`，job 失败 | deterministic_execute 的 CLI tick 未携带预算授权；无模型 API 调用 | worker 启动后、进入 provider 前 | 保留失败 job；确认账本 0 请求、0 未知；后续绑定预算授权并使用新 run/job 身份 | 配置修正后 run-start 预检通过；未改代码，未运行测试 | 本报告 PR |

## 可以改进的地方

<!-- 按速度、成本、预检、质量、流程分类；每条写预期收益、负责人和跟踪的 PR 或 backlog 条目。 -->
| 类别 | 改进 | 依据（本报告的数值或错误） | 预期收益 | 负责人 | 跟踪 |
|---|---|---|---|---|---|
| 预检／流程 | 通过 `drive()` 传入计划签发的 budget authorization，再启动 durable worker | 错误行；0 次 API 调用 | 避免产生无预算绑定的失败 job | 操作者 | 当前运行恢复步骤 |

## 实际覆盖范围

<!-- 按 L1–L4 写本轮执行、复用和未执行的部分。 -->
L1：复用既有、已批准的 Drive 源包与英文锚点。L2：仅 ES worker admission 失败；KO 未启动，两个候选均未生成。L3/L4：未运行、页面未变。旧中文文本和音频包不受影响。

## 遗留状态

<!-- Dev 上无引用的文件、未结束的 job hold、已用构建号、待删除的本地产物。 -->
保留原始失败 job `a7131092…17fea` 与 ES accounting，不删除或覆盖；无 active worker、无未结算 API attempt。后续使用新运行身份和新输出目录，旧预算计划不作为重试授权。

## 外部可见的变化

<!-- Dev 发布、TestFlight、受保护分支推送各自的证据；没做的验收写 not_run。 -->
not_run：没有页面部署、HTTP 回读、浏览器或设备验收。
