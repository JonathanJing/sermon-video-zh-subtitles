# 四层制作 Backlog 与进度追踪

Dev 跨层优先级与稳定任务 ID 统一维护在 [Dev 统一 Backlog](backlog.zh.md)。本页只记录某次制作的 Layer 1–4 检查点、证据、实际耗时与 ETA，不再作为全项目顶层 backlog。

本页是**每次制作**的操作清单和状态入口。正式包、门禁和失效规则以[四层接口合同](multilingual-production-interfaces.zh.md)为准；本地 tracker 是工作记录，**不能**凭勾选、文件路径或百分比授予人工批准、发布资格、HTTP、设备或现场验收。

需要跨设备查看时，使用[Firebase 四层公开 Tracker](../experiments/sermon-dubbing-poc/tracker-admin/README.zh.md)：它从本地账本、source monitor 与发行收据生成脱敏的实时只读页面，显示每语言页面、语音和声纹状态。

## 四层制作 Backlog

每篇只有一份 Layer 1；Layer 2 和 Layer 3 按目标语言独立推进。本次三语 Dev 发布要等中、韩、西三条正式音轨及对应门禁齐备后，才在 Layer 4 汇合发布。Tracker 因此把 Layer 4 画成单独的联合发布区；区内仍按 `pageId + targetLocale` 分列发布包、L4-01～04 检查点及交付验收，不能用一个汇合节点代替三语言的证据。其他发布计划可允许不同语言独立发布或显式 `audio_unavailable` 文字路径，不把本次三语等待条件写成普遍合同。以下 ID 是 tracker 的检查点，工程实现的详细任务分别见[Layer 2/3 开发 backlog](multilingual-layer-2-3-backlog.zh.md)和[Layer 4 开发 backlog](multilingual-layer-4-delivery-app-backlog.zh.md)。两类 backlog 不互相冒充完成。

| 层 | 检查点 | 完成证据及放行条件 |
|---|---|---|
| Layer 1 共享英文事实与锚点 | L1-01 来源媒体、身份与人工范围；L1-02 冻结英文文本与词级对齐；L1-03 句界、停顿和锚点核验；L1-04 英文人工审核与正式 Source Package | 媒体 hash／时长、操作员范围、唯一英文对齐轴、审核收据与 `ready_for_translation` 的包；缺任何一项只保留 shadow 或待审状态。 |
| Layer 2 目标语言文字，每语言 | L2-01 语言策略与经文版本；L2-02 逐单元翻译与覆盖；L2-03 独立机器复核与语言检查；L2-04 人工文字审核与 Candidate | 同 Layer 1 hash 的目标语言策略、完整 source-unit 覆盖、独立复核及该语言人工批准，最终 `human_translation_approved`。中文、韩语、西语互不继承审核。 |
| Layer 3 目标语言音频与同步，每语言 | L3-01 授权音色／能力／Speech Job；L3-02 逐单元合成；L3-03 完整解码／哈希／回转写；L3-04 排程／字幕／完整音轨；L3-05 人工全文听审；L3-06 同视频同步审核与 Audio Package | 同语言文字 hash 一致；每个单元和完整音轨可解码、自然语速、字幕排程有效、全文听审和 1 倍速同视频检查有独立收据。纯文字路径应显式生成 `audio_unavailable` 包；若该次决定等三语音频齐全，则三语均须有合格音轨。 |
| Layer 4 多语言发布与播放，每语言 | L4-01 同语言 Release Package／文件清单；L4-02 目标环境构建与上传；L4-03 线上 HTTP／hash／Range；L4-04 客户端文字／语言／播放核验 | `pageId + targetLocale` 独立包和 allowlist；线上逐资产核验；Web／App 消费真实 catalog 与音轨。设备验收和现场验收分别记录，不从 HTTP 成功推断。 |

### Layer 1 工程 Backlog

Layer 1 目前已有确定性 package generator 和未来周 shadow 接入；下列项是走向稳定正式主线仍需逐项核验的工作，不能从单个片段推断整篇通过：

- [ ] **L1-B01**：把来源媒体、人工范围、英文文本、词时间轴和审核收据的 hash 绑定做成可重复的完整 run 校验；输入变化时使全部语言失效。
- [ ] **L1-B02**：对无安全切点、对齐异常、低置信文本建立可恢复的审核队列；禁止用翻译或配音阶段补改英文。
- [ ] **L1-B03**：完整真实证道的英文逐句、词时间和句界人工审核，并保存 `ready_for_translation` 收据。
- [ ] **L1-B04**：中文 legacy 输入与新 Layer 1 包做 golden replay，核对 source-unit ID、词时间和来源身份无漂移。
- [ ] **L1-B05**：正式入口自动报告 Layer 1 阶段状态、耗时、问题数和包路径；shadow 与正式放行分别显示。

Layer 2 的实现、`zh-Hans` 兼容、韩语 fixture／整篇审核和语言策略任务见[详细清单第 3 节](multilingual-layer-2-3-backlog.zh.md#3-layer-2目标语言文字-backlog)。西班牙语需要同级策略、审核插件、经文版本、fixture、整篇人工审核和独立收据，不能由韩语通过推断完成。

Layer 3 的 renderer、音色能力、筛查、滚动排程、字幕、听审和恢复任务见[详细清单第 4 节](multilingual-layer-2-3-backlog.zh.md#4-layer-3目标语言音频与同步-backlog)。西班牙语同样需要独立音色／发音和整篇音轨验收。

Layer 4 的发布包、catalog、Web／iOS 语言选择、回滚和验证矩阵见[详细清单第 6 节](multilingual-layer-4-delivery-app-backlog.zh.md#6-layer-4-与-app-改进-backlog)。要把三语 Dev 页面用于实际发布，还须核对西语在 catalog 和客户端的能力，不能把韩语两语言用例当成三语言完成。

### Tracker 接入 Backlog

- [x] **TRK-001**：建立每次制作、每层／每语言的状态账本，显示检查点进度、阻塞、证据引用和条件 ETA。
- [ ] **TRK-002**：从正式 Layer 1–4 producer 的收据自动同步状态与实测耗时；同步前核对包 schema、source／locale hash 和 validator 结果。
- [ ] **TRK-003**：积累足够同类运行后，按片长、source-unit 数、语言和模型建立估时基线，显示区间与校准误差；人工审核等待另算。
- [ ] **TRK-004**：将 Dev／正式环境的 HTTP、设备、现场收据自动关联到对应 `pageId + targetLocale`，保留部署、设备和现场三个不同终点。
- [x] **TRK-005a**：提供四层步骤命令计时入口，复用现有追加式 `sermon-workflow-accounting-v2`，按检查点和语言记录实际执行、失败与重试；提供只读计时覆盖预检。旧步骤不得按文件时间补造耗时。
- [ ] **TRK-005b**：把 Layer 1–4 正式 producer 逐一接入计时入口，并将审核发出／回复、依赖就绪／开始的时间作为独立事件记录。区分程序执行、资源排队、人工审核等待、外部阻塞和返工；记录输入单元数、模型／prompt、缓存与 API 用量的可用性。
  - 首批已接入 L1-04 Source Package、L2-01 请求准备、L2-03 语言插件复核／候选准入、L2-04 人工审核稿／批准收据和 L3-01 Speech Job。正式译文模型调用、音频合成、同步与 Layer 4 producer 尚无自动 span；审核发出／回复和资源排队仍待独立事件接入。
- [ ] **TRK-006**：本轮三语 Dev 流程结束后，对同一 `pageId + source hash + locale` 做完整审计：核对日志覆盖、重试、并行重叠、人工等待、资源竞争及真实关键路径；用实测墙钟时间校准 Tracker ETA，并列出仍未知的时间。审计前不依据检查点百分比或文件时间给瓶颈排名。

### 多语言人工审核后台 Backlog

- [ ] **REV-001（P1）私有多同工审核工作台**：为不同语言和职责的同工提供登录后的待审队列、逐段审核窗口与明确的决定按钮；与现有[公开只读 Tracker](../experiments/sermon-dubbing-poc/tracker-admin/README.zh.md)分开。[远程审核到本机续跑通信设计](tracker-remote-review-bridge.zh.md)规定 Firebase 指令队列、本机领取、收据校验和 Agent 交接。先交付 Layer 2 译文与 Layer 3 音轨审核，再接 Layer 1 英文来源和 Layer 4 发布验收。
  - **分配和权限**：任务按 `pageId + layer + targetLocale + artifact hash + unit/group ID` 定位；管理员分配审核者及其语言／步骤权限。同工只读取获授权的原文、译文、音视频和审核证据；公开 Tracker 不接收正文、私有媒体或审核原因。不同语言可并行认领；当前正式 Layer 2 候选只接受同一审核者的全部组收据。同语言任务产生首个决定后若移交，新审核者须重审整份候选；跨审核者聚合要另做版本化 schema／validator 迁移。
  - **需要审核的窗口**：Layer 1 对照原视频、英文逐字稿、词时间、句界和来源范围；Layer 2 左右对照英文单元与本语言译文，显示覆盖、术语／经文出处、机器复核和风险标记；Layer 3 对照原视频、已批准文字、逐单元与整轨音频、字幕 cue、排程及回转写问题，提供 1 倍速和时间点定位；Layer 4 展示同语言页面字段、清单、线上 HTTP／Range 与客户端验收项目。每个窗口明确显示当前 hash、状态、尚未审核的范围和上游变更。
  - **人工输入与按钮**：逐段可输入改文、时间点／时间范围、问题类别与说明，并可“保存草稿”“标记问题”“提交修订”“通过当前段”“退回”。Layer 1 的“批准英文范围与锚点”、Layer 2 的“批准本语言文字”、Layer 3 的“批准本语言整轨”分别在规定范围已审完且无未解决问题时启用；Layer 3 还须记录全文 1 倍速听审与同视频同步检查。Layer 4 分开记录发布、HTTP、设备和现场验收，不用一个“通过”按钮合并这些状态。批量批准须预览所含 ID 与 hash。
  - **收据与层内解耦**：每次决定追加不可改写的收据，绑定审核者、带时区时间、身份／权限、来源包、候选或音轨 hash、语言、具体 ID、操作和问题。待审段不阻止其他段的机器准备、`preview_only` 配音或其他语言推进；正式包仍按现行 validator 的完整候选／音轨门禁聚合，不能用局部通过冒充整包批准。Layer 1 改动使所有语言相关决定失效；Layer 2 修订按每份收据声明的 `contextScope` 失效：默认 `whole_candidate` 重开该语言全部组，只有附独立性证据并通过校验的 `connected_blocks` 才可保留不受影响的组；Layer 2／3 改动都重开同语言正式下游聚合，不影响其他语言。审核后台不得原地修改已批准包，也不得把“草稿”“机器通过”或 Tracker `complete` 写成正式人审通过。
  - **验收**：两位不同语言同工可同时审核同一篇，按段保存与恢复；旧版本提交、越权访问、漏审、重复批准和并发冲突均被拒绝。测试同语言已开始审核后的移交：混合审核者收据不能聚合，新审核者重审全部组后才能放行；分别测试 `whole_candidate` 和有独立性证据的 `connected_blocks` 修订失效范围。正式包 validator 能读取新收据。后台记录发出、认领、回复时间供 TRK-005b 计算等待，公开 Tracker 只得到脱敏聚合状态。先用 Dev fixture 与权限规则／服务端校验测试，再用一篇真实三语片段验证完整审核交接。

### 周日页面提速 Backlog（本轮结束后按审计证据实施）

- [ ] **SPD-001**：验证 Layer 1 放行后三语 Layer 2 独立并行；每种语言经本语言人工批准后立即进入本语言 Layer 3，不等待其他语言文字。保留 source／locale hash 门禁和三语正式音轨齐全后的最终发布汇合点。
- [ ] **SPD-002**：把经文策略、音色授权与能力探针、页面外壳和来源监控等不消费正式下游包的准备工作前移，与 Layer 1／2 重叠。正式 Speech Job、Release Package 仍只消费已批准且 hash 匹配的输入。
- [ ] **SPD-003**：用相同片段和设备比较 Layer 3 单任务、两路及必要时三路合成；同时记录模型加载、单位音频墙钟、GPU／内存峰值、失败重试和音质。只采用实测端到端更快且不降低质量的并发数。
- [ ] **SPD-004**：审核稿在候选稳定时立即发出，三语可各自审核并批量展示风险单元；分别保存语言、版本 hash、请求／回复时间及修订轮数。压缩等待和重复呈现，不合并或推断人工批准。
- [ ] **SPD-005**：对冻结的同一批源单元做 Astra／Luna 文字阶段影子 A/B。比较端到端延迟、Token／费用、覆盖与经文引用错误、独立复核发现数、人工修订时间；先试低风险候选／检查，过同一质量门禁后才调整正式路由。Luna 不替代 Qwen TTS。
- [ ] **SPD-006**：按三语分支的实际最长路径、资源排队和最终汇合计算 Dev 发布 ETA 的区间；HTTP／Range、设备和现场验收继续分列。每次优化只改变一个变量，保留上一轮可比基线与回退方式。

## Status tracker 和 progress tracker

状态枚举：`pending`、`running`、`waiting_review`、`blocked`、`complete`。`complete` 必须附证据引用；引用只是定位信息，审核仍由各层正式 validator／人工收据决定。完成的检查点需要重做时用 `invalidate`，不要改写旧收据。共享 Layer 1 失效会重开所有语言的 Layer 2–4；Layer 2/3 失效只重开本语言下游。

用[本地 tracker](../scripts/four_layer_progress.py)为每个 page 建立一个**忽略 Git 的运行目录**中的账本。它不自动调用翻译、TTS 或部署；操作者在阶段完成、等待、阻塞时登记真实证据和时间。示例路径只用于新 run，不会覆盖已存在账本：

片段 POC 从新的、准确的发布 `pageId` 开始，使用 `init-poc` 将原视频身份和候选截取窗口写进本地账本。URL 哈希须对选定的规范来源 URL 原样计算；可选媒体 SHA-256 仅在已完整下载并核验媒体时提供。此记录标记为 `proposed_not_approved`，不代替 Layer 1 来源、人工范围或英文审核收据。来源或窗口若改变，应建立新账本，旧计时 span 不会错误套用到新身份。

```bash
POC_SOURCE_URL='https://www.youtube.com/watch?v=VIDEO_ID'
POC_URL_SHA256=$(printf %s "$POC_SOURCE_URL" | shasum -a 256 | cut -d ' ' -f1)
python scripts/four_layer_progress.py artifacts/new-clip/four-layer-progress.json init-poc \
  --page-id 2026-09-27-example-clip --target dev --locales zh-Hans ko es \
  --service-date 2026-09-27 --source-id VIDEO_ID \
  --source-url-sha256 "$POC_URL_SHA256" \
  --window-start-seconds 600 --window-end-seconds 780
```

`init-poc` 拒绝覆盖已有账本。若初始化时媒体尚未下载，完整取得并核验文件后先执行 `bind-source-media --media <完整原视频文件>`；它会计算文件 SHA-256、绑定原账本并保留既有进度和计时身份，换成不同媒体文件会拒绝。正式 Source Package 出来后，须核对其中的 `source.sourceId`、`source.sourceUrlHash`、媒体 hash 和 `source.approvedWindow` 与本次账本身份、实际文件及人工收据一致；这些字段不由 Tracker 自动授予批准。

```bash
python scripts/four_layer_progress.py artifacts/new-clip/four-layer-progress.json bind-source-media \
  --media artifacts/new-clip/source-video.mp4
```

用户已明确批准同一片段来源窗口，且本地存在该决定的 `sermon-clip-window-approval-v1` 收据时，运行一次：

```bash
python scripts/four_layer_progress.py artifacts/new-clip/four-layer-progress.json approve-source \
  --receipt artifacts/new-clip/clip-window-approval.json
```

命令要求收据有 `humanApproval=true`、审核人、带时区时间与具体证据，并逐项核对 `sourceId`、来源 URL hash、媒体 SHA-256 和片段相对起止时间。通过后，账本将来源绑定的 `approvalStatus` 更新为 `approved`，记录收据原始字节 SHA-256，并追加批准登记事件；重复使用同一收据为无操作，不同收据会被拒绝。批准前后不可变来源身份的计时绑定保持一致，已有真实执行 span 不丢失。此登记不会勾选 L1-01 或替代正式 Layer 1 英文来源、对齐和人工审核门禁；操作者仍需核对原录像窗口与收据的关系。

```bash
python scripts/four_layer_progress.py artifacts/my-multilingual-run/four-layer-progress.json init \
  --page-id my-page --target dev --locales zh-Hans ko es

python scripts/four_layer_progress.py artifacts/my-multilingual-run/four-layer-progress.json update \
  --step L1-01 --status complete --evidence source-media-report.json --elapsed-minutes 18

python scripts/four_layer_progress.py artifacts/my-multilingual-run/four-layer-progress.json update \
  --step L3-02@ko --status running --done-units 12 --total-units 45 \
  --elapsed-minutes 28

python scripts/four_layer_progress.py artifacts/my-multilingual-run/four-layer-progress.json update \
  --step L3-05@ko --status waiting_review --reason '等待韩语全文听审'

python scripts/four_layer_progress.py artifacts/my-multilingual-run/four-layer-progress.json show
python scripts/four_layer_progress.py artifacts/my-multilingual-run/four-layer-progress.json show --json

python scripts/four_layer_progress.py artifacts/my-multilingual-run/four-layer-progress.json acceptance \
  --locale ko --kind device --status passed --evidence iphone-ko-review.json
```

对尚未开工的检查点，可用 `update --step L2-02@es --status pending --estimate-minutes 40` 输入明确的人工估时。对可按单元计数的工作，用 `--done-units`、`--total-units`、`--elapsed-minutes` 计算实测剩余时间，并显示该单元进度。没有估时／实测速率、待审核或阻塞时，ETA 显示**未知**及原因。已有数字时，ETA 在命令行按洛杉矶时间显示，是“所有剩余工作连续串行、无人等待”的最早时间；它不包含休息、排队、返工、模型故障或发布窗口，不是承诺完成时间。层级百分比仅表示检查点完成数，不表示内容质量或媒体生成比例。

上游修订后，明确失效并保留历史事件：

```bash
python scripts/four_layer_progress.py artifacts/my-multilingual-run/four-layer-progress.json invalidate \
  --layer 2 --locale ko --reason '韩语批准译文修订'
```

上述首批正式 producer 已支持 `--progress-ledger`，也可对同一周运行设置 `SERMON_FOUR_LAYER_LEDGER`。它们会在账本旁的私有 `accounting/events.jsonl` 写账本运行身份、page ID／语言／目标环境、开始／结束 span、失败类型、输入单元数、组数及相关 JSON／策略／模型标识 hash；不会自动修改账本状态或授予人工批准。审计只采纳运行身份匹配的事件；同目录重建账本后，旧日志保留但不计入新页面。未带身份的旧计时记录保持未知。Tracker 公开快照 v2 按检查点显示累计实测执行耗时（含失败重试）、未结束执行记录截至快照的时长，以及 `running`／`waiting_review` 账本状态持续时间；旧版 v1 快照仍可读取，缺少的活动计时保持未知。后两项不是已完成执行耗时，也不证明进程或审核者仍在线。快照不公开私有开始时间、hash、原文、路径或错误消息。设备／现场验收按语言独立记录，须以各自收据为准。制作正式环境时把 `--target dev` 改为 `--target production`，重新建账本并重新核验，不能把 Dev 状态原样晋升。

### 从现在开始保留真实耗时

对已接入的正式入口，在原命令中加入同一运行账本即可自动记录；例如：

```bash
python scripts/produce_target_language_candidate.py prepare \
  --english-source-package artifacts/my-multilingual-run/english-source-package.json \
  --anchor artifacts/my-multilingual-run/anchor-manifest.json \
  --policy artifacts/my-multilingual-run/ko-policy.json \
  --progress-ledger artifacts/my-multilingual-run/four-layer-progress.json \
  --out artifacts/my-multilingual-run/ko/request.json
```

同一 producer 不要再套相同检查点的手动计时命令，否则会重复统计。产出候选或审核稿的命令即使执行成功，也不代表 Layer 2 的人工放行；`L1-04` 生成阻塞包时同样只证明执行完成，不表示可进入正式翻译。日志中的模型标识为 hash，须用冻结策略文件核对；外部翻译调用的 Token、缓存、费用和等待时间若没有原始收据，仍列为未知。

对尚未接入的四层命令，使用[计时入口](../scripts/four_layer_measure.py)运行。它在账本旁的私有 `accounting/events.jsonl` 追加实际执行 span，继承已有子流程日志，保留非零退出；**不**自动把 Tracker 步骤标为完成，也不授予审批。`--` 后使用原本要执行的命令：

```bash
python scripts/four_layer_measure.py run \
  --ledger artifacts/my-multilingual-run/four-layer-progress.json \
  --step L3-02@ko --billing local -- python scripts/YOUR_EXISTING_RENDER_COMMAND.py
```

人工审核发出时及时将对应步骤更新为 `waiting_review`，收到决定时再按正式收据更新状态；两次操作时间可算**操作员登记的等待区间**，不是人实际审阅时长。命令执行时间来自日志的独立开始／结束 span，重试各记一次；进程中断留下未结束 span，不能当成零耗时或成功。中途未计时的步骤保持“未知”，不以 Tracker `updatedAt`、产物 mtime 或模型音频长度倒推。审计预检只读，不启动生产或改变账本：

```bash
python scripts/four_layer_measure.py audit \
  --ledger artifacts/my-multilingual-run/four-layer-progress.json
```

`audit` 输出 `completedWithoutMeasuredExecutionCount` 与具体步骤 ID。快照及公开页也显示缺实测计时的已完成检查点数；本地旧账本和线上旧快照须重新生成、重新发布后才会带新字段。即使已有步骤标记为 `complete`，没有匹配本账本与来源窗口的真实 span，耗时仍为未知。

当前 9 月 20 日 178 秒片段的 19 个已登记完成步骤是事后根据正式收据回填，均无执行计时。新入口只对**此后通过它运行**的步骤建立实测时间；本轮结束时审计必须把这 19 项列为计时缺口，并结合已有正式收据与人工审核时间线说明可证范围。
