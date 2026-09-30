# 实验方向与退出门槛 / Experiment directions

[README 实测摘要](../README.md) · [App 设计](app-system-design.zh.md) · [后端工作流 DAG](backend-workflow-system-design.zh-en.md) · [执行环境](execution-environment-design.zh.md) · [文档索引](README.zh.md)

索引核查：2026-09-30，`dev@fc3e2fbc60b0fd2c5b59c64fcd515c465efc6b0b`。本页按问题组织仓库已有实验，不新增研究项目、不改正式模型 policy，也不重跑模型。每项链接保留原始语言、日期、输入与结论；退出门槛是进入后续验证或考虑晋升前的条件，不表示已经满足。

**状态词**：`已运行／未晋升` 是有范围明确的实验结果；`工具已实现／验收待补` 是代码存在但缺对应实测；`计划／未运行` 只表示已记录提案。正式流程虽有部分代码位于 `experiments/`，不能只按目录名判断成熟度；[配音系统](sermon-dubbing-system-design.zh.md)、[App](app-system-design.zh.md)与[正式 L3](formal-layer3-renderer.zh.md)以自己的生产合同为准。

## A. 英文来源、声学锚点与辅助理解

| 问题与冻结范围 | 状态与已有观察 | 证据 | 退出门槛 |
|---|---|---|---|
| Qwen ASR 与 Whisper 在同源本地英文识别上如何权衡？范围为 10 分钟 1 倍速回放及各自 runtime | 已运行／未形成全面质量排名；参考不是人工逐字 Gold，流式延迟口径不同 | [本地 ASR 基准](local-asr-benchmark.zh.md) | 人工源文 Gold、同口径延迟、ASR/翻译共存和现场麦克风验证齐备后才讨论替换 |
| Qwen 与 MFA 能否提供稳定词边界？60 秒、191 词同输入，并有分层扩样与句级映射 POC | 已运行／未证明声学精度优胜；MFA 本轮没有零时长词，结构通过不等于边界准确 | [对齐比较](../experiments/english-word-timeline-poc/ALIGNER-COMPARISON-2026-09-20.zh.md) · [扩样](../experiments/english-word-timeline-poc/EXPANDED-SENTENCE-ANCHOR-POC-2026-09-20.zh.md) | 人工词／句边界、缺口与截断审核；变更英文后重新绑定锚点及下游 |
| 音频是否改善 Gemini 断句／重音？两个 60 秒片段，文字、音文、静音、错配与重复共八次请求 | 已运行／只可作待回听候选；静音＋文字仍虚构声音描述，不能作为声学证据 | [Gemini prosody POC](../experiments/gemini-prosody-poc/README.md) | 本地静音/VAD、对齐与同文字不同读法负控，以及人工句界／重音标注 |
| 本地词间隔、F0、能量能否改善断句？复用同两段音频，逐步加入对齐间隔与声学特征 | 已运行／未晋升；部分输出结构失败，声学候选无人工准确率 | [本地断句](../experiments/local-prosody-poc/README.md) · [声学消融](../experiments/local-prosody-poc/ACOUSTIC-POC.md) | 人工听音参考、可靠 F0 覆盖、错稿／噪声／长停顿负例；不能以模型间一致代替真值 |
| Omni 能否区分读经、解释、画面与可听停顿？32 秒首样、12×15 秒消融及全篇 sidecar 工具 | 实验路径与夹具已实现；参考标注仍需人审，sidecar 不改正式字幕／译文／时间轴 | [Omni annotation 合同与入口](../experiments/omni-annotation-poc/README.zh.md) | 真实／静音／错配输入分别留证，人工 Gold 后才算语义区间或停顿准确率；完整源文缺口不能由标签补齐 |

## B. 文字模型、审核与实时分段

| 问题与冻结范围 | 状态与已有观察 | 证据 | 退出门槛 |
|---|---|---|---|
| 本地翻译模型的质量、速度、资源如何取舍？239 个冻结英文段、四模型同源文本比较 | 已运行／未替换周日默认；BLEU 和请求延迟不是人审语义或字幕共存证据 | [榜单](../data/benchmarks/live-sermon-translation-v1/runs/macbook-text-baselines/translation-only-leaderboard-20260903.md) · [基准合同](live-sermon-translation-benchmark.zh.md) | 独立双语语义审核、统一 runtime/量化说明、ASR 共存与资源上限通过 |
| 实时链路能否持续运行并恢复？20 分钟唯一音频以 1 倍速循环三轮、浏览器测试 MediaStream 注入 | 已运行／仅受控浏览器回放；60 分钟链路含真实模型，但没有经过扬声器、物理麦克风或教会调音台，实体手机与人审未完成 | [原始 60 分钟验收报告](../experiments/local-live-poc/benchmarks/SUNDAY_READINESS_20260904.zh.md) · [已校正传输说明](../experiments/local-live-poc/STREAMING.zh.md) | 真实声学输入、实体手机显示、人工语义与现场彩排分别留证；循环材料和浏览器注入不能替代物理输入验收 |
| 3 秒与 6 秒 ASR 最大窗口能否减少碎片？90 秒同源 replay | 已运行／保留 3 秒默认；6 秒有部分改善，也增加延迟并出现关系截断／增译 | [窗口 A/B](../experiments/local-live-poc/benchmarks/asr-window-ab-20260904.md) | 扩大冻结样本、语义审核、屏幕呈现延迟与现场输入验证；字幕事件不等于屏幕可读 |
| 合并 translation units 是否更完整？42 个变化单元、126 次 MiLMMT 请求 | 已运行／保留 legacy；有修复也有否定、因果、经文退化 | [单元 A/B](../experiments/local-live-poc/benchmarks/translation-unit-ab-20260904.md) | 风险语义不得退化，并在同输入上验证端到端显示延迟和恢复 |
| Astra/Sol 的初译与独立复核如何分工？韩语 14 单元植错与 45 单元／44 组扩样、Gemini 裁判 | 已运行／保留 Astra 初译 → Sol 逐组复核；支持逐组审核价值，不能证明某 reviewer 全面更好 | [Layer 2 A/B](reports/20260923-layer2-astra-sol-gemini-ab.zh.md) · [正式 policy](target-language-astra-sol-production.zh.md) | 更广语料与母语审核、完整用量/延迟收据；实验裁判不成为常规第三遍 gate |
| 初译成本能否降低而不损质量？三语 178 秒片段，Astra→Sol、Sol→Sol、Luna→Sol 对照 | 已运行／未晋升；机器通过和估算费用有差异，Sol→Sol 仍需母语盲评 | [9 月 28 日结果](reports/20260928-model-production-ab-results.zh.md) · [盲评表](reports/20260928-model-production-ab-blind-review.zh.md) | 相同输入/policy、母语非劣效审核、返工成本与整篇扩样；机器 pass 不等于人工批准 |
| 中文初译 prompt/model 改写是否更划算？首轮 8 条、第二轮 24 条、双机器裁判及反序复判 | 已运行／保留正式策略；只有 7/24 条稳定一致，且同时改模型与 prompt，不能证明非劣效 | [首轮](../experiments/prompt-model-ab-20260928/README.zh.md) · [第二轮](../experiments/prompt-model-ab-20260928/round2.zh.md) | 完成源音频核对和独立人审，拆开混杂变量，报告失败和不确定结论 |
| 领域后训练能否改进周日神学术语？MiLMMT v4.1 Q5/MLX 集成及 45 秒原声 replay | 已运行集成／神学质量门未过；17 条英文与中文 final 不是与默认 Q8 的同条件质量 A/B | [后训练计划](milmmt-sermon-post-training-plan.zh.md) · [v4.1 集成报告](../experiments/local-live-poc/benchmarks/MILMMT_V41_POC_INTEGRATION_20260905.zh.md) | sermon 级 train/dev/test 隔离、人工 Gold、神学质量与延迟/资源门；保持实验选择和分享限制直到明确晋升 |

## C. 声音、韵律与同步

| 问题与冻结范围 | 状态与已有观察 | 证据 | 退出门槛 |
|---|---|---|---|
| 授权 speaker 训练是否改善 Qwen Base 样音？同中文稿、不同声音条件的早期探针 | 已运行；已认可样片只绑定相应 checkpoint，不能推广为每周整篇验收；参考输入与 speaker slot 同时变化 | [授权声音实验](../experiments/sermon-dubbing-poc/AUTHORIZED_VOICE_REPORT_20260905.zh.md) · [讲员库](../experiments/sermon-dubbing-poc/SPEAKER_BANK_AND_WEEKLY_FLOW_REPORT_20260905.zh.md) | 授权来源、跨讲道样本、分维度听感与正式整轨听审；不把回转写差异当真实错误率 |
| pace 指令、整句生成、短语装配能否同步？六句英文 40.88 秒窗口及韩／中文变体 | 已运行／未证明同步达标；接近总时长不等于局部自然度，中文拼接曾被指出不自然 | [多语言韵律 POC](multilingual-prosody-poc.zh.md) | 源语声学停顿、目标语内容覆盖与人耳自然度，逐处同步且保持自然语速合同 |
| AuK 是否适合直接合成或速度后处理？六句韩语 Qwen 基线，两个 challenger 单元 | 已运行／不替换 Qwen，不注册当前后处理器；时长精确但内容退化，两个盲听偏好分裂 | [AuK 结果](../experiments/layer3-auk-poc/RESULTS-2026-09-22.zh.md) | 先过内容，再测独立速度变量、词覆盖与人耳；需独立 adapter/schema，不能冒充自然无拉伸 v1 |
| VoxCPM2、MOSS 是否适合克隆或控时？19 个短句/四语 smoke，另有中文长段 A/B | 已运行／继续 Qwen SFT；VoxCPM2 短句有偏好、长段 Qwen 获偏好；MOSS 无人耳通过样本 | [VoxCPM2/MOSS 结果](../experiments/layer3-voxcpm2-moss-poc/RESULTS-2026-09-22.zh.md) | 先解决重复音频听评冲突、分长度/维度扩样；MOSS 改善自然度后再考虑候选，其他语种单独听审 |

## D. 执行、资源与设备路径

| 问题与冻结范围 | 状态与已有观察 | 证据 | 退出门槛 |
|---|---|---|---|
| 本地 TTS/ASR 共存能否减少等待？64 GiB MacBook、一句 TTS 与历史 A.wav | 已运行／仅能力探针；推理区间重叠 1.69 秒，缓存/加载顺序混杂，不能推算整篇提速 | [并发报告与紧凑 JSON](../experiments/local-model-concurrency-poc/README.zh.md) | 交换顺序、多轮、内存压力/失败恢复及质量对照；遵守现有模型许可，不宣称 GPU kernel 并行 |
| Sol/Luna 能否安全选择 Supervisor 下一步？12 个冻结状态，模型只作 shadow 决策 | 已运行／保留确定性校验；动作正确不等于完整状态通过，未改变生产权限 | [Supervisor 与生产模型结果](reports/20260928-model-production-ab-results.zh.md) · [冻结输入](reports/20260928-model-production-ab-inputs.json) | 完整 schema、所有阻塞/恢复条件、总调度成本；不得用模型自然语言覆盖固定门禁 |
| DeepSeek Harness 或 Terra 是否减少调度开销？同 CUV 任务/缓存的 A/B/C 方案 | **计划／未运行**；Spark 云 API 阶段与后续本地模型阶段分开，尚未证明 ARM64 部署或模型兼容 | [既有调度实验提案](scheduler-harness-ab-experiment.zh.md) | 冻结 runtime、模型、预算与输入；全部关键阻塞用例通过，费用/延迟/人工介入可比，另行决定晋升 |
| 手机媒体回路的网络/播放队列是否可靠？单机及 admin/user、MacBook/DGX 顺序探针 | **工具已实现／手机实测待独立证据**；WS/WSS + WebAudio，没有 ASR、翻译、TTS，也不是 WebRTC/SFU | [media probe 合同](../experiments/mobile-live-translation/media-probe/README.zh.md) | 实际手机/网络/声学输出、丢帧和恢复证据分别记录；client-reported 下拉选项不能证明真机 |

## 采用结果的共同边界

每项退出须绑定实际输入 hash、模型及 prompt/revision、runtime、初始缓存、测试范围、结果与 reviewer。需要新运行时，重新确认该实验的预算和权限；本页不是运行授权。留存失败与不确定结果，未达门槛继续标记 experiment 或停止。

实验只能向对应层提出候选：L1 候选不能自签来源准确，L2 机器评分不能自签人审，L3 解码/ASR/音色相似度不能自签整轨听审，L4 浏览器或 replay 不能自签现场。进入生产后仍走[完整业务 DAG](backend-workflow-system-design.zh-en.md)，包括 text-only 的显式 L3 包。PR164 的 strict-verifier 是[计划中的工程合同](backend-workflow-system-design.zh-en.md#生成独立审核门禁与新修订--generation-review-gate-and-new-revisions)，不是已经运行的模型质量实验。
