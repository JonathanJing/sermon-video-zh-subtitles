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
