# 开源准备检查

English version: [open-source-readiness.md](./open-source-readiness.md)

这个 repo 计划未来公开，让更多人一起帮助完善英文证道中文字幕支持。在把 GitHub repo 改成 public 之前，先跑完这份 checklist。

## 公开定位

- 项目必须描述为独立开源项目。
- 不暗示 Mariners Church 参与、背书或运营本项目。
- 保持产品北星清楚：帮助中文会众在 11:30 PT 证道进行时跟上信息。
- 欢迎贡献者改进字幕质量、延迟、无障碍体验、手机/平板 UX、部署可靠性、经文术语和文档。

## Repo Metadata

建议 GitHub description：

```text
Open-source pipeline and PWA for usable Chinese captions during Sunday English sermons.
```

建议 topics：

```text
sermon, subtitles, captions, chinese, translation, accessibility, pwa, cloud-run, gcs, openai, gemini
```

在下面检查通过前，repo 先保持 private。

## 安全检查

- 公开前 `git status --short` 是干净的。
- 没有 tracked `.env`、cookies、service-account JSON、provider API key、OAuth secret、bearer token、webhook URL 或私有媒体。
- 生成的转写、字幕、模型 JSONL 和证道媒体没有被 tracked。
- Public browser 文件不包含 raw secret value 或 Secret Manager resource name。
- 文档不发布 raw secret value。Secret Manager reference 使用 `projects/PROJECT_NUMBER/secrets/openai-api-key/versions/latest` 这类占位符。
- 已检查 GCS artifacts 和 Cloud Run logs，没有误暴露 secret 或不应公开的生成内容。
- `LICENSE`、`CONTRIBUTING.md`、`SECURITY.md` 及中文对应文件都存在。

## 本地命令

```bash
git status --short
git ls-files
git diff --check
python3 -m unittest discover -s tests
node --check web/app.js
```

快速检查 tracked 文件路径：

```bash
git ls-files | rg '(^|/)(artifacts|secrets|data/raw)/|\.env|cookies|service-account|credentials|generated\.js'
```

快速文本扫描：

```bash
rg -n 'sk-[A-Za-z0-9]|AIza[0-9A-Za-z_-]|OPENAI_API_KEY=|GEMINI_API_KEY=|OPENROUTER_API_KEY=|Authorization: Bearer|BEGIN PRIVATE KEY'
```

扫描结果是 review prompt。文档可以提到环境变量名，但绝不能出现真实 secret value。

## 适合贡献者开始的方向

- 改进证道词汇的中文术语一致性。
- 增加经文和专有名词翻译 test fixtures。
- 改进手机和平板上的字幕阅读体验。
- 增加 Cloud Scheduler 和 Cloud Run Job 部署示例。
- 增加 OpenAI、Gemini、OpenRouter 的 provider benchmark fixtures。
- 改进触发时间、字幕可用时间、匿名设备数量的 observability dashboard。
