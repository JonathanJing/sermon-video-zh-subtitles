# Layer 2 三语模型实验盲评表使用说明

对应[实验计划](20260928-model-production-ab-plan.zh.md)与[结果](20260928-model-production-ab-results.zh.md)。本机 `artifacts/model-production-ab-20260928/layer2-{zh-Hans,ko,es}/blind-review.json` 含英文源单元、随机排列的三个选项、初译和 Sol 复核稿；同目录的 `blinding-key.json` 只在评分锁定后揭盲。两份文件均留在 Git 忽略目录，因为包含讲稿与译文。`scripts/experiments/build_blind_review_scores.py` 从匿名包生成同目录 `blind-review-scores.json`，保留每个选项的初译／复核双份空白评分，并绑定匿名包 SHA-256；使用排他创建，防止覆盖已填写的人审数据。

## 评分单位与顺序

1. 每种语言由能核对英语原文的该语言审核者逐组审阅。只给审核者 `blind-review.json` 和对应冻结术语、经文、格式政策；不要给模型臂对照键或其他选项的先验结果。
2. 对每个 `option` 分别评估 `draftUtterances` 和 `reviewedUtterances`。比较英文 `englishUnits`，并检查政策规定的术语、经文与引语；正式已批准译稿可在首轮独立评分后辅助裁决，不能只凭相似度判正确。
3. 记录下列错误数量，按源单元去重；每处注明对应英文单元 ID 和简短解释。零错误要明确填 `0`，未审保持 `null`。

| 字段 | 判定范围 |
| --- | --- |
| `omissionOrDistortion` | 遗漏或改变原意、逻辑关系、神学区分 |
| `negationNumberName` | 否定、数字、专名、指代错误 |
| `scriptureOrQuotation` | 经文版本、经文／引语归属或准确引文错误 |
| `addedMeaning` | 原文没有的事实、命令或神学判断 |
| `naturalness1to5` | 目标语言自然度：1 难以理解，3 可理解但明显需编辑，5 可直接流畅阅读；仅为语言质量，不抵消语义错误 |
| `editMinutes` | 把这份稿件修到审核者可批准状态的实际分钟数；不计等待时间 |

4. 对每个选项分别标注 `criticalError`：只要有一处足以误导听众的否定、数字、经文、人物、引用归属或核心含义错误，就填 `true`，并写证据。自然度高不抵消关键错误。
5. 若两位审核者意见不同，保留各自原始分数、分歧字段与裁决人、裁决依据；不要覆盖首轮评分。评分完毕后再用 `blinding-key.json` 揭盲并聚合每臂的关键错误率、人工修订分钟数及自然度。

匿名包中的 `excludedGroups` 明列三臂有缺项的组。它们计入结构失败率，不能偷偷从实验分母移除；如需比较剩余两臂，另建明确标为两臂配对的分析。任何机器 `semanticReview.status=pass`、语言插件 pass、匿名评分草稿都不是正式 `humanTranslationApproval`；正式候选、音频和发布仍走四层门禁。
