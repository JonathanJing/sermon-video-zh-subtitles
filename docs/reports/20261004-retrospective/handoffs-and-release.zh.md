# 2026-10-04 交接、审批与发布证据独立审计

## 方法与范围

仅离线读取本次 RUN；没有网络、模型、部署、设备或 UI 操作。复算脚本为 `audit_handoffs.py`（参数见 [复算入口](README.md)），只写指定输出目录 `metrics.json`。时间全部取记录内 UTC 字段，不把文件 mtime 当事件时间；SHA 均从现存文件复算。只读历史产物不能证明服务器现在的状态。

## 1. 已闭合的候选 → 批准 → 首轮启动链

六份初始全文/口语候选均验证 sourceCandidate 原始及 canonical SHA、approvedCandidate canonical SHA、human receipt 原始 SHA；其中五份在 accounting 中找到同候选 canonical hash 的 identity workload，且同 span 完成。中文全文的同 hash 完成事件未找到，不用目录时间补齐。三份口语再经过 native preparation → selected manifest → queue SHA → nativeCheck job SHA，闭合到实际 renderer invocation。

批准收据时间为 `2026-10-04T10:13:53.301601Z`；这是决定收据时间，并非开始阅读或聆听时间。

| 候选 | hash绑定 ready UTC | ready→批准 | 批准→本语调用 | 首轮队列内等待 |
|---|---|---:|---:|---:|
| zh-Hans full | 缺少同hash完成事件 | 不可计算 | 不直接配音 | 不适用 |
| zh-Hans spoken | 2026-10-04T08:57:33.131392+00:00 | 76.336 分钟 | 15.344 分钟 | 0.000 分钟 |
| ko full | 2026-10-04T07:28:11.750347+00:00 | 165.693 分钟 | 不直接配音 | 不适用 |
| ko spoken | 2026-10-04T09:44:12.461630+00:00 | 29.681 分钟 | 37.501 分钟 | 22.157 分钟 |
| es full | 2026-10-04T07:37:08.413290+00:00 | 156.748 分钟 | 不直接配音 | 不适用 |
| es spoken | 2026-10-04T09:31:42.467664+00:00 | 42.181 分钟 | 59.780 分钟 | 44.436 分钟 |

批准至队列进程启动为 **920.605900 秒（15.343 分钟）**。中韩西三份口语虽分别在 08:57、09:44、09:31 ready，统一批准在10:13；这些跨度含交接、其它语言准备及审阅安排，不能全部称为人工等待。韩语、西语各另含22.157和44.436分钟的明确串行队列等待。renderer invocation包含原生检查及加载，不是首个GPU推理时刻。

13:04:44 的时长修订版三语批准均与新 candidate及 launch manifest SHA匹配。请求文件没有事件时间，现有相关账本未找到同候选 identity+完成事件；launch manifest没有实际dispatch时间。因此这三语的 ready→批准和批准→首轮修订启动均报告缺失，不能用后续缓存复用 render开始时间代替。

## 2. 量化发布日志覆盖

有界样本：`zh-publication-v1`、`metadata-title-fix-v1`、`multilingual-publication-v2` 下深度≤4的控制receipt、中文final HTTP，以及4份原始KO/ES assets HTTP；排除 public快照、unit记录和大型音频审核/渲染子树。样本不是全部生产事件，也不是以副本数量估计部署次数。

| 指标 | 覆盖 | 缺失／异常 |
|---|---:|---:|
| 控制收据有顶层明确时间 | 15/56（26.8%） | 41/56 |
| HTTP收据有明确时间 | 5/27（18.5%） | 22/27 |
| 部署命令/catalog-deploy有时间 | 9/11 | 其中4份时间为继承旧文件，不可信作本次时间 |
| 部署收据包含部署版本字段 | 0/11 | 11/11（仅此有界样本；不代表外部日志绝无版本） |
| 新目录内deployment candidate路径指向本目录 | 5/9具candidate记录 | 4份指向旧ZH目录 |
| 初始批准hash链 | 6/6 | 0 |
| 初始ready事件hash链 | 5/6 | 中文全文缺少 |
| 初始口语调用链 | 3/3 | 首token时间不在此证据 |

### 确认的复制污染

同一份 deployment-command-receipt 原始 SHA `dd66b4c033de608e5227fa3e133835ce9ec39bfb86744f5abaea361944fe8038` 出现在5个目录：1份原始中文v4+4份后续副本。4份分别为metadata-title-fix/prod、asset-first-ko-es/prod、catalog prod-ko、catalog prod-es；仍写旧中文candidate与16:28:27.791511 UTC，不能作为各自新部署的完成时间或耗时。

另有 **6份**后续目录的 `final-http-receipt.json` 仍绑定旧catalog，与同目录public快照SHA不符（prod-ko/prod-es及dev-ko/dev-ko-v2/dev-ko-v3/dev-es-v3）。这不是最新资产HTTP失败，而是文件名看似final但身份过期。必须选择最终 `final-http-ko-es-receipt-v1.json`；脚本列出每份旧/新catalog SHA。

建议CLI复制候选时排除运行收据，将历史证据放独立只读history引用；完成时新建 attempt/environment/startedAt/finishedAt/deploymentVersion/catalogSHA/exitCode/HTTP证据。状态聚合必须校验SHA身份，不能按文件名或mtime选“最新”。

## 3. 原始HTTP、封装release与最后catalog绑定

最终prod和dev各15个记录文件，**30/30 HTTP文件SHA与对应本地public快照一致**；各3个Range共6/6记录为206。两份最终HTTP都没有verifiedAt/起止/部署版本字段，因此不能计算发布时间和耗时，也不能精确证明两次检查间隔。

KO/ES × prod/dev四份最终release：catalog releasePackageJsonSha256全部匹配release原始字节；release.httpVerification.evidenceSha256全部匹配对应原始 assets HTTP receipt（不是同目录继承旧receipt）；四份release各4个资产与原始HTTP、最终HTTP均匹配，合计16/16。原始assets receipt本身有18:12附近verifiedAt，可用于那次资产检查时间；不可改称最终catalog上线时间。

最终15项覆盖KO/ES资产、共享资源及catalog，未重新包含中文MP3/中文release。中文有独立v4 HTTP（16:28:45.647367 UTC）和后续metadata-title-fix的6项HTTP；不要把“最终每环境15项”扩写成同时重新验了全部三语所有文件。

## 4. 审核与真正验收边界

| 项目 | 收据支持的状态 | 不能推断 |
|---|---|---|
| 三语音频人审 | 各474个reviewedUnitIds；fullPlayback=approved；最终track SHA绑定；中文15:24:33，韩/西18:00:39决定 | 实际开始/结束聆听时间、真机整轨播放 |
| ASR机器筛查 | 三语human receipt均仍保留requires_review；人工逐疑点决策中文33、韩45、西38 | 不可把机器状态回写pass或把疑点数称为已确认错误数 |
| 视频同步 | 三语videoSync1x=not_run，另有publicationException | 不可声称32:22全轨视频同步通过 |
| 浏览器三语读回 | 18:22:23记录474、media readyState4/error null | 该收据三语playbackTest均not_run，不能说三语此轮已经播放验收 |
| 实体设备／现场 | final HTTP、release和browser receipt均not_run | native repository或模拟器截图不等于用户真机/现场验收 |

## 5. 现有报告抽查

`docs/reports/20261004-production-log-retrospective.zh.md` 与 `20261004-production-time-tokens.zh.md` 整体保留了失败、机器/人工、设备/现场的边界；未发现把最后HTTP pass直接写成真机验收通过。耗时报告也已提示旧deployment-command复制问题，本审计将其量化为4份副本并发现6份继承的旧final-http。

需更精确的表述：日志复盘第1节“这些数字证明连续拼接后的累计滞后”仅说明排程量，不足以暗示延迟必由大量短句累积；已有u172自身约61秒的局部异常，可在音频专项报告中单独分析。三语浏览器读回只能写目录/媒体就绪验证，因为对应playbackTest=not_run。不要把较早中/英浏览器片段播放扩大到后来KO/ES新版本。

## 证据索引

完整输入路径与原始SHA在 `metrics.json.evidence`。关键项：

| RUN相对路径 | SHA-256 |
|---|---|
| `RUN/formal-layer3-approved-v1/approval-manifest.json` | `ec5fb84680fede5c18748f393bec70a70c408eabc38b3c98b1d4a44c03b70db8` |
| `formal-layer3-execution-v1/native-job-preparation.json` | `62f6cd44a756ef28b045133d5fd5705a7838b3805bab6d8acfec85ae7f93eac4` |
| `formal-layer3-execution-driver-v1/queue.json` | `641150db2013c5f7996c59010e06e11fd951f129c50f35c4ff0d4e24988afb81` |
| `formal-layer3-execution-driver-v1/snapshot-122126.json` | `7958a3e1c6720c11034ac9d8a5de90c1f5cb5851f8097b691c72ab23701404de` |
| `metadata-title-fix-v1/prod/deployment-command-receipt.json` | `dd66b4c033de608e5227fa3e133835ce9ec39bfb86744f5abaea361944fe8038` |
| `metadata-title-fix-v1/prod/final-http-receipt.json` | `0850de21aea8b86f7b7f0839158bd7284cf52af559b5d7e46bc9022b8681cd0e` |
| `multilingual-publication-v2/catalog-ko-es-v1/prod-es/final-http-ko-es-receipt-v1.json` | `edca40a09691b30ee2db8a6d83a6717c5b7abd75eb9a753f552b5beb22067712` |
| `multilingual-publication-v2/catalog-ko-es-v1/dev-es-v3/final-http-ko-es-receipt-v1.json` | `003e499c61d0a02ed7cfe5ff9a752ebcb6f0ffea8c5219e70a8c17ac1ef3a601` |
