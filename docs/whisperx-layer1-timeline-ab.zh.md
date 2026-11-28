# Layer 1 时间轴：WhisperX 与 OpenAI `whisper-1` 的 A/B

状态：`machine_ab_requires_human_timing_gold`。机器对比完成，人工词级听审未完成；本文不改变任何现有 Layer 1 产物的可发布状态。

完整实验、产物哈希和复现命令见[实验 README](../experiments/whisperx-timeline-ab/README.zh.md)，运行记录见[2026-11-27 运行报告](reports/runs/20261127-whisperx-timeline-ab/INDEX.md)。

## 结论

**时间轴可以换，文本不要换。**

- 对同一份 6,136 词、已人工批准的英文表，WhisperX 强制对齐输出 6,136/6,136 词，0 缺失、0 零/负时长、0 相邻重叠、0 非单调起点；当前 `whisper-1` 时间轴有 4 个零/负时长词和 296 对相邻重叠。
- 以独立 MFA 为模型参照（5,080 个可比较词），词中点误差 P50/P95 从 `whisper-1` 的 0.055/0.235 秒降到 WhisperX 的 0.033/0.092 秒；WhisperX 更近 2,929 词，`whisper-1` 更近 1,151 词（1,000 平局）。
- 句级单元（216 个首尾均被 MFA 覆盖）的句首更近数：WhisperX 143 / `whisper-1` 45；句尾 129 / 51。
- 历史锚点构建器合成的 100 个词上，`whisper-1` 时间轴对 MFA 的 P95 为 1.079 秒，WhisperX 为 0.232 秒。这是最直接的收益点：旧时间轴本来就在这些词上借用了错误 span。
- WhisperX large-v3 **自己的文本** WER 为 2.812%，比 `whisper-1` 原始 2.552% 更差，远差于 `gpt-4o-transcribe` 原始 0.455%。因此只换时间轴，文本继续走 `gpt-transcribe`/`gpt-4o-transcribe` + 英文校正。

## 不能直接原地替换

换时间轴会改变 Layer 1 身份：

- 139/460 个句级单元起点移动 >0.25 秒，34 个 >0.5 秒；句尾 26/460 >0.25 秒（9 个 >0.5 秒）。
- 既有中文译文、TTS 和发布包都绑定旧时间轴；按[四层合同](multilingual-production-interfaces.zh.md)，Layer 1 身份变化会使所有 locale 失效。
- 只能对新 run 重建 L2/L3，不能把新时间写回旧包，也不能只改 SRT 而保留旧音频包。

## 建议的落地方式

1. **下一期起并行 shadow。** 保留现有 `whisper-1` 时间轴作为 A，新增 WhisperX 对最终批准英文的强制对齐作为 B；两套都记录时间和哈希，不发布 B。
2. **人工抽查。** 先听 `review/review.html` 中 20 个词级分歧和 10 个句级位移最大的单元，重点听专名、数字、否定、掌声/长停顿边界。机器听审不算人工 Gold。
3. **通过后切新 run 默认值。** 新 run 的 L1 时间轴用 WhisperX；文本/校正不变；旧 run 不迁移。保留 `whisper-1` 作为回退，直到连续两期人工抽查通过。
4. **接入时加结构门禁。** 对齐词序列必须与批准文本逐 token 一致；时间必须有限、正向、单调、在音频范围内；任一分块失败即 fail closed，不插值、不静默丢词。按单元分组，间隔 ≥1 秒处强制断开，避免把掌声塞进对齐窗口。
5. **运行环境隔离。** WhisperX 依赖 torch 2.8，不能塞进当前轻量 `.venv`；用独立 runtime（本次 `artifacts/whisperx-timeline-ab/runtime`，Python 3.11）或容器 worker。仅对齐 2,147 秒音频实测 66 秒（0.031× 实时），M1 Max CPU。

## 尚未回答

- 人工词级 Gold：目前只有 MFA 第三模型参照，没有逐词听审。
- 英文校正链路能否不再依赖 `whisper-1` 的分段：本次只测“保留文本、换时间”，没有测用 WhisperX 分段重做校正。
- 双讲员、音乐/掌声、强口音、其他会场麦克风：未覆盖。
- 生产接入后的费用：WhisperX/MFA 本地为 0，但模型下载约 3.3 GB；`whisper-1` 同规模约 US$0.22/期（历史复盘，不是发票）。

## 相关

- [实验方法、完整指标与复现](../experiments/whisperx-timeline-ab/README.zh.md)
- [运行报告](reports/runs/20261127-whisperx-timeline-ab/INDEX.md)
- [Layer 1 来源合同](multilingual-production-interfaces.zh.md)
- [离线字幕时间轴旧说明](weekly-offline-subtitle-generation.zh.md)
