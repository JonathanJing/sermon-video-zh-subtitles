# 观测与日志

目标：周日 11:30 场前后，可以从 GCP 日志知道三件事：

1. 直播采集什么时候被 Cloud Scheduler / Cloud Tasks / operator 触发。
2. 字幕什么时候生成并发布为会众可用状态。
3. 有多少不同设备打开了会众字幕网页。

## 结构化日志事件

所有后端、worker、promotion 日志都以 JSON 写到 stdout，Cloud Run / Cloud Run Jobs 会进入 Cloud Logging。

| Event | 来源 | 用途 |
|---|---|---|
| `live_source_monitor_completed` | `POST /api/admin/sundays/YYYY-MM-DD/discover-source` 或 `scripts/live_source_monitor.py` | 记录找源结果、选中的 service/source kind、fallback/operator alert 状态和候选数量。 |
| `live_capture_triggered` | `POST /api/admin/sundays/YYYY-MM-DD/generate` | 记录直播采集被触发，包含 `triggerSource`、`sunday`、`sessionId`、`runPrefix`、live source 摘要。 |
| `live_capture_planned` | API inline worker 关闭时 | 记录后端已生成 worker plan，适合 Cloud Scheduler 只负责排队/计划的模式。 |
| `live_capture_worker_started` | `python -m backend.worker` | 记录 Cloud Run Job / 手动 worker 真正开始跑。 |
| `worker_stage_started` / `worker_stage_completed` | API inline worker 或 Cloud Run Job | 记录 prepare、translate、upload、promote 各阶段开始/完成。 |
| `captions_ready` | worker 完成或 `promote_sunday_manifest.py` | 记录字幕已经 promotion 到稳定 Sunday manifest，可供会众页读取。 |
| `congregation_page_view` | 会众网页加载时 | 记录匿名设备访问，包含 `anonymousDeviceId`、`visitId`、viewport、timezone、language、viewMode。 |

## 触发来源识别

`triggerSource` 优先使用请求 payload 中的 `triggerSource` / `trigger_source`。如果没有，后端会根据 header 推断：

- `cloud-scheduler`
- `cloud-tasks`
- `internal-task`
- `operator`

Cloud Scheduler 建议请求 payload 中显式带上：

```json
{
  "triggerSource": "cloud-scheduler",
  "service": "auto",
  "operatorAlertTime": "09:58",
  "autoGenerate": true
}
```

## Cloud Logging 查询

直播采集触发：

```text
resource.type="cloud_run_revision"
jsonPayload.event="live_capture_triggered"
jsonPayload.sunday="2026-06-28"
```

找源结果：

```text
resource.type="cloud_run_revision"
jsonPayload.event="live_source_monitor_completed"
jsonPayload.sunday="2026-06-28"
```

字幕可用时间：

```text
resource.type=("cloud_run_revision" OR "cloud_run_job")
jsonPayload.event="captions_ready"
jsonPayload.sunday="2026-06-28"
```

会众页面访问：

```text
resource.type="cloud_run_revision"
jsonPayload.event="congregation_page_view"
jsonPayload.viewMode="congregation"
jsonPayload.sunday="2026-06-28"
```

## 设备数量

普通会众页会在浏览器 `localStorage` 中生成一个匿名 `anonymousDeviceId`。这不是用户登录身份，只用于估算不同设备/浏览器数量。

如果启用 Cloud Logging Log Analytics 或 BigQuery sink，可以按 `anonymousDeviceId` 去重：

```sql
SELECT
  COUNT(DISTINCT jsonPayload.anonymousDeviceId) AS unique_devices,
  COUNT(*) AS page_views
FROM `PROJECT.DATASET._AllLogs`
WHERE jsonPayload.event = "congregation_page_view"
  AND jsonPayload.viewMode = "congregation"
  AND jsonPayload.sunday = "2026-06-28";
```

## 隐私与安全

- 不记录 raw API key、Secret Manager resource name、cookie、Authorization header。
- live URL 只记录 host/path 和 hash，不记录完整 query。
- IP 和 user agent 只记录 hash。
- 设备 ID 是随机匿名 ID，按浏览器 profile 存储；卸载浏览器数据后会重新生成。
