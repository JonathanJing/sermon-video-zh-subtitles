# Admin 工作流

English version: [admin-workflow.md](./admin-workflow.md)

这份文档描述的是一条已经 working 的支持路径，不是当前 repo 的主 operator 工作流。

当前主要工作流是稳定的 post-live 阅读版 PDF 路径，见：

- [../README.zh.md](../README.zh.md)
- [stable-post-live-reading-pdf-workflow.zh.md](./stable-post-live-reading-pdf-workflow.zh.md)
- [stable-post-live-reading-pdf-workflow.md](./stable-post-live-reading-pdf-workflow.md)

Admin 页面是周日字幕 readiness 的 operator 界面。它和普通会众页面分开，避免会众看到直播源、GCS、触发按钮、导出按钮和日志细节。

## 与主流程的关系

当你需要浏览器内的监控、模拟、手动触发或 readiness 检查时，使用 Admin 页面。

但不要把 Admin 页面上的一次触发或一次页面检查，当作整个工作流已经完成。当前稳定完成标准仍然是阅读版 PDF 路径：source 已保存、证道时间窗已人工确认、`sermon_zh_en_reading.pdf` 已生成、PDF QA 已通过、run report 已写出。

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
