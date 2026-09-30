# Canonical package 只读检查

`python scripts/inspect_canonical_packages.py --config inspection.json` 输出
Source → 各语言 Text → Audio → Page 的 shadow proposal。它不 dispatch、写入
批准记录、启动模型、发布页面或修改作业状态。Page 的 `ready` 只表示其前置
package 和所需 receipt 已验证；Layer 4 产物检查仍未接入。

`sermon-canonical-package-inspection-config-v1` 保留 Source/Text 行为。
新增 v2 允许各 locale 配置 `audio`；v1 不接受该字段。两版均不从 progress
ledger 推导完成状态。所有路径相对配置文件，或使用绝对路径。

```json
{
  "schemaVersion": "sermon-canonical-package-inspection-config-v2",
  "source": "english-source.json",
  "anchor": "anchors.json",
  "locales": {
    "ko": {
      "policy": "ko/policy.json",
      "candidate": "ko/candidate.json",
      "humanReview": "ko/text-review.json",
      "audio": {
        "job": "ko/job.json",
        "adapter": "ko/adapter.json",
        "registry": "voice-registry.json",
        "clipTimelineMap": "timeline.json",
        "clipVoiceAuthorization": "voice-authorization.json",
        "clipVoiceCapability": "voice-capability.json",
        "renderManifest": "ko/render-manifest.json",
        "artifactRoot": "ko/artifacts",
        "package": "ko/audio-package.json",
        "humanReview": "ko/audio-review.json",
        "screening": "ko/asr-screening.json"
      }
    }
  }
}
```

`locales` 可选择 `zh-Hans`、`ko`、`es` 的非空子集。Audio 的 source、anchor、
candidate、policy 和 Text human receipt 由已验证的上游 lane 提供，不能在
`audio` 中另行覆盖。生产 source voice 授权路径可使用现有 producer 支持的
`sourceVoiceAuthorization`；具体授权组合仍由原有 speech-job validator 检查。

Audio adapter 使用 `build_target_language_audio_package.build_package` 在内存
重建 package，核对现有音频的 hash、decode、unit receipt、时间表、字幕、
job 与声线授权。重建结果不会写回；必须另有已保存且一致的 Audio Package。
这会运行本机 ffprobe/ffmpeg 的只读媒体检查，完整视频可能耗时；不是 TTS。

`candidate` / `machine_screened` 仅提供机器产物证据，Page 保留
`audio_listening_review`。`human_reviewed` 必须同时有独立 v1/v2 receipt，
绑定同一 package/track/locale/reviewer/时间/unit 集合，并明确批准完整试听与
1× 同视频同步。v2 还核验完整 ASR screening 与逐项人工 adjudication。
没有音频、receipt 过期或文件损坏均不能自动变成 `audio_unavailable`。
显式 text-only plan 与 audio-unavailable package 的 adapter 尚未接入。

输出只有 hash、固定诊断码与状态，不含原文、私有路径或 receipt 正文。
`stateRevision` 包含本次读取的配置/package/receipt 身份。当前接口用于观察；
未来 executable adapter 仍须在现有 durable admission lock 内重新校验全部
身份、批准与预算，不能把 shadow proposal 当执行授权。

本地证据来自 synthetic WAV、真实 package builders 和 validators；测试夹具中的
批准仅限 synthetic 数据。它不代表真实内容试听、真机、现场、Stage 1–3 或发布验收。
