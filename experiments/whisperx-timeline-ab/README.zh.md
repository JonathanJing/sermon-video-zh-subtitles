# WhisperX 替代 Layer 1 时间轴：A/B 实验

状态：`machine_ab_requires_human_timing_gold`（机器对比完成，人工词级 Gold 未完成）

## 结论

在同一份 2026-11-08 周日证道、同一份已人工批准的英文单元表上，**WhisperX 的强制对齐可以取代 OpenAI `whisper-1` 的词级时间轴**，但**不应取代文本转写**：

1. **时间轴：可以取代，机器证据明确偏向 WhisperX。**
   - WhisperX 对齐 6,136/6,136 个批准词，0 缺失、0 零/负时长、0 相邻重叠、0 非单调起点；当前 `whisper-1` 时间轴有 4 个零/负时长词、296 对相邻重叠。
   - 以独立 MFA（5,080 个可比较词，0.75 秒边缘保护）为模型参照，词中点误差 P50/P95：`whisper-1` 0.055/0.235 秒，WhisperX 0.033/0.092 秒；WhisperX 更接近 MFA 的词为 2,929，`whisper-1` 为 1,151（1,000 平局）。
   - 在 100 个由旧锚点构建器“借用/插值”合成的词上，差距最大：`whisper-1` 时间轴对 MFA 的 P95 为 1.079 秒，WhisperX 为 0.232 秒。
   - 在 216 个首尾都被 MFA 覆盖的句级单元上，句首更接近 MFA 的单元数为 WhisperX 143 / `whisper-1` 45；句尾为 129 / 51。
2. **文本：不能取代。** WhisperX large-v3 自己的转写对批准英文表的 WER 为 2.812%，比 `whisper-1` 原始文本 2.552% 更差，远差于 `gpt-4o-transcribe` 原始文本 0.455%。生产文本应继续走 `gpt-transcribe`/`gpt-4o-transcribe` + 英文校正。
3. **不是无痛替换。** 换时间轴会让 139/460 个句级单元的起点移动超过 0.25 秒、34 个超过 0.5 秒；Layer 1 身份变化会使所有 locale 下游失效。必须按新 run 重建 L2/L3，不能就地改旧包。

**建议**：下一轮先做 shadow（shadow 是并行运行、不发布）：保留现有 OpenAI 文本与校正，用 WhisperX 对最终英文做强制对齐，同时保留 `whisper-1` 时间轴；跑 2 期并人工抽查本报告 `review/review.html` 中的争议词/句。通过后再把新 run 的默认时间轴切到 WhisperX；旧 run 不迁移。

## 生产化（2026-11-27）

B 臂已经做成生产工具和真实候选：`source.whisperx_timeline` + `tools/ops/whisperx_align_runtime.py`，候选在 `artifacts/sentence-first-agent/20261108-sermon-source/layer1-whisperx/`。候选包 `translationEligible=false`；2026-11-27 21:59 PST 用户听审后 `--approve` 写批准包 `english-source.approved.json`（`b51086be…`），`sfa.py start --timeline-package` 只接受批准包。该批准包已设为逐句优先生产默认；2026-11-28 做第一次真实生产测试。完整命令和门禁见[WhisperX Layer 1 时间轴生产手册](../../docs/whisperx-layer1-timeline-production.zh.md)与[生产运行报告](../../docs/reports/runs/20261127-whisperx-timeline-production/INDEX.md)。

## 输入与两臂

| 项 | 值 |
|---|---|
| 来源 | 2026-11-08 周日证道，整段媒体已批准，2,147.051 秒 |
| Layer 1 run | `artifacts/sentence-first-agent/20261108-sermon-source/layer1` |
| 英文文本 | 460 个 `sourceUnits`，6,136 词，人工批准；词时间继承 `whisper-1` |
| A 臂 | OpenAI `whisper-1` `verbose_json` 词时间，经历史锚点构建器映射到校正文本 |
| B 臂 | WhisperX 3.8.6 + torchaudio `WAV2VEC2_ASR_BASE_960H`，对**同一份批准文本**做强制对齐 |
| 参照 | MFA 3.4.2 + 官方 `english_mfa` 词典/声学模型 + `english_us_mfa` G2P；仅作第三模型参照，不是人工 Gold |
| 排除 | 含需人工确认读法的数字 token 的分块；MFA 解析失败的 `c0049` 分块 |

A 臂不是“OpenAI 原始转写文本”，而是**当前生产时间轴**：批准文本替换了部分 whisper 词，历史构建器对不一致 token 用最近 span 分配或零时长邻居插值。B 臂不改文本，只改时间。

## 方法

- 按批准单元分组为 123 个对齐分块，目标 18 秒、最大 24 秒；相邻单元间隔 ≥1 秒时强制断开，避免把掌声/长停顿塞进同一个对齐窗口。
- WhisperX 对每个分块先用**精确边界**对齐，失败才回退到 ±1 秒 padding，再失败按单元回退；每一步都要求对齐出的词序列与批准文本逐 token 完全一致，否则不产生时间。
- MFA 在 117 个安全分块（5,760 词）上独立对齐；比较时丢掉距分块边界 0.75 秒内的词，避免分块切词偏差。
- 指标：结构有效性、A/B 逐词边界差、以 MFA 为参照的逐词/句级误差、文本 WER、句级单元位移。
- 本实验不调用付费 API；A/B 复用既有 Layer 1 产物。

## 结果

完整表格在 `artifacts/whisperx-timeline-ab/report-final/summary.md`。

### 结构

| 检查 | A (`whisper-1`) | B (WhisperX) |
|---|---:|---:|
| 输出词数 | 6,136 | 6,136 |
| 零/负时长 | 4 | 0 |
| 相邻重叠 | 296 | 0 |
| 非单调起点 | 0 | 0 |

### 以 MFA 为模型参照（5,080 词）

| 指标 | A P50 | A P95 | B P50 | B P95 | B 更近 | A 更近 | 平局 |
|---|---:|---:|---:|---:|---:|---:|---:|
| 起点 | 0.070 | 0.420 | 0.057 | 0.176 | 2,477 | 1,848 | 755 |
| 终点 | 0.060 | 0.350 | 0.025 | 0.113 | 3,297 | 868 | 915 |
| 中点 | 0.055 | 0.235 | 0.033 | 0.092 | 2,929 | 1,151 | 1,000 |
| 时长 | 0.130 | 0.500 | 0.060 | 0.230 | 3,467 | 1,240 | 373 |

句级单元（216 个首尾均被 MFA 覆盖）：

| 锚点 | A P50 | A P95 | B P50 | B P95 | B 更近 | A 更近 | 平局 |
|---|---:|---:|---:|---:|---:|---:|---:|
| 起点 | 0.100 | 0.463 | 0.038 | 0.190 | 143 | 45 | 27 |
| 终点 | 0.065 | 0.265 | 0.032 | 0.210 | 129 | 51 | 33 |

### 文本（对批准英文表）

| 转写 | WER | 替换 | 删除 | 插入 |
|---|---:|---:|---:|---:|
| `gpt-4o-transcribe` 原始 | 0.455% | 19 | 4 | 5 |
| `whisper-1` 原始 | 2.552% | 78 | 48 | 31 |
| WhisperX large-v3 | 2.812% | 90 | 55 | 28 |

### 句级单元 A→B 位移

| 锚点 | P50 | P90 | P95 | 最大 | >250 ms | >500 ms |
|---|---:|---:|---:|---:|---:|---:|
| 起点 | 0.128 | 0.456 | 0.531 | 4.104 | 139 | 34 |
| 终点 | 0.046 | 0.180 | 0.297 | 2.076 | — | — |

## 运行与成本

| 阶段 | 实测 | 说明 |
|---|---|---|
| WhisperX 仅对齐（123 分块） | 66 秒 / 2,147 秒音频 = **0.031× 实时** | M1 Max CPU，large-v3 模型仅加载一次；不含模型下载 |
| WhisperX 完整转写（text，仅作对照） | 约 12 分 45 秒 = **0.36× 实时** | CPU int8；不用于生产文本 |
| MFA 117 分块 | 37 秒对齐 + 约 14 秒 G2P | 仅作参照 |
| 模型下载 | 约 3.3 GB（faster-whisper-large-v3 2.9 GB + wav2vec2 360 MB） | 本机缓存，不进 Git |
| 费用 | WhisperX/MFA 本地 0；`whisper-1` 同规模约 US$0.22/期 | 以 2026-11-08 复盘的 ≈$0.22 为参照，不是发票 |

## 产物

忽略目录 `artifacts/whisperx-timeline-ab/`（不进 Git）：

| 产物 | SHA-256 |
|---|---|
| `case-20261108/case.json` | `4d28b699a751eeadd455a8254421e5fdfc54b1c807234d70cc26a20c468b786c` |
| `align-full-v2/whisperx-aligned.json` | `d943cf198b212f8c890e017be9f6a1e261194442b715730539947006b64e27fb` |
| `mfa-all-v3/mfa-aligned.json` | `b901801cf6364841ab3e24dc6cf6bb19f95e436564c4e5158946e317ea42ab4b` |
| `full-run/sermon-16k.json` | `1f701fb581e2465705a0a6176adcde4b45ebe0250908ebe529ca303b38db56d5` |
| `report-final/report.json` | `17f65807024ab4fc7fdf82478dec8baa06f4a51932ce06a9ef34d05fa3b314b8` |
| `report-final/summary.md` | `2345c54feabd1caae5cf85b53670d11101bd80c4cc428bd0d1a7347c7a1f860c` |
| 听审页 `report-final/review/review.html` | `09be12899d07b1f96e681b7baeeea34486f33ee0c195e832974f185b2972e907` |

模型身份：

- WhisperX `3.8.6`、torch `2.8.0`、torchaudio `2.8.0`、faster-whisper `1.2.1`、CTranslate2 `4.9.1`。
- 转写模型 `Systran/faster-whisper-large-v3`，HF snapshot `edaa852ec7e145841d8ffdb056a99866b5f0a478`。
- 对齐模型 `torchaudio.pipelines.WAV2VEC2_ASR_BASE_960H`，权重 360 MB，本机缓存。
- MFA `3.4.2`；词典/声学/G2P 的 SHA-256 记录在 `mfa-aligned.json` 的 `mfa.identity` 中。

## 复现

```bash
python3 experiments/whisperx-timeline-ab/prepare_case.py \
  --anchor-manifest <layer1>/anchor-manifest.json \
  --raw-whisper <layer1>/raw-whisper.json \
  --audio <source>/media/sermon-16k.wav \
  --out artifacts/whisperx-timeline-ab/case-20261108

artifacts/whisperx-timeline-ab/runtime/bin/python \
  experiments/whisperx-timeline-ab/run_whisperx_align.py \
  --case artifacts/whisperx-timeline-ab/case-20261108/case.json \
  --audio <source>/media/sermon-16k.wav \
  --out artifacts/whisperx-timeline-ab/align-full-v2

PYTHONPATH=packages/production/src python3 \
  experiments/whisperx-timeline-ab/run_mfa.py \
  --case artifacts/whisperx-timeline-ab/case-20261108/case.json \
  --audio <source>/media/sermon-16k.wav \
  --out artifacts/whisperx-timeline-ab/mfa-all-v3 \
  --all-safe --skip-chunk c0049

python3 experiments/whisperx-timeline-ab/score_ab.py \
  --case artifacts/whisperx-timeline-ab/case-20261108/case.json \
  --whisperx artifacts/whisperx-timeline-ab/align-full-v2/whisperx-aligned.json \
  --mfa artifacts/whisperx-timeline-ab/mfa-all-v3/mfa-aligned.json \
  --transcript artifacts/whisperx-timeline-ab/full-run/sermon-16k.json \
  --raw-whisper <layer1>/raw-whisper.json \
  --raw-gpt4o <layer1>/raw-gpt4o-transcribe.txt \
  --out artifacts/whisperx-timeline-ab/report-final

python3 experiments/whisperx-timeline-ab/build_review.py \
  --report artifacts/whisperx-timeline-ab/report-final \
  --audio <source>/media/sermon-16k.wav \
  --out artifacts/whisperx-timeline-ab/report-final/review
```

环境：

```bash
uv venv artifacts/whisperx-timeline-ab/runtime --python 3.11
uv pip install --python artifacts/whisperx-timeline-ab/runtime/bin/python whisperx==3.8.6
```

MFA 使用仓库既有本机环境 `artifacts/local-runtime/mfa-macbook/env/bin/mfa`（3.4.2）与模型；没有重新下载模型。

## 限制

- MFA 是第三模型估计，不是人工词级 Gold；它也有自己的错位（本报告保留最高分歧样例）。WhisperX 更接近 MFA 只能说明一致性，不能单独证明绝对准确。
- B 臂的首/尾分块词可能被切音影响；MFA 比较已丢掉分块边缘 0.75 秒内的词，但整篇结构统计仍包含这些词。
- A 臂的“当前生产时间轴”中有 100 词是历史构建器的合成 span；这些词的时间本来就不是 `whisper-1` 原生时间。
- 本实验没有覆盖：英文校正链路改用 WhisperX 分段、双讲员 diarization、音乐/掌声段的人工听审、其他讲员/会场。
- 机器审核不是人工批准；状态保持 `human_listening_pending`。

## 相关文件

- 主报告：`artifacts/whisperx-timeline-ab/report-final/summary.md`
- 听审页：`artifacts/whisperx-timeline-ab/report-final/review/review.html`
- 运行报告：`docs/reports/runs/20261127-whisperx-timeline-ab/INDEX.md`
- 决策摘要：`docs/whisperx-layer1-timeline-ab.zh.md`
