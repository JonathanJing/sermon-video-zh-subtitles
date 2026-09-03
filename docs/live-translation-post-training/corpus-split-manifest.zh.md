# Mariners 180 篇整篇证道拆分清单

日期：2026-08-31

状态：`provisional_split_frozen_training_blocked`

## 1. 拆分结果

| split | 篇数 | 原始视频时长 | 用途 |
|---|---:|---:|---|
| `train` | 141 | 88.592 小时 | 权利与质量门禁通过后的训练候选 |
| `dev` | 18 | 11.904 小时 | prompt、validator 和训练选择；不得调 test |
| `test` | 18 | 10.405 小时 | untouched whole-sermon 评测 |
| `poc` | 3 | 1.938 小时 | 当前 calibration；永久排除出 untouched test |
| **合计** | **180** | **112.839 小时** | 不含 10 条待授权 ASR |

拆分单位固定为完整 `sermonId`。同一证道未来产生的 sermon-only 片段、首译、中文编辑、prefix、Context Pack、hard negative 和教师 receipt 必须继承父证道 split，不能重新随机分配。

## 2. test 设计

18 篇 test 分成：

- 6 篇 `test_unseen_speaker`：Ed Stetzer 的现有 6 篇全部只在 test，train/dev 中为 0。
- 12 篇 `test_seen_speaker_new_sermon`：按讲员确定性分层抽取，测试见过讲员但没见过该篇证道。

三篇 POC：`cFLQLjzbnVg`、`mIyioBLQmJ0`、`wxcIGSolCvc`，均标记 `reserved_from_untouched_test`。

split 使用固定 seed `mariners-sermon-whole-split-v1-20260830`。相同 180 篇和相同元数据重复运行会得到相同分配；任何 seed、来源或元数据变化都必须发布新的 split version，不能原地修改 v1。

## 3. 讲员元数据补证

三个标题没有讲员后缀，已通过 hash-bound override 补齐，原始 manifest 没有被改写：

| 视频 | 补证讲员 | 证据 |
|---|---|---|
| `JlnrHEYXGKY` | Eric Geiger | [Mariners 官方 On the Table 2024 系列页](https://www.marinerschurch.org/series/on-the-table-2024/)列出日期、题目与讲员 |
| `b1Ggr2ww8Sc` | Eric Geiger | 原始字幕 `cue_00133`、`cue_00135–137` 的引介与自我介绍 |
| `z_UoOx-6mz4` | Christine Caine | 原始字幕 `cue_00001–00004` 的自我介绍 |

override 同时绑定对应 manifest 与 cue SHA-256。来源变化时，builder 和 verifier 都会拒绝旧补证。当前 180 篇 `unknown speaker = 0`。

## 4. 独立审计结果

`pass_training_blocked` 已验证：

- 180 个 assignment 与 180 个 raw asset 精确相等、ID 唯一。
- `141/18/18/3` 计数正确且集合互斥。
- 10 条 pending ASR 与 manifest 交集为 0。
- 每条 manifest/cue/transcript hash 与冻结来源一致。
- 没有相同 transcript hash 或 cue hash 跨 split。
- Ed Stetzer 只存在于 test。
- 三个 POC 与冻结选择完全一致。
- split、metadata override 和报告不含凭据。

## 5. 拆分不等于训练授权

所有 180 条仍是：

```json
{
  "rightsStatus": "unconfirmed",
  "trainingEligibility": "blocked"
}
```

此 manifest 只提前锁定泄漏边界，不批准云端翻译、学生训练、Silver/Gold、模型权重分发或生产使用。test 的目标中文也必须由人工审核，不能用教师自己生成的答案证明学生质量。

## 6. 产物与复现

- 完整 assignment：`data/reports/sermon-parallel-corpus-splits-v1/split-manifest.json`
- 摘要：`data/reports/sermon-parallel-corpus-splits-v1/split-summary.json`
- 元数据补证：`data/reports/sermon-parallel-corpus-splits-v1/metadata-overrides.json`
- 独立校验：`data/reports/sermon-parallel-corpus-splits-v1/final-verification.json`

```bash
uv run --with-requirements requirements.txt python \
  scripts/build_sermon_split_manifest.py

uv run --with-requirements requirements.txt python \
  scripts/verify_sermon_split_manifest.py
```
