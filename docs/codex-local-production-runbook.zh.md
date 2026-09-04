# Codex 本地周末生产 Runbook

## 生产边界

本周末开始采用 local-first hybrid：

- GCP Cloud Scheduler：只发现直播源并写入 GCS state
- GCS：保存 source、lease、run-status、timeline、审批、QA 和最终 PDF
- Codex 本地 automation：运行 Supervisor Agent 和确定性生产脚本
- Cloud Run Web：继续提供网页和公开交付入口

不再让 Cloud Run Job 负责 YouTube 下载和 post-live 重处理。

## 自动运行入口

```bash
.venv/bin/python scripts/run_codex_local_sermon_production.py --mode execute
```

默认配置：

- Sunday：按 `America/Los_Angeles` 计算当前或下一个周日
- state：`gs://sermon-zh-artifacts-ai-for-god/sundays/live-source-monitor/backend-state.json`
- work root：`artifacts/post-live-runs`
- report：`artifacts/sermon-production-supervisor/<Sunday>/latest.json`
- artifact bucket：`sermon-zh-artifacts-ai-for-god`
- OpenAI 与 YouTube Data API：通过 Secret Manager resource reference 读取
- operator 通知：通过 SendGrid Secret Manager resource reference 发送

## 每周模型与交付策略（2026-09-06 起）

未来每周使用 `gpt-6-astra`、`medium`：中文初译、阅读稿两轮编辑/审核及中文证道同行生成。现有 OpenAI provider 与 Secret Manager 配置继续使用；ASR 保持 `gpt-transcribe`。模型审核只标记机器审核，不等于人工 Gold 或周日双语提示词批准。

Supervisor 的 generation 命令固定传入上述参数及 `--export-sunday-context`。手动调用 `run_post_live_subtitle_generation.py` 时，翻译/阅读审核/证道同行也默认 Astra Medium；需要周日产物时显式加 `--export-sunday-context`。

双 PDF QA 通过后，在同一 run 的 `pipeline/sunday-context/` 导出：

- `saturday-segments.jsonl`：稳定英文及机器中文候选。
- `weekly-pack.json`、`manifest.json`：内容、目标周日、来源 hash、模型与有效期。
- `pack-readiness.json`：当前可用能力及降级原因。
- `message-identity-approval.json`、`asr-phrases.candidate.txt`：同篇确认状态与英文短语候选。

归档 `release_timestamp` 按洛杉矶时区确定来源日期；缺失时停止导出，要求通过 `--source-service-date` 提供核实过的日期，不用目标周日倒推来源日期。导出失败不能报告整次生产完成；这些结构化文件随两个 PDF 上传并验证远端 hash。旧周次不自动重做。

自动导出初始 `matchStatus=unknown`，不会把讲道窗口批准当成周六/周日同篇确认，也不会自动激活本地现场 pack。操作员确认同篇信息后，可按 exporter 的 `--message-approval` 与 `--message-match-status human_confirmed` 重新导出并检查 readiness；现场启动时仍要重新检查有效期与能力上限。

本机已创建定时跟进任务「每周周六双 PDF 与周日 Context Pack」：洛杉矶时间周六 18:00、20:00、22:00 执行检查/续跑，周日 08:00 补查。调度器同时唤醒的其他周末时段由任务提示词跳过；无变化时保持安静，需要人工窗口确认、失败或完成时才通知当前任务。此跟进通过命令行禁用 SendGrid 通知，仅在 Codex 内汇报。

## 周六运行

1. Cloud Scheduler 在直播窗口内尝试把 canonical YouTube URL 写入 GCS state。
2. Codex automation 在周六晚间周期性运行本地生产入口，并先从本地网络刷新同一份 GCS state；这是 Cloud Run 被 YouTube bot-check 阻断时的正式兜底。
3. Supervisor 取得 GCS lease，避免本地与回滚任务重复执行。
4. 直播仍是 `is_live` 时，本次运行安全退出。
5. 直播进入 `was_live/post_live` 后，本地 `yt-dlp` 下载音频并生成多阶段 timeline。
6. timeline 和建议窗口上传 GCS，流程停止在 `requires_operator_review`。

## 周日恢复

- 如果同一 Sunday 已经保存了周六直播链接，本地任务直接复用，不再运行 discovery，也不会覆盖该 source。
- 如果到周日仍没有已保存 source，本地 discovery 改用 `auto`，按 8:30、10:00 的顺序查找 Sunday service。
- 若设置了 `SERMON_YOUTUBE_COOKIES_FILE`，timeline 与人工批准后的 reading-PDF generation 会使用同一个本地 cookies 文件；路径只进入子进程参数并在 supervisor report 中脱敏。

## 人工确认

Operator 必须独立观看完整回放并确认绝对时间：

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

## 回滚

本地任务漏跑或机器不可用时：

1. 保留 GCS state，不修改或清空已捕获的 source。
2. 可以临时恢复 `sermon-sat-post-live-subtitles` Cloud Scheduler。
3. GCS lease 会阻止同一阶段重复并发。
4. 恢复前先检查是否已有本地 timeline 或 generation 在运行。
