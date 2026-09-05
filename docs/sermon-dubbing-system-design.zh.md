# 中文证道配音：系统设计与模型选择

这条分支把周六取得的英文证道，制作成可按原视频时间播放的中文音轨，并在按周组织的网页中提供中文字幕、证道同行大纲和讲员音色试听。目标是周日播放同一份视频时，中文听众可以跟随内容。它与现有双 PDF 生产共享已审文本和来源证据，与周日麦克风实时字幕保持独立。

当前已有完整同步试播候选；每周全自动接入、整篇人耳试听和现场同步仍有未完成项。本文描述代码接口和设计理由；数字结果以 [2026-09-05 Astra 修订报告](sermon-dubbing-astra-review-2026-09-05.zh.md)为准，操作命令见[周六配音 Runbook](../experiments/sermon-dubbing-poc/SATURDAY_AUDIO_RUNBOOK.zh.md)。模型官方资料于 2026-09-05 核对。

![两路视频来源、长期音色准备、每周配音与审核发布](diagrams/saturday-chinese-voice-workflow.svg)

## 1. 两路来源，统一到冻结任务

配音成立的前提是确认实际播放的视频版本。讲题相同、讲员相同或日期相近，不能证明剪辑、开场、结尾和时间轴相同。

| 来源 | 设计用途 | 当前实现与边界 |
|---|---|---|
| 周日实际播放的同版本纯证道视频 | 未来优先主路；明确整片只有证道后，使用 `0 → 完整片长` | 桥接器检查周次、`sameVersionConfirmed`、`sermonOnly`、确认依据、文件 SHA-256、实测片长和视频流；随后仍返回 `waiting_same_video_adapter`。来源接入与已审文本准备尚未实现。 |
| 直播归档中的已确认证道窗口 | 当前可用的半自动 fallback | 复用周六 `operator-window-approval.json`、时间线、裁剪回执、阅读 QA 与双 PDF QA。沿用 `validate_window_approval()`，不将模型边界记录写成人工窗口批准。 |

[continue_saturday_dubbing.py](../experiments/sermon-dubbing-poc/continue_saturday_dubbing.py)分别检查两路，按周次和来源使用独立锁。主路等待来源或接入器时，具备完整输入的 fallback 可继续。桥接器默认只读；显式 `--execute` 才准备或恢复已有来源的配音任务。配置结构见 [saturday-bridge.example.json](../experiments/sermon-dubbing-poc/saturday-bridge.example.json)。

当前 fallback 的准备器不是通用视频接入器：它消费现有周六目录，仍要求人工窗口及双 PDF 证据。未来纯证道 adapter 要建立自己的来源契约并生成可核验的共同输入，不能为了调用旧接口而伪造 v1 人工窗口。

## 2. 模块与部署分工

| 层 | 主要入口 | 职责与输出 |
|---|---|---|
| 来源与阅读生产 | [周六本地生产流程](codex-local-production-runbook.zh.md)、[sermon_production_supervisor.py](../scripts/sermon_production_supervisor.py) | 获取来源、确认窗口，生成英文参考、已审中文、双 PDF 与完成证据。 |
| 配音任务准备 | [weekly_dubbing.py](../experiments/sermon-dubbing-poc/weekly_dubbing.py) 的 `prepare()` | 验证来源、授权、文本、QA、讲员检查点；生成 `job.json`、段落和合成单元。 |
| 口播修订 | [apply_spoken_review.py](../experiments/sermon-dubbing-poc/apply_spoken_review.py) | 将对话中的 Astra 审核写入独立契约，派生新 job；保留父任务、原阅读稿与 PDF。 |
| 执行与恢复 | [run_weekly_dubbing.py](../experiments/sermon-dubbing-poc/run_weekly_dubbing.py) | 串行协调 Spark 合成、本地组装、原声定位、逐段回转写和时槽检查；恢复前核对缓存链。 |
| 中文语音合成 | [render_weekly_audio.py](../experiments/sermon-dubbing-poc/render_weekly_audio.py) | Spark 上加载讲员 SFT 检查点，以 Chinese 生成分段 WAV、逐段回执、自然音轨和实际字幕时间。 |
| 原声定位 | [align_weekly_source.py](../experiments/sermon-dubbing-poc/align_weekly_source.py) | 本地 ASR 和 ForcedAligner 生成词级声学证据，再与冻结英文匹配，输出段落锚点与问题。 |
| 音频内容筛查 | [screen_weekly_audio.py](../experiments/sermon-dubbing-poc/screen_weekly_audio.py) | 本地逐合成单元中文 ASR、文字差异和完整 MP3 解码；响度规范化由音轨组装阶段完成。 |
| 同步装配 | [check_weekly_timing.py](../experiments/sermon-dubbing-poc/check_weekly_timing.py) | 计算自然中文能否放入原声时槽，消费独立边界/播放编排审核，装配同步 MP3 与字幕。 |
| 静态应用与发布 | [build_weekly_app.py](../experiments/sermon-dubbing-poc/build_weekly_app.py)、[deploy_firebase.py](../experiments/sermon-dubbing-poc/deploy_firebase.py) | 生成显式发布文件清单，区分待审候选和正式版本，部署独立 Firebase Hosting 站点。 |

MacBook 负责来源资料、任务协调、本地 ASR/对齐和静态应用构建；DGX Spark 负责独立环境中的声音训练与每周 TTS 推理；OpenAI 负责英文文件转写和文本模型阶段。浏览器只消费已生成的音频与内容，不在听众设备上加载训练模型。完整原声、训练片段、检查点和本机审核材料留在忽略目录，不随网页发布。

## 3. 模型选择及其实际职责

### GPT-Transcribe：视频英文转写与原声风险复查

当前周六英文文件转写使用模型 ID `gpt-transcribe`。`SupervisorConfig` 的 `timeline_model` 与 `reference_model` 均为该值；[run_post_live_subtitle_generation.py](../scripts/run_post_live_subtitle_generation.py)和[sermon_pipeline.py](../scripts/sermon_pipeline.py)也保留对应默认配置。它接收从视频提取的音频，生成英文；并不直接理解视频画面。

选择它是为了延续已验证的英文转写主流程和来源回执，集中处理内容准确性。OpenAI 当前官方模型页列明文件语音转写、领域上下文和关键词提示能力；该页的模型别名/快照列表目前为 `gpt-transcribe`。这是本次核对的配置依据，不承诺未来别名永不变化。[OpenAI 模型说明](https://developers.openai.com/api/docs/models/gpt-transcribe)

有合适的现成英文字幕时仍可沿用其文本/时间来源；缺失、否定关系、专名、数字或引文边界有疑点时，回到原声音频做局部复查。已经确认的段落和转写缓存不因口播改稿而整篇重跑。9 月 5 日复查第 32 段的 `to not shield`，用于纠正否定关系；它与合成中文后的本地回转写属于不同阶段。

### GPT-6 Astra：语义修订和独立复核

周六阅读文本当前默认模型为 `gpt-6-astra`；实际运行模型与推理档位由 QA 回执保留，`job.inheritedReview` 继承这些字段。配音不把证道同行的摘要直接当讲稿，而是从已审双语阅读段落派生口播稿。

本轮在用户指定的 Codex 对话中使用 GPT-6 Astra 修订，并做独立复核和第二轮缩短。复核关注完整含义、否定/数字/专名、引文归属和自然口语；需要缩短时修改措辞后重新合成。选择的依据是它能结合完整英文、前后文和具体风险证据进行文字判断；本项目没有据此证明它优于所有其他模型，也不以更换模型代替听审。

审核契约 `sermon-spoken-script-review-v1` 要求覆盖全部段落、绑定父 job 与证据哈希、记录模型/审核身份、时间、理由及四项检查。`authority=user_directed_conversation_review` 表明本次对话授权来源，`humanApproval=false` 始终保留。桥接器只读取这些结果，没有内置一个已上线的 Astra 自动审稿服务。

常规中文修订不改英文。只有独立原声证据支持的 `sourceCorrection` 才能在新 job 中修正英文，并重新匹配原声词证据；父版本、原英文文件和 PDF 保持不变。

### Qwen3-ASR 0.6B 8-bit：本地逐段回转写

代码固定使用 `mlx-community/Qwen3-ASR-0.6B-8bit` 及具体 revision。它有两个明确用途：对原声生成定位辅助文本；对每个中文 WAV 回转写，发现可能漏读、重复或发音异常。选择 0.6B 的本地量化运行方式，是为了复用现有 MacBook 环境、按单元缓存并完成整篇覆盖；本项目未开展证明其质量等同更大模型的完整对照。

Qwen 官方 ASR 系列支持中文和英文识别，另提供独立 ForcedAligner。官方基础模型能力与项目使用的 MLX 社区 8-bit 转换版需要区分；具体转换版、revision 和输入哈希以 [prepare_voice_candidates.py](../experiments/sermon-dubbing-poc/prepare_voice_candidates.py)及回执为准。[Qwen 官方 ASR 文档](https://github.com/QwenLM/Qwen3-ASR)

逐单元处理避免把整篇长音频的一次转写误当完整覆盖。差异比较以实际送给 TTS 的 `spokenText` 为准，保留识别结果和差异候选。相同读音可能产生不同汉字，ASR 也可能识别错；差异条数不能直接报成 TTS 错误率，零差异也不等于人耳已验收。

### Qwen3-ForcedAligner 0.6B 8-bit：从声音取得时间锚点

项目固定 `mlx-community/Qwen3-ForcedAligner-0.6B-8bit` 及 revision，输入音频和英文文本，输出词边界。Qwen 官方将其定义为文本—语音强制对齐模型，支持包括中英文在内的 11 种语言；这个职责与“决定正确英文是什么”不同。[Qwen ForcedAligner 接口](https://github.com/QwenLM/Qwen3-ASR#forcedaligner-usage)

当前原声定位按 50 秒步进读取最多 60 秒窗口，保留重叠区，合并词时间后与冻结的英文段落匹配。覆盖不足、边界词不连续或时间不单调会形成复核项，不用阅读 PDF 的排版时间戳填补。更改英文时可以重用相同原声音频的词证据，但必须重新匹配并生成新报告。

### Qwen3-TTS 12Hz 1.7B Base：按讲员 SFT，再生成中文

当前训练底座为 `Qwen/Qwen3-TTS-12Hz-1.7B-Base`，训练脚本固定底座、Tokenizer 和上游源码 revision。Qwen 官方说明 Base 支持音频参考克隆和微调；系列覆盖中英文。官方微调路径支持单讲员训练，产出以 `speaker_name` 调用的检查点，符合本项目每位讲员独立管理的方式。[Qwen 模型说明](https://github.com/QwenLM/Qwen3-TTS#released-models-description-and-download)、[官方微调流程](https://github.com/QwenLM/Qwen3-TTS/tree/main/finetuning)

项目选择 1.7B Base 的具体理由是：已有可审计的单讲员训练接口、可保留权重与来源哈希、能用英文原声训练后实际生成中文，并且现有 Spark 环境已完成工程验证。每周加载的是对应讲员的训练检查点，以 `generate_custom_voice(text=..., language="Chinese", speaker=...)` 推理；不是直接选择官方九种预设音色。固定批量通常为 4 段，生成身份还包含 seed、温度、重复惩罚、最大 token 数与渲染脚本哈希。

Spark 训练与推理采用 Torch BF16、SDPA。BF16 是当前实测环境配置，不是本项目测得优于所有量化方案的结论；SDPA 是保留在隔离运行环境和补丁回执中的适配选择。历史 MLX 参考克隆或 IndexTTS 等候选比较仍是各自日期的探索材料，不能用来声称当前六位讲员/整篇配音的统一排名。官方低延迟或通用音质指标也不能替代本项目的整篇试听与现场同步证据。

实测支持的范围是：Eric 首轮与三篇扩充后的训练样片获用户认可；另外五位讲员已有独立检查点和中文试听，尚不能沿用 Eric 的认可。具体训练、兼容性修改和局限见[授权训练报告](../experiments/sermon-dubbing-poc/AUTHORIZED_VOICE_REPORT_20260905.zh.md)、[扩充与每周应用报告](../experiments/sermon-dubbing-poc/WEEKLY_APP_REPORT_20260905.zh.md)、[讲员库报告](../experiments/sermon-dubbing-poc/SPEAKER_BANK_AND_WEEKLY_FLOW_REPORT_20260905.zh.md)。

## 4. 长期训练与每周推理分开

声音训练是低频维护的讲员资产；每周生产只选择已登记检查点。新一周文本进入合成任务，不自动进入声音训练集，也不因生成了配音而更新模型。

| 长期声音准备 | 每周内容生产 |
|---|---|
| 确认训练/配音授权并绑定来源哈希 | 确认本周实际来源版本、讲员、主题和经文 |
| 按讲员与整篇证道来源划分 train/保留评估集 | 复用对应讲员 checkpoint，不重新训练 |
| 对齐英文句子，复核截句/混讲员风险并排除受保护评估来源 | 读取已审双语文本，单独修订口播稿 |
| 在隔离 Spark 环境执行有限 SFT，保存权重/输入/日志 | 按自然句群合成、逐段 ASR、检查时槽和试听 |
| 以固定中文探针和原声对照评估新检查点 | 冻结本周 MP3、字幕、审核与发布文件清单 |

本轮三篇模式限制每人恰好三个 train 来源、最多 96 个片段和 15 分钟，训练为 1 epoch、batch 1、梯度累积 4、学习率 `2e-6`。这是 [run_qwen_training_smoke.py](../experiments/sermon-dubbing-poc/run_qwen_training_smoke.py)的受限工程试跑配置。`productionTrainingAdmission=false` 与正式人工准入状态继续保留；“训练确实执行过”和“样本成为人工 Gold”是两种不同证据。

目前登记 Eric Geiger、Jared Kirkwood、Christine Caine、Doug Fields、Kenton Beshore 和 Steve Bang Lee 六位讲员。训练结果中的 `speakerKey`、检查点哈希和周任务讲员必须一致，渲染器也检查 checkpoint 的 speaker slot，防止串用声音。

## 5. 不可变任务、缓存与证据链

每个 `sermon-weekly-dubbing-job-v1` 冻结来源音频/原文件、裁剪回执、人工窗口、时间线、双语稿、QA、PDF、大纲、授权和声音训练回执的路径与 SHA-256；同时记录来源 URL/ID、周次、片段起止、检查点和逐段文本。`prepare()` 拒绝覆盖已存在目录。更换来源、阅读稿或声音时创建新 job。

口播修订以 `revisionOf` 指向父 job，以独立 `spokenScriptReview` 输入记录审核；不是直接覆盖旧 JSON。显示的 `text` 与发音规范后的 `spokenText` 分开，数字和神称代词的口播调整带有规则版本，字幕保留已审文字。

| 产物 | 绑定或验证内容 |
|---|---|
| `job.json` | 冻结输入、来源时间轴、讲员模型、段落与单元；派生任务还验证父链。 |
| `render/identity.json`、`unit-*.json` / WAV | job、checkpoint、渲染脚本与参数、完整单元内容和实际音频哈希。 |
| `render/report.json`、`audio/library.json` | 实测自然音轨时长、每个 cue、组装结果及 MP3 哈希。 |
| `audio/unit-screening/`、`audio/asr-screening.json` | 逐 WAV 哈希、期待口播文本、ASR 模型/revision、全单元覆盖与解码证据。 |
| `source-alignment/` | 原声音频、ASR/对齐窗口、词证据、英文匹配结果和待审锚点。 |
| `synchronization/report.json`、`assembly.json` | 当前 job、渲染、对齐及审核哈希、实际时槽计算、同步音频和字幕。 |
| `audio-review*.json` | 待审或实际人工审核身份、六项结果，以及所批准的 job、MP3 和 checkpoint。 |

恢复不是检查“MP3 是否存在”。`validate_cached_stages()` 和 `validate_candidate()`重验生成回执、自然音轨、窗口缓存、逐段 ASR 与当前时槽。哈希或参数不一致时停止并保留现场，恢复相符证据或派生新 job；不自动删除旧缓存或重新执行付费阶段。

修订可复用内容、发音输入、停顿和声音身份一致的 WAV，连同来源回执一起记录复用关系；ASR 只有在 WAV、预期文本和模型身份一致时复用。缓存提高迭代效率，同时防止旧审核误挂到新声音上。9 月 5 日第一轮复用 85 个 WAV、生成 34 个，第二轮复用 115 个、生成 3 个，是该机制的一次实际结果，并非每周固定配额。

## 6. 同步：原声锚点与中文播放安排各自留痕

系统有三条时间轴：原直播时间、批准证道片段时间、自然中文音轨时间。最终同步版本以批准证道片段的零点开始；例如本轮中文 `00:00` 对应原视频 `29:00`。自然版 `zh-natural.mp3` 只有中文连续播放时间，不能直接当同视频同步版。

时槽按原声段落起点到下一段起点（末段到片段结尾）计算，比较实际自然中文时长。超时段先回到中文审稿，保留原义、缩短表达、重新生成。装配在原声时间轴中放置完整自然 WAV 并补间隔，不靠截句、重叠或变速掩盖超时。

弱声学边界可以使用两类独立证据：真正人工复核保存在 `anchor-review.json`；本轮 Astra 复核保存在 `anchor-model-review.json`，schema 为 `sermon-anchor-model-review-v1`，要求逐块理由、模型身份、任务/原声/对齐证据哈希，并保持 `humanApproval=false`。本轮 9 处弱边界全部保留原起止。

可选 `placement-model-review.json` 使用 `sermon-playback-placement-review-v1`，只调整明确审查的中文播放起点。它要求当前 job、render、alignment、原声和独立证据哈希，限制最多提前 1 秒且不得早于前段英文结束，再重新计算相邻中文时槽。`sourceAnchorStart` 保留英文锚点；`playbackStart` 是中文编排，不改英文文本或原声词时间。

本轮末句 1.92 秒，原英文起点仍为 1768.88 秒，中文经明确编排在 1768.08 秒起播，提前 0.80 秒。这样的低能量间隔证据只能支持候选编排，不能宣称绝对静音或口型同步通过。模型播放编排先进入候选；正式验证会重新加载编排、核对其哈希并复算时槽，仍要求当前同步 MP3 的完整人工同视频审核和原周六生产完成。不能仅补一个人工批准布尔值就自动晋升。

## 7. 发布候选与正式完成是不同状态

[按周试听应用](https://ai-for-god-sermon-audio.web.app)提供周次选择、中文播放/下载、字幕跳转、±5 秒和 ±1/±0.25 秒调整、大纲弹窗、讲员音色对照以及深浅主题。文件构建支持多次传入 `--weekly-job`，显式 `--include-history` 保留历史试听内容。

| 构建方式 | 允许状态 | 不代表什么 |
|---|---|---|
| `--review-preview` | 明确标记的整篇待审自然音轨 | 不产生周日批准。 |
| `--review-preview --sync-preview` | 缓存链与时槽通过的同步候选，采用同步 MP3 和对应字幕 | 不证明完整人耳听审、现场设备或实际视频同步。 |
| 默认正式构建 | `validate_review()` 验证的已审同步版本 | 不能只凭文件存在、模型审核或网页可播绕过上游完成状态。 |

正式审核需要真实审核人、时间、`humanApproval=true`，以及讲员身份、音色相似度、中文流畅度、发音、无漏读/重复、同视频同步六项通过；还需全单元 ASR、完整解码、当前同步证据，并调用既有 `local_completion_artifacts()` 重查周六 generation、run-status、双 PDF 与远端发布证据。历史失败的周六任务不能因新配音候选已发布就被改称完成。

Firebase 只上传显式构建清单，完整媒体和检查点不进入该目录。候选也验证线上文件哈希、音频 Range 请求、播放/跳转、字幕和大纲。网页检查与手机尺寸预览不等于实体手机后台/蓝牙或真实场地验收。

## 8. 当前证据与下一步

[9 月 5 日报告](sermon-dubbing-astra-review-2026-09-05.zh.md)记录 55 段审阅、18 段中文修订，最终 118 个合成单元，55 段时槽无失败，同步长度 29:30。同步 WAV 与自然语音逐块对比波形误差为零，MP3 完整解码；118 段 ASR 全覆盖。61 条文字差异经 Astra 逐项复核，其中 3 处专名声调疑点和 2 处 ASR/口语差异仍留在试听清单。该报告另记录当次 102 项 Python、8 项前端测试和 21 个线上文件哈希检查；这些数字是已记录运行结果，本文更新没有重做模型生产。

继续推进有三项明确工作：取得周日同版本纯证道视频并实现来源 adapter；完成各讲员/整篇人工试听和现场同步，绑定实际播放编排与最终 MP3；恢复周六定时任务接线并确认真实任务回读。两路桥接器和六位讲员配置已准备、真实 8 月 30 日来源检查通过，但 9 月 5 日定时任务更新接口未返回，回读仍是原双 PDF / Context Pack 任务，不能称配音调度已经接通。

恢复接线无需重做已经通过的音频与审核。后续新周次沿用来源隔离、不可变 job 和缓存验证，只有实际缺失或改变的阶段才继续执行。
