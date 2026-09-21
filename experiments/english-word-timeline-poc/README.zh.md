# 英文逐字稿与词级时间轴 POC

本 POC 把英文文字与原声时间轴移到翻译和配音之前：先由固定版本的 `Qwen3-ASR-0.6B-8bit` 生成英文候选，再由 `Qwen3-ForcedAligner-0.6B-8bit` 将同一候选对齐到逐词起止时间。输出用于人工核对和后续覆盖检查，不自动进入中文翻译、配音或发布。

## 输出与状态

- `report.json`：输入／模型身份、逐词绝对时间、窗口来源、缺口和审核状态。
- `word-timeline.tsv`：便于人工抽查的逐词表。
- `transcript.txt`：按保留词序列生成的英文候选，不冒充人工逐字稿。
- `window-*/asr.json`、`alignment.json`：每个重叠窗口的原始机器收据。

即使结构检查全部通过，状态仍为 `machine_candidate_requires_review`，且 `transcriptCompletenessProven=false`。ForcedAligner 只能回答“给定的文字在声音中的位置”，不能证明 ASR 没有漏掉声音中的字词。超过阈值的词间空白统一进入 `possible_silence_or_missing_transcript`，由听审区分静音和漏词。

在此输出之上，版本化的[句级锚定与滚动同传合同](../../docs/sentence-aligned-interpretation.zh.md)会保持 word ID 不变，用标点和停顿提出意义单元，并阻断漏句、语义复核失败、非自然倍率和同传延迟超限。该合同是 shadow 候选接口，不会自动改变当前生产音轨。

## 本地运行

模型运行环境单独放在忽略目录，避免修改项目轻量 `.venv`：

```bash
uv venv artifacts/english-word-timeline-poc/runtime
uv pip install --python artifacts/english-word-timeline-poc/runtime/bin/python \
  -r experiments/local-live-poc/requirements-qwen-asr.txt

artifacts/english-word-timeline-poc/runtime/bin/python \
  experiments/english-word-timeline-poc/run.py \
  --audio /absolute/path/to/approved-sermon-audio.m4a \
  --source-id SOURCE_ID \
  --start-seconds 300 \
  --duration-seconds 60 \
  --timeline-offset-seconds 0 \
  --out artifacts/english-word-timeline-poc/RUN_ID
```

单次 POC 最长 300 秒；默认用 60 秒窗口、10 秒重叠，并只保留重叠区中线各自一侧的词，减少重复。`timelineOffsetSeconds` 用于把输入音频内时间换算到完整礼拜时间；它必须来自已批准的来源窗口，不能猜测。

## 第一阶段验收

1. 一段真实英文证道音频产生非空逐词时间轴，模型、音频和文本身份均留痕。
2. 时间必须有限、正向、单调且位于所选音频区间；ASR 与 ForcedAligner 的 token 序列不同即失败。
3. 精确零 PCM 由前置门槛拒绝，不让静音直接进入模型。
4. 人工对照原声抽查开头、中段、结尾、专名、数字、否定和窗口交界；未完成前保持 `humanReview=pending`。
5. 取得当前问题周次的批准原声后，用同一入口跑真实片段，再决定是否扩展到整篇和接入发布阻断器。

首轮真实片段和静音负例的结果见[2026-09-20 POC 记录](RESULT-2026-09-20.zh.md)，同输入的 Qwen ForcedAligner／MFA 结果见[对齐器对比记录](ALIGNER-COMPARISON-2026-09-20.zh.md)。

测试：

```bash
.venv/bin/python -m unittest \
  experiments/english-word-timeline-poc/test_run.py \
  experiments/english-word-timeline-poc/test_compare_aligners.py \
  experiments/english-word-timeline-poc/test_run_mfa_from_word_report.py \
  experiments/english-word-timeline-poc/test_sentence_translation_map.py \
  experiments/english-word-timeline-poc/test_render_sentence_reanchor.py \
  experiments/english-word-timeline-poc/test_run_expanded_sentence_anchor.py -v
```

## Qwen ForcedAligner 与 MFA 对比

两种 aligner 必须使用同一音频和同一份冻结英文。MFA 完成后，使用以下入口比较词序、零时长／重叠以及逐词边界分歧：

```bash
.venv/bin/python experiments/english-word-timeline-poc/compare_aligners.py \
  --audio /absolute/window-0000/audio.wav \
  --asr /absolute/window-0000/asr.json \
  --qwen-alignment /absolute/window-0000/alignment.json \
  --mfa-segments /absolute/mfa/segments.json \
  --mfa-runtime /absolute/mfa/spark-runtime.json \
  --out artifacts/english-word-timeline-poc/ALIGNER_RUN/comparison
```

`comparison-report.json` 给出结构门槛和边界差值；`word-comparison.tsv` 保留逐词成对结果。没有人工逐词 Gold 时，报告固定为 `machine_comparison_requires_human_gold`，只允许判断结构是否有效和两个模型是否一致，不允许宣布某个模型时间更准确。

## 句级英中映射与时间窗 POC

逐词时间轴有效后，`sentence_translation_map.py` 验证以下约束：

1. MFA 冻结英文句及其词位必须保持单调、正时长；
2. POC 范围内的每个英文句必须恰好进入一个翻译组，截断的上下文句必须显式排除并说明原因；
3. 每个英文句必须有一个候选中文落点，落点文字必须确实存在于该组最终中文；
4. 使用已发布中文 cue 的实测时长，将该音频重锚到对应英文句组起点后，必须能放入英文时间窗；
5. 结构通过仍固定为 `semanticCoverageProven=false`、`releaseEligible=false`。字段齐全不能证明译意正确，也不能替代听审。

从现有词时间报告取得冻结 transcript，并用 Spark MFA 生成主时间轴：

```bash
.venv/bin/python experiments/english-word-timeline-poc/run_mfa_from_word_report.py \
  --word-report /absolute/report.json \
  --audio /absolute/audio.wav \
  --chunk-id SAMPLE_ID \
  --out artifacts/sentence-translation-alignment-poc/SAMPLE_ID
```

再用句级映射规格生成报告：

```bash
.venv/bin/python experiments/english-word-timeline-poc/sentence_translation_map.py \
  --mfa-segments /absolute/segments.json \
  --spec experiments/english-word-timeline-poc/fixtures/20260920-gap-1218-sentence-map.json \
  --out artifacts/sentence-translation-alignment-poc/20260920-gap-1218/sentence-map
```

9 月 20 日两处实际错位片段的结果见[句级英中对齐记录](SENTENCE-TRANSLATION-POC-2026-09-20.zh.md)。当前 POC 已生成两段独立的本地重锚试听轨，只证明既有中文音频能以原实测时长放入对应英文时间窗；尚未生成整篇替换混音、证明整篇覆盖或完成人工听审。

`render_sentence_reanchor.py` 可从已发布中文轨精确抽取对应 cue，并生成独立英文原声、句起点重锚中文、以及“左英文／右中文”的试听 WAV 和本地 `review.html`。它只写入忽略的实验产物，固定 `releaseEligible=false`，不会替换正式音频。

## 扩大句锚范围

`run_expanded_sentence_anchor.py` 把两段已知错位扩展为分层抽样：开头、结尾、经文／专名、最高英文词量、最高句数、最高中文字符速率、重复句、时间分位点和两处已知错位。它从已发布 block 起点建立有界音频窗口，冻结对应英文，批量运行 MFA，并输出：

- 稳定的句 ID、句首／句尾和对应词 ID；
- 当前中文块相对最后英文词的提前／滞后量；
- 长句、窗口边缘和句数／cue 数不一致风险；
- 抽样句锚 SRT、逐块原声以及本地听审页。

本入口不会自动批准句界：已发布 block 起点仍只是窗口候选，MFA 时间仍需听审。9 月 20 日的 13 区块实跑结果见[扩大句级锚定报告](EXPANDED-SENTENCE-ANCHOR-POC-2026-09-20.zh.md)。
