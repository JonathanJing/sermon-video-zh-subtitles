# 固定 Layer 3 adapter 与恢复

统一 owner 使用 `scripts.sermon_unified_audio.inspect(config_path)` 生成计划，随后调用
`execute(config_path, output_path, expected_plan_hash=plan["planHash"], allow_synthesis=...)`。
配置只选择数据和白名单设置，不支持命令、shell、任意模块或 argv。

## 配置

```json
{
  "schemaVersion": "sermon-unified-audio-job-v1",
  "paths": {
    "source": "source.json",
    "anchor": "anchors.json",
    "candidate": "candidate.json",
    "job": "render/job.json",
    "adapter": "adapter.json",
    "policy": "policy.json",
    "human_receipt": "translation-human-review.json",
    "registry": "speaker-registry.json",
    "clip_timeline_map": "timeline.json",
    "source_voice_authorization": "voice-authorization.json"
  },
  "checkpointMap": "checkpoint-map.json",
  "audioOperationPolicies": "audio-operation-policies.json",
  "settings": {
    "assemblyOnly": true,
    "seed": 42,
    "batchSize": 8,
    "replicas": 8,
    "device": "cuda:0",
    "dtype": "bfloat16",
    "attention": "sdpa",
    "trackFormat": "mp3",
    "maxSynthesisUnits": 0
  }
}
```

路径相对配置文件。`unitInstructions`、`strictRubric`、`reuseFrom` 可选。
`paths` 也支持原 renderer 的 clip voice authorization/capability。
示例中的声音设置须替换为该任务原来冻结的设置；已有 CUDA/batch cache 在 CPU
机器执行 assembly-only 时仍保留原 sound identity，不能把 `device` 改成 CPU。

- inspect 只读检查正式 job、上游人工文字批准、声音授权、输入 hash 和已有 WAV 收据。
- `assemblyOnly` 默认 true；必须全部 committed cache，缺任何单元均拒绝，不加载模型。
- 新合成要求配置 `assemblyOnly=false`、显式单位预算，且 owner 传入 `allow_synthesis=True`。
- 预算在 renderer 锁内重新检查。batch 缺项需重放完整固定窗口，预算包含未缺邻居的计算；旧提交不覆盖。
- 初始审核与输入快照每 attempt 执行一次；逐 WAV 仍完整解码，逐项绑定 job/text/locale/hash。
  依赖的 inode/size/mtime/ctime 在单元间检查，结束时再次核验全部 hash。
- 同步使用原 8 秒目标。成功输出仍是 `human_pending`、ASR `not_run`，不产生人审或发布资格。

## 异常与恢复

正式 renderer 支持 `--assembly-only`、`--max-synthesis-units N`。
`--quarantine-unit N --quarantine-reason '具体异常'` 会先保存该 WAV、intent、render commit、
收据和旧 manifest 并核验副本，随后恢复该项。不得与 assembly-only 同用。
文字或声音身份改变时仍须使用新批准的 job/revision；隔离并不判定 TTS 或译文谁有错。

`early-unit-timing-diagnostics.json` 随已完成单元更新，保留测量覆盖范围、duration/source 比、
局部 lag 跳升和后续传播。`unit-timing-diagnostics.json` 是完整排程诊断。
两者均标为 measured，不是后续尚未生成内容的预测；不会自动放宽容差。

可选 ASR 裁决细节：

```sh
.venv/bin/python scripts/target_audio_recovery.py \
  --audio-package /absolute/audio-package.json --artifact-root /absolute/render \
  --group GROUP_ID --reason asr_misrecognition --evidence '实际听审依据' \
  --corrected-transcript '正确转写' --out /absolute/new-adjudication.json
```

原因包括 `asr_misrecognition`、`acceptable_reading`、`repair_audio`、`repair_text`、`unresolved`。
该附加证据绑定单元 WAV、track 和 target text hash，不替代原有整体批准。
`summarize_adjudications` 只统计提供且绑定有效的逐项裁决；未裁定项不进入误报分母。

## 只读计时与容量实验

```sh
.venv/bin/python scripts/benchmark_audio_receipts.py \
  --job /absolute/render/job.json --out /absolute/new-benchmark.json
```

在同一批收据/WAV 上顺序执行 baseline 和 snapshot，保留完整解码、总耗时与验证数量。
缓存变化或身份失败即拒绝，不修改原生产产物。真实性能结论以完成的收据为准。

`target_audio_capacity_experiment.py plan --input PLAN_ARGUMENTS.json --out PLAN.json`
只生成 cold/warm × new synthesis/cache validation × replica 的固定质量矩阵，不派发 GPU。
参数使用 Python API 同名字段：`speech_job_sha256`、`sound_identity_sha256`、`unit_indices`、
`max_generated_units`、`max_wall_seconds`，可选 `replicas`、`batch_size`。

`compare --input PLAN.json --results RESULTS.json --out COMPARISON.json` 校验各 case 绑定、
预算、真实 job/audio package/人审收据、完整 track 解码和原 8 秒排程。
缺测 case 保持 partial；GPU 峰值缺测为 unknown，不自动修改生产容量策略。

## Owner 冻结与只读恢复

先调用 `freeze(draft_config_path, new_config_path)` 写出带 `inputSnapshotSha256` 的新配置，
再让 owner 把新配置绑定到 run manifest。`inspect` 返回 `inputsSha256` 和 `snapshotBound`；
后者不为 true 时不得执行。修改嵌套输入不能通过重算 planHash 自动获得旧 run 的准入。
实际 renderer 会在锁内再次对比 owner 冻结的完整依赖闭包。

合成 attempt 的 checkpoint 目录包含所有文件、目录成员变化和符号链接目标检查；
assembly-only 保留 checkpoint 身份绑定，但不消费本地模型权重。

`verify_result(config_path, result)` 供 revision 复用／unknown reconciliation 使用。
它只读复核 input snapshot、manifest、逐 WAV/receipt、track/PCM、排程、字幕、声音授权、
intent/render commit 与输出 audio package 的闭包，并完整解码；不重新合成或启动 ASR。
execute 的结果保存 `artifactClosure` 和 `audioPackage` 引用，human review 仍 pending。

## ASR 细节与原有听审入口

`review_target_language_audio.py prepare --details-template-out NEW_DETAILS.json` 可选生成
绑定当前筛查收据的逐项空表与五种原因选项。操作员填写后，`approve --adjudication-details
DETAILS.json --artifact-root ROOT` 校验每项 unit/track/text hash；修音频、修文字或未裁定的项
不能被批准。空缺的可选细节不使既有整体批准失效，也不当作已得到逐项真值。

结果目录另存细节和统计 sidecar；既有 v2/v3/v4 人审收据格式保持不变。
