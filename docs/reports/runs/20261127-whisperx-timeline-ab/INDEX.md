# 运行报告：20261127 WhisperX Layer 1 时间轴 A/B

生成时间：2026-11-28（报告由本机 agent 手写脱敏，导出器未识别本轮自定义产物名）

## 结论先行

- **交付类型**：研究/基准实验，不是 `four_layer_release`、`dual_pdf` 或 `live_session`。
- **目的**：回答“WhisperX 能否在 Layer 1 取代 OpenAI `whisper-1` 的词级时间轴，精度如何”。
- **最终状态**：`machine_ab_requires_human_timing_gold`。机器证据支持“时间轴可以换、文本不要换”；人工词级听审未完成。
- **证据边界**：A 臂是历史生产时间轴，B 臂是 WhisperX 对同一份人工批准英文的强制对齐，MFA 是第三模型参照。三者都不是人工词级 Gold；没有发布、没有改生产默认值、没有产生付费 API 调用。

## 输入

| 项 | 值 |
|---|---|
| 日期 | 2026-11-08 |
| 来源 | 周日证道整段媒体，已人工批准窗口 0–2,147.054667 秒 |
| 音频（本次对齐） | `media/sermon-16k.wav`，2,147.051 秒，SHA-256 `27946c1ffe33387c…` |
| Layer 1 清单 | `layer1/anchor-manifest.json`，460 个单元、6,136 词 |
| 英文批准 | `humanApproval=true`，reviewer `Jony (chat)`，2026-11-08T04:02:23Z |
| A 臂 | OpenAI `whisper-1` `verbose_json` 词时间，经历史构建器映射到校正文本 |
| B 臂 | WhisperX 3.8.6 强制对齐同一份批准文本 |
| 参照 | MFA 3.4.2（`english_mfa` + `english_us_mfa`），117 个安全分块、5,760 词 |

## 环境与模型

| 组件 | 身份 |
|---|---|
| WhisperX | `3.8.6` |
| torch / torchaudio | `2.8.0` / `2.8.0` |
| faster-whisper / CTranslate2 | `1.2.1` / `4.9.1` |
| 转写模型 | `Systran/faster-whisper-large-v3`，HF snapshot `edaa852ec7e145841d8ffdb056a99866b5f0a478` |
| 对齐模型 | `torchaudio.pipelines.WAV2VEC2_ASR_BASE_960H` |
| MFA | `3.4.2`，本机 `artifacts/local-runtime/mfa-macbook/env/bin/mfa` |
| 平台 | Apple M1 Max，CPU（CTranslate2 int8；未使用 MPS） |

## 运行阶段与耗时

| 阶段 | 命令入口 | 观测耗时 | 说明 |
|---|---|---|---|
| 案例冻结 | `prepare_case.py` | <1 秒 | 460 单元 → 123 个对齐分块 |
| WhisperX 仅对齐 | `run_whisperx_align.py` | 66 秒 | 123 分块，0 失败；0.031× 实时 |
| WhisperX 完整转写（对照） | `whisperx` CLI | 约 12 分 45 秒 | 2,147 秒音频；0.36× 实时；仅用于文本 WER |
| MFA 参照 | `run_mfa.py --all-safe --skip-chunk c0049` | 37 秒对齐 + 约 14 秒 G2P | 117 分块、5,760 词 |
| 评分与听审页 | `score_ab.py`、`build_review.py` | <10 秒 | 30 条听审片段 |

没有付费 API 调用；没有 Spark 调用；没有改生产代码或发布。

## 结果

### 结构

| 检查 | A (`whisper-1`) | B (WhisperX) |
|---|---:|---:|
| 输出词数 | 6,136 | 6,136 |
| 零/负时长 | 4 | 0 |
| 相邻重叠 | 296 | 0 |
| 非单调起点 | 0 | 0 |

### 以 MFA 为模型参照（5,080 词，边缘保护 0.75 秒）

| 指标 | A P50/P95 (s) | B P50/P95 (s) | B 更近 | A 更近 | 平局 |
|---|---|---|---:|---:|---:|
| 起点 | 0.070 / 0.420 | 0.057 / 0.176 | 2,477 | 1,848 | 755 |
| 终点 | 0.060 / 0.350 | 0.025 / 0.113 | 3,297 | 868 | 915 |
| 中点 | 0.055 / 0.235 | 0.033 / 0.092 | 2,929 | 1,151 | 1,000 |
| 时长 | 0.130 / 0.500 | 0.060 / 0.230 | 3,467 | 1,240 | 373 |

句级单元（216 个首尾均被 MFA 覆盖）：

| 锚点 | A P50/P95 (s) | B P50/P95 (s) | B 更近 | A 更近 | 平局 |
|---|---|---|---:|---:|---:|
| 起点 | 0.100 / 0.463 | 0.038 / 0.190 | 143 | 45 | 27 |
| 终点 | 0.065 / 0.265 | 0.032 / 0.210 | 129 | 51 | 33 |

### 文本 WER（对批准英文表，6,152 参考词）

| 转写 | WER | 替换 | 删除 | 插入 |
|---|---:|---:|---:|---:|
| `gpt-4o-transcribe` 原始 | 0.455% | 19 | 4 | 5 |
| `whisper-1` 原始 | 2.552% | 78 | 48 | 31 |
| WhisperX large-v3 | 2.812% | 90 | 55 | 28 |

### 句级单元 A→B 位移

| 锚点 | P50 | P95 | 最大 | >250 ms | >500 ms |
|---|---:|---:|---:|---:|---:|
| 起点 | 0.128 | 0.531 | 4.104 | 139/460 | 34/460 |
| 终点 | 0.046 | 0.297 | 2.076 | — | — |

## 产物与哈希

以下文件都在被忽略的 `artifacts/whisperx-timeline-ab/`，不进 Git：

| 产物 | 大小 | SHA-256 |
|---|---:|---|
| `case-20261108/case.json` | 2.4 MB | `4d28b699a751eeadd455a8254421e5fdfc54b1c807234d70cc26a20c468b786c` |
| `align-full-v2/whisperx-aligned.json` | 1.7 MB | `d943cf198b212f8c890e017be9f6a1e261194442b715730539947006b64e27fb` |
| `mfa-all-v3/mfa-aligned.json` | 2.9 MB | `b901801cf6364841ab3e24dc6cf6bb19f95e436564c4e5158946e317ea42ab4b` |
| `full-run/sermon-16k.json` | 900 KB | `1f701fb581e2465705a0a6176adcde4b45ebe0250908ebe529ca303b38db56d5` |
| `report-final/report.json` | 208 KB | `17f65807024ab4fc7fdf82478dec8baa06f4a51932ce06a9ef34d05fa3b314b8` |
| `report-final/summary.md` | — | `2345c54feabd1caae5cf85b53670d11101bd80c4cc428bd0d1a7347c7a1f860c` |
| `report-final/review/review.html` | — | `09be12899d07b1f96e681b7baeeea34486f33ee0c195e832974f185b2972e907` |

MFA 模型、词典、G2P 的 SHA-256 在 `mfa-all-v3/mfa-aligned.json` 的 `mfa.identity` 中；本报告不复制这些长哈希。

## 错误与处理

| # | 现象 | 原因 | 处理 |
|---|---|---|---|
| 1 | 首版分块跨越 5 秒掌声，MFA 把 `wife` 拉到 6.99 秒，`Krista` 被推到 76.85 秒 | 对齐窗口跨越长非语音段 | 改为单元间隔 ≥1 秒强制断块；MFA 参照重跑，异常消失 |
| 2 | 首版 WhisperX 用 ±1 秒 padding，27 个非单调起点、36 对重叠 | padded 窗口允许词越过分块边界 | 改为精确边界优先、padding 仅作回退；重跑后 0 非单调、0 重叠 |
| 3 | MFA `--all-safe` 在 `c0049` 报 `Invalid MFA phones timing` | 单个分块的音素层解析不符合生产适配器的严格校验 | 排除 `c0049` 后重跑 117 块；不修改适配器、不跳过校验 |
| 4 | WhisperX CLI 报 torchcodec 解码失败警告 | 本机 torchcodec 与 ffmpeg 动态库不匹配；`whisperx.load_audio` 走了 ffmpeg 回退 | 非致命；记录在 `full-run/whisperx.log`，不影响结果 |
| 5 | 首版 MFA 参照只有 1,391 词，句级覆盖 75 个 | 先跑了 1/4 抽样 | 扩到 117 块、5,080 可比较词、216 个单元；本报告使用扩展版 |

## 覆盖范围

- **L1 时间轴**：执行（A/B/MFA、结构、精度、文本 WER、句级位移、听审页）。
- **L2/L3/L4**：`not_run`；本实验不翻译、不合成、不发布。
- **人工词级 Gold**：`not_run`；`review/review.html` 已生成 20 个词和 10 个单元的听审片段，等待人工。
- **其他音频**：`not_run`；只测 2026-11-08 一期、单讲员、CPU 路径。

## 外部可见变化

无。没有部署、没有改生产默认值、没有推送页面或音频。Git 只新增实验代码、文档和本报告。

## 相关

- [实验 README](../../../../experiments/whisperx-timeline-ab/README.zh.md)
- [决策摘要](../../../whisperx-layer1-timeline-ab.zh.md)
- [复盘](RETROSPECTIVE.md)
