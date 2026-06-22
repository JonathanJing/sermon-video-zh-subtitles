# 文档索引

<p>
  <a href="./README.md">
    <img src="https://img.shields.io/badge/Language-English-blue" alt="English Documentation" />
  </a>
</p>

这里收集证道中文字幕 pipeline 的产品目标、系统设计、研究报告、backlog 和测试审查文档。

## 核心文档

- [中文 System Design](./system-design.zh.md)
- [中文 Findings Report](./findings-report.zh.md)
- [中英文 YouTube 证道字幕 pipeline 分析](./youtube-sermon-subtitle-pipeline-analysis.zh-en.md)
- [开发 Backlog](./backlog.md)
- [Development Notes](./development-notes.md)
- [Review / Testing Notes](./review-testing.md)

## 推荐阅读顺序

1. 先读根目录 [中文版 README](../README.zh.md)，了解产品目标和 POC 命令。
2. 再读 [system-design.zh.md](./system-design.zh.md)，理解 11:30 会众字幕架构。
3. 用 [backlog.md](./backlog.md) 选择下一步开发任务。
4. 在做 GCS 或 Cloud Run 生产式测试前，读 [review-testing.md](./review-testing.md)。

## 文档语言策略

repo 默认入口使用英文，便于 GitHub 浏览和协作；中文说明通过 README 顶部按钮进入。较深入的产品和 operator 文档会保留中文版本，因为这个项目的核心使用场景是服务中文会众。
