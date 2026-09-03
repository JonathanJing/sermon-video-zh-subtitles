# 三篇语料 POC 扩展到 180 篇的门禁

日期：2026-08-30

状态：6 篇 train/dev canary 已完成；当前总体结论为 `needs_pipeline_revision`

这组门禁只判断“语料生成流程能否从 3 篇扩展到 180 篇”。它不替代学生模型的实时翻译 promotion gate。

## 1. 当前门禁表

| 门禁 | 通过标准 | 当前证据 | 状态 |
|---|---|---|---|
| 原始来源冻结 | 3/3 manifest 与 cue SHA-256 保持不变 | 独立 verifier 通过 | pass |
| sermon-only 边界 | 3/3 对照源音频，由人确认完整 spoken unit，并绑定 source/review hash | v2 已收敛三个开始 cue，尚无人工音频批准 | pending |
| POC 英文校正 | 117/117 对照音频；专名、数字、经文、关键否定全部裁决 | hash-bound 审核包已导出；final decision 0/117 | pending |
| POC 中文校准 | 117/117 双语人工复核；严重新增、关键遗漏、经文错误均为 0 | 质量目录为 117 isolated、0 Silver、0 Gold | pending |
| 自动 Silver 精度 | 当前 34 条普通队列全部人工核对，不能出现 material error；高风险规则漏报为 0 | normal 审核 0/34，校准状态 pending | pending |
| 结构与 lineage | ID、时间轴、阶段覆盖、来源哈希、prompt/model receipt、队列完整 | 117/117 通过 | pass |
| 去重与泄漏 | POC 三篇固定 `split=poc`，永不进入 untouched test；跨证道 ID 唯一 | verifier 通过 | pass |
| 整篇 split 冻结 | 180 篇按 `sermonId` 分成 train/dev/test/POC，所有衍生物继承父 split | 141/18/18/3；独立 split verifier 通过 | pass |
| 凭据安全 | key/resource name 不进入衍生物或报告 | verifier 通过 | pass |
| 成本 | 模型调用不高于 US$0.10/sermon-only 分钟，另报人工成本 | v1 + v2 约 US$7.77 / 88.22 分钟，即约 US$0.088/分钟 | pass（模型调用） |
| 同步吞吐 | 每篇累计 API 时间不高于对应 sermon-only 时长；相同输入重跑不得重复调用 | 三篇均快于 1.0x realtime；cache replay 已验证 | pass（POC） |
| 180 篇调度 | 失败可按 video/stage 恢复，受控并发/Batch 不覆盖 receipt，且先做 5–10 篇 canary | 6 篇、265 段完成；两槽并发与缓存恢复通过，但同步长尾导致多次批次降级，出现 78 个重复成功阶段-段绑定；API 累计等待/内容时长 1.015x | needs_pipeline_revision |
| 来源训练权 | rights receipt 明确允许云端处理、本地训练及目标分发范围 | 未确认 | blocked |
| GPT 外部蒸馏许可 | 书面授权允许把 GPT 输出用于 Qwen 学生训练，或改用获准教师 | 未确认 | blocked |

只要任何 `pending`、`needs_pipeline_revision` 或 `blocked` 硬门禁存在，就不得启动 180 篇生成，也不得把 POC/canary 条目标记为 Silver/Gold。用户已接受独立模型复核作为当前文本质量基线，但这不等同于音频听校、人工 receipt 或训练授权。

## 2. 质量判定口径

`material error` 包括：

- 改变讲员主张、否定、条件、因果或对象。
- 遗漏或新增完整信息单元。
- 人名、地名、机构、数字或经文引用错误。
- 把周六资料或相邻段落内容加入当前段。
- 中文虽通顺，但不由当前英文支持。

Silver 不是“模型觉得没问题”。只有完成 117 条 calibration 后，才能用人工标签估计自动 normal/high-priority 规则的精度和漏报。POC 中 34 条普通队列若发现任何 material error，先修 validator/prompt 并重新校准，不自动晋级。

Gold 仍要求逐条人工确认英文与中文，并记录 reviewer、时间、修订和 source hash。

## 3. 成本和吞吐说明

- US$0.10/分钟是本项目第一轮扩展上限，不是 OpenAI 的价格承诺。
- reasoning token 已包含在 output token，不重复计费。
- 180 篇预算外推必须同时列模型费用、重试、人工英文听校、中文复核和 adjudication 工时。
- POC 的 1.31x 内容时间/API 时间只能证明同步基线可运行；扩展前仍要验证受控并发或 Batch 的限流、失败恢复和 receipt 完整性。

## 4. 下一次决策所需证据

1. 三个 hash-bound `approved-boundary.json`。
2. 117 条人工英文/中文审核记录及 material-error 汇总。
3. 普通队列精度、高风险召回、审核者一致率与 adjudication 报告。
4. rights manifest 与教师输出许可结论。
5. 用异步/Batch 调度修复本次 6 篇 canary 暴露的尾延时与重复请求，再补 provider billing export 成本核对；当前验证见 `data/reports/sermon-parallel-corpus-expansion-v1/canary-verification.json`。

这些证据齐备后，扩展决策只能是 `go_for_canary`、`needs_pipeline_revision` 或 `blocked_by_rights`，不能仅凭“脚本跑通”直接进入 180 篇。
