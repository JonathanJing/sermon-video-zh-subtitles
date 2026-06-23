# 文档索引

<p>
  <a href="./README.md">
    <img src="https://img.shields.io/badge/Language-English-blue" alt="English Documentation" />
  </a>
</p>

这里收集证道中文字幕 pipeline 的产品目标、系统设计、研究报告、backlog 和测试审查文档。

## 核心文档

| 主题 | English | 中文 |
|---|---|---|
| System Design | [system-design.md](./system-design.md) | [system-design.zh.md](./system-design.zh.md) |
| Findings Report | [findings-report.md](./findings-report.md) | [findings-report.zh.md](./findings-report.zh.md) |
| 模型/Provider 比较 | [model-provider-comparison.md](./model-provider-comparison.md) | [model-provider-comparison.zh.md](./model-provider-comparison.zh.md) |
| Cloud Run 部署准备 | [cloud-run-deployment-prep.md](./cloud-run-deployment-prep.md) | [cloud-run-deployment-prep.zh.md](./cloud-run-deployment-prep.zh.md) |
| 周日 live test runbook | [sunday-live-test-runbook.md](./sunday-live-test-runbook.md) | [sunday-live-test-runbook.zh.md](./sunday-live-test-runbook.zh.md) |
| YouTube source analysis | [youtube-sermon-subtitle-pipeline-analysis.zh-en.md](./youtube-sermon-subtitle-pipeline-analysis.zh-en.md) | 同一份中英文文档 |
| 开发 Backlog | [backlog.md](./backlog.md) | [backlog.zh.md](./backlog.zh.md) |
| Development Notes | [development-notes.md](./development-notes.md) | 同文件英文优先内容 |
| Review / Testing Notes | [review-testing.md](./review-testing.md) | 同文件英文优先内容 |

## 推荐阅读顺序

1. 先读根目录 [中文版 README](../README.zh.md)，了解产品目标和 POC 命令。
2. 再读 [system-design.zh.md](./system-design.zh.md)，理解 11:30 会众字幕架构。
3. 读 [findings-report.zh.md](./findings-report.zh.md)，理解为什么公开视频 VOD 不满足现场目标。
4. 做模型、Cloud Run 或 live-test 工作前，读 [model-provider-comparison.zh.md](./model-provider-comparison.zh.md)、[cloud-run-deployment-prep.zh.md](./cloud-run-deployment-prep.zh.md) 和 [sunday-live-test-runbook.zh.md](./sunday-live-test-runbook.zh.md)。
5. 用 [backlog.md](./backlog.md) 和 [review-testing.md](./review-testing.md) 选择与验证下一步开发任务。

## 文档语言策略

repo 默认入口使用英文，便于 GitHub 浏览和开源协作；中文文档与英文文档并列存放，文件名使用 `.zh.md`。如果文档改动影响产品行为、部署行为或 11:30 会众目标，应同步更新中英文版本。
