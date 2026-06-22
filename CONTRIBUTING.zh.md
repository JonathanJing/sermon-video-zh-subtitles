# 贡献指南

谢谢你帮助改进证道中文字幕 pipeline。

## 项目目标

本项目的北星目标很实际：周日 11:30 PT 场证道进行时，中文会众应该能使用中文字幕听道。产品、模型、UI 和基础设施改动，都应该用是否改善这个现场体验来评估。

## 开发原则

- 不要把生成的证道内容、转写、字幕、模型输出、API key、cookies 或凭证提交进 Git。
- Provider key 和敏感 token 使用 Google Secret Manager。
- 生成物进入配置好的 GCS bucket，不进入仓库。
- 尊重平台权限和版权。不要加入绕过访问控制、DRM 或服务条款的代码或文档。
- 会众视图保持简单、低干扰；review 控制放在 operator 视图。
- 测试优先使用 deterministic fixture，不依赖实时网络。

## 文档语言

repo 默认使用英文入口，方便开源协作。中文文档与英文文档并列存放，文件名使用 `.zh.md`。

新增或重要修改公开文档时：

1. 先更新英文文档。
2. 再新增或更新中文对应文档。
3. 如果文档属于核心阅读路径，同时更新 `docs/README.md` 和 `docs/README.zh.md`。

## 本地检查

提交 PR 前运行测试：

```bash
python3 -m unittest discover -s tests
```

如果只是文档改动，也要确认链接指向真实文件，并确认没有 staged 的生成物。

## Pull Request Checklist

- 改动服务于 11:30 会众字幕目标。
- 没有提交 secret、cookies、原始转写、模型输出或大媒体文件。
- 涉及用户阅读路径时，英文和中文文档都已更新。
- 行为改动有对应测试。
- public browser bundle 不暴露 Secret Manager resource name 或 secret value。

安全问题或误提交 secret 的处理方式见 [安全政策](./SECURITY.zh.md) / [Security Policy](./SECURITY.md)。
