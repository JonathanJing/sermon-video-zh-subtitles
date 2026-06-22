# 安全政策

English version: [SECURITY.md](./SECURITY.md)

## 敏感数据

不要提交：

- OpenAI、Gemini、OpenRouter、YouTube、Bible API、告警或监控 API key。
- OAuth client secret、cookies、bearer token、service account JSON key 或 webhook URL。
- 生成的证道转写、生成字幕、模型输出 JSONL、私有音视频或授权经文全文。
- 暴露 secret value 的 GCS manifest，或在 public browser artifact 中暴露 Secret Manager resource name。

运行时 secret 应进入 Google Secret Manager，并通过权限最小化的 Cloud Run service account 读取。

## 报告方式

如果发现漏洞或误提交 secret，请优先使用 GitHub private security advisory；如果不可用，请直接联系仓库 owner。不要在公开 issue 中粘贴 secret、攻击细节、私有媒体或生成转写内容。

如果 secret 已暴露：

1. 立即在对应 provider 撤销或轮换。
2. 从本地 artifact 和日志中移除该值。
3. 审计 GCS、Cloud Run logs、Firestore 和生成的 playback 文件。
4. 如果暴露来自代码路径，补充回归测试或文档 guard。

## 平台与版权边界

本项目不得绕过平台访问控制、DRM 或服务条款。生产输入源应来自公开页面/直播、明确授权的音视频，或 operator 自己提供的实时音频。
