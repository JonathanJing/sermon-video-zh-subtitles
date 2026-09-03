# 三篇证道中英语料 POC 运行说明

日期：2026-08-30

状态：隔离研究 POC；不构成 Silver、Gold 或可训练数据集

## 1. 固定样本

| 视频 ID | 选择原因 |
|---|---|
| `cFLQLjzbnVg` | 最新 Eric Geiger 主讲，约 30 分钟 |
| `mIyioBLQmJ0` | Christine Caine 主讲，覆盖不同讲员与口音 |
| `wxcIGSolCvc` | Doug Fields 较旧长视频，约 55 分钟，覆盖复杂 sermon-only 边界 |

三篇全部标记为 `split=poc`，未来不得再进入 untouched test。

## 2. 凭据处理

运行时只接受 Google Secret Manager resource reference。脚本在内存中读取 key，不把 key 或 resource name 写入衍生物、报告或 Git。

本地 `.env` 不是本流程的默认路径。含正文的衍生物写入已忽略的 `data/derived/`。

## 3. 流程

```text
immutable YouTube auto captions
  -> coarse boundary candidate
  -> exact cue boundary candidate
  -> semantic/timed English segments
  -> GPT first translation
  -> candidate proper-name glossary
  -> Chinese edit pass 1
  -> bilingual QA/edit pass 2
  -> Scripture resolver + deterministic validators
  -> complete human-review queue
```

所有 API batch 按 prompt、模型、reasoning 和输入哈希缓存。相同输入重跑会读取缓存；输入或 prompt 改变而缓存路径未改变时，脚本拒绝静默复用。

## 4. 训练资格

每条 GPT 产物固定为：

```json
{
  "qualityTier": "isolated_reference",
  "reviewStatus": "model_reviewed_requires_human",
  "trainingEligibility": "blocked",
  "teacher": {
    "provenance": "gpt_isolated_nontrainable"
  }
}
```

当前 blockers：

- 证道来源的模型训练权尚未确认。
- GPT 输出用于外部 Qwen 学生训练的授权尚未确认。
- sermon-only boundary 尚未人工批准。
- YouTube 自动英文字幕尚未人工校正。
- 中文尚未双语人工确认。

复用 API key 只解除技术凭据阻塞，不解除以上任何门禁。

## 5. 运行

```bash
PROJECT_ID="$(gcloud config get-value project)"

uv run --with-requirements requirements.txt python \
  scripts/build_sermon_parallel_corpus_poc.py \
  --api-key-secret "projects/$PROJECT_ID/secrets/openai-api-key/versions/latest" \
  --model gpt-5.6-sol \
  --reasoning-effort high

uv run --with-requirements requirements.txt python \
  scripts/verify_sermon_parallel_corpus_poc.py
```

不要把 key 写进命令行参数；`--api-key-secret` 只能接收 resource reference。

## 6. 产物

每篇证道目录包含：

- `source-receipt.json`
- `boundary-candidate.json`
- `segments.en.jsonl`
- `segments.zh.first.jsonl`
- `segments.zh.edit1.jsonl`
- `segments.zh.final.jsonl`
- `glossary.candidate.json`
- `scripture-alignments.json`
- `human-review-queue.jsonl`
- `run-report.json`
- `cache/{boundary,translate,edit,qa}/...`

Git 可审查报告位于 `data/reports/sermon-parallel-corpus-poc/`。报告只含数量、状态、模型、prompt version、token usage、耗时和 blocker，不含 key。

## 7. POC 通过与训练通过的区别

`pass_with_training_blockers` 只证明：

- 原始字幕哈希没有变化。
- 三个阶段 ID 覆盖一致。
- 时间轴、中文非空和 JSON 结构通过。
- 所有样本进入人工队列。
- 没有密钥材料进入产物。

它不证明边界正确、翻译忠实、数据可训练、Silver/Gold 已产生或模型可以晋级。

## 8. v2 边界复核与人工批准

v1 边界出现半句开始时，保留 v1，不直接编辑 `boundary-candidate.json`。运行：

```bash
PROJECT_ID="$(gcloud config get-value project)"

uv run --with-requirements requirements.txt python \
  scripts/prepare_sermon_boundary_reviews.py \
  --api-key-secret "projects/$PROJECT_ID/secrets/openai-api-key/versions/latest"
```

输出位于忽略目录 `data/derived/sermon-boundary-operator-review-v2/`。每篇包含：

- `review-packet.json`：v1/v2、字幕上下文和 source/review hash。
- `review.zh.md`：人工可读工作表。
- `operator-decision.template.json`：空白决定模板，不是批准。

生成后先验证复核包：

```bash
uv run --with-requirements requirements.txt python \
  scripts/verify_sermon_boundary_reviews.py
```

`pass_requires_operator_review` 只证明 packet/source hash、候选上下文和空白模板安全；它明确不代表人工批准。

人工必须对照源音频，把 template 复制为 `operator-decision.json` 后填写。随后运行：

```bash
uv run --with-requirements requirements.txt python \
  scripts/apply_sermon_boundary_approvals.py
```

审批脚本要求：`status=approved`、`audioReviewCompleted=true`、approver、带时区的 approvedAt、decision reason，以及匹配的 source/review SHA-256。三篇全部验证后才会一次性写出 approved boundary；缺一篇或 hash 漂移都会安全停止。

生成脚本已经支持 `--approved-boundary-root`。批准后默认写入新的 `sermon-parallel-corpus-poc-v2` 和独立报告目录，不覆盖 v1：

```bash
uv run --with-requirements requirements.txt python \
  scripts/build_sermon_parallel_corpus_poc.py \
  --api-key-secret "projects/$PROJECT_ID/secrets/openai-api-key/versions/latest" \
  --approved-boundary-root data/derived/sermon-boundary-approved-v1
```

## 9. 导出人工审核包与质量目录

当前可以先验证审核工具，但由于 v1 边界已知存在半句起点，正式人工逐条审核应等待边界批准并基于新 POC 版本重新导出。

```bash
uv run --with-requirements requirements.txt python \
  scripts/export_sermon_parallel_review_bundle.py

uv run --with-requirements requirements.txt python \
  scripts/verify_sermon_parallel_review_bundle.py
```

审核模板不是决定。只把已经完成的 final rows 合并为审核根目录的 `human-decisions.jsonl`，不能混入 `pending_human_input`。然后运行：

```bash
uv run --with-requirements requirements.txt python \
  scripts/build_sermon_parallel_quality_catalog.py

uv run --with-requirements requirements.txt python \
  scripts/verify_sermon_parallel_quality_catalog.py
```

完整字段、审核顺序和 Silver/Gold 规则见 [人工审核与质量分层](./corpus-human-review-and-quality-tiers.zh.md)。

边界批准并重新导出后，使用本机审核界面逐条保存决定，避免手工拼接 JSONL：

```bash
uv run --with-requirements requirements.txt python \
  scripts/serve_sermon_parallel_review.py --open
```

当前未批准的 v1 包只能使用 `--read-only --open` 预览；可写启动会安全停止。
