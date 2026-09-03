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

当前页面已经可以选择麦克风、开始/停止录音、显示电平和计时，并在停止后提供音频与 JSON 日志。页面中的中英文句子只是有明确标识的界面演示数据；尚未连接真实 ASR 和翻译模型。

## 下一步最小链路

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

首版 gateway 只允许一条现场翻译链路。没有 context 命中、检索超时或 context pack 不可用时，直接使用普通翻译，并写入 fallback 事件。

### 当前 MacBook 与运行时选择

2026-09-03 只读盘点：这台机器是 M1 Max、64 GB 内存；Ollama 本地 API `0.32.15` 正常响应，但当前没有已安装或驻留的模型；`ffmpeg 9.0.1` 已安装；MLX、MLX-LM、MLX Whisper 和 whisper.cpp 尚未安装。

建议按两步推进，避免一次引入两个不确定运行时：

1. **第一条 working backend：whisper.cpp + Ollama。** whisper.cpp 负责英文 ASR，Ollama 只负责英译中。Ollama 已经运行，并提供本地 HTTP、流式输出和性能字段，是最短的翻译接入路径。翻译模型先 benchmark `translategemma:4b`；如果它不能稳定处理证道术语，再测专用翻译模型，而不是马上扩大 UI 或 gateway。
2. **第二条可替换实验：MLX Whisper / MLX-LM。** MLX 在 Apple Silicon 上原生运行；`mlx_lm.server` 提供近似 OpenAI Chat Completions 的本地接口。它适合作为同一个 adapter 后面的实验实现，但官方说明该 server 只适合基本本地服务，不应直接暴露到网络。

不要让浏览器直接调用 `11434` 或 `8080`。所有模型调用都经过 localhost gateway，这样 UI 不需要知道模型名称、prompt、context pack 或运行时：

```text
ASRProvider: whisper_cpp | mlx_whisper
TranslationProvider: ollama | mlx_lm
```

首轮推荐组合：

| 用途 | 首选 | 原因 |
|---|---|---|
| 现场英文 ASR | whisper.cpp + Metal | Apple Silicon 支持成熟，并有实时 microphone/stream 示例 |
| 现场中文翻译 | Ollama + TranslateGemma 4B | 当前机器已有服务，模型体积较小，HTTP 接入最简单 |
| 专用翻译候选 | Hy-MT2 1.8B | 专门面向翻译、支持英中；需要先验证 GGUF 或 MLX 转换与提示格式 |
| Apple 原生实验 | MLX Whisper + MLX-LM | 便于测 Apple Silicon 原生性能，但当前机器尚未安装 |

模型下载和安装不属于本次前端提交。下一阶段先建立 20–50 条冻结英文片段的 translation benchmark，再决定现场默认模型；不要根据模型名称直接决定生产链路。

参考：

- [Ollama local API](https://docs.ollama.com/api/introduction)
- [Ollama streaming](https://docs.ollama.com/api/streaming)
- [TranslateGemma in Ollama](https://ollama.com/library/translategemma)
- [MLX-LM HTTP server](https://github.com/ml-explore/mlx-lm/blob/main/mlx_lm/SERVER.md)
- [MLX Whisper](https://github.com/ml-explore/mlx-examples/tree/main/whisper)
- [whisper.cpp](https://github.com/ggml-org/whisper.cpp)
- [Tencent Hy-MT2 1.8B](https://huggingface.co/tencent/Hy-MT2-1.8B)

## Context Pack

Context pack 是候选知识库，不是整篇讲章 prompt。分三层：

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

## 会后 A/B

现场只运行一条预先选定的链路。会后从同一份录音做两类 replay：

- 端到端 replay：比较 ASR、切句或完整模型链路。
- 冻结英文 replay：固定 `segmentId`、英文输入和分段，只比较 `contextPolicy=none` 与 `contextPolicy=retrieval_v1`。

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

当前浏览器版录音与单个 JSON 日志只是 UI POC。接入 gateway 后，录音应按小块增量落盘，不能等整场结束才生成唯一 Blob。

## 明确不做

- 摄像头与视频录制；
- 现场 A/B 双路推理；
- 字幕历史、时间线、诊断抽屉和评分页；
- 云同步、发布、PDF、VTT/SRT；
- 登录、用户管理或仪表盘；
- 在模型接入前宣称字幕来自真实翻译。
