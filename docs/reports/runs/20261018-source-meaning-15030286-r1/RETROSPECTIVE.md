# 复盘：20261018-source-meaning-15030286-r1

## 结论先行

本次是正式来源含义机器复听，完成 14 次已返回请求，裁定 7 个冻结英文单元；确认 4，未定 3，更正 0。`humanApproval=false`。收据文件 SHA-256 为 `2047e849b7a2b4cb23f43d6bd3aa31d98effb35aa9a1c69761d0753d9a265829`，原始收据、音频和模型输出留在本地私有 artifact；本报告只有脱敏的状态与哈希。

## 总时间

本次没有 journal、起止时间或 timings.tsv，不能给出可信的完整耗时。下次运行补 run journal。

## 各层模型、耗时与速度

| 阶段 | 模型／后端 | 请求 | 费用与用量 | 证据 |
|---|---|---:|---|---|
| 复听 | OpenAI gpt-transcribe / prod | 7 | 成本未知：响应缺可用 token／音频价格结算；不记为零 | `report-input-r1/summary.json` |
| 含义裁定 | gpt-6.1-sol medium / default / prod | 7 | 已知估算费用 $0.027124，非发票核对；全阶段预留 $0.394564 | 同上 |
| Layer 2–4 | not_run | 0 | 本次仅裁定来源含义 | 同上 |

## 错误与疑点

没有未知或失败的 provider 请求。机器裁定的逐单元状态：`chunk-0000-u024` undetermined, `chunk-0000-u025` undetermined, `chunk-0003-u001` transcript_confirmed, `chunk-0003-u039` transcript_confirmed, `chunk-0004-u004` transcript_confirmed, `chunk-0007-u034` undetermined, `chunk-0009-u028` transcript_confirmed。`undetermined` 只提供按冻结英文处理的备注，不代表更正或人工批准。

## 改进

为源含义裁定入口补阶段计时 journal；现有报告不能分离复听、裁定与等待时间。对音频分钟计费结算补可靠来源，避免把 7 个 ASR 请求的成本未知误读成免费。

## 实际覆盖范围

本次仅复听和裁定当前 Source Package / anchor 中列出的单元。没有重建 Layer 1，也没有产生 Layer 2 候选、Layer 3 音频或 Layer 4 发布。

## 遗留状态与外部变化

本地保留原始收据、缓存、裁定备注和预算账本。Dev、Production 页面、设备及场地均 `not_run`。
