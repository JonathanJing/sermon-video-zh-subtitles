# 中文讲稿连贯性本地复跑（DeepSeek，2026-10-26）

实验线记录，不改生产、不写冻结 run。配套代码和结果在同目录；本文件记录这次复跑的目的、方法、执行流程、结果、与 PR #1397 的对照和限制。

## 摘要

- 输入和 #1397 相同：2026-10-25 证道 447 句，9 个 arm（#1397 原有 8 个加接线后的 `p123_wired`）。
- 翻译用 `deepseek-flash` low，评委用 `deepseek-flash` high，单评委；评委和翻译同属 DeepSeek，这是本次复跑最大的方法限制。
- 结论方向与 #1397 的 Sonnet/Opus 评委一致：带前文中文（s2）收益最大，术语表单独无收益，合并接续（s3）≈ s2，连读审核（s5）无可测收益，阅读版（s4）最好读，`p123_wired` 全面优于 baseline、但仍略低于 s2。可懂度排名与两个 Claude 评委的 Spearman 相关都是 0.87，已知问题修复数的相关是 0.88 / 1.00。
- DeepSeek 评分整体偏宽（baseline 可懂度 8.17，published 只有 8.11），绝对分数不能与 #1397 的 Claude 表直接比较，只能比较 arm 之间的方向和相对差距。
- 成本约 4.4 美元（2260 次成功调用，另约 0.10 美元被截断的重试），比 #1397 的约 98 美元低两个数量级。

## 1. 目的与范围

#1397 用 Claude CLI `opus` 翻译、Sonnet/Opus 双评委证明了五项改法的效果，并明确限制“两个评委都是 Claude 系，可能偏好 Claude 的译文”。本次在本地换一个模型族重跑，回答两个问题：

1. 五项改法的排序是否只在 Claude 上成立？
2. #1397 新接入 Layer 2 的 `p123_wired` 在另一个模型族下是否仍优于现行做法（baseline）？

实验只跑 benchmark，不写 production、不改冻结 run、不发布。代码基线是 #1397 当前头（`56654e72`，包含 `0b44e352` 的接线和 `56654e72` 的窗口草稿）。前 8 个 arm 的结果是在 `a8fd8a9f`（接线前）跑出的，接线提交只新增代码、没有改原有提示词，合并后 9 个 arm 又从缓存重放并补跑了 `p123_wired`。

## 2. 输入与身份

| 项目 | 值 |
| --- | --- |
| 页面 | `revelation-jesus-wins-20261025` |
| 中文内容 | `https://ai-for-god-sermon-audio.web.app/content/revelation-jesus-wins-20261025/zh-Hans.json`，sha256 `024433bd20713c70f51155ec01f64687c6b3cb94d4814500c44840afaa435d06` |
| 英文参考 | `https://ai-for-god-sermon-audio.web.app/english-reference/revelation-jesus-wins-20261025.json`，sha256 `2f4c08da62e50a4417e7160ca3cfe1810832605c3ce6224d0cc296f409ac49df` |
| 单元 | 447 句；continuation groups 442（5 组合并） |
| published | 线上 human_reviewed 版本（Sol 初译 + 人工审阅），只作参照 |
| 政策 | `config/target-language-policies/zh-Hans.json`，sha256 `8c744774b70e74493ebda45db92bb2de843d73c5fc46bbcc7e528e5f42e3ea9c` |

线上英文参考与 #1397 运行时逐块内容相同（447 块英文全部一致，只有 JSON 排版和文件 hash 不同），所以分数差异不是输入差异造成的。

## 3. 方法

### 3.1 Arm

| arm | 方法 |
| --- | --- |
| published | 线上 human_reviewed 版本，参照，不重译 |
| baseline | 生产现行做法：一句一请求，前 3 后 2 句英文上下文，生产 translator 指令 |
| s1_glossary | baseline + 全篇术语/称谓表（第 1 项） |
| s2_prior | 每 12 句一个窗口，带前面已译中文，顺序翻译（第 2 项） |
| s2b_two_pass | s1 再翻一遍，请求里带邻近句初译中文；每组仍独立并行（第 2 项的折中） |
| s3_merge | s2 + 合并接续小句（第 3 项），447→442 组 |
| s5_review | s3 + 每 25 句一窗的连读审核（第 5 项） |
| s4_reading | s5 按段重组的阅读版（第 4 项，只用于阅读，不用于字幕/配音） |
| p123_wired | #1397 接进 Layer 2 的实际做法：8 条链按原文顺序跑（`--chunks 4`），链内每 8 句先整段起草，再逐句用生产提示词翻译，输入带分段术语表、本句窗口草稿、前 8 句最终中文和接续提示；只跑译者 |

### 3.2 模型与请求

- 翻译：`deepseek-flash`，`reasoning_effort=low`（生产 Layer 2 初译档）。
- 评委：`deepseek-flash`，`reasoning_effort=high`（生产复核档），单评委。
- 请求形状照 `text/models.py` 的 `model_payload`：`model`、`reasoning_effort`、`messages`、`response_format=json_object`，直连 `https://api.deepseek.com/chat/completions`；key 只从 `DEEPSEEK_API_KEY` 读取。
- 缓存按 `(backend, model, effort, baseURL, system, user)` 的 sha256 落盘；恢复时只补缺失调用。

### 3.3 评委

- 每 25 句一个窗口，盲评（看不到 arm 名），1–10 分打可懂度、自然度、忠实度，并列出问题类型（fragment/drift/pronoun/reference/meaning/unnatural）。
- 全篇一致性单独一次调用；**本次加了“最多 20 条最严重、note ≤30 字”的上限**，因为 DeepSeek high 在无上限时把 8192 和 16384 token 输出都打满。9 个 arm 用同一条上限提示，arm 之间仍可比，但不能和 #1397 的无上限计数直接比。
- 18 个已知问题逐条核对，判“是否仍存在”。

## 4. 执行流程

1. **07:00 起**：先按 #1397 原样准备 Claude CLI。OAuth token 过期（401），改为 DeepSeek；用户指定“使用 deepseek 做翻译”，评委也用 DeepSeek。
2. **25 句冒烟（8 arm）**：104 次调用，约 0.15 美元。确认 JSON 解析、评分、已知问题核对和 p123 之前的 8 个 arm 都能跑通。
3. **全量 447 句（8 arm）翻译**：约 07:34 全部就绪，随后进入评审。
4. **两次截断失败**：全篇一致性调用在 8192 token 输出上限被截断；把上限提到 16384 后，`s5_review` 那次仍被截断。两次失败共 6 次重试，约 0.10 美元。
5. **加上限后完成**：一致性提示改为最多 20 条，输出上限提到 32768，8 个 arm 评审完成；只有缺失的评分调用付费，翻译和已完成评分全部命中缓存。
6. **缓存重放**：用最终版 runner 从缓存重放一遍，刷新 summary 里的 runner hash，结果不变。
7. **合并 #1397 新头**：`0b44e352`、`56654e72` 在 07:47 推到 #1397，新增 Layer 2 接线和 `p123_wired`。合并后先跑 25 句 p123 冒烟（33 次调用，约 0.04 美元），再跑 9 个 arm 全量；新增 532 次调用、1.06 美元，其余全部命中缓存。
8. **最终结果**：9 个 arm 的 summary 在 `results/20261026-deepseek/summary.json`；运行身份、调用数、成本在 `run-metadata.json`。

全程没有因为失败重跑整个实验：成功过的付费调用都只付一次，两次截断只损失重试费用。

## 5. 结果

### 5.1 总表

DeepSeek 评委（单评委）；“已知问题”是与 18 条人工评估问题的逐条核对。

| arm | 可懂度 | 自然度 | 忠实度 | 问题数 | 残句 | 全篇不一致(≤20) | 已知问题 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| published | 8.11 | 7.56 | 8.17 | 104 | 30 | 11 | 1/18 |
| baseline | 8.17 | 7.72 | 8.11 | 91 | 13 | 8 | 6/18 |
| s1_glossary | 8.11 | 7.61 | 8.39 | 99 | 14 | 5 | 6/18 |
| s2_prior | 9.11 | 8.17 | 8.89 | 74 | 9 | 5 | 14/18 |
| s2b_two_pass | 8.44 | 7.89 | 8.50 | 88 | 17 | 3 | 11/18 |
| s3_merge | 8.78 | 7.89 | 8.83 | 80 | 9 | 3 | 12/18 |
| s5_review | 8.78 | 8.11 | 8.56 | 84 | 7 | 5 | 13/18 |
| s4_reading | 9.00 | 7.94 | 8.88 | 58 | 1 | 2 | 13/18 |
| p123_wired | 8.72 | 8.06 | 8.78 | 73 | 6 | 4 | 11/18 |

### 5.2 问题类型

| arm | fragment | drift | pronoun | meaning | reference | unnatural | 其他 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| published | 30 | 8 | 13 | 17 | 5 | 30 | 1 |
| baseline | 13 | 17 | 13 | 10 | 4 | 34 | 0 |
| s1_glossary | 14 | 16 | 12 | 7 | 5 | 45 | 0 |
| s2_prior | 9 | 5 | 6 | 12 | 1 | 41 | 0 |
| s2b_two_pass | 17 | 11 | 5 | 10 | 4 | 41 | 0 |
| s3_merge | 9 | 3 | 12 | 10 | 3 | 43 | 0 |
| s5_review | 7 | 7 | 5 | 21 | 4 | 40 | 0 |
| s4_reading | 1 | 3 | 4 | 13 | 0 | 37 | 0 |
| p123_wired | 6 | 5 | 6 | 11 | 4 | 41 | 0 |

published 那 1 条“其他”是评委用了不在允许列表里的类型（naturalness），不影响总分，但说明单评委的格式遵守不是 100%。

### 5.3 修好的已知问题

| arm | 修好的编号 | 数量 |
| --- | --- | --- |
| published | K09（误判，见限制） | 1 |
| baseline | K07 K08 K14 K15 K16 K17 | 6 |
| s1_glossary | K05 K06 K10 K15 K17 K18 | 6 |
| s2_prior | K01 K02 K03 K05 K06 K07 K08 K09 K10 K14 K15 K16 K17 K18 | 14 |
| s2b_two_pass | K04 K05 K06 K07 K10 K13 K14 K15 K16 K17 K18 | 11 |
| s3_merge | K01 K03 K05 K06 K07 K08 K09 K10 K15 K16 K17 K18 | 12 |
| s5_review | K01 K02 K03 K05 K06 K07 K08 K09 K10 K15 K16 K17 K18 | 13 |
| s4_reading | K01 K02 K03 K05 K06 K07 K08 K09 K10 K15 K16 K17 K18 | 13 |
| p123_wired | K01 K03 K05 K06 K08 K10 K14 K15 K16 K17 K18 | 11 |

p123_wired 比 s2 少修 K02、K07、K09。K09（D.A. 卡森被切成独立一句）在 p123 里仍存在，因为这次输入还是旧的 Layer 1 切句；#1397 的 `mfa_alignment.py` 已修新计划。

### 5.4 p123_wired 在三个评委下

| 评委 | 可懂度 | 自然度 | 忠实度 | 问题数 | 已知问题 |
| --- | --- | --- | --- | --- | --- |
| DeepSeek high | 8.72 | 8.06 | 8.78 | 73 | 11/18 |
| Claude Sonnet（#1397） | 7.44 | 7.22 | 6.94 | 146 | 12/18 |
| Claude Opus（#1397） | 8.56 | 8.17 | 8.78 | 95 | 14/18 |

三个评委下 p123 都优于 baseline（DeepSeek 可懂度 +0.55、已知问题 6→11；Claude Sonnet +0.44、7→12；Opus +0.28、10→14），也都低于 s2（DeepSeek 可懂度 9.11、已知 14；Sonnet 7.50、15；Opus 8.89、18）。方向一致。

### 5.5 与 Claude 评委的排序一致性

对 9 个 arm 做 Spearman 秩相关（DeepSeek 单评委 vs #1397 的 Sonnet/Opus）：

| 指标 | vs Sonnet | vs Opus |
| --- | --- | --- |
| 可懂度 | 0.87 | 0.87 |
| 自然度 | 0.67 | 0.87 |
| 忠实度 | 0.63 | 0.10 |
| 已知问题修复数 | 0.88 | 1.00 |

可懂度和已知问题修复数的排序高度一致；忠实度在 DeepSeek 下被压在 8.1–8.9，区分度不足，排序不可用。自然度中等。

## 6. 与 #1397 结论的对照

| 结论 | #1397（Claude） | 本次（DeepSeek） | 是否复现 |
| --- | --- | --- | --- |
| 第 2 项带前文中文收益最大 | s2 可懂度 7.50 / 8.89，已知 15 / 18 | s2 可懂度 9.11，已知 14/18，问题数 91→74 | 是 |
| 第 1 项术语表单独收益小 | 7.11 / 8.44，已知 8 / 11 | 8.11，已知 6/18，与 baseline 持平 | 是 |
| 第 3 项合并接续 ≈ s2 | 7.50 / 8.89，已知 16 / 17 | 8.78，已知 12/18，问题数 80 vs 74 | 是 |
| 第 5 项连读审核无可测收益 | 7.39 / 8.83，已知 17 / 17，改动 11 处 | 8.78，已知 13/18，问题数 84 vs 80，改动 18 处 | 是 |
| 第 4 项阅读版最好读 | 8.00 / 8.94，残句 6 / 4，已知 18 / 17 | 可懂度 9.00、问题数 58、残句 1、不一致 2 最好；已知 13/18，低于 s2 | 部分：最好读复现，“修复最多”没有复现 |
| s2b 只拿到部分收益 | 已知 14 / 14，残句未减少 | 已知 11/18（baseline 6），残句 17（baseline 13） | 是 |
| p123 接线版优于 baseline | 已知 12 / 14，可懂度 +0.44 / +0.28 | 已知 11/18，可懂度 +0.55 | 是 |
| p123 仍略低于 s2 | 可懂度 7.44 / 8.56 vs 7.50 / 8.89 | 8.72 vs 9.11 | 是 |

## 7. 限制

- **同族评委**：翻译和评委都是 DeepSeek，存在同族偏好；单评委、每个窗口只评一次，没有重复抽样。分差 0.3 以内按噪声处理。
- **评分偏宽、天花板效应**：baseline 可懂度 8.17，published 只有 8.11；#1397 的两个 Claude 评委都把 baseline 显著高于 published。DeepSeek 对线上版本并不“客气”，但也压不开高分段的差距。
- **已知问题误判**：published 被记为修复了 K09，但 published 里 `D·A·卡森` 仍是独立一句（`asr-u0256`）。逐条核对是单次模型判断，不是人工复核。
- **一致性上限**：20 条上限是为了让 DeepSeek high 能完成；计数不能与 #1397 无上限的结果直接比。
- **单一证道、单一翻译档**：只跑了 2026-10-25 这一篇，翻译只用了 `deepseek-flash` low；没有测 high 翻译档，也没有第二篇证道。
- **p123 只跑译者**：`p123_wired` 不跑复核，和 baseline、s1 一样；不能把它当成完整的 Layer 2 生产链。
- **时间差**：前 8 个 arm 跑在 #1397 接线前（`a8fd8a9f`），p123 跑在合并后的头上；接线提交只新增代码、没有改原有提示词，缓存重放验证了前 8 个 arm 的结果不变。
- **绝对分数不可比**：评委不同，只能比较 arm 之间的方向和相对差距。

## 8. 复现

```bash
# key 只在 ~/.config/tongxing/deepseek.env（600，不进 Git）
. ~/.config/tongxing/deepseek.env

# 输入（也可用仓库内 artifacts 的同一份副本）
curl -sS -o zh.json \
  https://ai-for-god-sermon-audio.web.app/content/revelation-jesus-wins-20261025/zh-Hans.json
curl -sS -o en.json \
  https://ai-for-god-sermon-audio.web.app/english-reference/revelation-jesus-wins-20261025.json

.venv/bin/python experiments/zh-transcript-coherence/run_benchmark.py \
  --zh zh.json --en en.json --out artifacts/zh-coherence/20261026-deepseek \
  --translator-backend deepseek --judge-backend deepseek --workers 6
```

- 省略 `--arms` 会跑全部 9 个 arm；`--limit 25` 用于冒烟。
- 缓存按请求 hash 落盘，重跑只补缺失调用；`summary.json` 的 `costUsd` 只反映当次进程的付费调用，累计成本见 `run-metadata.json`。
- 代码基线与 hash：`summary.json` 的 `runnerSha256`、`inputs`；基线 commit 见 `run-metadata.json` 的 `codeBasis`。

## 9. 成本与证据

| 阶段 | 成功调用 | 成本 |
| --- | --- | --- |
| 8-arm 冒烟 + 全量 + 两次续跑 | 1695 | 约 3.20 |
| 截断重试（未缓存） | 6 次尝试 | 约 0.10 |
| p123 冒烟 + 9-arm 全量 | 565 | 1.06 |
| 合计 | 2260 | 约 4.40 |

Token：输入 5.70M、输出 2.15M（含评委推理 token），按 DeepSeek 峰价（输入 0.30、输出 1.20 美元/百万 token）估算。

| 文件 | 内容 |
| --- | --- |
| `results/20261026-deepseek/summary.json` | 9 个 arm 的分数、问题类型、不一致、已知问题逐条结果 |
| `results/20261026-deepseek/glossary.json` | 8-arm 阶段的全篇术语表 |
| `results/20261026-deepseek/review-edits.json` | s5 的 18 处连读改动 |
| `results/20261026-deepseek/run-metadata.json` | 运行身份、输入 hash、调用数、成本、失败与恢复说明 |
| `run_benchmark.py` | DeepSeek backend、缓存、成本核算、输入/runner hash |

原始逐 arm 译文、缓存和日志在忽略的 `artifacts/zh-coherence/20261026-deepseek/`，不提交。

## 10. 结论

1. 五项改法的排序不依赖 Claude：可懂度和已知问题修复数的排序与 #1397 高度一致，只有忠实度在 DeepSeek 下区分度不足。
2. 第 2 项仍是收益最大的单项；第 1 项单独不值得接；第 3 项与 s2 持平且全篇不一致更少；第 5 项没有可测收益，与 #1397 的“暂不建议接入”一致。
3. 第 4 项阅读版在“最好读”上最稳（问题数、残句、不一致都最低），但本次没有复现“修复已知问题最多”。
4. `p123_wired` 在独立模型族下仍然全面优于 baseline，方向与 #1397 一致；它仍略低于 s2，说明“每句最后仍由单独请求定稿”会丢掉一部分窗口收益。
5. 若要进一步验证，优先级是：人工盲评少量窗口（去同族偏差）> 恢复 Claude 登录后用同一批缓存译文补 Claude 评委（可直接对齐 #1397）> 换第二篇证道。
