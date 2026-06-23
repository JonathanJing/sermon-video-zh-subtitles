# 证道视频中文字幕

<p>
  <a href="./README.md">
    <img src="https://img.shields.io/badge/Language-English-blue" alt="English README" />
  </a>
  <a href="./LICENSE">
    <img src="https://img.shields.io/badge/License-MIT-green" alt="MIT License" />
  </a>
</p>

这个项目用于在 Mariners Church 周日 11:30 PT 场证道中，为正在听道的中文会众提供可使用的中文字幕，让中文会众可以在证道进行时跟上信息。

这是一个独立开源项目，并非 Mariners Church 官方项目，也不代表 Mariners Church 背书或运营。

这个 repo 正在为更广泛的开源协作做准备。欢迎大家一起帮助完善，尤其是字幕质量、生成延迟、经文术语、手机/平板 UX、部署可靠性、测试和文档。

## 产品北星

这个项目的核心目标不是只做事后归档，也不是单纯翻译视频。核心目标是：

```text
到 11:30 PT 场证道开始时，中文会众应该已经有一个可用的字幕体验，帮助他们实时听懂正在被传讲的信息。
```

所有实时链路、离线链路、UI、存储和导出工作，都应该用“是否改善 11:30 会众现场听道体验”来评估。

## 当前重点

- 在 11:30 PT 会众需要字幕之前，准备可用的中文字幕。
- 优先使用 11:30 PT 之前最早可验证的同篇 Mariners live service 作为准备源，10:00 PT 作为保守默认。
- 让 operator 监控 readiness，复核关键术语/经文，并在 11:30 场前发布字幕。
- 生成内容物进入 GCS，便于 Cloud Run 和生产式流程使用。
- API/model key 存在 Google Secret Manager；public browser 文件和生成物不能包含 key 明文或 Secret Manager resource name。
- 离线处理、笔记、金句提取作为质量复核、归档和后续改进功能。

## 关键发现

根据当前 Mariners Church YouTube 公开视频 metadata 分析，等待公开视频 VOD 出现无法满足周日 11:50 PT 前完成字幕的目标。近期主证道视频通常在 12:28-12:43 PT 公开，中位数约 12:31 PT。

更可行的输入是官方 live service。Mariners Online 列出周日直播时间为 7:00、8:30、10:00、11:30 AM PT。系统设计因此选择从最早可验证的同篇早场直播准备字幕，将 10:00 PT 作为保守生产默认，并将公开视频 VOD 作为后续离线质量补齐源。

## 文档

| 主题 | English | 中文 |
|---|---|---|
| 文档索引 | [docs/README.md](docs/README.md) | [docs/README.zh.md](docs/README.zh.md) |
| System Design | [docs/system-design.md](docs/system-design.md) | [docs/system-design.zh.md](docs/system-design.zh.md) |
| System Design 实现差距审计 | [docs/system-design-gap-analysis.md](docs/system-design-gap-analysis.md) | [docs/system-design-gap-analysis.zh.md](docs/system-design-gap-analysis.zh.md) |
| Findings Report | [docs/findings-report.md](docs/findings-report.md) | [docs/findings-report.zh.md](docs/findings-report.zh.md) |
| 模型/Provider 比较 | [docs/model-provider-comparison.md](docs/model-provider-comparison.md) | [docs/model-provider-comparison.zh.md](docs/model-provider-comparison.zh.md) |
| Cloud Run 部署准备 | [docs/cloud-run-deployment-prep.md](docs/cloud-run-deployment-prep.md) | [docs/cloud-run-deployment-prep.zh.md](docs/cloud-run-deployment-prep.zh.md) |
| Admin 工作流 | [docs/admin-workflow.md](docs/admin-workflow.md) | [docs/admin-workflow.zh.md](docs/admin-workflow.zh.md) |
| 中文圣经来源 | [docs/scripture-source.md](docs/scripture-source.md) | [docs/scripture-source.zh.md](docs/scripture-source.zh.md) |
| 观测与日志 | [docs/observability.md](docs/observability.md) | [docs/observability.zh.md](docs/observability.zh.md) |
| 开源准备检查 | [docs/open-source-readiness.md](docs/open-source-readiness.md) | [docs/open-source-readiness.zh.md](docs/open-source-readiness.zh.md) |
| 周日 live test runbook | [docs/sunday-live-test-runbook.md](docs/sunday-live-test-runbook.md) | [docs/sunday-live-test-runbook.zh.md](docs/sunday-live-test-runbook.zh.md) |
| YouTube source analysis | [中英文报告](docs/youtube-sermon-subtitle-pipeline-analysis.zh-en.md) | [同一份中英文报告](docs/youtube-sermon-subtitle-pipeline-analysis.zh-en.md) |
| Backlog / Review | [docs/backlog.md](docs/backlog.md), [docs/review-testing.md](docs/review-testing.md) | [docs/backlog.zh.md](docs/backlog.zh.md) |

其他项目文件：

- [历史发布时间数据](data/mariners_church_sunday_sermon_publish_times.csv)
- [Live source findings 数据](data/mariners_church_live_source_findings.csv)
- [前端 operator 原型](web/)
- [Development notes](docs/development-notes.md)

## 运行前提

本地 POC 需要：

- Python 3.10 或更新版本。
- `yt-dlp` 已安装并在 `PATH` 中，用于公开视频 metadata 和字幕提取。
- 可以访问 POC 使用的公开源 URL。

如果要发布生成物到 GCS / 模拟 Cloud Run 流程，还需要：

- Google Cloud SDK `gcloud` 已安装并完成认证。
- 对目标 GCS bucket 有访问权限。
- 使用 Secret Manager resource name 配置模型/API key；不要传入 raw key。

## 运维与日志

Cloud Run API 和 worker 会把结构化 JSON 日志写到 stdout，并进入 Cloud Logging。当前日志覆盖直播采集触发、worker 阶段耗时、字幕可用时间、会众页面匿名设备访问。详见 [观测与日志](docs/observability.zh.md)，里面包含 event 名称、Cloud Logging 查询和设备数量统计的隐私边界。

## Live-Link POC

用直播归档链接准备网页播放模拟数据：

```bash
python3 scripts/prepare_live_link_playback.py \
  --live-url 'https://www.youtube.com/watch?v=FsUijL9uB1I'
```

然后打开 `web/index.html`，点击 `模拟播放`。页面会显示证道标题、直播链接状态，以及正在为 11:30 会众视图生成的字幕片段。

如果生成内容需要进入 Cloud Run / 生产式测试流程，可以上传到 GCS，并通过 Secret Manager 引用模型 API key：

```bash
python3 scripts/prepare_live_link_playback.py \
  --live-url 'https://www.youtube.com/watch?v=FsUijL9uB1I' \
  --gcs-bucket sermon-zh-artifacts \
  --gcs-prefix runs/2026-06-22/FsUijL9uB1I \
  --api-key-secret projects/PROJECT_ID/secrets/openai-api-key/versions/latest
```

脚本会把 report、VTT/SRT、playback data 和 `cloud-manifest.json` 上传到 GCS。Secret Manager resource name 只在运行时校验，不写入公开生成物；公开 artifact 只记录 `apiKeyMaterialIncluded=false` 和 `secretResourceNamesIncluded=false`。

底层调试时，也可以直接从直播归档链接提取证道字幕：

```bash
python3 scripts/offline_live_sermon_subtitles.py \
  --live-url 'https://www.youtube.com/watch?v=FsUijL9uB1I'
```

从 POC 输出生成浏览器播放模拟数据：

```bash
python3 scripts/build_playback_simulation.py \
  --report artifacts/offline-live-sermon-poc/report.json \
  --out web/playback-simulation.generated.js
```

如果当前只有英文字幕源，UI 会保留 English sidecar，并在中文行显示 `AI 中文待生成`，直到后续接入翻译模型。

## 开源安全边界

- 不提交 API key、cookies、生成转写、生成字幕、模型输出 JSONL、私有媒体或 service account JSON。
- 运行时 secret 进入 Google Secret Manager，详见 [Cloud Run 部署准备](docs/cloud-run-deployment-prep.zh.md)。
- 生成物进入 GCS 或本地忽略目录 `artifacts/`。
- 尊重平台权限、版权和服务条款。本项目不绕过访问控制或 DRM。
- repo 改成 public 前，先跑 [开源准备检查](docs/open-source-readiness.zh.md)。

## 贡献

见 [CONTRIBUTING.zh.md](CONTRIBUTING.zh.md)、[CONTRIBUTING.md](CONTRIBUTING.md)、[SECURITY.zh.md](SECURITY.zh.md) 和 [SECURITY.md](SECURITY.md)。适合先参与的方向包括字幕质量、provider benchmark、手机/平板阅读体验、经文匹配、部署自动化和 observability。

## License

MIT，见 [LICENSE](LICENSE)。

## Source Video

- 目标视频：[The Cure for Our Rebellion - Eric Geiger | Mariners Church](https://www.youtube.com/watch?v=V6OKiwbjDZE)
- Live archive candidate：[The Cure for Our Rebellion - Eric Geiger | Mariners Church](https://www.youtube.com/watch?v=FsUijL9uB1I)
- Channel：[Mariners Church](https://www.youtube.com/@marinerschurch)
