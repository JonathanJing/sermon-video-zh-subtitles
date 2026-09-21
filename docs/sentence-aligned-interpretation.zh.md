# 句级锚定与滚动同传设计

## 结论

采用“冻结英文词序列 → MFA 词级时间 → 标点句／停顿分句 → 完整中文 → 独立语义复核 → 自然语速 TTS → 滚动同传排程”的路线。它把英文内容完整性、句界、中文语义和时间安排分成四项证据，不再让一个大 block 的中文从 block 起点一次播完，也不再用删义或加速来满足原声时槽。

当前代码可以作为 **shadow / 候选生成合同** 合入 `main`，但不应直接替换正式音轨。只有真实整篇完成英文听审、句界听审、逐句翻译复核、自然语速合成和 1 倍速全篇试听后，才允许把该周候选升级为正式产物。

## 为什么采用滚动同传，而不是逐句硬塞回原时槽

现场同传必须先听到一个足以确定含义的英文单元，中文才开始表达。因此 v1 使用 `rolling_interpreter_v1`：

1. 英文词和原声时间冻结后，标点先提出句界；超过 12 秒的长句，只能在可听停顿或分句标点处提出更小的意义单元。
2. 每个中文组必须显式列出其 `sourceUnitIds`。允许多句英文合成一段中文，也允许一段英文拆成多句中文，但所有英文单元须按顺序恰好覆盖一次。
3. 中文组最早在最后一个来源单元稳定后开始；上一段中文尚未结束时顺延。这样保留自然语速，并记录真实的开始／结束延迟。
4. 最大结束延迟默认 8 秒。超过阈值时停止候选，不通过删义、自动加速、拉伸或裁切音频处理。

这与“同视频替换音轨、每句中文必须在同一个英文句时槽结束”的目标不同。后者遇到中英文表达长度差异时会不断诱发压缩；滚动同传允许有界延迟，更接近现场译员的工作方式。

## 四层合同

### 1. 英文与句锚

- 输入必须是冻结英文和 MFA `wordTimes`；Forced Aligner 只定位给定英文，不能证明 ASR 没有漏词。
- 每个词获得稳定 `wordId`，句／分句只引用这些 ID，不重写英文。
- 普通句沿用冻结文本的标点边界；长句的内部拆分须有停顿或分句标点证据，并保持 `requiresOperatorReview=true`。
- 英文完整性和句／停顿边界是两个人工门槛，不能由结构检查自动批准。

合同：[英文句锚 schema](../schemas/sermon-sentence-anchor-manifest-v1.schema.json)。生成器：[sermon_sentence_interpretation.py](../scripts/sermon_sentence_interpretation.py)。

### 2. 初译与独立复核

初译请求只翻译目标 `sourceUnitIds`，相邻英文仅作消歧上下文。输出必须保存精确的中文 substring coverage。独立的第二次模型请求逐单元检查：

- `completeMeaning`
- `negationsNumbersNames`
- `quotationAttribution`
- `noAddedMeaning`
- `spokenChinese`

模型复核不是人工批准。任何检查失败、疑点未清、来源 ID 缺失／重复或上下文被误译进目标，都阻止进入听审候选。

### 3. 自然语速音频与滚动排程

每个中文组绑定最终文字、实测音频时长和合成收据。验证器要求 `playbackRate=1.0`、`ratePolicy=natural_no_time_stretch`，并拒绝音频文字与批准中文不一致。排程公式为：

```text
start = max(source_stable_at + reaction_lag,
            previous_chinese_end + inter_utterance_gap)
end   = start + measured_natural_audio_duration
```

停顿自然地成为可用缓冲，但不会把下一句英文偷进上一句的来源覆盖。排程延迟超限时，应重新检查分句／分组或采用更长的整体播放延迟，而不是改变语义或播放倍率。

### 4. 正式批准

候选只有同时保存真实审核人、审核时间、全部来源单元 ID，并通过以下五项，才可能得到 `releaseEligible=true`：

1. 英文逐字稿完整；
2. 句界和停顿边界正确；
3. 中文逐句完整；
4. 自然语速、发音和声音质量通过；
5. 同一录音、正常 1 倍速的全篇播放通过。

候选合同：[中文同传 candidate schema](../schemas/sermon-sentence-interpretation-candidate-v1.schema.json)。

## 9 月 20 日扩大 POC

对既有 13 个分层区块的 MFA 结果运行 v1 生成器：

| 指标 | 结果 |
|---|---:|
| 冻结英文标点句 | 94 |
| 英文词 | 1,316 |
| 句／停顿意义单元 | 99 |
| 被停顿／分句标点拆开的长句 | 5 |
| 拆分后最长单元 | 11.44 秒 |
| 结构问题 | 0 |
| 待人工听审的单元 | 99 |

这证明 1,316 个既有 MFA 词可以无丢失地进入有界句锚，并把 5 个超长标点句拆成 10 个可追溯分句。句锚阶段本身**不证明** 94 句英文逐字完整或 99 个边界听感正确，其输出保持 `machine_anchor_candidate_requires_review`，再交给以下独立模型阶段。

随后通过项目既有 Google Secret Manager 凭据调用 `gpt-6-astra` Medium；密钥只注入运行进程，不写入缓存或报告。模型访问预检和实际结果为：

| GPT 阶段 | 结果 |
|---|---:|
| 模型访问预检 | Responses HTTP 200 |
| 初译批次 | 7 |
| 独立复核批次 | 7 个不同 API request |
| 英文意义单元／中文组 | 99 / 99 |
| 独立复核逐单元通过 | 99 / 99 |
| 复核实际改写初译 | 26 组 |
| 最终中文字符 | 2,308 |
| 未解决模型语义问题 | 0 |

第一次复核保留了 18 个“已经修复的问题”或“英文歧义已在中文中如实保留”的说明，fail-closed 校验没有把它们误报为通过。提示合同随后明确区分：已经修复／已保留的来源歧义写入 `evidence`，只有最终仍未解决的问题进入 `issues` 或 `uncertainty`。第二次独立复核在不降低五项语义检查的前提下得到 99/99 通过，并保留全部请求、响应和缓存哈希。

这一结果证明句锚可以驱动完整的逐单元初译和独立校对，但仍是模型候选：英文完整性、边界听审和全篇人工播放尚未通过，`releaseEligible=false`。

### 自然语速 TTS 实测

随后把同一份 99 组语义候选原文冻结为新的 TTS job，复用既有 Eric `eric_pilot` Qwen3-TTS 1.7B 检查点，在 MacBook MPS float32、batch 4、seed 42 下生成。每组送入 TTS 的文字与语义候选 `chinese` 完全一致；没有 `spokenText` 替换、速度参数、时长拉伸、截断或响度后处理。逐组 WAV、合并 WAV、生成参数和输入哈希均有独立回执。

| 自然语速指标 | 实测结果 |
|---|---:|
| 中文组 / 逐组 WAV | 99 / 99 |
| 中文字符 | 2,308 |
| 纯语音总长 | 449.20 秒 |
| 含 0.12 秒组间隔的合并 WAV | 460.96 秒 |
| 单组时长中位数 / P95 / 最大值 | 3.92 / 10.64 / 13.44 秒 |
| 中文 TTS / 对应英文意义单元总时长 | 1.1003× |
| 生成耗时 | 407.27 秒 |
| 逐组及合并 WAV 完整解码 | 99/99 + 1 通过 |
| 代表性中文回转写 | 4/4 规范化后完全匹配 |
| 滚动结束延迟中位数 / P95 / 最大值 | 8.33 / 20.56 / 26.13 秒 |
| 超过 8 秒门槛 | 52 / 99 组 |

代表性回转写覆盖第一组、最长中文组和两组密集教会术语；它只说明这些样本在 Qwen3-ASR 规范化比较中没有文字差异，不等于发音、韵律或音色已由人耳通过。

实测结论是：**完整中文可以按自然语速合成，但当前“等整个句级意义单元稳定后才开始中文”的 v1 排程不合格。** `block-01` 的最大结束延迟为 26.13 秒，`block-31` 为 15.95 秒；52 组超限使候选保持 `candidate_blocked`。这不是靠放宽标签或把 8 秒改成更大数字来解决的问题。下一轮应把较长英文句保留为可审计的父句，同时在已有逗号／可听停顿处生成约 6–8 秒的 clause-stable 子单元，再以新的来源映射重做翻译与 TTS；不能在合成后随意切中文，也不能复用本轮 99 组的通过状态冒充新边界已审。

忽略目录中的真实产物：

- `artifacts/sentence-interpretation-poc/20260920-stratified-13/anchor-manifest.json`
- `artifacts/sentence-interpretation-poc/20260920-stratified-13/translation-request.json`
- `artifacts/sentence-interpretation-poc/20260920-stratified-13/model-access.json`
- `artifacts/sentence-interpretation-poc/20260920-stratified-13/models-gpt-6-astra/semantic-candidate.json`
- `artifacts/sentence-interpretation-poc/20260920-stratified-13/tts-qwen-eric-natural-v1/final/tts-metrics.json`
- `artifacts/sentence-interpretation-poc/20260920-stratified-13/tts-qwen-eric-natural-v1/final/validation-report.json`
- `artifacts/sentence-interpretation-poc/20260920-stratified-13/tts-qwen-eric-natural-v1/screening/representative-asr-screening.json`

## 运行与验证

```bash
.venv/bin/python scripts/sermon_sentence_interpretation.py prepare \
  --mfa-segments <segments.json> \
  --out artifacts/sentence-interpretation-poc/<run-id>

.venv/bin/python scripts/sermon_sentence_interpretation.py prepare-review \
  --anchor-manifest <anchor-manifest.json> \
  --draft <translation-draft.json> \
  --out <independent-review-request.json>

.venv/bin/python scripts/run_sentence_interpretation_models.py \
  --anchor-manifest <anchor-manifest.json> \
  --out artifacts/sentence-interpretation-poc/<run-id>/models-gpt-6-astra \
  --model gpt-6-astra \
  --reasoning-effort medium \
  --api-key-secret projects/<project>/secrets/openai-api-key/versions/latest

artifacts/model-routing/macbook-tts/runtime/bin/python scripts/render_sentence_interpretation_tts.py prepare \
  --anchor-manifest <anchor-manifest.json> \
  --semantic-candidate <semantic-candidate.json> \
  --checkpoint artifacts/model-routing/macbook-tts/checkpoint \
  --out artifacts/sentence-interpretation-poc/<run-id>/tts/job

artifacts/model-routing/macbook-tts/runtime/bin/python experiments/sermon-dubbing-poc/render_weekly_audio.py \
  --job artifacts/sentence-interpretation-poc/<run-id>/tts/job/job.json \
  --checkpoint artifacts/model-routing/macbook-tts/checkpoint \
  --out artifacts/sentence-interpretation-poc/<run-id>/tts/render \
  --device mps --batch-size 4

artifacts/model-routing/macbook-tts/runtime/bin/python scripts/render_sentence_interpretation_tts.py finalize \
  --anchor-manifest <anchor-manifest.json> \
  --semantic-candidate <semantic-candidate.json> \
  --job artifacts/sentence-interpretation-poc/<run-id>/tts/job/job.json \
  --render artifacts/sentence-interpretation-poc/<run-id>/tts/render \
  --out artifacts/sentence-interpretation-poc/<run-id>/tts/final

HF_HUB_OFFLINE=1 artifacts/english-word-timeline-poc/runtime/bin/python \
  scripts/screen_sentence_interpretation_tts.py \
  --job artifacts/sentence-interpretation-poc/<run-id>/tts/job/job.json \
  --render artifacts/sentence-interpretation-poc/<run-id>/tts/render \
  --out artifacts/sentence-interpretation-poc/<run-id>/tts/screening \
  --indices <first,longest,dense-terminology>

.venv/bin/python scripts/sermon_sentence_interpretation.py validate \
  --anchor-manifest <anchor-manifest.json> \
  --candidate <candidate.json> \
  --out <validation-report.json>

.venv/bin/python -m unittest \
  tests.test_sermon_sentence_interpretation \
  tests.test_render_sentence_interpretation_tts \
  tests.test_screen_sentence_interpretation_tts -v
```

在生产接线前，还需要完成更细 clause-stable 锚定的同输入对照、把 GPT 初译／独立复核 runner、TTS 单元收据和正式人工 review receipt 接到现有周任务；合并本合同本身不会改变当前生产输出。
