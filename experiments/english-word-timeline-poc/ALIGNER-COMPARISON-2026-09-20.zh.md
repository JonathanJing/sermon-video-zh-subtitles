# Qwen ForcedAligner 与 MFA 同输入对比：2026-09-20

## 结论

同一段 60 秒音频、同一份 191 词冻结英文候选上，**MFA 通过当前结构门槛，Qwen ForcedAligner 未通过**：MFA 保留全部 191 词且没有零时长、重叠或词序变化；Qwen 也保留 191 个词位，但其中 3 词为零时长。

这轮只能选出结构更稳的候选，不能宣布 MFA 的边界“更准确”。两者词中点绝对差的中位数为 15 ms、P95 为 55 ms、最大为 90 ms；没有人工逐词 Gold，模型一致仍可能是共同错误。POC 下一轮以 MFA 为主时间轴、Qwen 为 shadow 对照，取得当周原声并完成听审前不进入生产放行。

## 冻结输入

- 音频：2026-09-13 已有生产音频的 sermon clip `300–360` 秒，不是 2026-09-20 问题段落。
- 音频 SHA-256：`5073d5c9fa0ade24ee77518a0ebe2a90c08c8a1025b7ce8a611aac6a61118ace`。
- 英文：同一次 Qwen ASR 候选，规范化后 191 词；两种 aligner 的词序与冻结英文完全一致。
- 英文 SHA-256：`9f1024d29cb3c320bb327a35f08319273370abe8a87506a3b1687d206bb2187b`。

## 运行身份

| 对齐器 | 实际执行 | 固定身份 |
|---|---|---|
| Qwen ForcedAligner | MacBook MLX | `mlx-community/Qwen3-ForcedAligner-0.6B-8bit@0e1a68e91d815300c7c9754b2a7639378b23db15` |
| MFA | DGX Spark CPU，`spark-38f8`，Linux aarch64 | MFA `3.4.2`；官方 `english_mfa` 词典／声学模型和 `english_us_mfa` G2P，实际文件哈希记录在运行回执 |

本机当前 PATH 没有 MFA，因此按仓库已有路由使用 DGX Spark。Spark 只运行独立 MFA CPU 作业，没有改动或重启现有模型服务。

## 结果

| 指标 | Qwen ForcedAligner | MFA |
|---|---:|---:|
| 冻结词位 | 191 | 191 |
| 词序完全一致 | 是 | 是 |
| 零／负时长词 | 3 | 0 |
| 其他结构无效词 | 0 | 0 |
| 当前结构门槛 | 失败 | 通过 |

Qwen 的三个零时长词在 MFA 中均取得正时长：

| 词序号 | 词 | Qwen | MFA | MFA 时长 |
|---:|---|---|---|---:|
| 44 | `to` | 14.480–14.480 | 14.470–14.510 | 40 ms |
| 129 | `going` | 41.120–41.120 | 41.000–41.120 | 120 ms |
| 142 | `the` | 45.280–45.280 | 45.260–45.330 | 70 ms |

逐词边界分歧：

| 绝对差 | 中位数 | P90 | P95 | 最大 |
|---|---:|---:|---:|---:|
| 开始时间 | 20 ms | 50 ms | 70 ms | 120 ms |
| 结束时间 | 20 ms | 50 ms | 75 ms | 120 ms |
| 词中点 | 15 ms | 45 ms | 55 ms | 90 ms |
| 词时长 | 30 ms | 70 ms | 90 ms | 140 ms |

15 个词的中点差超过 50 ms，没有词超过 100 ms；按本次 80 ms 复核阈值，共 6 个词位进入复核表，其中包括三个 Qwen 零时长词。

## 产物与验证

忽略目录中的机器产物：

- `artifacts/english-word-timeline-poc/20260920-qwen-vs-mfa/comparison/comparison-report.json`，SHA-256 `402a8f10b2186559028adb348bd4a5b60521599d35de577eaa96a8a45da47561`。
- `artifacts/english-word-timeline-poc/20260920-qwen-vs-mfa/comparison/word-comparison.tsv`，SHA-256 `9901ebf07912835cdbad22e75abf63e830a6dcee7918a29ec8ffcaf0911f8961`。
- MFA `segments.json`，SHA-256 `24fbf6d2cd9517245939bf98770e6a601016ece90e0c7e3ce16aef7266a29178`。

`test_run.py` 与 `test_compare_aligners.py` 共 7 项定向测试通过。比较器遇到任一 aligner 改词／漏词即失败，并固定输出 `machine_comparison_requires_human_gold`，避免把模型间一致误标为人工准确率。

## 下一门槛

1. 取得 2026-09-20 批准原声，只跑用户指出的漏译／语速异常段落。
2. 对 Qwen 零时长词、两模型分歧最大词、专名、数字、否定词和窗口边界做人工逐词听审。
3. 以人工词界为 Gold 计算边界误差；此前只采用“MFA 在本样本结构通过”的结论。
