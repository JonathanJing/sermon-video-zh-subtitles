# 9 月 20 日句级英中对齐 POC

## 结论

两处实际播放错位都通过了句级结构和实测时长门槛。问题不是这些中文必须加速才能放下，而是现有块级排程把中文提前播放了：

| 样本 | 目标英文句 | MFA 英文时间窗 | 已发布中文实测时长 | 当前提前结束 | 按英文句起点重锚后的余量 |
|---|---:|---:|---:|---:|---:|
| `20260920-gap-1218` | 3 | 9.86 秒 | 8.72 秒 | 13.11 秒 | 1.14 秒 |
| `20260920-gap-1880` | 2 | 17.76 秒 | 10.40 秒 | 18.77 秒 | 7.36 秒 |

因此，这两个样本支持下一步把排程单位从大块 `blockId` 改为显式英文句组。它们不证明整篇都能通过，也不证明译意已经由人工逐句确认。

两段均已生成本地试听产物：独立英文原声、按英文句起点重锚的中文、以及左英文／右中文的双声道 WAV。第一段中文在 14.46 秒片段内延后 3.25 秒开始；第二段在 20.14 秒片段内延后 1.01 秒开始。`ffprobe` 验证双声道试听文件分别为 14.46 秒和 20.14 秒，未修改线上音频。

## 输入锁定

- 来源 ID：`7c193fd4-bc90-4f3b-aa00-37dfe8423aa0`。
- 来源媒体 SHA-256：`728f864e92ea08dbce249249369016e0fee47950ec4e6dcb60cd6d83185e8caf`。
- 本次读取的线上 `weekly.json` SHA-256：`6b7bbd018e1df2d39ea5287c9e6a3114ee6a6a0c953e2f39cdc4d3d3244204bf`。
- 中文时长直接取已发布 cue 的开始／结束时间，没有按字数重新估算。
- 英文文字来自既有 Qwen ASR 候选；MFA 只对冻结文字定时，不证明 ASR 完整。

两个 fixture 将窗口左侧承接上一 cue 的残句显式标为 `left_context_fragment_from_previous_published_cue`，不把截断残句偷算进本轮目标覆盖。

## 对齐器复查

两段都以 DGX Spark 上的 MFA 3.4.2、官方 `english_mfa` 词典／声学模型和 `english_us_mfa` G2P 运行。MFA 在两个样本分别得到 35 和 36 个正时长词；Qwen ForcedAligner 各有一个零时长词：

| 样本 | MFA | Qwen | 词中点差中位数 | P95 | 最大值 |
|---|---|---|---:|---:|---:|
| `gap-1218` | 35/35 有效 | 1 个无效 | 15 ms | 111.5 ms | 225 ms |
| `gap-1880` | 36/36 有效 | 1 个无效 | 20 ms | 97.5 ms | 1.385 秒 |

两份比较报告都保持 `machine_comparison_requires_human_gold`。这里只能说 MFA 在结构上通过、Qwen 在这两个样本未通过；没有人工逐词 Gold，不能宣称 MFA 的边界一定更准确。

## 句级契约

`sentence_translation_map.py` 为每个 MFA 英文句生成稳定的 `sourceSentenceId` 和连续 `wordId`，然后验证：

- 所有目标英文句恰好分配一次；
- N:1 合并必须显式列出全部源句；
- 每个源句都有一个存在于最终中文中的候选落点；
- 发布 cue 的文字必须与映射中的中文完全一致；
- 使用发布 cue 的实测中文时长，重锚后不得越过对应英文句组时间窗。

两个实际报告均为 `structural_pass_semantic_review_pending`，且没有结构问题。报告仍固定：

- `semanticCoverageProven=false`；
- `humanTranslationReview=pending`；
- `humanWordBoundaryGold=not_supplied`；
- `releaseEligible=false`。

候选 coverage ledger 只证明每个英文句都有明确中文落点，不能自己证明翻译等义、完整或自然。

## 产物与下一门槛

忽略目录下保留：

- `artifacts/sentence-translation-alignment-poc/20260920-gap-1218/`；
- `artifacts/sentence-translation-alignment-poc/20260920-gap-1880/`。

每段包含 MFA 模型／输入回执、Qwen 与 MFA 比较、句级 `report.json`、文本摘要，以及可听的英文原声、重锚中文和“左英文／右中文”对照 WAV。正式接入前还需要：

1. 对这两段听审 MFA 句界和计划重锚点；
2. 听审已生成的句级重锚片段，确认没有抢句或跨句；
3. 用独立模型或人工检查 coverage ledger 的语义完整性；
4. 增加一个中文接近时间上限的密集负载样本；
5. 扩到整篇后要求零未映射英文句、零超时组，再决定是否替换块级生产排程。
