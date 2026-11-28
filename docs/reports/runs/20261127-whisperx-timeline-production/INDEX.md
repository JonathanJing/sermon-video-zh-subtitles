# 运行报告：20261127 WhisperX Layer 1 时间轴生产候选

生成时间：2026-11-28（手写脱敏；产物在忽略目录）

> 后续：2026-11-27 该批准包已设为逐句优先生产默认；2026-11-28 做第一次真实生产测试。默认规则见[生产手册](../../../whisperx-layer1-timeline-production.zh.md)。

## 结论先行

- **交付类型**：Layer 1 时间轴生产工具 + 真实候选包；不是页面、不是 `dual_pdf`、不是 `live_session`。
- **状态**：`default_enabled_pending_production_test`。工具、结构门、`prepare_clip` 消费、批准路径、真实人工批准和默认切换均已完成；等待 2026-11-28 第一次真实生产测试。
- **证据边界**：候选包已由用户在 2026-11-27 21:59 PST 批准，批准包 `translationEligible=true`、`review.humanApproval=true`；机器检查不是人工批准，批准前没有 L2/L3。

## 输入

| 项 | 值 |
|---|---|
| 父英文包 | `artifacts/sentence-first-agent/20261108-sermon-source/layer1/english-source.json`，SHA-256 `391cf435…` |
| 父包状态 | `ready_for_translation`，`review.humanApproval=true`（2026-11-08 用户批准） |
| 源媒体 | `media/Saturday_530pm_Live__1080-2.mp4`，2,147.055 秒，SHA-256 `daf51ba5…` |
| 批准窗口 | 0–2,147.054667 秒，`humanApproval=true` |
| 文本 | 460 个单元、6,136 词；本工具不改写 |

## 工具身份

| 组件 | 身份 |
|---|---|
| 核心 producer | `packages/production/src/tongxing_production/source/whisperx_timeline.py`，SHA-256 `85fec2d2…` |
| runtime adapter | `tools/ops/whisperx_align_runtime.py`，SHA-256 `7b6028b7…` |
| 开工集成 | `experiments/sentence-first-agent/sfa.py`，SHA-256 `14862209…` |
| 测试 | `tests/test_whisperx_timeline.py`，9 项通过 |
| runtime | WhisperX 3.8.6 / torch 2.8.0 / torchaudio 2.8.0 / faster-whisper 1.2.1 / CTranslate2 4.9.1 |
| 对齐模型 | `WAV2VEC2_ASR_BASE_960H` |
| 平台 | Apple M1 Max，CPU；独立 Python 3.11 runtime |

## 运行阶段

| 阶段 | 观测 | 说明 |
|---|---|---|
| 媒体哈希 + 抽音频 | 约 1–2 秒 | 批准媒体 → `source-clip.wav` 66 MB / 2,147 秒 |
| 分块 | <1 秒 | 460 单元 → 123 分块；间隔 ≥1 秒断开 |
| WhisperX 对齐 | **50.3 秒**（0.023× 实时） | 123/123 `chunk_exact`，0 失败 |
| 校验与包构建 | <2 秒 | 0 零/负时长、0 重叠、0 非单调；最长词 2.462 秒 |
| 听审页片段 | 约 5 秒 | 20 个位移最大的单元 |
| 真实批准 | 2026-11-27 21:59 PST | 用户批准；写批准包与收据 |

## 候选结果

| 指标 | 值 |
|---|---|
| 单元 / 词 | 460 / 6,136 |
| 对齐分块 | 123，全部精确匹配 |
| 结构 | 0 零/负时长、0 相邻重叠、0 非单调起点 |
| 最长词 | 2.462 秒 |
| 单元起点位移 | P50 0.1275 / P90 0.4555 / P95 0.5312 / 最大 4.104 秒 |
| 起点 >250 ms / >500 ms | 139 / 34（共 460） |
| 单元终点位移 | P50 0.046 / P90 0.180 / P95 0.297 / 最大 2.076 秒 |
| 终点 >250 ms | 26 / 460 |
| 与 A/B 实验 B 的逐词起点差 | 最大 0.000 秒（6,136 词） |

## 人工批准

| 项 | 值 |
|---|---|
| 批准人 | Jony（chat，2026-11-27 21:59 PST） |
| 批准时间 | `2026-11-28T05:59:19+00:00` |
| 批准包 | `english-source.approved.json`，SHA-256 `b51086be4e4cb5a56ccbe1342f5b6eb4099cbbdbf4c8f4df3449bdcc515ca879` |
| 批准收据 | `timeline-approval-receipt.json`，SHA-256 `c00ec9e15c00817a78f647077ed74c0befc0ca8608840ddfaacfd4304e9dfed4` |
| 语义 | timing-only revision；文本/窗口继承父批准；`wordAlignment` 是新的人工结论 |
| 未改变 | 父包、发布状态、生产默认值、L2–L4 |

## 产物与哈希

忽略目录 `artifacts/sentence-first-agent/20261108-sermon-source/layer1-whisperx/`：

| 产物 | 大小 | SHA-256 |
|---|---:|---|
| `anchor-manifest.json` | 754 KB | `1fccaa1b603747605f1a1f3f2bd0d2636e417e08ffc28e18968a3a9ff426b294` |
| `english-source.json`（候选） | 101 KB | `b1fdcd26941ebbf16fa29fa24045e5096d500829be3ff23dc72d8d6d1cbb989f` |
| `whisperx-words.json` | 426 KB | `b41c2d612110463c89d08a7147c0e07a4ea56e1f3514af0bc0c47a68bdf2b23b` |
| `whisperx-aligned-segments.json` | 695 KB | `6a6f7102ad3dcadcfd90f5171f5e16206b98e29202d3d5e6881ef8c19a00343d` |
| `whisperx-timeline-receipt.json` | 5.9 KB | `d4f3faac744832cfbee7fc4dafb14fe8ed8b4e4ad31b153a278a802291171393` |
| `timeline-review.csv` | 58 KB | `ae501cceea0bd732c992b7f7ff7c3356933894c4e5285a8b1fa0ca90d3ff92fc` |
| `timeline-review.html` | 8.6 KB | `b485d469e4e1e04217359092482fc829af0997143be440d83c2d8b194b49318e` |
| `runtime-result.json` | 618 KB | `190d98a7869fcbb1a3eeae864d0da2447c685c5b5540312353f9618a95a6a14b` |
| `source-clip.wav` | 66 MB | `27946c1ffe33387c7db646107aacf66cc67bd74c81a4303096845d2ce5333232` |
| `english-source.approved.json` | 102 KB | `b51086be4e4cb5a56ccbe1342f5b6eb4099cbbdbf4c8f4df3449bdcc515ca879` |
| `timeline-approval-receipt.json` | 2.2 KB | `c00ec9e15c00817a78f647077ed74c0befc0ca8608840ddfaacfd4304e9dfed4` |

`sfa.py start` 真实 setup 验证（批准包、无翻译/TTS）在 `artifacts/sentence-first-agent/whisperx-timeline-approved-setup-proof/`：`setup.json`（`1c040da7…`）、`decisions.json`（`0a3d0b4b…`）、460 句、460 个切片、setup preflight pass。

早期 `prepare_clip` 验证副本 `artifacts/sentence-first-agent/whisperx-timeline-proof-20261108/`（不代表正式 run）：

| 产物 | 值 |
|---|---|
| `sentences.jsonl` | 460 句，单调，SHA-256 `4f7c03df…` |
| `words.json` | 6,136 词，SHA-256 `ade25652…` |
| `slices/` | 460 个原声切片 |
| `clip.json` | 绑定候选 anchor；媒体 0.526–2145.96 秒 |

## 门禁结果

| 门 | 命令 | 结果 |
|---|---|---|
| 候选结构 | `whisperx_timeline --out <out> --check` | `pass` |
| `prepare_clip` | 用候选 anchor 建 460 句/切片 | 成功；句界单调 |
| 候选包拒绝 | `sfa.py start --timeline-package <candidate>` | 拒绝：`not translation-eligible` |
| 批准包接受 | 真实批准后 `sfa.py start --plan --timeline-package <approved>` | plan 通过；字段自动填充 |
| 批准包字段 | `--check` | `ready_for_translation` + `humanApproval=true` + 四项 `checks=approved` |

## 错误与处理

| # | 现象 | 原因 | 处理 |
|---|---|---|---|
| 1 | 首次合成测试写包时 `artifact_missing`（候选 receipt 尚未存在） | 包 evidence 引用 receipt，receipt 又引用包哈希，形成循环 | 包 evidence 去掉 receipt；receipt 单独绑定包。真实运行前修复 |
| 2 | 批准包四项 checks 原为 `inherited_parent_approved`，发布器要求 `approved` | 发布器只认 `approved` | 批准包四项写 `approved`，另加 `checksInheritedFromParent` 和收据说明；文本/窗口确实继承父批准 |
| 3 | 批准路径初次测试用类属性，测试读不到实例字段 | 测试写法 | 改用实例；真实工具逻辑未改 |

真实候选运行本身 0 失败、0 重试、0 非精确分块。

## 覆盖范围

- **Layer 1 时间轴**：执行（父包校验、媒体哈希、抽音频、分块、WhisperX 对齐、结构门、候选包、听审页、批准路径测试）。
- **Layer 1 文本**：`not_run`（工具不改文本；父包文本已人工批准）。
- **人工时间轴听审/批准**：执行；2026-11-27 21:59 PST 用户批准 timing-only revision。
- **`sfa.py start` setup**：执行；批准包、460 句/切片、setup preflight pass；未进入翻译/TTS。
- **L2/L3/L4**：`not_run`；没有翻译、TTS、发布。
- **真实周更**：`not_run`；批准包已就绪，等待第一次真实周更。

## 外部可见变化

无。没有部署、没有改生产默认值、没有发布页面或音频；Git 只新增工具、测试、文档和本报告。

## 相关

- [生产手册](../../../whisperx-layer1-timeline-production.zh.md)
- [A/B 决策摘要](../../../whisperx-layer1-timeline-ab.zh.md)
- [A/B 运行报告](../20261127-whisperx-timeline-ab/INDEX.md)
- [复盘](RETROSPECTIVE.md)
