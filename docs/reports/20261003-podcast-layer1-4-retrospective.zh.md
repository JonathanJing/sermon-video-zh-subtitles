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
| r8 | 3 | 2.129 秒 | 0 | failed；缓存身份预检拒绝，没有新 API 请求 |
| r9 | 3 | 893.192 秒 | 702 | failed |
| r10 | 3 | 2079.681 秒 | 1678 | 模型阶段 completed；之后插件 26 组拒绝 |
| r11 | 3 | 1523.869 秒 | 1204 | failed/未完成；保留 602 组结果 |
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

## 下一轮应优先解决的流程问题

1. **固定实际源身份。** 入口由下游绑定反查 source/anchor hash；并列 approved 包必须显示差异。源纠正明确标记受影响单元、整包失效范围及可复用的机器证据。
2. **先完成最小跨层交付。** 用一个短的双讲员、同源样本验证 L2 政策/插件、L3 路由/镜像、L4 App reader，再放大到 839 单元。这样能提前暴露包版本、locale、候选状态和 WAV 路径不兼容。
3. **政策与执行一起冻结。** 将术语、经文引用范围和豁免状态同时传入翻译、独立审查、插件及准入，保留修订证据；只修失败或身份受影响的组。
4. **让进度来自运行证据。** 公共进度快照不能替代真实执行 DAG；需要指向当前源身份、正在执行的 run、机器/人工状态、部署 release 与 App 验收收据。
5. **统一记录耗时边界。** 模型新请求、缓存读取、运行环境构建、人工听审、部署和浏览器验收分别记起止与退出状态；未知区间明确保留，避免音频长度或对话间隔代替运行时间。

原请求的 Spark 单次 cold batch=2 实验仍是独立工作：本轮准备了 41 单元样本和隔离的 v3 validator 候选，不能用生产双副本 batch=8 配音代替该实验。`artifacts/stage2/one-trial-manifest-draft.json` 仍标为未准入，缺少正式安装/执行证据。本次复盘不宣称该实验已经运行。

## 本报告验证

对本地现存 source package、机器审查、waiver、ASR/音轨审查及 Firebase receipt 做只读复核；文档执行 `git diff --check` 与引用路径检查。没有重跑模型、媒体生产或设备/现场验收。本 PR 只加入复盘与关联文档，制作实现保留在原分支。
