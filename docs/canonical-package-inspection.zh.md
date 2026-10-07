# Canonical package 只读检查

`python scripts/inspect_canonical_packages.py --config inspection.json` 输出
Source → 各语言 Text → Audio → Page 的 shadow proposal。它不 dispatch、写入
批准记录、启动模型、发布页面或修改作业状态。Page 的 `ready` 只表示其前置
package 和所需 receipt 已验证；v3 可继续验证现有 formal-dev Layer 4 candidate。

译文门（`translation_review`）和试听门（`audio_listening_review`）可以由机器质检豁免满足；这时批准记录带 `kind=machine_quality_waiver`，节点状态多一项 `waivedGates`，列出由豁免而不是人工批准满足的门。没有 `kind` 的仍是人工批准，未知的 `kind` 不满足任何门。豁免不改变其余状态，也不是人工批准。

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

## v3：已有 formal-dev Release candidate

v3 保留 v1/v2 原有行为，在顶层增加必填 `pageId`，各 locale 可增加：

```json
{
  "release": {
    "package": "ko/release.json",
    "assetRoot": "prepared/assets",
    "contentReview": "ko/content-review.json"
  }
}
```

此时 `schemaVersion` 使用 `sermon-canonical-package-inspection-config-v3`。
只有 Source/Text/Audio 和独立试听 receipt 已通过，才检查 Release。调用的
`stage_formal_multilingual_dev.validate_release_assets` 是现有 preflight 共用
的只读函数：检查本地 candidate 身份、content/audio/captions 三种 asset 的
固定路径与 hash、已测量时间表、逐句文本，以及独立 metadata review 的绑定。
适配范围是现有 formal-dev content schema；完整阅读稿/短口播双候选 release
和其他 legacy 输出不被隐式视为兼容。

所有指定 locale 的 Page candidate 验证后可输出 `terminal_evidence_observed`，
代表本地 candidate 证据齐备；`productionAcceptance=not_evaluated`、
`deviceAcceptance=not_run`、`dispatchEnabled=false` 不变。该接口不验证线上
HTTP，也不采信 candidate 中自填的发布、设备或现场 pass。Release 本体、
metadata receipt 和资产身份均进入 revision，合法重建也产生新的 revision。
