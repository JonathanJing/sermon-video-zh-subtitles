# Codex 本地周末生产 Runbook

2026-09-11 安装与验收状态见 [Agents API 生产切换记录](agents-api-production-cutover-20260911.zh.md)：代码已安装，正式入口 shadow/execute 验收通过，每周调度已启用；当前等待目标周日匹配源。

## 生产边界

2026-09-11 起，本地生产入口默认使用 Agents API（Astra Medium），继续采用 local-first hybrid：

- GCP Cloud Scheduler：只发现直播源并写入 GCS state
- GCS：保存 source、lease、run-status、timeline、审批、QA 和最终 PDF
- Codex 本地 automation：唤醒本机入口；Agents API 管理 Supervisor 会话，本机执行确定性工具
- Cloud Run Web：继续提供网页和公开交付入口

不再让 Cloud Run Job 负责 YouTube 下载和 post-live 重处理。

2026-09-11 已退役旧 `sermon-post-live-timeline` Job；其配置、IAM 和执行记录保存在本地 `artifacts/evidence/gcp-cleanup-20260911/`。对应 `sermon-sat-post-live-subtitles` Scheduler 保持暂停，不能仅恢复调度就恢复云端生产。

## MFA 阅读对齐

新 reading 生产默认使用 MFA 词/音素对齐，替代字符比例估时。所有本地模型的目标路由为 **MacBook 优先、DGX Spark 备用**；MFA／G2P 优先使用本机独立环境，本机健康时不联系 Spark。备用默认启用，可用 `MFA_SPARK_FALLBACK=0` 或 `--no-mfa-spark-fallback` 禁用，远端使用独立的 `MFA_SPARK_*` 模型路径。远程可经 Tailscale 的 Mac mini relay。配置、ARM64 备用环境限制与缓存边界见 [MFA 生产接入](mfa-production.zh.md)。

备用仅处理运行环境或推理可用性故障；文字错误、未知音素、损坏对齐与待审核状态仍停止，不能通过切换机器绕过。MFA 时间仍为模型估计，句界来自冻结英文标点；源窗口审批与人工审核要求保持不变。代码路由不代表两端部署、真实推理或某周产物已验收。

OpenAI 云端转写与语言 API 保持不变。每周 TTS 和配音质检也采用 MacBook 优先、Spark 备用。MacBook MPS 已用授权讲员检查点完成 10 字中文单元的真实合成，输出 2.56 秒音频；短样本成功不代表整篇吞吐、音质或人工听审获准。媒体处理、排版和校验保留在调度端；无模型声音指纹匹配继续在听众浏览器内执行。

## 人工范围流程（2026-09-19 代码更新）

完整礼拜不再调用模型识别证道起止位置。当前顺序为：下载完整媒体 → ffprobe/完整性核验 → 操作员提供绝对起止时间 → 持久化审批 → 英文转写、中文翻译与双 PDF。纯证道来源沿用独立同视频入口；在归档入口也可人工确认 `0 → 完整片长`。`gpt-transcribe` 仅在后续内容转写等独立阶段使用。

新媒体准备报告使用 `schemaVersion=2`、`stage=source_media_verified`、`boundaryMethod=operator_supplied`，记录实测 `durationSeconds`、`audioSha256`、`audioSizeBytes`，`modelsUsed=[]`，不产生建议范围。审批写入及恢复校验均检查范围未超出实测时长，并继续绑定来源、周次和报告哈希。媒体子报告存为 `timeline/source-media-report.json`。

为兼容已有审批、租约和会话，`run_timeline_probe`、`resume_failed_timeline`、`timelineReportSha256` 与既有 job-report 路径保留旧名称；它们现在只对应媒体准备或旧证据读取。历史报告及仍有效的审批不自动迁移、覆盖或重跑。旧 `build_post_live_timeline.py` / `build_multistage_post_live_timeline.py` 明确拒绝执行，HTTP `timeline-probe` 返回 410；新 Scheduler 配置不再提供该 action 或模型参数。

删除旧模型配置会改变 Supervisor 会话配置指纹。自动入口会检查同目录其他配置的 active 指针；旧会话未确认远端终止、或仍有未结算工具时，停止并要求核对旧会话，不能以新配置绕过执行记录。部署升级前结束旧 runner；本次本地代码和离线测试不代表远端服务、已部署容器或调度已更新。

## 按现有状态续跑

先读取当前 source、timeline、approval、run status 和 QA；已有授权及仍与 source/timeline hash 匹配的人工审批可继续使用。只推进确定性状态允许的下一阶段，不为重新整理流程再次下载、付费生成或重复索取相同批准。独立资料审核可并行，持有同一 source lease 的生产阶段保持顺序执行。

每次时间线、生成和配音运行自动追加阶段耗时、API Token 与费用估算；失败及缓存复用分别记录。交付时同时检查账本覆盖缺口，不把未知用量记为零。文件位置、汇总命令及费用口径见[流程记账说明](workflow-accounting.zh.md)。对话内审核／人工听审等进程外阶段另列未记录项，不用媒体时长代替执行时长。

这些字段必须保存在本地 log 中，不能仅在对话结束时口头报告。每次完成或停止都保留执行摘要，并关联来源／版本、工作量、质量、审批、交付和恢复证据；尚未采集的指标明确注明。必记内容与现有采集边界见[日志内容规范](workflow-accounting.zh.md#已接入的指标与保留边界)。

排查最近一次执行：`.venv/bin/python scripts/sermon_logs.py artifacts/post-live-runs/YYYY-MM-DD/accounting --level WARNING`。需要完整事件去掉 `--level WARNING`；需要检查退出码加 `--check`。入口、阶段和子进程共享 `runId`，失败及业务等待状态保留在同一账本；详见[统一事件与错误追踪](workflow-accounting.zh.md#统一事件与错误追踪)。

## 自动运行入口

需要连同配音候选一起检查或顺序推进时，使用[周六统一入口](saturday-harness.zh.md)：默认只读，显式 `execute` 才调用现有生产阶段；不会自动替换当前定时任务。续租、超时、目录锁和远端结果核对见[执行保护与恢复](sermon-execution-harness.zh.md)。

```bash
.venv/bin/python scripts/run_codex_local_sermon_production.py \
  --mode execute --agent-backend agents-api \
  --notify-sendgrid-secret '' --notify-recipients-secret '' --notify-sender-secret ''
```

默认配置：

- Sunday：按 `America/Los_Angeles` 计算当前或下一个周日
- state：`gs://sermon-zh-artifacts-ai-for-god/sundays/live-source-monitor/backend-state.json`
- work root：`artifacts/post-live-runs`
- report：`artifacts/sermon-production-supervisor/<Sunday>/latest.json`
- artifact bucket：`sermon-zh-artifacts-ai-for-god`
- OpenAI 与 YouTube Data API：通过 Secret Manager resource reference 读取
- 本任务通知：命令中禁用 SendGrid，仅在 Codex 内报告；CLI 保留兼容配置，单独启用须有收件通知授权
- Supervisor：`gpt-6-astra` / `medium`，默认 `--agent-backend agents-api`；显式 `sdk` 为人工选择的回退，不在 API 失败后自动切换

## Agents API 会话与生产工具

模型只看到 ISO 周日日期、固定下一步枚举、source/timeline 是否存在、窗口审批/QA/发布是否通过和租约布尔值。完整路径、源 URL、讲稿、配置、日志及审批细节留在本机。API 使用 `environment: none`，不向远端沙箱上传仓库。

工具只允许检查状态、执行确定性状态允许的来源媒体准备、执行已有人工批准的双 PDF 生成，以及提交结构化决定。每次修改后必须重新检查；同一会话每阶段最多尝试一次，持久化结果防止重放。最终完成同时要求根 turn 完成、结构化输出齐全和新的本地生产证据通过。底层 lease、下载授权、QA、hash 与审批契约保持生效。

默认报告目录下的 `agents-api-runs/` 保存绑定指纹、session ID 和工具收据。未确认远端停止的 timeout/cancel ACK 不允许另开会话重置执行记录；异常停止先检查本地 `state.json`、`result.json` 与远端状态。需要显式续跑原会话时增加 `--agent-run-dir <原目录> --resume-agent-session`。保留 executing 工具记录时必须人工核实实际阶段结果，不删除记录重试。只有确认原会话终止、无未决工具且生产状态允许后才选择新会话或 SDK 回退。

`--mode shadow` 不刷新源、不执行生成、不恢复失败阶段。`execute` 的源刷新仍由本机确定性入口负责；已完成周次先走 completion latch，证据仍有效时无需模型调用。API usage 是 best-effort；账本记录 backend 与已知用量，缺失用量/金额保持 unknown。设计、恢复与验证详见 [Supervisor 设计](sermon-production-supervisor-agent.zh.md)。

## 每周模型与交付策略（2026-09-06 起）

未来每周使用 `gpt-6-astra`、`medium`：中文初译、阅读稿两轮编辑/审核及中文证道同行生成。现有 OpenAI provider 与 Secret Manager 配置继续使用；ASR 保持 `gpt-transcribe`。模型审核只标记机器审核，不等于人工 Gold 或周日双语提示词批准。

后续同行制作默认使用和合本（CUV）。英文来源冻结后、交付与配音前，按[和合本经文锁定与证道重译](sermon-cuv-production.zh.md)执行 `scripts/sermon_cuv_translation.py run`：识别直接经文、从固定库精确取文、锁定引用，再完成全篇翻译和独立审校。字幕、阅读 PDF、TTS 及大纲中的经文引用须采用同一份通过审校的锁定中文；大纲仍可概括讲解，不能作为配音稿。解释、玩笑和讲员错引保留为讲员话，不强改成经文；机器审核不授予人工批准。现有 Supervisor 不会自动调用此新步骤，须核对实际执行收据；重译后更新关联产物，并用新音频重新测量时长。

Supervisor 的 generation 命令固定传入上述参数及 `--export-sunday-context`。手动调用 `run_post_live_subtitle_generation.py` 时，翻译/阅读审核/证道同行也默认 Astra Medium；需要周日产物时显式加 `--export-sunday-context`。

双 PDF QA 通过后，在同一 run 的 `pipeline/sunday-context/` 导出：

- `saturday-segments.jsonl`：稳定英文及机器中文候选。
- `weekly-pack.json`、`manifest.json`：内容、目标周日、来源 hash、模型与有效期。
- `pack-readiness.json`：当前可用能力及降级原因。
- `message-identity-approval.json`、`asr-phrases.candidate.txt`：同篇确认状态与英文短语候选。

归档 `release_timestamp` 按洛杉矶时区确定来源日期；缺失时停止导出，要求通过 `--source-service-date` 提供核实过的日期，不用目标周日倒推来源日期。导出失败不能报告整次生产完成；这些结构化文件随两个 PDF 上传并验证远端 hash。旧周次不自动重做。

自动导出初始 `matchStatus=unknown`，不会把讲道窗口批准当成周六/周日同篇确认，也不会自动激活本地现场 pack。操作员确认同篇信息后，可按 exporter 的 `--message-approval` 与 `--message-match-status human_confirmed` 重新导出并检查 readiness；现场启动时仍要重新检查有效期与能力上限。

2026-09-11 迁移检查发现旧文档所述任务未出现在本机自动化清单；用户明确授权后已创建并回读核验 ACTIVE 跟进任务「每周周六双 PDF 与周日 Context Pack」（ID：`pdf-context-pack`）：洛杉矶时间周六 18:00、20:00、22:00 执行检查/续跑，周日 08:00 补查。调度器同时唤醒的其他周末时段由任务提示词跳过；无变化时保持安静，需要人工窗口确认、失败或完成时才通知当前任务。此跟进通过命令行禁用 SendGrid 通知，仅在 Codex 内汇报。

## 周六运行

1. Cloud Scheduler 在直播窗口内尝试把 canonical YouTube URL 写入 GCS state。
2. Codex automation 在周六晚间周期性运行本地生产入口，并先从本地网络刷新同一份 GCS state；这是 Cloud Run 被 YouTube bot-check 阻断时的正式兜底。
3. Supervisor 取得 GCS lease，避免多个生产实例重复执行。
4. 直播仍是 `is_live` 时，本次运行安全退出。
5. 直播进入 `was_live/post_live` 后，本地 `yt-dlp` 下载完整音频，检查媒体完整性并记录实测时长与哈希。
6. 来源媒体报告上传 GCS，流程停止在 `requires_operator_review`，等待操作员提供并确认起止时间。

## 周日恢复

- 如果同一 Sunday 已经保存了周六直播链接，本地任务直接复用，不再运行 discovery，也不会覆盖该 source。
- 如果到周日仍没有已保存 source，本地 discovery 改用 `auto`，按 8:30、10:00 的顺序查找 Sunday service。
- 若设置了 `SERMON_YOUTUBE_COOKIES_FILE`，timeline 与人工批准后的 reading-PDF generation 会使用同一个本地 cookies 文件；路径只进入子进程参数并在 supervisor report 中脱敏。

## 人工确认

缺少有效窗口审批或绑定的 source/timeline 已改变时，Operator 必须独立观看完整回放并确认绝对时间；已存在匹配审批时直接续跑：

```bash
.venv/bin/python scripts/run_sermon_production_supervisor_agent.py \
  --sunday YYYY-MM-DD \
  --state-file 'gs://sermon-zh-artifacts-ai-for-god/sundays/live-source-monitor/backend-state.json' \
  --work-root artifacts/post-live-runs \
  --gcs-bucket sermon-zh-artifacts-ai-for-god \
  --api-key-secret 'projects/ai-for-god/secrets/openai-api-key/versions/latest' \
  --youtube-api-key-secret 'projects/ai-for-god/secrets/youtube-data-api-key/versions/latest' \
  --approve-window \
  --start-time HH:MM:SS \
  --end-time HH:MM:SS \
  --approved-by Jony \
  --content-scope sermon_only \
  --approval-note '独立观看完整录像后确认' \
  --mode execute
```

下一次 Codex automation 会读取有效审批并启动阅读版生成。

## YouTube 下载授权

先尝试公开回放，不读取浏览器 cookies。

若本地也出现 `waiting_for_download_access`，operator 可以明确提供已授权导出的 Netscape cookies 文件：

```bash
export SERMON_YOUTUBE_COOKIES_FILE=/absolute/path/youtube.cookies.txt
```

不要把 cookies 文件加入 Git、GCS artifact 或 automation prompt。

## 完成标准

只有下列条件同时满足才是生产完成：

- generation report `status=completed`
- `reading-edition-v2/reading_quality_report.json` 为 `pass`
- `sermon_zh_en_reading.qa.json` 为 `pass`
- `sermon_interpretation_zh.qa.json` 为 `pass`
- 阅读版 PDF 和证道解读 PDF 都已上传 GCS
- 当前人工审批仍与 source URL 和 timeline SHA-256 匹配
- generation 的 `publication.status=pass`，已验证本地/远端要求产物的 hash 一致；配置周日导出时也包含该批 Context Pack/readiness 产物

Supervisor 以新读取的 `snapshot.recommendedAction.action == "complete"` 为最终完成判断；其实现位于 [sermon_production_supervisor.py](../scripts/sermon_production_supervisor.py)。不要另列更宽松的模型口头标准。

## 本地恢复与云端重建

本地任务漏跑或机器不可用时：

1. 保留 GCS state，不修改或清空已捕获的 source。
2. 先检查是否已有 timeline 或 generation 在运行，并核对 GCS lease；不要绕过现有租约或清空审批。
3. 在已配置的可用本机上按现有状态续跑，复用仍有效的 source、timeline 和人工审批。
4. 若确需恢复云端执行，先使用留存配置和可用容器镜像重建、验证 Job，再考虑恢复 `sermon-sat-post-live-subtitles` Scheduler。旧 Job 已删除，本次退役没有进行云端重建或运行验证。
