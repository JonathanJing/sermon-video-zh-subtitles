# 复盘：20261127 WhisperX Layer 1 时间轴 A/B

## 1. 结论先行

- **类型**：研究/基准实验；不是生产发布、不是 `dual_pdf`、不是 `live_session`。
- **状态**：`machine_ab_requires_human_timing_gold`。
- **结论**：WhisperX 强制对齐可以在 Layer 1 取代 `whisper-1` 的时间轴；不能取代文本。机器证据见 [INDEX.md](INDEX.md)。
- **证据边界**：MFA 是第三模型参照，不是人工 Gold；听审页已生成但未听。没有改生产默认值，没有发布。

## 2. 总时间

墙钟约 **23 分钟**（2026-11-27 21:17 → 21:40 PST）。这是交互式实验，不是排队生产，时间只作工程参考。

| 阶段 | 时长 | 性质 |
|---|---:|---|
| 环境、模型下载、烟测 | 约 6 分钟 | 计算（网络 + CPU） |
| WhisperX 仅对齐 | 66 秒 | 计算 |
| WhisperX 完整转写（对照） | 12 分 45 秒 | 计算；大部分与 MFA/评分重叠 |
| MFA 参照（抽样 + 扩展） | 约 3 分钟 | 计算；含一次返工 |
| 评分、听审页、文档 | 约 8 分钟 | 计算 |

没有人工等待、没有付费 API 等待；返工约 6 分钟，来自首版分块跨掌声和 MFA `c0049` 解析失败。

## 3. 各阶段模型、耗时与速度

| 层/阶段 | 模型或后端 | 调用 | 计算耗时 | 规模 | 速度 | 费用 | 证据 |
|---|---|---|---:|---|---:|---:|---|
| L1 时间轴 A | OpenAI `whisper-1` verbose_json | 复用 | 未重跑 | 6,136 词 / 2,147 秒 | — | 复用，≈US$0.22（历史） | `layer1/raw-whisper.json` |
| L1 时间轴 B | WhisperX 3.8.6 + wav2vec2 | 123 分块 | 66 秒 | 6,136 词 | 0.031× 实时 | 0 | `align-full-v2/whisperx-aligned.json` |
| L1 文本对照 | WhisperX large-v3（faster-whisper） | 1 次 | 12 分 45 秒 | 2,147 秒 | 0.36× 实时 | 0 | `full-run/sermon-16k.json` |
| L1 参照 | MFA 3.4.2 | 117 分块 | 37 秒 + 14 秒 G2P | 5,760 词 | — | 0 | `mfa-all-v3/mfa-aligned.json` |
| L2–L4 | — | — | — | — | — | — | `not_run` |

## 4. 错误

| # | 层/阶段 | 现象 | 原因 | 发现时机 | 处理 | 回归 |
|---|---|---|---|---|---|---|
| 1 | 分块 | MFA 把 `wife` 拉到 6.99 秒 | 分块跨越约 5 秒掌声 | 评分时 | 单元间隔 ≥1 秒强制断块 | `prepare_case.py` 测试 + 重跑 |
| 2 | B 对齐 | 27 个非单调起点、36 对重叠 | 先用 ±1 秒 padding，词可越过分块边界 | 评分时 | 精确边界优先，padding 只作回退 | 重跑后 0/0 |
| 3 | MFA 参照 | `c0049` 报 `Invalid MFA phones timing` | 单块音素层不符合生产适配器严格校验 | 全量参照时 | 排除该块，不修改校验 | 117 块全部通过 |
| 4 | WhisperX CLI | torchcodec 解码警告 | 本机 torchcodec 与 ffmpeg 动态库不匹配 | 烟测时 | `load_audio` 走 ffmpeg 回退；非致命 | 完整转写成功 |
| 5 | 参照覆盖 | 首版只有 1,391 词 / 75 单元 | 只跑了 1/4 抽样 | 评分时 | 扩到 117 块 / 5,080 词 / 216 单元 | 本报告使用扩展版 |

## 5. 可以改进的地方

- **质量**：见 [决策摘要](../../../whisperx-layer1-timeline-ab.zh.md)。下一步是 2 期 shadow + 人工抽查，不是直接切默认。
- **预检**：WhisperX 运行时（torch 2.8）应与生产轻量 `.venv` 隔离；本次用 `artifacts/whisperx-timeline-ab/runtime`。生产接入需要一个受控 worker/容器和模型缓存预检。
- **精度**：B 臂首/尾分块词仍受切音影响；可用重叠窗口 + 取最内层词进一步降低边界偏差，再复测。
- **参照**：MFA 对 OOV 专名的 G2P 可能错位（本次 `Krista` 等）；生产参照应提供确认读法或显式排除 OOV 邻域。
- **自动化**：把 `prepare_case → align → MFA → score` 串成一个工具，输出固定 `summary.json`，便于运行导出器识别；本次导出器没有识别自定义产物名，报告是手写脱敏。

## 6. 实际覆盖范围

- L1 时间轴：执行（A/B/MFA、结构、精度、文本 WER、句级位移、听审页）。
- L1 文本：只做 WER 对照；没有改生产文本链路。
- L2/L3/L4：`not_run`。
- 人工词级 Gold：`not_run`；`review/review.html` 已生成 20 个词 + 10 个单元片段。
- 其他讲员/会场/音乐段：`not_run`。

## 7. 遗留状态

- 本机 `artifacts/whisperx-timeline-ab/` 保留全部产物；模型在 `~/.cache/huggingface`（约 3.3 GB）和 `~/.cache/torch`（360 MB）。
- 没有 Spark 会话、没有未结束的 job hold、没有未上传的构建号。
- 没有生产环境改动；没有发布。

## 8. 外部可见的变化

无。没有部署、没有改生产默认值、没有推送页面或音频；Git 仅新增实验代码、文档和运行报告。
