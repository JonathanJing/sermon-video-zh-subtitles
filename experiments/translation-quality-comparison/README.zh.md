# 翻译质量对比：pastors.ai 机器中文 vs 我们的生产中文

这个实验回答一个受限问题：**在同一个英文讲道窗口里，pastors.ai 实际下发的机器中文，和我们生产链生成的中文，哪个更忠实、更流畅、术语更准？**

它不是“谁绝对正确”的评测：没有中文金标；它只比较两个候选，并且只对本次窗口、本次模型/prompt、本次抽样成立。

## 比较对象

| 候选 | 来源 | 说明 |
|---|---|---|
| pastors.ai | capture 的 `session.mandarin.jsonl` final 行 | 直播/TTS 导向的机器翻译；按段 final，`ts` 是落定时间 |
| 我们的 Layer 2 | 生产 run 的 `segments_timed_zh.json` | 与 pastors.ai 最接近的“翻译本身” |
| 我们的阅读版 | 生产 run 的 `reading-edition-v2/reading_blocks.final.json` | 额外经过 2-pass 阅读编辑；比较的是交付文本，不是纯翻译 |

**不要混比**：先把 `--ours layer2` 或 `--ours reading` 写死；阅读版对比不能拿来证明我们的翻译模型更好。

## 流程

```text
session.english.jsonl（英文锚点，provider ts）
  ├── session.mandarin.jsonl（pastors.ai 中文）
  └── segments_timed_zh.json / reading_blocks.final.json（我们的中文）
        ↓ 按时间对齐，生成 English anchor units
        ↓ 分层抽样 + A/B 随机盲化
        ↓ 2 位评分人独立评分（忠实/流畅/错误/偏好）
        ↓ 解盲 + 确定性检查 + bootstrap
        ↓ summary.json / report.md / run report PR
```

对齐是最大的误差源：pastors.ai 中文的 `ts` 是段落落定时间，不是句子起点；我们的段边界也不同。脚本按时间邻近生成 `alignment.jsonl` 并标记 `high/medium/low`，**low 不进主抽样**；抽样前必须人工抽查对齐。

pastors.ai final 的行数决定可用 unit 数。**5 分钟 demo 只有 9 行 final，实际只生成 5 个 eligible unit**；请求 30 个会得到 `warning`。正式对比用完整 80 分钟场次，或把结论明确写为 pilot。

## 命令

### 1. 生成对齐、抽样和盲评表（不调用模型）

```bash
.venv/bin/python experiments/translation-quality-comparison/compare.py prepare \
  --capture-dir artifacts/live-capture/mariners-north-irvine/2026-11-15 \
  --ours-dir artifacts/live-reading-tests/20261115-north-irvine \
  --ours layer2 \
  --outdir artifacts/translation-comparison/20261115-north-irvine \
  --sample-size 30 --seed 20261115
```

输出：

- `alignment.jsonl`：全部 unit 的英文锚点、两个中文候选、覆盖/置信度、flags；
- `sample.json`：抽样、分层、A/B 顺序（**评分前不要给评分人看**）；
- `review.packet.md`：A/B 盲评包；
- `ratings.rater1.csv`、`ratings.rater2.csv`：评分模板；
- `comparison.manifest.json`：输入哈希、参数、计数、脚本哈希。

### 2. 评分

评分人独立填写 CSV，不知道 A/B 来源。列：

```
unit_id,a_adequacy,a_fluency,b_adequacy,b_fluency,preference,
critical_a,major_a,minor_a,critical_b,major_b,minor_b,notes
```

- `adequacy`/`fluency`：1–5；
- `preference`：`A`、`B` 或 `tie`；
- 错误数：非负整数，没有填 0；
- 只评 `review.packet.md` 里的 unit；不参考另一评分人。

### 3. 汇总

```bash
.venv/bin/python experiments/translation-quality-comparison/compare.py score \
  --outdir artifacts/translation-comparison/20261115-north-irvine
```

输出：

- `summary.json`：偏好计数、ours 胜率 + bootstrap 95% CI、分项均分差、错误计数、分层结果、评分人一致性、确定性检查；
- `report.md`：脱敏聚合报告。

`score` 会自动读取 `ratings.rater*.csv`；也可以显式传 `--ratings`。

## 评分维度

| 维度 | 记法 |
|---|---|
| 忠实度/充分性 | 1–5；漏译、增译、反义、否定、数字、经文引用错误单列 |
| 流畅度/可读性 | 1–5；断句、标点、书面语、口语词、重复 |
| 术语一致性 | 按 [`docs/series-terminology.zh.md`](../../docs/series-terminology.zh.md) 和本场术语清单核对 |
| 完整性 | 该 English unit 是否被完整覆盖 |
| 严重度 | critical（教义/否定/数字/经文）、major（漏译/增译/人名）、minor（风格/标点） |
| 偏好 | A / B / tie，附一句理由 |

## 统计口径

- 偏好：`ours` / `pastors` / `tie` / `disputed`；`disputed` 是评分人偏好不一致，**不进主胜率分母**；
- 胜率：`ours / (ours + pastors)`，bootstrap 95% CI；
- 分数：每个 unit 对评分人取均值，再算 `ours - pastors` 的均值与 bootstrap CI；
- 错误：按来源汇总 critical/major/minor；
- 一致性：偏好完全一致率、分数平均绝对差；
- 确定性检查：数字/经文 regex 的缺失/多余提示，只是提示，不是语义判断。

## 结论规则

- 只有人工评分显示稳定优势（胜率 CI 下界 > 50% 或分项 CI 不含 0），才考虑改生产链；
- 若差异落在 CI 内，维持现状或扩大样本，不宣布赢家；
- 若双方都有 critical 错误，先加确定性门禁，再谈偏好；
- pastors.ai 中文只能作对照，**不得**作为 Layer 2 批准文本、训练金标或“已验证样例”；
- 机器检查/LLM judge 不能替代人工批准。

## 产物与边界

- 完整对齐文本只留在本机 gitignored `artifacts/`；报告只放聚合、分布、脱敏示例和哈希。
- 不调用模型、不联网、不产生费用。
- 一次对比只覆盖一场/一个窗口；不能外推到其他讲员、系列、语言或模型版本。
- 没有中文金标；这是相对比较。
- 需要至少 2 位独立评分人；1 位时只能做 pilot，报告要写清单人偏差。

## 本机 prepare 试跑

2026-11-14 用 5 分钟 demo 的 `session.english.jsonl` + `session.mandarin.jsonl` + 我们的 `segments_timed_zh.json` 跑了一次 `prepare`：143 行英文 → 13 个 unit；9 行 pastors.ai final → 只有 5 个 eligible（2 high / 3 medium），请求 10 个时写出 warning。**这不是质量结论**，只验证了对齐/抽样/盲评表能跑通，也暴露了短窗口 final 行数不足的问题。

## 相关

- 采集与阅读版：[`experiments/live-translate-capture/README.zh.md`](../live-translate-capture/README.zh.md)
- 可复跑 runbook：[`AGENTS.md`](AGENTS.md)
- 机器质量口径：[`docs/machine-quality-waiver.zh.md`](../../docs/machine-quality-waiver.zh.md)
