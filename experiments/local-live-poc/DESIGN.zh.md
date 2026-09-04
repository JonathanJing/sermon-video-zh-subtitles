# 本地证道实时字幕 POC

## 目标

周日现场只解决两件事：

1. 在 MacBook 单页界面上清楚显示中文字幕，并保留较小的英文原文。
2. 可靠保存录音和事件日志，回家后可以用同一份输入复现实验。

现场不做双路 A/B，不做人工评分，也不连接现有云端管理页面。录音是底线；ASR、翻译或 context 失败时，录音仍应继续。

## 当前可运行范围

```text
MacBook 麦克风
      │
      ├── MediaRecorder ──> 会后下载的音频文件
      │
      ├── AudioContext ───> 页面音量表
      │
      └── UI session ─────> 会后下载的 JSON 事件日志
```

当前页面已经可以选择麦克风、开始/停止录音、显示电平和计时。麦克风 PCM 通过 WebSocket 进入 Gateway，使用能量 VAD、本地 ASR 和 MiLMMT A0 生成稳定字幕；停止后保留 WebM 恢复录音、规范化 ASR WAV、JSONL 事件和 manifest。`sunday-live.sh` 在 MLX runtime 与模型 cache 可用时默认选择 `Qwen3-ASR-0.6B MLX 8-bit`，否则回退到 `whisper.cpp`。

## 当前最小链路

![本地实时字幕运行架构](../../docs/diagrams/local-live-architecture.svg)

只新增一个本地 gateway，不扩展现有页面：

```text
Browser microphone
  -> localhost gateway (PCM + incremental recording)
  -> local streaming ASR
  -> optional context retrieval
  -> one local translation model
  -> caption events back to the page
  -> append-only audio + JSONL + manifest
```

建议接口只有三类：

- `audio_frame(sequence, pcm)`：浏览器发送有序音频帧。
- `caption_event(segmentId, en, zh, state, timing)`：gateway 返回草稿或稳定字幕。
- `session_event(type, detail)`：所有状态、降级和错误追加到日志。

传输边界已经固定：session 控制继续使用 REST；接入 ASR 时新增一条双向 WebSocket 传输 PCM 帧和字幕事件。浏览器保留独立的 MediaRecorder 恢复录音，Gateway 统一管理 VAD、ASR、context 和翻译。具体格式、背压和分阶段落地见 [STREAMING.zh.md](./STREAMING.zh.md)。

首版 gateway 只允许一条现场翻译链路。没有 context 命中、检索超时或 context pack 不可用时，直接使用普通翻译，并写入 fallback 事件。

### 当前 MacBook 与运行时选择

2026-09-03/04 的 tracked 测试记录使用 M1 Max、64 GB 内存；当次 Ollama `0.33.3`、MiLMMT Q8、Qwen3-ASR MLX 和 Whisper fallback 均有运行证据。这是带日期的环境快照，不保证当前本机仍保持相同服务、cache 或版本。真实浏览器麦克风链路已完成英文 ASR、中文 token streaming、UI 显示和落盘验证；修复后的固定 60 分钟长测也已完成，但教会现场彩排和人工 ASR Gold 仍未完成。

当前实现边界：

1. **Working translation backend：MiLMMT-46-4B Q8_0 + Ollama。** A0 固定为 `sermon-milmmt-46-4b-v1-q8:benchmark`，使用 benchmark 已验证的官方 completion prompt、`raw=true`、temperature 0 和 top-k 1。浏览器只访问 gateway，不直接访问 Ollama。
2. **Working ASR：Qwen3-ASR MLX，Whisper fallback。** AudioWorklet 生成 100 ms PCM 帧；Gateway 用 VAD 形成稳定英文片段，只翻译 `asr.final`。一键启动器优先 Qwen3-ASR 0.6B MLX 8-bit，运行时或 cache 不可用时回退到 `whisper.cpp`。
3. **可替换实验：其他 MLX / llama.cpp provider。** 模型和运行时都位于 adapter 后面；直接 MLX 翻译 serving 与后训练产物仍属于 Discovery，只能替换 provider 配置，不能改变 UI、日志或 Weekly Pack 契约。

不要让浏览器直接调用 `11434` 或 `8080`。所有模型调用都经过 localhost gateway，这样 UI 不需要知道模型名称、prompt、context pack 或运行时：

```text
ASRProvider: qwen-mlx-websocket | whisper-cli
TranslationProvider: ollama | mlx_lm
```

首轮推荐组合：

| 用途 | 首选 | 原因 |
|---|---|---|
| 现场英文 ASR | Qwen3-ASR 0.6B MLX 8-bit | 当前一键启动默认；离线与连续 replay 的 provisional winner，Whisper 保留为低资源 fallback |
| 现场中文翻译 | Ollama + MiLMMT-46-4B Q8_0 | 已完成 239 段本机 A0 benchmark，并固定 prompt 与解码参数 |
| 专用翻译候选 | Hy-MT2 1.8B | 专门面向翻译、支持英中；需要先验证 GGUF 或 MLX 转换与提示格式 |
| Apple 原生实验 | 其他 MLX ASR + MLX-LM | 便于比较 Apple Silicon 原生性能；直接 MLX 翻译 serving 尚未晋级当前 A0 |

Qwen3-ASR 是当前 POC 默认，不等于已经通过生产 promotion。七模型离线 bakeoff、Qwen 与 `small.en` 连续 replay、Qwen + MiLMMT 共存和 60 分钟浏览器长测已经完成；正式选择仍被六条人工逐词 Gold 校正和教会现场声学门槛阻塞。不要把单一房间的 VAD 参数推广到现场。

参考：

- [Ollama local API](https://docs.ollama.com/api/introduction)
- [Ollama streaming](https://docs.ollama.com/api/streaming)
- [TranslateGemma in Ollama](https://ollama.com/library/translategemma)
- [MLX-LM HTTP server](https://github.com/ml-explore/mlx-lm/blob/main/mlx_lm/SERVER.md)
- [MLX Whisper](https://github.com/ml-explore/mlx-examples/tree/main/whisper)
- [whisper.cpp](https://github.com/ggml-org/whisper.cpp)
- [Tencent Hy-MT2 1.8B](https://huggingface.co/tencent/Hy-MT2-1.8B)

## Context Pack

Context pack 是候选知识库，不是整篇讲章 prompt。周六与周日视为同一篇讲章的两个 delivery version：大纲和经文方向高度重合，但具体措辞、增删和现场发挥可能不同。分三层：

| 层 | 来源 | 内容 |
|---|---|---|
| Core | 已授权、已审核的历史训练集 | 神学术语、人名、书卷别名、稳定短语映射 |
| Weekly | 已公布的下周经文、系列、讲员材料 | 当周高概率经文和专名 |
| Runtime | 当前英文和最近 1–2 个稳定分段 | 实时命中的 3–8 条短证据 |

构建规则：

- 只从已审核语料抽取短语级映射，不把历史整段译文直接注入。
- 预测的下周内容只提高检索优先级，不能自行补写译文。
- 当前英文始终是唯一 source of truth。
- exact scripture/term/alias 优先；模糊命中只记录，不自动注入。
- 每次记录 pack version、命中来源、分数和是否实际使用。

### 周六直播如何进入 Weekly Pack

可以进入，但需要把“证据”和“可注入内容”分开：

```text
Saturday audio (SHA-256, immutable)
  -> English ASR segments
  -> machine Chinese candidates
  -> scripture / term annotations
  -> weekly-pack.json
  -> Sunday live English retrieval
  -> approved context only
```

- 周六原始音频不进入 prompt；它作为 provenance、时间定位和会后 replay 母本。
- 周六英文字幕用于检索相似片段，即使仍是机器稿也必须保留 `transcriptStatus`。
- 周六机器中文只保存为 `candidateTargetTextZh`，默认 `canInjectTranslation=false`，避免把周六错误在周日放大。
- 人工审核过的短语、经文引用和完全相同的双语片段可以进入 prompt。
- 相似但非完全相同的整句译文不注入；只返回命中证据和审核术语。
- Weekly Pack 有明确 `validUntil`，周日结束后自动失效，不能长期污染 Core Pack。

### 把周六内容用作顺序讲章地图

Weekly Pack 中每个周六片段都有递增的 `sequence`，可选带 `sectionId` 和 `sectionTitle`。周日 gateway 不保存隐式会话状态；页面在每次请求中传回上次的 `cursorSequence`，因此现场和会后 replay 使用完全相同的输入，也能复现同一个检索结果。

```text
Sunday stable English + previous cursor
  -> search Saturday segments near cursor (default +/- 8)
  -> confident local match: suggest next cursor
  -> no local match: global lexical fallback
  -> terms / scripture / reviewed reference version
  -> translate CURRENT SOURCE only
```

首版只做确定性的词汇重叠、短语命中和邻近加权，不引入 embeddings 或 vector DB。四种 replay policy 为：

- `none`：不使用周六 pack，作为 A0。
- `english_alignment_v1`：只检索周六英文地图来维护 cursor；不向翻译 prompt 注入任何周六内容，继续使用冻结 A0 prompt。
- `weekly_terms_v1`：只使用审核术语、审核经文和完全相同的审核译例，作为 A1。
- `saturday_alignment_v1`：在 A1 基础上，把高置信、已审核的相邻周六双语片段作为“另一演讲版本参考”，作为 A2。

只有英文完全相同的审核译文可成为 exact example。位置相邻或语义相近的审核译文不得直接输出，只能放入明确标注的 reference block；prompt 同时声明周六版本可能有增删，任何周日当前英文没有支持的内容都不得复制。机器译文在所有 policy 下都不进入 prompt。

启动器基于 readiness 选择的 policy 同时是 gateway 的能力上限。REST 或 WebSocket 客户端只能选择同级或更低级 policy，不能绕过启动器把 English-only Pack 提升为术语或双语对齐。创建 session 时，gateway 在 manifest metadata 中冻结实际 policy、Pack version、Pack SHA-256、来源日期和有效期。

每个字幕事件额外记录 `previousCursor`、`suggestedCursor`、`alignmentStrategy`、`confidence`、`matchedSegmentId` 和 `contextPolicy`。这既能观察现场是否跑偏，也使回家后的 A0/A1/A2 比较无需重新猜测现场位置。

会后晋级采用单向门槛：经过人工审核、来源授权且多场稳定的术语可以进入 Core Pack；整段音频、未经审核的字幕与单周预测不能自动晋级。每条记录保留周六音频 SHA-256、source id、segment id、时间范围、pack version 和审核状态。

## 会后 A/B

现场只运行一条预先选定的链路。会后从同一份录音做两类 replay：

- 端到端 replay：比较 ASR、切句或完整模型链路。
- 冻结英文 replay：固定 `segmentId`、英文输入、分段和 cursor 序列，比较 `none`、`english_alignment_v1`、`weekly_terms_v1` 与 `saturday_alignment_v1`。

A/B 必须固定模型、量化、解码参数、硬件和输入顺序。人工标签先只保留：A 更好、B 更好、相同、都不好，以及 `meaning_error`、`term_error`、`scripture_error`、`unsupported_addition`。

## 最小现场数据

每场至少保存：

- 原始或规范化音频；
- append-only 字幕/状态事件；
- session manifest；
- 麦克风、模型、量化、context pack 与代码版本；
- `audioStartMs`、`audioEndMs`、ASR 完成、翻译完成、渲染时间；
- 每次 fallback 和错误原因；
- 录音 SHA-256，作为会后 replay 的不可变输入标识。

当前 gateway 已在每次开始时自动创建 `artifacts/sessions/<session-id>/`。MediaRecorder chunk 增量写入恢复录音；100 ms PCM 帧按秒批量写入 `asr-audio.pcm`；事件逐条追加到 `events.jsonl`。停止时生成 `asr-audio.wav`、完成 `manifest.json` 并计算录音与 PCM SHA-256。浏览器 Blob 下载继续作为恢复副本。

## 明确不做

- 摄像头与视频录制；
- 现场 A/B 双路推理；
- 字幕历史、时间线、诊断抽屉和评分页；
- 云同步、发布、PDF、VTT/SRT；
- 登录、用户管理或仪表盘；
- 在模型接入前宣称字幕来自真实翻译。
