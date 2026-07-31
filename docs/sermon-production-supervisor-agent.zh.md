# 证道阅读版生产 Supervisor Agent

## 结论

当前 post-live 阅读版 PDF 流程已经由一个单一的 OpenAI Agents SDK Agent 负责跨阶段监管：

- Cloud Scheduler 仍负责准时唤醒
- 现有 Python 脚本和 Cloud Run Job 仍负责确定性执行
- GCS state、run-status 和 QA JSON 仍是事实来源
- `Sermon Production Supervisor` 负责读取状态、选择下一步和调用受限工具
- operator 仍然必须人工确认证道开始和结束时间

Agent 不直接下载、裁剪、转录、翻译或渲染 PDF。它只能调用现有的、可测试和可恢复的工具层。

## 架构

```mermaid
flowchart TD
    A[Cloud Scheduler] --> B[production-supervisor endpoint]
    B --> C[Cloud Run Job: Supervisor Agent]
    C --> D[读取 backend-state / timeline / approval / run-status / QA]
    D --> E{recommendedAction}
    E -- run_timeline_probe --> F[确定性 timeline job]
    F --> G[requires_operator_review]
    G --> H[Operator 独立确认绝对 start/end]
    H --> I[写 operator-window-approval.json]
    I --> C
    E -- run_reading_pdf_generation --> J[确定性 reading-PDF pipeline]
    J --> K{阅读质量与 PDF QA 都 pass?}
    K -- 否 --> L[blocked / human review]
    K -- 是 --> M[complete]
```

## 代码入口

- Agent runner：`scripts/run_sermon_production_supervisor_agent.py`
- 确定性工具与状态契约：`scripts/sermon_production_supervisor.py`
- Timeline 工具：`scripts/run_post_live_timeline_job.py`
- 阅读版生成工具：`scripts/run_post_live_subtitle_generation.py`
- API 入口：`POST /api/admin/sundays/<date>/production-supervisor`

Python 依赖固定为：

```text
openai-agents>=0.19.1,<0.20
```

## 两种运行模式

### Shadow

Shadow 模式只向 Agent 暴露 `inspect_production_state`。

Agent 可以：

- 读取当前 production snapshot
- 解释 blocker
- 给出建议动作

Agent 不能：

- 启动 timeline job
- 启动 PDF generation
- 写人工审批

本地示例：

```bash
.venv/bin/python scripts/run_sermon_production_supervisor_agent.py \
  --sunday 2026-08-02 \
  --state-file artifacts/live-source-monitor/state.json \
  --work-root artifacts/post-live-runs \
  --gcs-bucket '' \
  --mode shadow \
  --out artifacts/sermon-production-supervisor/2026-08-02-shadow.json
```

### Execute

Execute 模式另外暴露两个受限工具：

- `run_timeline_probe`
- `run_approved_reading_pdf_generation`

这两个工具内部仍会验证当前状态。Agent 不能通过 prompt 强迫工具跳过状态门禁。

生产示例：

```bash
.venv/bin/python scripts/run_sermon_production_supervisor_agent.py \
  --sunday 2026-08-02 \
  --state-file 'gs://sermon-zh-artifacts-ai-for-god/sundays/live-source-monitor/backend-state.json' \
  --work-root /tmp/sermon-post-live-subtitles \
  --gcs-bucket sermon-zh-artifacts-ai-for-god \
  --gcs-prefix sundays \
  --api-key-secret 'projects/ai-for-god/secrets/openai-api-key/versions/latest' \
  --youtube-api-key-secret 'projects/ai-for-god/secrets/youtube-api-key/versions/latest' \
  --mode execute \
  --out /tmp/sermon-post-live-subtitles/2026-08-02/production-supervisor-report.json
```

## 人工时间窗审批

机器生成的 `suggestedWindow` 不能直接进入 PDF pipeline。

operator 独立观看完整录像后，使用同一个 runner 写审批：

```bash
.venv/bin/python scripts/run_sermon_production_supervisor_agent.py \
  --sunday 2026-08-02 \
  --state-file 'gs://sermon-zh-artifacts-ai-for-god/sundays/live-source-monitor/backend-state.json' \
  --work-root /tmp/sermon-post-live-subtitles \
  --gcs-bucket sermon-zh-artifacts-ai-for-god \
  --api-key-secret 'projects/ai-for-god/secrets/openai-api-key/versions/latest' \
  --approve-window \
  --start-time 00:29:35 \
  --end-time 01:00:55 \
  --approved-by 'Jony' \
  --approval-note '独立观看完整录像后确认' \
  --mode execute
```

审批文件同时绑定：

- Sunday 日期
- canonical source URL hash
- start/end time
- operator identity
- 当前 timeline report SHA-256

如果 source 或 timeline report 改变，旧审批自动失效。Agent 工具不接受模型提供的 start/end 参数，只能读取有效的审批文件。

## 状态决策

| 当前证据 | Supervisor 动作 |
|---|---|
| 没有 persisted URL | `wait_for_source` |
| 有 URL、没有 timeline report | `run_timeline_probe` |
| 直播还未结束 | `waiting_for_post_live` |
| 云端下载授权失败 | `operator_download_handoff` |
| Timeline 待审核、没有有效审批 | `request_window_approval` |
| 有有效审批 | `run_reading_pdf_generation` |
| 阅读质量或 PDF QA 失败 | `review_quality_failure` |
| GCS artifact 无法读取 | `restore_artifact_access` |
| Generation completed 且两个 QA 都 pass | `complete` |

`accessIssues` 与 “artifact missing” 分开记录。网络、凭据或 IAM 错误不会被误判为“尚未生成”。

## Scheduler / API 接入

Scheduler 配置脚本支持 `production-supervisor`：

```bash
python3 scripts/configure_live_source_scheduler.py \
  --project ai-for-god \
  --location us-west1 \
  --service-url 'https://sermon-zh-caption-web-...' \
  --job-id sermon-production-supervisor-shadow \
  --action production-supervisor \
  --sunday upcoming \
  --schedule '*/10 18-23 * * SAT' \
  --timezone America/Los_Angeles \
  --supervisor-mode shadow \
  --agent-model gpt-5.6
```

对应 endpoint：

```text
POST /api/admin/sundays/upcoming/production-supervisor
```

建议生产部署先运行 shadow mode。验证多周决策与人工 operator 判断一致后，再把 Scheduler payload 改为：

```json
{
  "mode": "execute",
  "model": "gpt-5.6",
  "maxTurns": 8
}
```

当 `ENABLE_INLINE_WORKER` 关闭时，API 只返回经过验证的 Agent command；实际长任务由 Cloud Run Job 执行。

## 完成标准

Agent 只能在以下证据同时成立时返回 `complete`：

- generation report 的 `status = completed`
- `reading-edition-v2/reading_quality_report.json` 为 `pass`
- `sermon_zh_en_reading.qa.json` 为 `pass`

部分转录、PDF 文件单独存在或模型口头判断都不能代表生产完成。

## 安全边界

- Agent 没有工具可以写人工审批。
- API/Scheduler 入口不能传 `startTime` 或 `endTime` 给 Agent。
- Secret resource name 只进入受控命令；raw secret 不进入报告。
- OpenAI trace 设置 `trace_include_sensitive_data=False`。
- Mutation tools 在 shadow mode 完全不暴露。
- GCS、网络或认证读取失败会 fail closed。
- 原有 QA 门禁、缓存和可恢复状态不因 Agent 接入而改变。
