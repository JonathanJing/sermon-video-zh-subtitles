# 证道中英平行语料人工审核与质量分层

日期：2026-08-31

状态：POC 审核包和质量目录工具已完成；当前 0/117 人工决定，0 Silver，0 Gold，全部禁止训练

## 1. 结论

当前三篇 POC 已经转换为 117 条不可变、hash-bound 的人工审核项，但这只是把模型候选整理成可审计的工作包，不是人工审核完成。

质量与训练资格必须分开：

- `qualityTier` 回答“内容经过了哪一级质量控制”。
- `trainingEligibility` 回答“权利、教师输出使用授权、边界和质量门禁是否允许训练”。
- 即使一条内容成为 `gold_human_reviewed`，在来源训练权和 GPT 外部学生蒸馏许可未确认时，仍然是 `trainingEligibility=blocked`。

当前目录实测为：117 条 `isolated_reference`、117 条 `pending_human`、0 条人工决定。独立 verifier 状态为 `pass_training_blocked`。

## 2. 对象与不可变关系

```text
review item + reviewPayloadSha256
                |
                v
       final human decision
                |
                v
     quality catalog segment
                |
                v
       dataset manifest
```

四种正式对象位于 `schemas/sermon-parallel-corpus-v1/`：

| 对象 | 用途 | 是否可直接编辑 |
|---|---|---|
| `review-item` | 固定原始英文、中文候选、时间轴、cue、边界、风险和模型来源 | 否；改变候选必须重新导出 |
| `human-review-decision` | 记录听校、英中裁决、经文/专名/数字检查、错误类型和审核者 | 是；但必须绑定当前 `reviewPayloadSha256` |
| `released-segment` | 合并决定后的内容质量目录 | 否；由脚本生成 |
| `dataset-manifest` | 记录完整数量、split、hash、状态和全局 blocker | 否；由脚本生成 |

旧决定不能套到新内容上。只要英文、中文候选、cue、边界或 provenance 改变，`reviewPayloadSha256` 就会改变，旧决定会被拒绝。

## 3. 正确审核顺序

1. 先对三篇 sermon-only 边界进行源音频审批。当前 v2 只是模型候选，三篇均未批准。
2. 用批准后的边界生成新的 POC 版本；不要覆盖 v1。
3. 从新 POC 版本重新导出 review bundle。边界变化可能改变 segment 与 review hash。
4. 先审 83 条 high，再审 34 条 normal；每条都听对应源音频。
5. 英文只在 `approvedEnglish` 中纠正，原始 YouTube 自动字幕保持不变。
6. 中文选择 `keep` 或 `corrected`。周六稿和邻段只能帮助识别术语，不能给当前英文添加没有说出的信息。
7. 逐项确认经文、专名和数字；有实质错误时填写 `materialErrorTypes`。
8. 只把已经完成的 final decision rows 写进审核根目录的 `human-decisions.jsonl`。不能把 `pending_human_input` 模板行混入决定文件。
9. 生成质量目录并运行独立 verifier；任何 hash 漂移、未知 ID 或伪批准都会失败停止。

三篇源音频的直接时间点和决定填写步骤见 [边界音频审核指南](./corpus-boundary-operator-review-guide.zh.md)。

审核者不能只读字幕。`status=approved` 强制要求：

- `audioChecked=true`
- 英文为 `keep` 或 `corrected`
- 中文为 `keep` 或 `corrected`
- `scriptureChecked=true`
- `properNounsChecked=true`
- `numbersChecked=true`
- `adjudicationComplete=true`
- reviewer、role 和带时区的 `reviewedAt`

## 4. 分层规则

| 边界 | 内容人工决定 | 自动风险 | 质量层 | 训练资格 |
|---|---|---|---|---|
| 未批准 | 无 | 任意 | `isolated_reference` | blocked |
| 已批准 | 无 | normal 且无实质风险 | `silver_automatic_candidate` | blocked，直到 Silver 校准和权利门禁通过 |
| 任意 | `changes_required` / `rejected` | 任意 | `isolated_reference` | blocked |
| 未批准 | `approved` | 任意 | `human_reviewed_boundary_blocked` | blocked |
| 已批准 | `approved` | 任意 | `gold_human_reviewed` | 仍由权利与教师许可单独决定 |

`silver_automatic_candidate` 中的 candidate 是刻意保留的：它表示规则命中，不表示当前 POC 已经校准通过，也不表示可以训练。

POC 的 34 条 normal 要全部由人核对。若其中任何一条出现 material error，则自动 Silver 校准为 fail，先修正 prompt、风险规则或 validator，再重新校准。完成审核后，这 34 条本身会因人工决定进入 Gold 或其他人工状态；它们的作用是验证后续未审样本能否安全使用 Silver 规则。

质量报告还单列 `riskRuleCalibration`：只有 117 条全部审核后才计算完整覆盖；任何 material-error segment 落在 normal 都表示高风险规则存在漏报，并把该门禁标成 fail。没有人工标签时 recall 保持 `null`，不能用 100% 代替未知。

## 5. 当前审核包

正文衍生物位于已忽略目录：

```text
data/derived/sermon-parallel-review-poc-v1/
  review-items.all.jsonl
  human-decisions.template.all.jsonl
  README.zh.md
  <videoId>/review-items.jsonl
  <videoId>/human-decisions.template.jsonl
```

当前统计：

| 指标 | 数量 |
|---|---:|
| 总条目 | 117 |
| high | 83 |
| normal | 34 |
| final 人工决定 | 0 |
| `sourceAsrRisk` | 74 |
| `properNounRisk` | 35 |
| `needsHumanReview` | 26 |
| `scriptureMismatch` | 3 |
| `additionRisk` | 2 |
| `omissionRisk` | 1 |
| `numberMismatch` | 1 |

这个 v1 审核包绑定尚未批准、且已经发现起点问题的 v1 边界。因此它适合检查流程和准备审核，但不应投入正式逐条审核。正式审核应在三个 v2 边界获音频批准、重新切分和重新导出之后开始。

## 6. 命令

从 POC 导出审核包并独立验证：

```bash
uv run --with-requirements requirements.txt python \
  scripts/export_sermon_parallel_review_bundle.py

uv run --with-requirements requirements.txt python \
  scripts/verify_sermon_parallel_review_bundle.py
```

审核过程中，可以把已完成的 final rows 逐步合并为：

```text
data/derived/sermon-parallel-review-poc-v1/human-decisions.jsonl
```

不建议手工维护这份 JSONL。边界批准并重新导出审核包后，启动仅监听本机的审核界面：

```bash
uv run --with-requirements requirements.txt python \
  scripts/serve_sermon_parallel_review.py --open
```

工具嵌入对应 YouTube 时间点，逐条显示英文、中文、经文、专名、模型备注与风险标签。提交时会验证 `reviewPayloadSha256`、必需核对项和并发版本，原子写入当前决定，并在 `decision-history/` 留下每次新建或替换的完整 receipt。

当前 v1 包的边界尚未批准，所以可写模式会拒绝启动。检查现状或只读预览使用：

```bash
uv run --with-requirements requirements.txt python \
  scripts/serve_sermon_parallel_review.py --check

uv run --with-requirements requirements.txt python \
  scripts/serve_sermon_parallel_review.py --read-only --open
```

服务固定绑定 `127.0.0.1`，使用临时 session cookie、同源写入限制和 CSP；不会对局域网或公网开放。

随后生成并验证质量目录：

```bash
uv run --with-requirements requirements.txt python \
  scripts/build_sermon_parallel_quality_catalog.py

uv run --with-requirements requirements.txt python \
  scripts/verify_sermon_parallel_quality_catalog.py
```

质量目录位于 `data/derived/sermon-parallel-quality-catalog-poc-v1/`；Git 可审查的数量、覆盖和独立验证报告位于 `data/reports/sermon-parallel-quality-catalog-poc-v1/`。

## 7. 当前全局 blockers

- 三篇边界尚未由人对照音频批准。
- 英文/中文人工决定为 0/117。
- 来源证道用于模型训练的权利未确认。
- GPT 输出用于外部 Qwen 学生蒸馏的授权未确认。
- 34 条 normal 的 Silver 精度校准尚未开始。

在这些 blocker 消失前，不能扩到 180 篇，不能将任何条目写成 `trainingEligibility=eligible`，也不能启动学生模型后训练。
