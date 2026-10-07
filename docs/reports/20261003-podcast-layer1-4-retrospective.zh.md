# 播客 Layer 1–4 制作流程复盘

记录日期：2026-10-03。对象为《如果我有更多时间 · 耶稣配得》（`if-i-had-more-time-jesus-is-worthy`）。这次从已有英文转写、对齐和被机器裁判拒绝的锚点候选续跑，完成中文、西班牙文、韩文制作及 Firebase Dev App 页面交付。它暴露了源身份选择、政策与提示词一致性、双讲员合同、运行环境和 App 交付验收方面的缺口。

本报告依据本地保留的源包、模型 accounting、逐单元配音收据、ASR 结果、Firebase 部署收据和本轮执行记录复核。证据目录 `artifacts/podcasts/if-i-had-more-time-jesus-is-worthy/` 被 Git 忽略；下文证据路径相对此目录。报告只提交汇总，不把媒体、模型回复、私钥或凭据带入 PR。

## 交付状态

| 层 | 已完成的实际结果 | 状态边界 |
| --- | --- | --- |
| Layer 1 | 修正源文并建立匹配的英文源包、锚点和说话人路由；826 句、839 单元；修订后机器裁判 826/826 通过，并保留人工源审收据 | 声学匿名标签或线上模型返回的姓名不能单独建立真实人物身份 |
| Layer 2 | 三语均完成 Astra 初译、Sol 独立审查和语言插件准入；中文全文人工批准；ES/KO 依用户指令记录全文人工审核豁免 | ES/KO `humanApproval=false`，不能把审核豁免标为人工通过 |
| Layer 3 | 各语种 839 单元双讲员配音、合成音轨、目标音轨字幕；全覆盖 ASR 筛查及人工听审/争议裁定收据 | ASR 原始 `requires_review` 记录保留，人工裁定是另一个证据；没有视频口型同步要求 |
| Layer 4 | 三语进入 Firebase Dev App 的页面选择器、内容和播放器；完成资源哈希、HTTP Range、浏览器读回 | 仍为 Dev 候选；生产发布、真机验收与现场验收未由这些证据完成 |

三语 Dev 页：[中文](https://ai-for-god-sermon-audio-dev.web.app/?week=if-i-had-more-time-jesus-is-worthy&contentLang=zh-Hans)、[西班牙文](https://ai-for-god-sermon-audio-dev.web.app/?week=if-i-had-more-time-jesus-is-worthy&contentLang=es)、[韩文](https://ai-for-god-sermon-audio-dev.web.app/?week=if-i-had-more-time-jesus-is-worthy&contentLang=ko)。iOS Beta 分类界面、签名和 TestFlight 准备另见[分类与 Beta 复盘](20261003-content-category-beta-retrospective.zh.md)。

## Layer 1：源文和边界没有一次冻结到位

| 问题与影响 | 本轮处理及证据 | 后续改进 |
| --- | --- | --- |
| 原 8 秒切分把谓语、宾语或节目名分开，机器裁判 807/826 通过、19 处高风险失败。仅增大长度上限的候选仍失败，并改变了大量边界，扩大了复核范围。 | 保留原候选，采用确定性边界覆盖修订；`sentence-interpretation-v2-targeted-19/` 及对应源审收据。短句 `Not at all.` 的过短 MFA 估计另行听审；没有改写旧机器失败结果。 | 切分先保证完整句意和说话人轮次；定向覆盖先于全局参数调整。 |
| pyannote 初始受模型访问权限阻挡；Spark 基础环境没有 Torch/pyannote，CPU 尝试迟迟未产出；所谓 15/45 秒探针实际上处理了全文件。 | 确认依赖故障后使用 Mac MPS；最终保存 660 段普通 RTTM、666 段 exclusive RTTM、两匿名标签。再用线上带授权声样的 diarization 与文字假设交叉核对，提交人工映射。`diarization/pyannote-community-1-raw.json`、`speaker-hypotheses/online-speaker-sentence-overlap-v1.json`。 | 先做确实裁剪过的短音频能力检查，并验证输出范围；姓名假设、声学聚类和人工身份确认分别记录。 |
| 翻译到 `0-u083` 才发现英文将 `quote-unquote secular` 误写为 `Korah, quote, secular`。改动源身份，使已经请求的 88 组中文不能直接充当新源的候选。 | 用户回听裁定；仅该段重新 MFA，保留其他音频/对齐和原始 ASR；重建完整源身份、锚点、审查和收据。`pipeline/source-revision-quote-unquote/`。 | 在批量翻译前审查低置信专名、引语和独立转录冲突；源文争议必须回到原音频解决。 |

最终实际使用的源包是 `pipeline/source-revision-quote-unquote/english-source-package.json`，canonical JSON SHA 为 `de074b675fcbea73b4ebaeb3f7a78f56e955d4cf94c863f0d679a86a2bff30e3`；锚点 canonical SHA 为 `f9a0a8246c3c16a314a1c329c518bf77d3aaf39b6b02a0ac0c35fa5073a751df`。目录名中的 `approved` 或文件修改时间不能替代这些身份。

## Layer 2：已批准的政策与实际执行提示词发生冲突

| 问题与影响 | 本轮处理及证据 | 后续改进 |
| --- | --- | --- |
| 通用提示要求所有直接经文引用使用固定译本，而已批准政策仅对启示录 5:9 的限定片段采用精确引文，其他经文讨论作转述。Sol 在 `1-u076`、`1-u077`、`2-u131` 等处报告归属/译本不确定，造成多次停跑。 | 将批准范围写进执行提示词，并按新的 policy/prompt 身份修订运行；`operator-review/scripture-policy-decision-group-0713.md`、中文 `full-run-r6` 至 `full-run-r12`。 | 冻结前让政策、Astra/Sol 提示词和语言插件共同处理已知引文/转述例子；政策变更不能只改说明文件。 |
| 旧语言插件绑定另一篇证道，不能直接适用于本播客；术语样本检查还曾把 reviewer 布尔值当失败。中文 r10 模型阶段完成后，数字/序数词面和歌名规则导致 26 组被插件拒绝；韩文插件把引号内英文 mantra 的忠实译法也当作禁用称谓。 | 建立本源范围插件，修订术语/歌名规则；保留失败回复，按各次源/政策身份完成必要重跑和定向修复。中文 `full-run-r10/language-review-receipt.json` 记录 813 pass/26 fail；韩文 `translation-0-u078` 修订和收据保留。 | 规则检查应区分叙述、引语、专名和转述；接口返回值类型要与检查器一致。 |
| 默认并发 3 与用户要求的 24 不一致；若直接从头再跑，会浪费已完成模型回复。 | 中断旧运行，冻结 24-worker 身份；中文 r12 在请求 payload 完全匹配时复用 602 组，完成剩余 237 组。`full-run-r12/accounting/summary.json`。 | 并发作为运行参数显式检查；缓存以请求内容、模型、源和政策身份核验，不能把缓存回放当完整生成性能。 |
| ES/KO 初轮选用了旧 `targeted-19-approved` 包：source SHA `8980bbb3…`、anchor SHA `18259b0e…`，与已经纠正的正式 `de074b67…` / `f9a0a824…` 不同。这是可以在模型请求前避免的源包选择错误。 | 早期 ES `model-run-r1` 和 KO `model-run-r1..r4` 保留作历史记录；重新建立 `source-refresh-r2/` 下的政策、运行、候选和收据。错源五轮记录共 3362 次 API 尝试、累计 runner 耗时约 553.6 秒，不能作为最终候选或最终源的性能。 | 付费模型请求前从运行清单和下游绑定核对身份；不要手选目录名含 approved 的包。并列源版本必须提示不一致。 |
| 用户要求 ES/KO 跳过人工全文审核，但原合同只接受人工批准。直接沿用批准字段会制造错误审核状态。 | 新建独立 waiver 收据，保留 `humanApproval=false`、`releaseEligible=false`；机器审查与音轨听审继续执行。`layer2-formal-prep/{es,ko}/source-refresh-r2/user-review-waiver-r2.json`。 | 审核豁免应从任务入口贯穿候选、音轨与 UI；发布准入需明确识别该状态。 |

## Layer 3：双讲员功能和可运行环境在生产中补齐

| 问题与影响 | 本轮处理及证据 | 后续改进 |
| --- | --- | --- |
| 现有正式 speech job、renderer 和 audio package 只表达一个 adapter/checkpoint；`batch=8` 不能自动成为 Eric/Steve 双人配音。 | 版本化增加逐单元说话人路由、双 worker manifest、逐单元身份收据及播客 audio package。每语种 Eric 551、Steve 288 单元，各 worker batch=8，按源轮次合成。`layer3-dual-worker-runtime-v1/` 和 `layer3-dual-worker-prep/{es,ko}-voice-extension-r2/`。 | 大规模 TTS 前完成两讲员短样本的路由、覆盖与合并验证；家族支持某语言不等于微调讲员 checkpoint 已验收。 |
| NGC PyTorch/torchaudio 组合不匹配；ASR 镜像第一次因缺少 `dynet_config` 导入失败。 | 在隔离镜像中固定 Torch/torchaudio 2.10.0 CUDA 13.0；ASR 增加匹配的 DyNet 依赖后导入并实际运行。保留 Dockerfile、运行镜像与模型修订身份。 | 维护经 GB10 实际推理验证的固定运行环境；先验证 import 和短推理，再提交整批。 |
| 同机常驻模型占用资源；仅观察 GPU 空闲不能证明资源窗口已独占。 | 中文运行没有停止原服务；后续用户明确要求优先 ES/KO 配音，才停止指定 llama/ImageLab/ComfyUI 工作负载，随后顺序执行 TTS 与 ASR。 | 将资源检查、暂停授权和恢复路径提前落实；目前不能从这两段不同条件的运行推断独占带来的性能增益。 |
| 回转写误把专名/同音字等标成不一致，例如“尼禄”转成“麋鹿”。中文 38、ES 53、KO 45 单元被标为待审。 | 完成 839/839 ASR 覆盖，保留原始结果，通过独立人工听审与逐单元裁定解除交付争议。`asr-screen-v1/` 和各语种 audio human review receipt。 | 相似度用于生成复核队列；不得把 ASR 差异直接等同配音错误，也不得将人工裁定改写为机器通过。 |
| ES/KO 候选包曾把 ASR model 与 revision 重复拼接；TTS render receipt 虽绑定 checkpoint/text/audio，却没有完整 runtime image 和 Python/Torch/qwen-tts 版本字段。 | candidate-v3 将 ASR `model` 与 `modelRevision` 分列；ASR runtime 的版本可核对。ES/KO TTS 的环境身份缺口仍存在，不能仅靠中文 Dockerfile 补成完整收据。 | 对每个语种/运行写入执行 image digest、包版本、代码 hash 与权重 hash；包构建复核字段语义。 |

播客是 audio-only。最终字幕和 schedule 使用目标音轨累计时间，保留自然语速和完整句子，没有压缩中文/ES/KO 去匹配英语句长。三语音轨长度分别为 3804.68、4112.92、4609.72 秒；这些是媒体长度，不是生成耗时。

## Layer 4：第一次部署没有完成用户所说的 App 页面交付

第一次 Hosting 部署上传了音频、内容、字幕和 v2/v3 目录，也完成 HTTP 与哈希检查，却没有把该候选接入 App 的“本期与往期”选择器。我把资源部署进度说成页面交付完成，验收范围不足。用户指出实际页面入口后，才补接 reader、选择器、播放元数据和字幕。这是本轮需要纠正的交付判断。

| 问题与影响 | 本轮处理及证据 | 后续改进 |
| --- | --- | --- |
| 标准 Layer 4 builder 要求旧版单讲员音轨包及三语输入，不能直接消费本轮播客包；iOS/catalog reader 对 v3、候选状态及 WAV 路径也有不同限制。 | 增加播客 Dev 适配，保留原包哈希；不降级已有 v3 页面。中文 App-page 部署收据为 `deployment-bundle-v2/deployment-receipt-v2.json`。 | 在 L1–L3 批量运行前先核对目标 reader 真正消费的 package/catalog、状态、音频格式和 URL。 |
| URL 可返回 200、目录含页面，不代表 App 列表可选和播放器可用。 | 中文浏览器收据确认 selector 可见、839 cues、播放推进至 12 秒后暂停；ES/KO 收据确认选择、audio ready 和审核状态标注。 | 发布完成条件直接使用用户的 App 路径：列表进入 → 页面打开 → 音频起播 → 字幕推进 → 语言切换。 |
| ES/KO 文稿只有机器审查，UI 必须披露豁免；只显示“完成”会掩盖生产准入差异。 | Dev UI 显示“DEV 候选 · 文稿审核豁免 · 整篇配音”，音轨保留人工听审状态。`deployment-bundle-v4/deployment-receipt-v3.json`。 | Dev 与正式 release 状态、设备与现场验收分别记录；不要用一个总完成标签覆盖多个状态。 |

## 时间与日志的证据边界

从用户于 `2026-10-02 22:06:03Z` 指示续跑，到最终 ES/KO Dev 页面修订的 Hosting releaseTime `2026-10-03 15:47:36Z`，墙钟跨度约 **17 小时 41 分 33 秒**。起点已有转写/对齐，期间包含模型、人工审查、修改实现、部署与 Spark 实验准备，不能用作冷启动端到端性能。

第一次仅资源部署的收据核对时间为 `07:09:28Z`，中文 App-reader 接入部署 releaseTime 为 `13:15:30Z`，相隔约 **6 小时 6 分 2 秒**。这个跨度含对话停顿和独立工作；它说明交付边界直到后续修订才满足，不能算成 Hosting 部署耗时。

现有机器时间和后续复盘均应同时注明：源/政策/插件身份、实际新 API 请求数、缓存命中范围、失败尝试、人工等待及 reader 验收范围。仅从最终成功运行的耗时计算“整篇速度”，会漏掉源纠正和合同返工；仅累加各目录的 839 组结果，又会重复计算缓存。

Layer 2 accounting 中可核对的运行片段如下。累计是列出的各轮 `wallSeconds` 相加，不含轮与轮之间修改、人工确认或停顿；`apiAttempts` 包含重试，不能当作独立翻译组数。

| 中文运行 | 并发 | runner 耗时 | API attempts | accounting 状态 / 后续边界 |
| --- | ---: | ---: | ---: | --- |
| r5 | 3 | 240.156 秒 | 176 | failed；尚未产出全量候选 |
| r6 | 3 | 985.194 秒 | 742 | failed |
| r7 | 3 | 15.072 秒 | 2 | failed；定向修订 |
| r8 | 3 | 2.129 秒 | 0 | failed；缓存回放在 require 校验阶段拒绝，具体 message 缺失，没有新 API 请求 |
| r9 | 3 | 893.192 秒 | 702 | failed |
| r10 | 3 | 2079.681 秒 | 1678 | 模型阶段 completed；之后插件 26 组拒绝 |
| r11 | 3 | 1523.869 秒 | 1204 | failed/未完成；KeyboardInterrupt，保留 602 组结果；中断主体/原因未记录 |
| r12 | 24 | 79.150 秒 | 474 | completed；复用 602 组，补齐 237 组 |

这八轮 runner 记录合计 **5818.443 秒（约 96 分 58 秒）**、**4978 次 API attempts**。其中包含旧源、政策修订、失败与重跑，不能称为一个固定源/固定政策的生产基准。r12 的持久化跨运行复用没有反映在 accounting `cacheHits` 字段（该字段为 0）；602 组复用须依据分组结果和剩余请求记录确认。

| 运行范围 | runner 耗时 | API attempts | 实际工作和限制 |
| --- | ---: | ---: | --- |
| 中文 `full-run-r12` | 79.150 秒 | 474 | 602 组复用；237 组实际新增 Astra/Sol 请求。不是 839 组从零生成耗时。 |
| ES 初轮旧源 r1 | 241.429 秒 | 1678 | 839 组双角色调用，后因源身份不一致被保留为历史结果。 |
| KO 初轮旧源 r1–r4 | 合计 312.210 秒 | 合计 1684 | 包括语义/插件定向修订；最终仍属于旧源。 |
| ES 正确源 `source-refresh-r2/model-run-r1..r4` | 合计 269.528 秒 | 合计 1684 | 经不完整句 `0-u276`（“And Him”）及 `2-u087`（“Let's”）的修订，最终完成 839 组。 |
| KO 正确源 `source-refresh-r2/model-run-r1..r2` | 合计 282.449 秒 | 合计 1680 | 全量 839 组双角色调用及一个单元的双角色定向修订。 |

以上 ES/KO 运行均记录 workers/maxInFlightGroups=24；两语种依次执行，不能把结果解释成两个完整语种同时 24 并发。accounting 还保留 `unknownCostAttempts`；usage receipt 完整不代表价格完整，本报告不把 `knownEstimatedUsd` 当实际账单。

Layer 3 的逐单元 render receipt 有 `renderSeconds`，同一 batch 各单元都从模型调用开始计时，随着音频写入、哈希核对而递增。直接相加会把一次批处理重复计算。按 `(workerId, batchSeed)` 分组，每批取最大值后，能核对以下累计值：

| 语种 | Eric 69 批 | Steve 36 批 | 两 worker 调用时间之和 | 范围 |
| --- | ---: | ---: | ---: | --- |
| zh-Hans | 916.37 秒 | 583.50 秒 | 1499.88 秒 | 模型调用开始至各批末单元收据计时点的累计值 |
| es | 919.07 秒 | 554.65 秒 | 1473.72 秒 | 同上 |
| ko | 1014.90 秒 | 587.40 秒 | 1602.30 秒 | 同上 |

每语种均为 105 批（104 个八单元批次、1 个七单元尾批）。表中含模型生成、音频写入和哈希计算，**不是纯模型推理时长**。两个 worker 并发，累计值有重叠，**也不是整个运行的墙钟耗时**；未包含模型启动、镜像构建、传输、拼接和 ASR。ASR runtime/receipt 没有起止或 elapsed 字段；听审 `reviewedAt` 只有决策时间。现有证据无法精确补出这些阶段的执行或审听时长，不能用文件修改时间推算。

## 2026-10-03 逐轮日志审计补充

### 覆盖范围与每轮失败原因

本次读取 20 个 accounting JSONL、235,042 条事件，按 event/attempt/response 身份去重；22 次运行包含 19 次 Layer 2 与 3 次 pipeline。再核对账本之外的源句模型响应、术语 POC、diarization、逐单元 TTS/ASR 和部署收据。汇总保存在忽略目录 `log-audit-20261003/audit-summary.json`。早期中文 r1–r4 缺少完整运行及原始响应账本；42 个 speaker-hypothesis batch 也没有可核对的响应 ID，不能从后续缓存推算其真实请求数、时间或费用。

中文逐轮原因补充：r5 在 `0-u083` 的专名/引语源文不确定；r6 的 `1-u076`/`1-u077` 及 r7 的缓存组因经文逐字文案未获准而阻断；r9 的 `2-u131` 同属经文政策问题。r10 的 1678 次请求完成，独立语言插件另有 26/839 拒绝，不能归为 API 失败。r11 在 `accounting/operations.log:13258` 留下 `KeyboardInterrupt`，中断主体及原因未知。r8 只有缓存校验异常 stack，缺具体异常 message，不能认定为缓存身份、网络或模型质量问题。

| ES/KO 运行 | wallSeconds | 新 API attempts | 逐轮结果与证据边界 |
| --- | ---: | ---: | --- |
| ES 旧源 r1 | 241.429 | 1678 | runner completed，但 source/anchor 不是最终 canonical identity |
| KO 旧源 r1 | 251.573 | 1532 | `2-u157` 的 them 指代不清，Sol 语义审核拒绝 |
| KO 旧源 r2 | 32.647 | 112 | 同组修订仍有 referent uncertainty，失败 |
| KO 旧源 r3 | 17.510 | 38 | runner completed，仍绑定旧源 |
| KO 旧源 r4 | 10.480 | 2 | 单组修订 completed，仍绑定旧源 |
| ES 换源 r1 | 99.742 | 642 | `0-u276` 的 And Him 缺独立完整意义，Sol 拒绝 |
| ES 换源 r2 | 121.228 | 774 | `2-u087` 的 Let's 悬空；译文增加含义，Sol 拒绝 |
| ES 换源 r3 | 1.876 | 0 | 缓存组在 require 校验失败；异常 message 缺失，具体原因 unknown |
| ES 换源 r4 | 46.682 | 268 | 有界修订 completed |
| KO 换源 r1 | 274.865 | 1678 | 839 组 completed |
| KO 换源 r2 | 7.584 | 2 | 最后单组修订 completed |

三次 pipeline 依次 failed 196.525 秒/3 次 transcribe 请求、failed 14.990 秒/0 新请求、completed 58.099 秒/0 新请求；前两次异常在 alignment 路径。19 次 Layer 2 的 wallSeconds 累计为 **6924.057 秒**，不是跨层关键路径，也不含修改和人工等待。上述已记账 API attempt 全部为 completed；内容/插件准入失败、中断与 provider 请求失败须分列。

### DAG 的实际作用与缺口

本轮有 66,296 个 stage、60,808 条依赖边，未解析引用为 0；但跨 run、跨 workflow、跨文件边均为 **0**，非空 `decisionId` 为 **0**。这些证明 producer 局部依赖记录可解析，配合实际缓存恢复及 Layer 3 输入/输出 hash 校验，提供了局部恢复证据；不证明统一 Layer 1–4 scheduler 已接管或完整关键路径可计算。ES/KO 旧源五轮 3362 次调用后才人工换源，说明当前 canonical revision 的跨层准入仍需 R01 与既有 DAG 任务落实。既有其他运行的跨进程/mock DAG 证据保留，但不能外推到本播客。

Layer 3 三语共 2517 单元、315 个生产 batch，各语种 ASR 覆盖 839/839，核对未发现 text/audio hash 不匹配；这些是本轮产物绑定证据。`renderSeconds` 从 batch 模型调用前累积到各 unit WAV 写入及 hash 完成后；每 batch 取最大值只能避免重复相加，不能作为纯推理或整个 job wall time。ASR 起止/elapsed 仍缺测。Layer 4 的 v2 部署收据被复制到 v3/v4 目录，复制不增加部署次数；资源 HTTP、真实 App-reader 行为、设备/现场验收仍分别记录。

### Luna usage、TPS 与 API 次数

主 Codex 会话原生 usage 按 response ID 去重，范围为 `2026-10-02 22:06:03Z` 至 `2026-10-03 15:47:37Z`，配置模型为 `gpt-6-luna`；18 个有 usage 的 root turn、2862 个模型响应。usage 小计与该窗口末累计计数一致。此口径含工程及人工调度，不含全部子 Agent 遥测；它与业务账本的 response ID 交集为 0。这里只提交脱敏汇总，不提交原始会话、用户消息或工具正文。

| 指标 | 实测值及限制 |
| --- | --- |
| Luna input tokens | 393969205；其中 cached input 387880704（98.45%），non-cached input 6088501；上下文重复计入各请求，不是独立文本规模 |
| Luna output tokens | 1401366；reasoning 764835 已包含在输出中，不重复相加 |
| Luna 窗口平均输出率 | 1401366 / 63694 秒 = 22.00 token/s；包含工程、工具、人工及生产等待，不能称纯推理或纯调度 TPS |
| 纯生成 TPS / TTFT / 纯调度耗时 | unknown：缺 request-start/first-token/生成结束和工程/生产用途关联；不以相邻日志时间代替请求时长 |
| 业务账本 attempts | 11707 = Astra 5852 + Sol 5852 + gpt-transcribe 3；含各失败修订轮次，实际账单未核对 |
| 账本外额外保留收据 | 234 = source judge 224（四轮各 56）+ terminology POC 6 + diarize 3 + Whisper 1 |
| 已知业务请求下限 | 11941；不含无法核对的早期轮次或其他作用域；账本范围早于上述 Luna 窗口，不使用该窗口计算业务 TPS |
| 本播客 Agents API HTTP POST/GET | unknown：未找到绑定本播客的 session/HTTP 收据；未找到不等于 0；2862 个 native 模型响应不等于 HTTP 操作次数 |

### Findings 与既有 backlog 的关系

下列 F01–F06 仅为本报告证据编号，沿现有工程 ID 补充，不新建 Epic。三项新增集成/计量证据与一个真实中断夹具，与已写过的修复要求分别标识；[backlog 验收补充](../backlog.zh.md#podcast-log-audit-followup-20261003)记录待交付及关闭条件。

| Finding | 事实、影响与本轮证据 | 与既有要求的关系 |
| --- | --- | --- |
| F01 / P1 | 审计快照 `dev@1dfa9dd004f445471c7d5d97ece7ece83e03a6fe` 及 PR 准备基线 `dev@d31cdc2aac87c5358a80b40e55cf908af4279302` 均没有 `scripts/render_podcast_dual_worker.py`、`scripts/build_podcast_audio_package.py`、`schemas/sermon-podcast-audio-package-v2.schema.json`；实际执行代码仍在 `codex/stage2-activation-packet@e8218e7`。仅合并复盘不建立正式 producer 能力。 | 新集成事实；补 `DEV-L3-001/004`、`DEV-DIAG-017` 的合并/迁移/正式入口验收，落实 R05/R06 |
| F02 / P1 | ES 正确源 And Him / Let's，以及 KO 旧源 them 的具体 `semanticReview` 失败；目标语失败本身不能断言 Layer 1 切分错误。 | And Him / Let's 已在 R04；补 them、上下文受影响范围与错误译文对照到 `DEV-L1-001`/`DEV-L2-001`，不重复称为完全遗漏 |
| F03 / P1 | 中文 r11 `KeyboardInterrupt` 在 1204 个已完成请求后被总状态记为 failed；不能算 provider/content/schema 失败，也不能推定取消主体。ES 换源 r3、中文 r8 的 require 异常 message 未保留。 | 既有 `RQC-04`/`SPD6-LOG-05` 的真实中断及缺失诊断夹具补充；要求 execution/review/admission 分列并保留安全异常原因 |
| F04 / P1 | 234 条已保留调用收据不在 business accounting；账本 11707 不能冒充完整制作调用总数。 | 新覆盖证据；补 `DEV-TRACK-001`/`SPD6-LOG-03` 的调用类别接线、去重与缺测口径；估算不当账单 |
| F05 / P1 | native Luna 2862 个响应与 22.00 窗口平均输出率可核对，但 request-start/first-token、用途及 HTTP 操作分母缺失。 | `SPD6-ARCH-04` 已要求工程/生产分离；新增真实计数及计时/分母验收细节归 `SPD6-LOG-04`/`DEV-SPD-005` |
| F06 / P2 | ASR 全覆盖/hash 一致不补足时间；batch unit 累计计时不等于推理或 job wall；旧部署收据复制不能增加部署计数。 | TTS/ASR span 已在 R10，App 收据已在 R07；补真实计数/复制夹具到 `DEV-TRACK-001`/`SPD6-LOG-02/05`，属于待落实要求 |

## 修复意见与实施顺序

以下为待实施建议。已有的哈希校验、双 worker、审核收据和 Dev reader 应复用；本次文档更新不代表建议已经完成开发。P1 表示下一轮整篇制作前优先闭合，P2 表示随后完善复现、恢复和观测。每项都应单独留下变更与验收证据，不要求重新执行全部历史制作。

| 编号 / 优先级 | 修复对象 | 具体交付 | 验收标准 |
| --- | --- | --- | --- |
| R01 / P1 | 所有层的源包选择 | 一份不可变运行清单，声明 run/revision、源媒体、当前批准源包、anchor、逐 locale policy/plugin/candidate 及审核状态；哈希字段明确区分文件字节与 canonical JSON。Layer 2/3/4 从清单取输入，CLI 手工路径也必须与清单一致。当前 revision 指针由受保护的状态转换更新，不按目录名或 mtime 选“最新”。 | 用本次两个 approved 包复现：旧 source/anchor/policy 即使彼此匹配，也因不匹配运行清单而在首个 API/GPU 请求前拒绝；三个 locale 读到同一当前源身份。清单切换后旧派生包保持可审计且不再被误准入。 |
| R02 / P1 | Layer 1 源争议与切分 | 在冻结前汇总已有独立转录冲突、异常专名、引语和跨句边界，生成含前后文的有限音频复核队列；先定向修边界，确有必要才改全局切分参数。裁定产生新 revision/diff，保留原 ASR、原锚点和未变音频/对齐。 | `quote-unquote secular` 进入源复核队列；19 处边界修复给出准确 changed unit 清单。确认不变的窗口/源审不重复索取批准；源身份变化按现行合同使各 locale 下游重新绑定。声学匿名聚类和人工姓名映射仍分列。 |
| R03 / P1 | Layer 2 政策、提示词和插件 | 从同一冻结政策生成 Astra 与 Sol 的经文指令及插件约束，显式表示精确引文范围、译本、转述、术语/歌名和 review waiver；冻结可核对的实际请求 payload/hash。插件接口以 schema 明确结果类型。 | 覆盖 `1-u076`、`1-u077`、`2-u116`、`2-u131`：批准范围内精确引文合规，其他讨论遵循批准的转述规则，角色间没有矛盾指令；布尔值/字符串类型不再被错误判读。保持 Astra→Sol，不增加常规第三轮模型关口。 |
| R04 / P1 | Layer 2 语言规则与定向修复 | 数字规则区分数字、序数和习语，称谓规则区分叙述与引号内原话，专名/歌名规则绑定 source unit 上下文。准入失败输出 group/check/evidence 和 repair brief；修复后走规定译者、审查者、插件及准入链。 | 回归 r10 的 26 组插件拒绝、韩文 `0-u078`、ES `0-u276`/`2-u087` 等真实案例，并保留应被拒绝的错误译文对照；修复只派发失败及受上下文影响的组。改变源/政策/请求身份时准确扩大重跑范围。 |
| R05 / P1 | 跨层合同与 App 兼容性 | 提供统一的制作预检，列明 source/locale、speaker route、job/audio/release/catalog schema、音频格式、审核状态和目标 reader 能力；验证当前包的连续消费关系，再用已准入的短双讲员样本走 Dev reader。静态/已有缓存检查先执行，所需实际模型调用范围明确。 | 为两讲员运行传入单讲员包、错 locale、WAV 路径不匹配和未支持的 review 状态时，在整篇派发前定位具体层；有效样本可从 App 列表进入、播放和推进字幕。无需等 839 单元做完才发现 reader 不兼容。 |
| R06 / P1 | Layer 3 双讲员与恢复合同 | 将现有播客实现整理为可验证的逐单元 speaker/checkpoint/worker 绑定和按源顺序合成路径；覆盖数来自 job，不硬编码 839。记录双 worker、batch membership、种子、目标音轨时钟；部分 batch/orphan 产物进入核对流程，不能直接重放。 | 本次 551/288 分配、每语种 105 批和自然目标音轨重建一致；换一个不同单元数的两讲员样本仍通过。漏单元、重复单元、错 speaker/checkpoint/hash 被拒绝；中断后只复用身份与文件哈希都匹配的完整 batch。 |
| R07 / P1 | Layer 4 完成条件和审核披露 | 将“App 页面可用”作为独立验收阶段：进入目标 origin/page/locale 的真实列表、打开页面、起播、定位字幕和切换语言；receipt 绑定部署 version、代码/资源 hash、浏览器实际行为与审核状态。资源 HTTP 校验成功后仍需执行此阶段。 | 上传目录但未接 reader 的情况明确显示“资源已部署，App 验收未完成”；播放后确认 currentTime 前进、对应 cue 变化、换语言后的 text/audio locale 正确。Dev waiver 文稿继续披露为未人工批准；生产、设备和现场状态分别记录。页面内容更新只在客户端合同确需变更时才要求新 Beta build。 |
| R08 / P2 | 运行环境、能力与资源占用 | 每个 TTS/ASR 运行收据写实际 image digest、Python/Torch/torchaudio/Qwen 版本、代码、模型 revision/checkpoint hash、设备和 locale。用实际裁剪文件做短能力检查，并核验输出覆盖；资源窗口记录排队/暂停目标、原状态和恢复动作。 | ES/KO 从自己的收据可还原环境，不能借中文 Dockerfile 推定；15/45 秒探针的输入时长和输出范围吻合。Spark→Mac fallback 仅用于已确认基础设施/运行失败；暂停/恢复严格绑定授权目标，未知任务状态先核对。保持单次 batch=2 实验与生产 batch=8 各自独立。 |
| R09 / P2 | ASR 争议与人工裁定 | 原始识别结果不可变；复核队列并列目标文本、识别文本、音频片段、规范化规则与疑点。人工 receipt 绑定被听音频 hash、source/group 和裁定；生成派生的 adjudicated 状态，不篡改机器 pass/fail。 | “尼禄/麋鹿”、数字/同音字和 ES/KO 专名等案例保留原始差异、人工决定与证据；旧 hash 的听审不能批准新音频。修复后的单位/受影响时间线按变化范围复核，未变化的已有批准继续复用。 |
| R10 / P2 | 并发、缓存、计时和进度 | 运行入口显示冻结的 workers/batch，并记录 `fresh_api_attempts`、`reused_groups`、剩余组、重试与失败。TTS 为每 batch 单独记录生成和写入耗时，为双 worker/job 记录墙钟起止；ASR、组装、部署和验收有各自 span。记录 UTC 起止及单调时钟 elapsed。进度只投影当前 run/revision 的执行与审核/部署证据。 | 602 组复用 + 237 组新请求得到明确计数，恢复/修改并发不把跨运行复用藏在 `cacheHits=0`。同一 batch 计时不按八个 unit 重复求和；worker 累计时间和 job 墙钟时间可区分。展示快照带更新时间、run/source 身份与 receipt，旧源进度不覆盖当前源。缺失计时标 unknown。 |

建议按三个可独立评审的变更包推进：

1. **源与翻译准入（R01–R04）。** 先阻止错源付费请求，再统一政策执行和语言规则；重点回归本轮已保存案例，不以再次跑三语整篇作为默认测试方式。
2. **跨层交付与双讲员（R05–R07）。** 复用现有兼容适配，先把短样本闭合至真实 Dev reader，再验证整包合成和中断恢复；正式准入保持既有审核要求。
3. **复现与观测（R08–R10）。** 为各运行补完整环境身份和时间边界，完善 ASR 裁定、资源恢复与当前 run 的进度投影。

实施入口可从现有 `scripts/target_language_policy.py`、`scripts/run_target_language_models.py`、`scripts/canonical_layer2_controller.py`、`scripts/render_podcast_dual_worker.py`、`scripts/screen_podcast_audio_package.py` 及 web/catalog reader 复用。合同字段变更需要版本与迁移；既有有效包、缓存和批准保留。上述验收标准是后续实施要求，本次尚未执行这些实现验收。

原请求的 Spark 单次 cold batch=2 实验仍是独立工作：本轮准备了 41 单元样本和隔离的 v3 validator 候选，不能用生产双副本 batch=8 配音代替该实验。`artifacts/stage2/one-trial-manifest-draft.json` 仍标为未准入，缺少正式安装/执行证据。本次复盘不宣称该实验已经运行。

## 本报告验证

对本地现存 source package、机器审查、waiver、ASR/音轨审查及 Firebase receipt 做只读复核；文档执行 `git diff --check` 与引用路径检查。没有重跑模型、媒体生产或设备/现场验收。本 PR 只加入复盘与关联文档，制作实现保留在原分支。
