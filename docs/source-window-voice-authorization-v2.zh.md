# 已批准来源片段的声音授权 v2

本次迁移只补充真实来源窗口与用途的表达。它不创建用户许可、文字批准、声音能力听审或音频验收，也不修改已发布页面、旧收据或 renderer 声音身份。

## 版本与绑定

- [source-user-voice-attestation v1](../schemas/sermon-source-user-voice-attestation-v1.schema.json) 与 [source-voice-authorization v1](../schemas/sermon-source-voice-authorization-v1.schema.json) 保留原义：完整媒体的 `0 .. media.durationSeconds`，用途同时包含正式音频和页面。
- 新 [attestation v2](../schemas/sermon-source-user-voice-attestation-v2.schema.json) 与 [authorization v2](../schemas/sermon-source-voice-authorization-v2.schema.json) 显式记录 `sourceId`、原媒体 SHA、`mediaDurationSeconds` 和真实 `approvedWindow`。窗口满足 `0 <= start < end <= duration`，两端必须与源包现有人工批准窗口一致。媒体时长仍为原媒体时长，不得改成截取长度。
- `source_approved_window_formal_audio_only` 必须且只能对应 `authorizedUses=["formal_audio_generation"]`；`source_approved_window_formal_audio_and_page_only` 必须对应 `authorizedUses=["formal_audio_generation", "formal_page_publication"]`。不能只改 scope 或把音频批准推断成页面批准。
- 收据与 attestation 必须同版本，且声音、locale、checkpoint、来源、窗口、用途一致。收据继续绑定源包及确切候选 canonical SHA、原始 attestation 文件与 JSON SHA。

现有 `prepare_target_language_speech_job.prepare_source_voice_authorization` 根据真实 attestation 版本生成同版本派生收据。旧目录不可覆盖；新候选/新权限产生新收据。调用方必须先具备真实、范围准确的原始授权，生成器不会替用户补一份授权。

Speech Job 继续使用 **v2**，Audio Package 继续使用 **v1**：job 的 `sourceVoiceAuthorization` 原本就是通用、带 hash 的 `jsonArtifact` 引用，没有内嵌 v1 授权 schema，所以不需要修改 job schema。实际 consumer 按引用内容的版本严格分派。已人工批准的文字、独立同 hash 收据、registry 授权、locale capability 或合法既有 capability reuse、clip timeline、checkpoint 与三项音频策略仍照常校验。

## L4 命令迁移

以下新页面准备/暂存入口现在必须为每个 locale 提供原音频使用的 `--speech-job LOCALE=PATH`：

- `scripts/build_formal_dev_release_assets.py`
- `scripts/stage_formal_multilingual_dev.py`
- `scripts/build_full_video_app_release.py prepare`

例如在原命令中追加：

```sh
--speech-job zh-Hans=/absolute/zh-Hans/job.json \
--speech-job ko=/absolute/ko/job.json \
--speech-job es=/absolute/es/job.json
```

每个 job 必须与该 Audio Package 的 `targetLanguageSpeechJobJsonSha256` 完全相等。入口重新读取 job 绑定的源包、锚点、候选、policy、人审、registry 和授权及 attestation；不能传一个拥有更宽授权的新 job 去替代真实生成 job。人工音频批准不扩展声音使用许可。

`sourceVoiceAuthorization` v1/v2 都必须包含 `formal_page_publication` 才能准备页面。v2 audio-only 可继续正式 L3，但在 Dev 页面与正式发布两类入口均拒绝。既有 `clipVoiceAuthorization` 的 `*-dev-app-and-audio_only` 只在两个明确 Dev 入口保留其原范围；`build_full_video_app_release.py prepare` 不将它当成正式页面许可。

只读 canonical inspection 从已配置的 `locales.<locale>.audio.job` 取得同一个原 job，无需新增 release inspection 字段。缺失原 job 或任一绑定改变时，新 L4 检查失败；旧静态 catalog/page 的读取与部署封装不在此次迁移范围内。

## 验证范围

定向测试覆盖合法非零窗口的真实 speech-job 准备、v1完整媒体兼容、v2 AudioPackage真实构建、既有 scoped demo capability、仅音频拒绝页面、原 job 与完整证据链绑定，以及越界/反向窗口、来源、媒体、时长、locale、speaker/checkpoint、candidate、receipt版本与scope/用途不匹配。所有新增审批数据只存在于合成测试临时目录；没有产生真实审批或执行 TTS。
