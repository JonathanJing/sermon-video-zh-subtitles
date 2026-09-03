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
