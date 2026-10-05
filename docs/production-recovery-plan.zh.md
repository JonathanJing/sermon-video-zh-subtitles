# Layer 3 异常留存与恢复清单

本入口落实[下一轮规划](reports/20261005-production-findings-next-iteration-plan.zh.md)第一批 P0。它解释已有证据和待恢复范围，最终仍由 canonical producer 在锁内准入；清单不派发模型、不迁移缓存、不放行批准、不释放 unknown owner。

## 异常音频

正式 renderer 在单句前缀出现自身超窗、传播 lag 超限或尾部超限时，保存 `anomalies/unit-NNNN-HASH/`。完整排程再次验证；解码失败的 partial 和即将替换的旧 partial 也会留存。显式 quarantine 在删除原件前保存新版证据，同时保留原有 `sermon-audio-quarantine-v1` 收据及整轨资产。新版 `sermon-audio-anomaly-v1` 是补充证据，不改写旧 schema，无需升级原来的 quarantine 消费者。

快照包含原始 WAV、完整 job/unit、现存 intent/render commit/unit receipt、replica runtime、各文件 SHA、错误类别和 timing。checkpoint/speaker/seed/batch 身份从 job 与 intent 留存，不复制模型权重；缺失证据明确列在 `unavailableEvidence`。`context.json` 可能含已批准文字，应留在 ignored render root，不能提交 Git。

快照以临时目录写入、复制后核对 SHA，fsync 文件、子目录及父目录，再 rename 完成持久化。复用快照需重新核对 identity、完整 saved 清单和校验值并确认落盘。写入／持久化失败时不删除原件。旧 quarantine 的所有将删除资产与 receipt 也完成 fsync；损坏、symlink 或变化的证据拒绝继续。

首尾诊断完整读取 PCM16，以 10 ms 的全声道 RMS 窗口、-45 dBFS 阈值记录边缘低能量时间。低声、辅音、呼吸也可能低于阈值，因此 `safeTrimSeconds=null`；没有自动裁剪、变速、缩译或提高容差。全低能量文件单独标记，不把首尾时间重复相加。无法测量的 WAV 仍保留原字节，不假定根因。

单独只读测量：

```sh
.venv/bin/python -m scripts.target_audio_anomaly \
  --wav /path/to/unit.wav --out artifacts/diagnostics/unit-edge.json
```

`--out` 必须为新文件；不覆写音频，不调用模型。本轮只支持未压缩 PCM16 的声学测量，其他格式保留证据但标记 measurement unavailable。

## 逐单元恢复清单

```sh
.venv/bin/python -m scripts.production_recovery_plan \
  --job /resolved/path/job.json --render-root /resolved/path/render-root \
  --expected-intents artifacts/diagnostics/expected-intents.json \
  --execution-state artifacts/diagnostics/owner.json
```

输出 JSON 到 stdout。只读取得已有 formal render lock 的 shared/nonblocking 锁，不新建锁；busy 表示 active。检查 lock inode、输入／产物 SHA 和路径，拒绝 symlink 和读中变化。

`expected-intents.json` 必须是当前 canonical renderer 对目标 job/settings 产生的完整 `_intent`，逐 unitIndex 排列，不能把旧 intent 复制后冒充当前身份。本轮不提供自动制作这个快照的入口：生产者／调用方负责提供，缺失时保守阻塞复用资格。封装为：

```json
{
  "schemaVersion": "sermon-l3-recovery-intent-snapshot-v1",
  "jobJsonSha256": "canonical job SHA",
  "jobFileSha256": "job bytes SHA",
  "intents": []
}
```

`intents` 上例仅示意结构，实际必须完整覆盖 job 全部单元。owner 快照为 `sermon-l3-recovery-execution-snapshot-v1`，同样包含两种 job SHA、resolved `renderRoot` 和 `status=terminal|active|unknown`。terminal 只是已经观察到的历史状态，不授予新派发权；缺少 owner 证据时，合法缺项仍可显示 proposed recompute，但 blocked。

| 类别 | 条件及下一步 |
|---|---|
| reuse | 当前 exact intent、commit、WAV SHA、完整解码和 receipt 相符；仍需 producer 准入 |
| revalidate | 缺 receipt、已 commit partial、包装身份变化或跨 job/context 身份；重验证或对账，不自动清缓存 |
| recompute | 已知当前 intent 的合法缺项；owner 未确认时阻塞派发 |
| unknown | started 未闭合、无 commit 音频、损坏／变化证据；持槽对账，不盲重发 |

`plannedModelUnitEvaluations` 计完整固定批窗重放，`plannedMissingUnitCommits` 只计缺项；已提交邻句保留原字节。文字、speaker/checkpoint、seed、batch/window 输入逐字段解释；package hash 变化和实际 model request 变化分开。source/anchor/policy/implementation 总 hash 单独变化不足以确定真实模型输入影响，记 unknown 影响，不推断全 layer 重算。

音频变化后同 locale 排程、整轨、cue、音频包／听审和 release 绑定需重验。清单只覆盖 canonical L3；不推断未提供的 L1/L2 全局依赖，不实现跨 job ASR cache 迁移或跨主机容量释放。其他 locale 的有效产物不因这份诊断被修改。Layer 2 的首调用规则校验见[规则冻结](target-language-rule-preflight.zh.md)。
