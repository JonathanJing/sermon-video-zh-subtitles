# 证道中英平行语料 Schema v1

这组 schema 把四种对象分开：

- `review-item.schema.json`：不可修改的模型候选与来源绑定。
- `human-review-decision.schema.json`：人工对英文、中文、经文、专名和数字的决定。
- `released-segment.schema.json`：合并人工决定后的质量目录条目。
- `dataset-manifest.schema.json`：一次版本化发布的数量、hash、split 与授权状态。

质量与训练资格是两个独立轴：

| 字段 | 含义 |
|---|---|
| `qualityTier` | 内容经过自动检查、人工审核或仍在隔离状态 |
| `trainingEligibility` | 权利、教师输出许可、边界和审核门禁是否允许进入训练 loader |

`gold_human_reviewed` 不自动等于 `trainingEligibility=eligible`；反过来，有训练权也不能把未审核内容称为 Gold。

发布条目同时保留 `sourceEnglishSha256`、`releasedEnglishSha256` 和 `releasedChineseSha256`。人工纠正英文时，源字幕 hash 不随发布文本变化；两者不能复用同一字段。

v1 只覆盖完整语义 segment。实时 `WAIT/WRITE` prefix、真实 ASR emission 与 Context Pack hard negative 使用后续独立 schema，不能伪装成历史 YouTube 字幕的真实流式 emission。
