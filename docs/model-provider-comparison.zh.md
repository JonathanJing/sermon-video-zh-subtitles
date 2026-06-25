# 翻译模型与 Provider 比较

English version: [model-provider-comparison.md](./model-provider-comparison.md)

更新日期：2026-06-22

本文比较 OpenAI、Gemini 和 OpenRouter 上适合本项目的翻译模型，并给出 50 分钟 11:30 PT 证道场景的成本、延迟和质量判断。核心目标仍然是：在 11:30 PT 场证道进行时，让中文会众获得可使用的中文字幕，而不是只在事后生成高质量归档字幕。

## 1. 结论

生产优先采用 hybrid 架构：

1. 实时主链路：OpenAI `gpt-realtime-translate` 或 Gemini `gemini-3.5-live-translate-preview` 直接从音频生成实时中文字幕。
2. 英文 sidecar：并行跑 streaming ASR，保留英文原文时间轴，方便 operator 复核、回放、重翻译和离线修正。
3. 稳定修正链路：每 5-15 秒把已稳定英文 transcript 送入文本翻译模型，用 glossary、圣经书卷/人名、经文索引做低延迟纠错。
4. 离线链路：服务结束后使用文本翻译模型重新生成高质量 VTT/SRT、笔记和金句。

OpenRouter 不应作为实时音频主链路。它更适合作为 ASR 后的文本翻译路由和 fallback 层，因为它提供统一 chat/completions 接口和多模型路由，但实时音频翻译能力、音频流端到端延迟和字幕稳定性不如原生 realtime provider 可控。

## 2. 候选模型矩阵

| 场景 | Provider / 模型 | 适合程度 | 延迟判断 | 质量判断 | 主要风险 |
|---|---|---:|---|---|---|
| 实时音频直译 | OpenAI `gpt-realtime-translate` | 高 | 最适合 p50 低延迟字幕；价格按分钟 | 直译速度强，术语/经文需要 sidecar 修正 | 对圣经专名、经文 paraphrase 的可控性需要实测 |
| 实时英文 sidecar | OpenAI `gpt-realtime-whisper` | 高 | 可与翻译并行 | 为纠错、回放和离线重译提供英文基准 | 增加约 50% realtime OpenAI 成本 |
| 实时音频直译 | Gemini `gemini-3.5-live-translate-preview` | 高 | 低延迟实时语音翻译；支持输入/输出 transcript | 直接竞争 OpenAI realtime translate | preview 模型；噪音、口音、语言检测和输出稳定性需实测 |
| 低价实时音频 | Gemini `gemini-3.1-flash-live-preview` | 中 | 价格最低，实时对话优化 | 可做实验组，不作为首选生产模型 | 不是专门的 translation model，中文字幕一致性未知 |
| ASR 后文本翻译 | OpenAI `gpt-5.5-mini` | 高 | 段级翻译一般可控在数秒内，取决于 batching | 中文自然度、术语约束和结构化输出较稳 | 不能直接解决音频到字幕，需要 ASR |
| ASR 后文本翻译 | Gemini `gemini-3.1-flash-lite` | 高 | 低成本、适合高频段级翻译 | 翻译任务性价比高 | 对复杂神学表达和经文暗引需要 benchmark |
| ASR 后文本翻译 | Gemini `gemini-3.5-flash` | 中高 | 比 Flash-Lite 贵，但更强 | 质量更稳，适合离线重译或困难段落 | 实时全量使用成本没必要 |
| ASR 后文本翻译 | OpenRouter `qwen/qwen3.7-plus` | 中 | 依赖路由、provider 排队和流式输出 | 中英翻译可能有性价比优势 | provider 漂移、路由延迟和质量一致性要监控 |
| ASR 后文本翻译 | OpenRouter `minimax/minimax-m3` | 中 | 类似 Qwen，适合 fallback benchmark | 中文表达可能不错 | 生产 SLA 需要固定 provider 和超时策略 |

## 3. 50 分钟成本估算

### 实时音频链路

| 方案 | 单价 | 50 分钟估算 | 备注 |
|---|---:|---:|---|
| OpenAI realtime translate only | $0.034 / min | $1.70 | 最小实时中文字幕链路 |
| OpenAI realtime translate + realtime whisper | $0.034 + $0.017 / min | $2.55 | 推荐生产形态：中文字幕 + 英文 sidecar |
| Gemini 3.5 Live Translate | 约 $0.0368 / min | $1.84 | 官方按音频 token 折算的有效分钟价 |
| Gemini 3.1 Flash Live Preview | $0.005 audio input + $0.018 audio output / min | $1.15 | 便宜，但不是专门翻译模型 |

### 文本翻译链路

本项目的 `V6OKiwbjDZE` 对应 live archive POC 样本当前读取到：

- 本地字幕文件：`artifacts/offline-live-sermon-poc/FsUijL9uB1I.sermon.en-orig.local.vtt`
- 字幕时长：约 30.94 分钟
- 字幕 cue：1,672 个
- 英文词数：约 17,362
- 粗略英文输入 token：约 23,091
- 粗略中文输出 token：约 19,098-27,779

按这个样本密度外推到 50 分钟，约为 37k 英文输入 token、31k-45k 中文输出 token。

| 方案 | 输入/输出单价 | 50 分钟文本翻译估算 | 备注 |
|---|---:|---:|---|
| OpenAI `gpt-5.5-mini` | 上线前以 OpenAI 当前 pricing 为准 | 待复核 | 适合稳定修正和离线高质量字幕 |
| Gemini `gemini-3.1-flash-lite` | $0.25 / $1.50 per 1M tokens | $0.06-$0.08 | 很适合高频段级翻译和离线批处理 |
| Gemini `gemini-3.5-flash` | $1.50 / $9.00 per 1M tokens | $0.33-$0.46 | 用于困难段落或质量对照 |
| OpenRouter `qwen/qwen3.7-plus` | 约 $0.32 / $1.28 per 1M tokens | $0.05-$0.07 before platform fees | 适合作为文本 fallback benchmark |
| OpenRouter `minimax/minimax-m3` | 约 $0.30 / $1.20 per 1M tokens | $0.05-$0.07 before platform fees | 适合作为中文质量对照 |

文本翻译本身很便宜，真正决定 11:30 体验的是音频输入是否足够早、实时 ASR/翻译延迟、字幕稳定性和经文术语准确率。

## 4. 延迟比较

| 架构 | 首屏字幕 | 稳定字幕 | 质量修正 | 适合 11:30 会众 |
|---|---|---|---|---|
| 音频直连 realtime translate | 最快，目标 p50 < 2.5s | 取决于模型的 partial/final 策略 | 较弱，需要 sidecar | 适合主链路 |
| streaming ASR + text translate | ASR 稳定后再翻译，通常慢 1-4s | 更可控 | 最强，可用 glossary 和 scripture resolver | 适合修正链路 |
| 早场直播离线预生成 | 11:30 前已经生成 | 最稳定 | 最强，可人工 review | 如果确认同篇证道，这是最佳体验 |
| 公开视频 VOD 后处理 | 太晚 | 稳定 | 强 | 不满足 11:30 目标 |

推荐 SLA：

- p50 首个中文字幕片段：小于 2.5 秒。
- p95 稳定中文字幕片段：小于 6 秒。
- 断线恢复：小于 10 秒恢复到可读字幕。
- 经文明确引用：90% 以上能显示标准化引用，例如 `Numbers 16` / `民数记 16`。
- 关键人名和神学词汇：通过 glossary 固定翻译，避免同一篇证道内漂移。

## 5. 质量评估标准

实时字幕不是普通机器翻译。对本项目，质量评分应该看这些点：

| 维度 | 权重 | 说明 |
|---|---:|---|
| 意义完整 | 30% | 是否准确传达讲员正在说的主要意思 |
| 中文可读 | 20% | 手机竖屏下是否自然、短句、适合快速阅读 |
| 经文和专名 | 20% | 经文书卷、人名、地名、神学术语是否固定准确 |
| 时间轴可用 | 15% | 字幕是否跟得上讲员，是否出现明显滞后或错位 |
| 稳定性 | 10% | partial 是否频繁大改，是否影响会众阅读 |
| 安全兜底 | 5% | 模型不确定时是否保留英文 sidecar 或标记待复核 |

## 6. Benchmark 设计

需要用 `V6OKiwbjDZE` 做 benchmark，因为这篇证道包含本项目关心的真实特征：圣经经文、英文讲道口语、神学术语、Mariners Church 人名，以及长时间连续音频。

当前已完成的是本地字幕规模和成本 benchmark：用 live archive POC 生成的英文 VTT 估算真实证道文本量，并据此外推 50 分钟成本。尚未完成的是三家 provider 的在线延迟和质量 benchmark，因为这需要实际 API key、网络调用和可计费模型请求；上线前必须补齐这一项。

### 输入

- YouTube VOD：`https://www.youtube.com/watch?v=V6OKiwbjDZE`
- Live archive candidate：`https://www.youtube.com/watch?v=FsUijL9uB1I`
- 本地字幕 fixture：`artifacts/offline-live-sermon-poc/FsUijL9uB1I.sermon.en-orig.local.vtt`

### 实验组

1. OpenAI realtime translate：音频直连，记录 partial/final 字幕时间。
2. Gemini 3.5 Live Translate：音频直连，记录 input/output transcription 和字幕时间。
3. Gemini 3.1 Flash Live Preview：作为低价实时实验组。
4. OpenAI `gpt-5.5-mini`：用英文 ASR cue 逐段或滑动窗口翻译。
5. Gemini `gemini-3.1-flash-lite`：同样文本输入，比较延迟和质量。
6. OpenRouter Qwen / MiniMax：同样文本输入，固定 provider，记录 p50/p95。

### 指标

- `first_partial_ms`：从音频 chunk 进入 provider 到第一段中文字幕出现。
- `first_stable_ms`：第一段可稳定显示的中文字幕出现。
- `segment_final_ms_p50` / `segment_final_ms_p95`：每段完成延迟。
- `revision_rate`：已显示字幕被大幅改写的比例。
- `terms_accuracy`：经文、人名、神学术语准确率。
- `omission_rate`：重要信息漏译比例。
- `readability_mobile`：iPhone 竖屏每行长度和阅读压力。
- `operator_fix_count`：每 10 分钟需要人工修正次数。

### 通过门槛

实时主链路通过门槛：

- p50 首字延迟小于 2.5 秒。
- p95 稳定延迟小于 6 秒。
- 10 分钟内明显误译不超过 3 处。
- 明确经文引用识别准确率不低于 90%。
- iPhone 竖屏两行内可读，避免长句刷屏。

离线/修正链路通过门槛：

- 每 5-15 秒窗口翻译耗时小于 2 秒。
- 术语和人名一致性高于 realtime direct path。
- 可以输出结构化字段：`zh_text`、`source_text`、`scripture_refs`、`terms`、`confidence`。

## 7. 当前推荐

短期 POC：

1. 先接 OpenAI `gpt-realtime-translate` 作为最低延迟主链路。
2. 并行 OpenAI `gpt-realtime-whisper` 或 Gemini ASR sidecar，保留英文时间轴。
3. 每 10 秒用 Gemini `gemini-3.1-flash-lite` 或 OpenAI `gpt-5.5-mini` 做稳定修正，优先修正经文、人名和术语。
4. OpenRouter 放入 benchmark，不进入第一版 11:30 生产主链路。

中期生产：

1. 同时保留 OpenAI realtime 和 Gemini Live Translate 两个 provider，Cloud Run 配置切换。
2. 早场直播成功时，11:30 前发布已 review 的字幕；早场不可用时，退回实时链路。
3. 所有 model output JSONL、VTT/SRT、benchmark metrics 写入 GCS。
4. API key 只存 Google Secret Manager，GCS artifact 不记录 secret value 或 Secret Manager resource name。

## 8. 资料来源

- OpenAI API pricing：<https://openai.com/api/pricing/>
- Gemini API pricing：<https://ai.google.dev/gemini-api/docs/pricing>
- Gemini Live Translation docs：<https://ai.google.dev/gemini-api/docs/live-api/live-translate>
- OpenRouter quickstart：<https://openrouter.ai/docs/quickstart>
- OpenRouter pricing：<https://openrouter.ai/pricing>
- OpenRouter models API：<https://openrouter.ai/api/v1/models>
