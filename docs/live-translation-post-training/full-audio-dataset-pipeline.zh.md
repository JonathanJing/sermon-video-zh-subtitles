# 字幕优先、选择性音频审核的全量语料运行方案

日期：2026-09-01

状态：编排器、选择规则、恢复机制和离线测试已完成；全量模型/API 调用尚未启动

## 1. 固定流水线

已有英文字幕的证道不再先做全量语音转写。冻结的 YouTube 英文字幕是候选英文来源，GPT-Transcribe 只为风险段提供音频证据：

```text
公开证道视频 + 冻结英文字幕时间轴
  -> 字幕整理为 24–55 秒语义段
  -> 字幕密度门禁：稀疏段占比达到 10% 的视频先做英文来源核对
  -> Terra High 英中初译
  -> 独立 Sol High 双语文本复审
  -> 选择音频审核段
       Sol needs_audio_review
       来源/确定性异常
       过快或过慢语速、噪声标记
       其余 pass 的稳定 5% 抽样
  -> 只下载所需视频音频、只切所需片段
  -> GPT-Transcribe 音频核对
  -> 一致：模型审定候选
  -> 不一致或转写无效：排除，等待英文来源核对后重新翻译与复审
```

入口：`scripts/run_full_sermon_dataset_preparation.py`。

GPT-Transcribe 使用现有 `account-video-transcript-collector` 的已验证转录模块和已有 key。key 不复制到本仓库，也不写入回执。Terra/Sol 使用 ChatGPT-managed Codex 登录和共享额度，教师进程移除 API key。两种认证与费用渠道保持隔离。

音频转写不会静默替换原字幕。审核记录同时保存字幕、转写、相似度、触发原因和 hash；发现冲突时先排除该段，核对英文事实来源后再跑 Terra/Sol。

## 2. 全量边界

冻结 split 共 180 篇：train 141、dev 18、test 18、POC 3。默认生产只选择 train + dev，即 159 篇、约 99.99 小时。test/POC 使用独立输出根，不能混入训练。

没有现成语义段的证道使用完整公开视频字幕时间轴分段；已有 6 篇扩展产物复用其语义段和边界。完整视频来源仍记录 `segmentOrigin`，不能把模型边界写成人工批准边界。

## 3. Dry run：不调用模型、不产生费用

```bash
python3 scripts/run_full_sermon_dataset_preparation.py --max-videos 0
```

2026-09-01 实际结果：

| 指标 | 结果 |
|---|---:|
| train/dev 视频 | 159 篇 |
| 字幕语义段 | 7,334 段 |
| 字幕覆盖时长 | 98.546 小时 |
| 6 篇 calibration | 265 段 |
| Sol `needs_audio_review` | 44 段，16.60% |
| 翻译前确定性规则命中 | 994 段，904.60 分钟 |
| 按现有 calibration 外推的工作预计 | 29.36%，1,736.15 分钟，约 7.81 美元 |
| 不扣除规则重叠的保守预计上界 | 31.90%，1,886.35 分钟，约 8.49 美元 |
| 全量音频上界 | 5,999.20 分钟，约 27.00 美元 |

费用以每分钟 0.0045 美元估算；运行前须重新核对官方价格。29.36% 是把翻译前风险的实际时长占比与现有 6 篇 Sol 风险率合并后的工作估计；31.90% 假设两类风险完全不重叠，是更保守的规划上界。真正完成 Terra/Sol 后才会得到精确选择清单。它不含 Terra/Sol 共享 credits、失败重试、下载流量和学生后训练。

没有句号、自动字幕单段较长等常见现象不单独触发音频审核，否则会把大多数自动字幕重新推回全量 ASR。

## 4. 三阶段 canary

第一阶段只整理三段字幕，不调用任何模型：

```bash
python3 scripts/run_full_sermon_dataset_preparation.py \
  --video-id nre_3kR0PHk \
  --segment-limit 3 \
  --stage prepare-caption \
  --source-root data/derived/sermon-caption-source-canary-v1 \
  --execute
```

第二阶段使用 Terra/Sol 共享额度：

```bash
python3 scripts/run_full_sermon_dataset_preparation.py \
  --video-id nre_3kR0PHk \
  --segment-limit 3 \
  --stage translate-review \
  --source-root data/derived/sermon-caption-source-canary-v1 \
  --teacher-out-root data/derived/sermon-terra-sol-caption-canary-v1 \
  --execute \
  --confirm-shared-codex-usage
```

第三阶段只核对被规则选中的音频段，并使用独立工作根：

```bash
python3 scripts/run_full_sermon_dataset_preparation.py \
  --video-id nre_3kR0PHk \
  --segment-limit 3 \
  --stage audio-audit \
  --source-root data/derived/sermon-caption-source-canary-v1 \
  --teacher-out-root data/derived/sermon-terra-sol-caption-canary-v1 \
  --work-root data/work/sermon-selective-audio-canary-v1 \
  --execute \
  --confirm-billable-asr
```

三段 canary 可能因没有风险段且未命中稳定抽样而不调用 GPT-Transcribe；这属于正常结果。需要验证付费链路时，应选择已知 `needs_audio_review` 段，但不能为测试而改变生产判定。

## 5. 全量 train/dev

先按阶段运行，便于在产生下一类费用前审核结果：

```bash
python3 scripts/run_full_sermon_dataset_preparation.py \
  --split train --split dev --max-videos 0 \
  --stage prepare-caption --execute --confirm-full-run

python3 scripts/run_full_sermon_dataset_preparation.py \
  --split train --split dev --max-videos 0 \
  --stage translate-review --execute \
  --confirm-full-run --confirm-shared-codex-usage

python3 scripts/run_full_sermon_dataset_preparation.py \
  --split train --split dev --max-videos 0 \
  --stage audio-audit --execute \
  --confirm-full-run --confirm-billable-asr
```

`--stage all` 也会严格按“字幕、教师、选择性音频审核”运行，但全量建议保留上述人工门禁。test/POC 必须另行 dry-run 或使用独立 source、teacher 和 work 根执行。

## 6. 选择、恢复和 fail-closed 规则

- Sol `needs_audio_review` 必选；来源标记为 ASR、字幕已有 `potentialAsrIssues`、极端词速和噪声标记也必选。
- Terra/Sol 前先执行字幕密度门禁：低于 0.6 英文词/秒视为稀疏段；一篇中稀疏段达到 10% 即阻断教师阶段并进入 source reconciliation。该门禁来自两篇端到端 canary 的实测差异。
- 无其他风险的 `pass` 使用 segment ID 的确定性 hash 做 5% 抽样；重跑仍选择同一批。
- 下载整篇音频只发生在该篇至少有一个入选段时；只切入选片段，并在目标边界两侧默认各留 750 ms。
- 公开视频独立音频 URL 若因 YouTube GVS/PO Token 返回 403，下载器先回退到公开合并格式 18，再尝试无需账号 cookies 的 `web_embedded` 公开音频；不自动启用账号 cookies。合并格式由 ffmpeg 只读取音轨。
- 字幕、音频片段、模型、prompt、选择规则与输入 profile hash 绑定；改变输入不会静默复用旧结果。
- 音频证据和字幕相似度低于阈值、转写为空或明显异常时，该段进入 `excluded_requires_source_reconciliation`，而不是自动改写英文。
- 英文来源人工/独立核对完成后，必须从字幕来源阶段更新 canonical English，并重新运行 Terra 与 Sol；不能沿用旧中文。
- 每篇失败写入批次报告，其他篇可继续；缓存仅补缺失项。

## 7. 产物

```text
data/derived/sermon-caption-source-v1/<video-id>/
  segments.en.jsonl
  run-report.json

data/derived/sermon-terra-sol-dataset-preparation-v1/<video-id>/
  segments.codex.first.jsonl
  segments.codex.final.jsonl
  selective-audio-audit.jsonl
  segments.selective-audio-audited.jsonl
  selective-audio-audit-report.json
  run-report.json
  cache/

data/work/sermon-selective-audio-audit-v1/
  audio/<video-id>.<ext>
  <video-id>/profiles/<input-hash>/clips/*.mp3
  <video-id>/profiles/<input-hash>/transcripts/

data/reports/sermon-caption-selective-audio-pipeline-v1/
  latest-plan.json
  latest.json
  batch-*.json
```

下游只能消费 `segments.selective-audio-audited.jsonl`。`segments.en.jsonl` 是字幕来源，不是人工听写 Gold；`segments.codex.final.jsonl` 仍包含尚未通过选择性音频门禁的教师结果。

## 8. 训练资格

Sol High 取代当前常规双语文本复核，但不能记录为人工审核。选择性音频一致只表示音频证据支持字幕，不等于 Human Gold；冲突段必须排除。

即使模型审定和音频抽检通过，当前仍统一保持：

- `source_training_rights_unconfirmed`；
- `gpt_external_student_distillation_not_authorized`；
- `trainingEligibility: blocked`。

论文若需要独立 Gold 测试真值，仍应准备人工听音频确认的小规模集合；否则只能报告 model-judged 指标。
