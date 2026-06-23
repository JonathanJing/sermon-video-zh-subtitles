# Admin 工作流

English version: [admin-workflow.md](./admin-workflow.md)

Admin 页面是周日字幕 readiness 的 operator 界面。它和普通会众页面分开，避免会众看到直播源、GCS、触发按钮、导出按钮和日志细节。

## Route

- 会众页：`/`
- Admin 页：`/admin` 或 `/admin.html`

Admin 页面故意做成偏运维、信息密度较高的界面。主要设备是 desktop 和 iPad。手机可以做快速检查，但不是主要 operator 界面。

## Operator 可以检查什么

- 当前 Sunday slice。
- GCS bucket 和 prefix。
- caption manifest 状态。
- manifest 可用时的 sermon title 和 translation status。
- secret 只显示 `configured`、`missing` 或 `unknown`；不显示 raw key 或 Secret Manager resource name。
- 从直播源发现到会众页可用的生成阶段。
- `live_capture_triggered`、`worker_stage_completed`、`captions_ready`、page views 和 unique-device estimate 的日志证据标签。

## 手动触发

Admin 页面保留手动触发流程：

1. 输入 live/archive YouTube URL。
2. 可选输入证道大致开始时间，例如 `00:23:25`。
3. 选择 Sunday slice。
4. 点击 `手动触发`。

浏览器会发送：

```json
{
  "triggerSource": "operator",
  "liveUrl": "https://www.youtube.com/watch?v=...",
  "sermonStart": "00:23:25"
}
```

到：

```text
POST /api/admin/sundays/YYYY-MM-DD/generate
```

后端 endpoint 由 `OPERATOR_ADMIN_TOKEN` 或 `INTERNAL_TASK_TOKEN` 保护。当前浏览器页面不会暴露或要求输入这些 token。如果后端返回 `401`，Admin 页面会明确显示真实触发被 auth 阻止，并继续本地模拟，方便验证 UI。

## Read-Only Status Endpoint

Admin 页面读取：

```text
GET /api/admin/status
```

这个 endpoint 只返回安全的 runtime status：

- bucket 和 prefix
- 当前 Sunday
- timezone
- manifest summary
- caption summary
- provider label
- secret configured/missing 状态

它不能返回 raw API key、operator token、Secret Manager resource name、cookie 或 Authorization header。

## 会众页边界

普通会众页必须保持简单：

- 状态提示
- sermon title/status
- 字幕免责声明
- 英文听写原文
- 中文翻译字幕
- 完整字幕列表
- 经文/sidebar 内容

会众页不能显示 source discovery controls、manual trigger、导出按钮、GCS 设置、secret 状态或 operational logs。
