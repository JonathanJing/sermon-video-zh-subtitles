# 三篇证道中英语料 POC 结果

日期：2026-08-30

状态：端到端生成与完整性校验已完成；边界与翻译质量待人工验收；全部数据禁止进入学生模型训练

## 1. 结论

复用现有 Google Secret Manager 中的 OpenAI key 后，三篇代表性证道已经完成：sermon-only 边界候选、英文语义切分、GPT 首译、中文编辑一轮、双语 QA 一轮、经文解析、确定性检查和完整人工复核队列。

本轮证明管线能够可恢复地跑通，并能保留来源、模型、prompt、哈希、耗时、token 和训练门禁。它没有证明边界或翻译已经达到 Silver/Gold。人工检查还发现三篇的开始边界都落在半句话中，因此本批数据继续保持 `trainingEligibility=blocked` 是必要的。

随后运行的 v2 边界复核没有覆盖 v1：三篇结束 cue 均保持不变，开始 cue 分别从 `cue_00068 -> cue_00067`、`cue_00005 -> cue_00001`、`cue_00188 -> cue_00186`。三个 v2 结果与人工字幕审计一致，但仍是 `requires_operator_review`，不是人工批准。

## 2. 固定样本与产量

三篇都固定为 `split=poc`，并从未来 untouched test 中永久保留出去。

| 视频 | 讲员 | sermon-only 候选窗口 | 段落 | 高优先级人工项 | 经文解析 |
|---|---|---:|---:|---:|---:|
| `cFLQLjzbnVg` | Eric Geiger | 27.19 分钟 | 46 | 24 | 9 已解析 / 2 未解析 |
| `mIyioBLQmJ0` | Christine Caine | 30.73 分钟 | 38 | 34 | 27 已解析 / 1 未解析 |
| `wxcIGSolCvc` | Doug Fields | 30.29 分钟 | 33 | 25 | 10 已解析 / 0 未解析 |
| **合计** | 3 位讲员 | **88.22 分钟** | **117** | **83** | **46 已解析 / 3 未解析** |

83/117（70.9%）段落因自动字幕、专名、数字、经文或双语 QA 风险被标为高优先级。其余 34 条也全部进入普通人工队列；没有任何一条被自动批准。

## 3. 边界人工审计

| 视频 | 开始边界观察 | 结束边界观察 | 当前判断 |
|---|---|---|---|
| `cFLQLjzbnVg` | 从 `cue_00068` 的 `were a part` 开始；需连同前一 cue 才是完整句 | 结束于信息相关祷告的 `Amen`，下一 cue 是 `Let's worship together now` | 结束候选合理；开始点必须修订 |
| `mIyioBLQmJ0` | 从 `cue_00005` 的 `right here at Mariners` 开始；前四个 cue 是同一讲员的问候和自我介绍 | 结束于信息回应，下一 cue 是通用线上 outro | 结束候选合理；开始点必须修订 |
| `wxcIGSolCvc` | 从 `cue_00188` 的 `today now` 开始；前两 cue 是同一讲员的开场问候 | 结束于转入敬拜，随后是音乐和回应诗歌；更晚出现的是整场礼拜祝祷 | 结束候选合理；开始点必须修订 |

这是模型候选，不是人工批准。下一版边界 prompt 应同时满足：

1. 包含同一讲员、与本篇信息直接相关的开场问候。
2. 不从字幕 cue 的句中碎片起步；必要时向前扩展到完整 spoken unit。
3. 继续排除主持人广告、通用线上 outro、回应诗歌和整场礼拜结束语。
4. 提升 prompt version 并使用新 cache namespace，保留本轮 v1 receipt，不覆盖历史结果。

## 4. 自动质量信号

高优先级队列的主要信号是：

- `sourceAsrRisk`：74 次；原始英文是未人工校正的 YouTube 自动字幕。
- `properNounRisk`：35 次；集中在讲员、影视人物、圣经人物和机构名。
- `needsHumanReview`：26 次；双语复核仍有不确定性。
- 经文、数字、遗漏或新增等确定性/模型信号也已进入对应 segment 的 `issues`。

抽样阅读显示中文整体可读，祷告、释经和叙事段落均能形成连续译文；同时也确认了源 ASR 专名错误、半句边界和个别数字告警真实存在。由于尚未建立人工 gold 对照，本轮不能报告 COMET、BLEU、忠实度通过率或人工错误率。

## 5. 成本与吞吐基线

本轮使用 `gpt-5.6-sol`、`reasoning_effort=high` 和同步 Responses API：

| 指标 | 实测 |
|---|---:|
| API 请求 | 69 |
| 输入 token | 273,850 |
| 其中 cache write token | 267,860 |
| 其中 cached read token | 4,760 |
| 输出 token | 313,971 |
| 其中 reasoning token | 214,930（已包含在输出 token 内，不重复计费） |
| API 请求累计耗时 | 4,027.19 秒（67.12 分钟） |
| 内容分钟 / API 累计分钟 | 1.31x |

按 2026-08-30 [OpenAI 官方模型页](https://developers.openai.com/api/docs/models/gpt-5.6-sol)所列价格——输入 US$4/百万、cached input US$0.40/百万、输出 US$20/百万，cache write 按普通输入的 1.25 倍——本轮估算约 **US$7.63**，约 **US$0.086/sermon-only 分钟**。实际账单是最终依据；促销价格、重试、Batch 折扣和后续 prompt 变化都会改变结果。

v2 边界复核新增 3 次请求、25,880 输入 token、869 输出 token和 15.95 秒累计 API 时间，估算约 US$0.15。v1 + v2 合计约 **US$7.77**，即约 **US$0.088/sermon-only 分钟**。

180 个原始视频共约 6,770 分钟。仅按本次样本外推，若 sermon-only 比例相近，模型调用约 US$444；若按整段原始视频上界计算，约 US$585。这个区间只适合预算预留，不是采购承诺，也不含人工审核成本。

## 6. 验证结果与门禁

独立 verifier 状态为 `pass_with_training_blockers`，确认：

- 三篇源字幕哈希未变化。
- 117 个跨证道 segment ID 唯一，各阶段覆盖完全一致。
- 时间轴单调、中文非空、没有 Markdown 泄漏。
- 所有条目都保留 `gpt_isolated_nontrainable` provenance，并进入人工队列。
- 报告和衍生物没有 key 材料或 Secret Manager resource name。

仍然阻断训练的事项：

- 来源证道的模型训练权未确认。
- GPT 输出用于外部 Qwen 学生蒸馏尚未获得书面授权。
- 三篇 sermon-only 边界未人工批准，且开始点已发现需修订。
- 英文自动字幕未人工校正。
- 中文未由双语人员逐条批准。

因此，本轮没有 Silver、Gold、train/dev/test 正式集合，也没有学生训练或模型晋级。

随后已经把 117 条转换为正式、不可变且绑定 `reviewPayloadSha256` 的审核项，并生成空白决定模板。审核包独立校验为 `pass_requires_human_review`；质量目录独立校验为 `pass_training_blocked`。当前决定覆盖仍是 0/117，因此质量目录保持 117 条 `isolated_reference`、0 Silver、0 Gold。这一步只完成了审核基础设施，没有改变上述训练结论。

## 7. 下一轮验收顺序

1. 人工批准或修订三篇开始/结束 cue，重新切分并保留 boundary revision receipt。
2. 先审核 83 条高优先级，再审核其余 34 条；记录英文修订与中文修订为独立字段。
3. 用人工结果计算边界准确率、ASR 修订率、中文忠实度错误率和每分钟人工工时。
4. 只有来源权利与教师输出许可都放行后，才能把合格条目晋级为 Silver/Gold 并开展 4B/9B 学生实验。
5. 三篇 POC 永不进入 untouched test；正式 train/dev/test 必须按整篇证道切分。

## 8. 可复核证据

- 运行汇总：`data/reports/sermon-parallel-corpus-poc/poc-generation-summary.json`
- 独立校验：`data/reports/sermon-parallel-corpus-poc/final-verification.json`
- 模型访问预检：`data/reports/sermon-parallel-corpus-poc/openai-model-access-preflight.json`
- 运行说明：`docs/live-translation-post-training/corpus-poc-runbook.zh.md`
- 扩展门禁：`docs/live-translation-post-training/corpus-poc-expansion-gates.zh.md`
- v2 边界汇总：`data/reports/sermon-parallel-corpus-poc/boundary-review-v2-summary.json`
- v2 边界独立校验：`data/reports/sermon-parallel-corpus-poc/boundary-review-v2-verification.json`
- 生成脚本：`scripts/build_sermon_parallel_corpus_poc.py`
- 边界复核脚本：`scripts/prepare_sermon_boundary_reviews.py`
- 人工审批校验脚本：`scripts/apply_sermon_boundary_approvals.py`
- 边界复核校验脚本：`scripts/verify_sermon_boundary_reviews.py`
- 校验脚本：`scripts/verify_sermon_parallel_corpus_poc.py`
- 审核包汇总：`data/reports/sermon-parallel-review-poc-v1/export-summary.json`
- 审核包独立校验：`data/reports/sermon-parallel-review-poc-v1/final-verification.json`
- 质量目录汇总：`data/reports/sermon-parallel-quality-catalog-poc-v1/summary.json`
- 质量目录独立校验：`data/reports/sermon-parallel-quality-catalog-poc-v1/final-verification.json`
- 人工审核与分层协议：`docs/live-translation-post-training/corpus-human-review-and-quality-tiers.zh.md`
