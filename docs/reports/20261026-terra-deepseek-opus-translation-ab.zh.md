# GPT-6.1 Terra vs DeepSeek Flash vs Opus 5.5：13 组中译盲评（2026-10-26）

**状态：** `experimentOnly=true`、`productionEligible=false`、`humanApproval=false`。这是一次 39 段小样本的机器盲评，不是生产运行，也不是人工批准。

## 结论先行

用户指定“用之前用过的翻译”做一次三方横评。本轮沿用 20261005 冻结的三分钟样本（13 组、39 段、zh-Hans），四份译文在同一提示词下比较：DeepSeek Flash low、DeepSeek Flash high、新发布的 GPT-6.1 Terra high，以及复用的 Opus 5.5 high。

| 项目 | DeepSeek low | DeepSeek high | Opus 5.5 | Terra high |
|---|---:|---:|---:|---:|
| 组内第一 | 5 | **6** | 1 | 1 |
| 组内第二 | 4 | 2 | 5 | 2 |
| 组内第三 | 3 | 3 | 6 | 1 |
| 组内第四 | 1 | 2 | 1 | **9** |
| Borda（4/3/2/1） | **39** | 38 | 32 | 21 |
| 中位名次 | 2 | 2 | 3 | 4 |
| 评审标记的语义问题 | 0 | 0 | 1 | 5 |
| 二次复核确认的改义 | 0 | 0 | 1 | 2 |
| 中位耗时（秒/组） | 6.21 | 5.18 | 5.72\* | **4.17** |
| 输入 token/组 | 842 | 842 | 2,430 | 21,264 |
| 规划成本 | ≈US$0.025 | ≈US$0.018 | 订阅额度（标价折算 US$0.326） | 订阅额度，无美元收据 |

\* Opus 译文与耗时复用 20261008 的同提示词运行，未在今日重跑。

**判定：DeepSeek 两档领先且基本打平，Opus 居中，GPT-6.1 Terra 最后。**

- **DeepSeek** 是两个第一：low 的 Borda 39、high 38，13 组内有 7 组 low 胜 high、6 组 high 胜 low。差别不在语义，而在术语和残句：low 更口语，但会把 `AI`、`CEO` 留在中文里；high 更愿意写“人工智能”“首席执行官”，个别句子更书面。
- **Opus** 只有 1 次第一，6 次第三。它仍然最像口语讲道，但会加“其实”“可……呢”“都”这类原文没有的强调；其中 g007 的“世界的问题都会找到解决办法”被复核确认为全称过强。
- **Terra** 最快，却 9 次排第四。它的主要问题不是不流畅，而是**改写原文的命题**：g007 把未说完的 “everything is going to” 补成“一切都会变好”，又把 “the world is going to have solutions” 升成“世界上的问题都会……得到解决”；另外用“他”指神、书名缺《》、g012 把 `oversees` 弱化成“看顾”。
- **速度不等于便宜。** Terra 每次调用带约 2.1 万输入 token 的 CLI 开销，是 DeepSeek 的 25 倍；它的 4.17 秒/组是在订阅额度上换来的，不是更低成本。

## 数据与身份

| 项目 | 值 |
|---|---|
| 来源目录 | `artifacts/codex-cli-layer2-180s-20261005` |
| 样本 | `fresh-g001`–`fresh-g013`，`fresh-diagnostic-u001`–`u039`，13 组 39 段 |
| 媒体 | 三分钟片段，媒体 SHA256 `79bada8f…e906b`，180.013 秒，zh-Hans |
| 提示词 | 10/05 冻结的 13 份 `group-*-astra.policy-preview.json`，四臂逐字相同；每份 `policySha256`、`payloadSha256` 在运行前校验 |
| DeepSeek | `deepseek-flash` low / high，DeepSeek 官方 API `https://api.deepseek.com`，单次请求、不重试 |
| Opus | `claude-opus-5-5` high，复用 20261008 的 `pairs.json`，不重跑 |
| Terra | `gpt-6.1-terra` high，`service_tier=fast`，ChatGPT 登录的 Codex CLI 0.164.0-alpha.11.1 |
| 盲评裁判 | `gpt-6.1-sol` high fast，13 次独立调用，不参与任何一臂 |
| 二次复核 | `gpt-6-astra` high fast，对 6 条被标记项做 1 次独立裁定 |

Terra 的可用性先在本机核实：Codex 模型目录（客户端 0.164.0，目录抓取于 2026-10-26）列出 `gpt-6.1-terra`，上下文 500K，支持 low/medium/high/xhigh，fast 档标称 1.5×。本轮 Terra 只经 Codex CLI 调用，没有 API 调用收据或供应商金额收据；模型身份只有请求值，服务端未回传实际模型。

## 方法

1. 复用 10/05 的冻结英文与提示词，构造四份译文：DeepSeek low、DeepSeek high、Terra high 现场生成；Opus 从 10/08 的已验证产物读取，逐段按 `coverage[].targetText` 还原。
2. 每组把四份译文随机标成 A–D（每组独立置换，盐只写入 `blind-key.json`），裁判只看到英文、四份中文和项目术语要求，看不到模型名。
3. 裁判按三项排序：语义保真（增义、漏义、否定、数字、人名、引文边界、残句）、术语与格式（沙盒、人工智能、书名号、《》、神/主/祂）、口语自然度；只有改义才标 `severe`。
4. 13 组组内排名换算 Borda（4/3/2/1），并统计两两胜负。
5. 对裁判标出的 6 条语义问题，用不参与任何一臂的 Astra 做保守二次裁定：`meaning_changing` / `minor` / `acceptable`。

评分不是 BLEU/chrF：这 39 段没有人工金标，自动指标只会偏向某一条参考。规模小，但每一步都能复核。

## 逐组结果

| 组 | 第一 | 第二 | 第三 | 第四 | 依据（摘要） |
|---|---|---|---|---|---|
| g001 | DeepSeek high | DeepSeek low | Opus | Terra | Terra 把残句补成完整陈述；DeepSeek high 最保留原结构。 |
| g002 | DeepSeek high | Opus | DeepSeek low | Terra | DeepSeek low 用 `AI`/`CEO`；Terra“规程的制定走在开发前面”被判改义，复核降为轻微。 |
| g003 | DeepSeek low | Terra | Opus | DeepSeek high | DeepSeek high 与 Opus 都用 `AI`；low 术语干净且保留未完句。 |
| g004 | DeepSeek high | DeepSeek low | Opus | Terra | Terra“大家就是这么说的”淡化“我们被告知”，复核为轻微。 |
| g005 | DeepSeek high | Terra | Opus | DeepSeek low | DeepSeek low 加“却”强化转折；high 最平实。 |
| g006 | DeepSeek low | DeepSeek high | Opus | Terra | Terra 添加“对人工智能的看法变得悲观了”；DeepSeek low 最保留句尾承接，书名带《》。 |
| g007 | DeepSeek low | DeepSeek high | Opus | Terra | Terra 补全残句并加全称；Opus 同样把“有解决办法”升成“问题都会解决”。 |
| g008 | DeepSeek high | DeepSeek low | Terra | Opus | Opus 加“好好”，把“能交谈”加强。 |
| g009 | DeepSeek low | Opus | DeepSeek high | Terra | Terra“王位或领袖继承人”生硬；low 最准确自然。 |
| g010 | DeepSeek low | Opus | DeepSeek high | Terra | Terra 把“我们”泛化为“人们”；Opus/low 都保留第一人称。 |
| g011 | Terra | Opus | DeepSeek low | DeepSeek high | Terra 与 Opus 书名缺《》；DeepSeek 两档格式正确，但加“总是/真正”。 |
| g012 | Opus | DeepSeek low | DeepSeek high | Terra | Terra 用“他”指神且“看顾”偏弱；Opus“监管”也偏行政。 |
| g013 | DeepSeek high | Opus | DeepSeek low | Terra | Terra 添“主”和“今天”；三臂书名缺《》。 |

两两胜负（行胜列）：

| | DeepSeek low | DeepSeek high | Opus | Terra |
|---|---:|---:|---:|---:|
| DeepSeek low | — | 7 | 8 | 11 |
| DeepSeek high | 6 | — | 8 | 11 |
| Opus | 5 | 5 | — | 9 |
| Terra | 2 | 2 | 4 | — |

## 关键差异

| 组/段 | 英文 | Terra | 其他臂 | 复核 |
|---|---|---|---|---|
| g007/u020 | everything is going to, all the problems … | 认为一切都会变好，世界上所有的问题…… | DeepSeek 保留“一切都会——”；Opus 保留停顿 | **确认改义**：把未完成的自纠句补成“一切都会变好”。 |
| g007/u021 | the world is going to have solutions | 世界上的问题都会因这项新技术得到解决 | Opus“世界的问题都会找到解决办法”；DeepSeek“世界就会有解决办法” | **确认改义**：Terra 与 Opus 都把“有解决办法”升为“所有问题都解决”。 |
| g012/u036 | He oversees everything | 他看顾着一切 | DeepSeek“祂统管着一切/万有”；Opus“祂监管着万有” | Terra 用“他”不符合项目“祂”的要求，`oversees` 也弱化成照顾。 |
| g006/u016 | We're in a dystopian view … | 现在我们对人工智能的看法变得悲观了…… | DeepSeek“反乌托邦式的看法”；Opus“反乌托邦的看法” | 复核为轻微，但补出“人工智能”、把状态改成“变得悲观”确实是增义。 |
| g011/u033、g013/u039 | the book of Revelation | 启示录 | DeepSeek 只在 g011 用《启示录》，g013 也未加 | g011 只有 Terra 与 Opus 缺书名号；g013 四臂都缺；Terra 另加“主”和“今天”。 |
| g009/u026 | the heir apparent … Austria-Hungary | 奥匈帝国的王位或领袖继承人 | DeepSeek“王储/法定继承人”；Opus“王储” | Terra 的“王位或领袖继承人”搭配生硬，身份关系不如“王储/法定继承人”清楚。 |
| g002/u004 | some of the CEOs … are saying | 一些首席执行官说 | Opus“一些……都在说”；DeepSeek low 用 `AI`/`CEO` | Opus 的“都”在中文里可读作“其中一些全部”，未按改义计；Terra 未犯此错。 |

DeepSeek 的问题集中在术语和收尾，而不是语义：

- low：g002 保留 `AI`、`CEO`；g003、g004 用 `AI`；g013“而是有一位统管万有的”偏书面。
- high：g003 用 `AI`；g012 添“主”；g013“我们有那一位统管万有的”偏书面。
- 两档都保留了 g007 的停顿，也都没有把 `some` 说成“都”。

## 速度与成本

| 臂 | 合计秒 | 中位秒/组 | 最快/最慢 | 输入 token/组 | 输出 token/组 | 计价 |
|---|---:|---:|---|---:|---:|---|
| DeepSeek low | 95.319 | 6.211 | 3.306 / 16.430 | 842 | 1,369 | API 列价上限 ≈US$0.025 |
| DeepSeek high | 69.574 | 5.184 | 2.564 / 9.881 | 842 | 966 | API 列价上限 ≈US$0.018 |
| Opus | 81.524\* | 5.717\* | 4.221 / 9.387\* | 2,430 | 564 | 订阅；标价折算 US$0.326\* |
| Terra | **61.038** | **4.166** | 3.075 / 7.857 | **21,264** | 215 | 订阅；token 可计，美元不可计 |

\* 来自 20261008 同提示词运行。

- DeepSeek 金额按 peak 列价最坏情况估算：输入 US$0.30/百万、输出 US$1.20/百万，未扣缓存折扣，不是发票。两档合计约 **US$0.043**。
- Terra 13 次调用共 276,440 输入 token（其中 184,320 命中缓存）、2,793 输出 token；Codex CLI 没有返回美元金额，不能与 DeepSeek 的 API 账单直接比较。
- 不同 harness 的墙钟不能当严格随机对照：DeepSeek 是 HTTP 请求，Terra 是 Codex CLI 进程（含启动与 2 万余 token 系统提示），Opus 是 10/08 的 Claude CLI 运行。Terra 的“快”有一部分是 CLI 侧的固定开销被订阅额度吸收。

## 偏差与限制

1. **单一机器裁判。** 13 组全部由 `gpt-6.1-sol` 排序，没有人工双语裁定，`humanApproval=false`。
2. **裁判与 Terra 同属 GPT-6.1 家族。** 若存在家族偏好，方向应有利于 Terra；Terra 仍 9 次垫底，这个结论不依赖“裁判讨厌 Terra”。
3. **裁判的 `severe` 偏严。** 它标了 Terra 5 条、Opus 1 条；二次裁定只确认 Terra 2 条、Opus 1 条为改义，其余 3 条是轻微增义/淡化。正文同时给出两个口径，排名仍按裁判原始结果。
4. **Opus 不是同期生成。** 译文来自 20261008，提示词相同、模型相同，但服务版本与负载不同；速度只作参考。
5. **样本单一。** 一段关于人工智能与《启示录》的讲道节选，没有直接经文引用，不能代表经文密集、诗歌或多人对话的段落。
6. **调用路径不同。** Terra 走 Codex CLI + 输出 schema，DeepSeek 走 OpenAI 兼容 API + `json_object`，Opus 走 Claude CLI + schema；比的是“各家的整条调用路径”，不是纯模型权重。
7. **输出形状不同。** DeepSeek 11/13（low）、13/13（high）把 `targetUtterances` 写成 `{sourceUnitId, targetText}` 对象；canonical `_utterances` 会规范化这种形状，所以不算失败，但说明其原生输出与 schema 不总一致。
8. **Terra 的内部推理未绑定。** CLI 回传 `reasoning_output_tokens=0`，无法确认 high 档是否实际生效；只能记录请求值。
9. **没有 L3/L4 证据。** 未生成音频、未回转写、未构建页面、未发布、未做设备或场地验收。

## 建议

1. **生产默认不动。** 继续用 DeepSeek Flash 作为 Layer 2 默认；本轮没有足够证据用 Terra 或 Opus 替换它。
2. **DeepSeek low/high 不必二选一。** 两者 Borda 只差 1 分：low 更快、更口语，但会留 `AI`/`CEO`；high 术语更稳、残句略少。字幕终稿可以优先 high，或在 low 后加一遍“AI→人工智能、沙箱→沙盒、书名号”的术语检查。
3. **Terra 暂不进候选。** 如果还要试，提示词必须显式约束：用“祂”、书名用《》、不补全未完成句、不把部分说成全部；否则它的流畅度会掩盖改义。
4. **Opus 仍只适合口语候选。** 上线前需要针对全称强化（“都”）和 `AI` 混用做后编辑。
5. **下一轮。** 对 g007/u020、g007/u021、g012/u036、g013/u038 这 4 段做人工双语盲评，并加第二个独立裁判；若要评估经文，换含直接引用的 605 秒样本。

## 证据文件

原始数据留在被忽略的 `artifacts/terra-ab-20261026/run/`：

| 文件 | 内容 | SHA-256（前 12 位） |
|---|---|---|
| `identity.json` | 运行身份、基线哈希、模型与 CLI 版本 | `720dc3a191a4` |
| `translations.json` | 13 组 × 4 臂的逐段译文与收据 | `51605249f809` |
| `summary.json` | 各臂耗时、token、输出形状汇总 | `d2c83e7c4a92` |
| `blind/blind.json` | 裁判看到的盲评输入 | `0ed444993274` |
| `blind/blind-key.json` | 每组 A–D 与臂的映射（评完后才读） | `a8d826c812dc` |
| `blind/rankings.json` | 13 组原始排名、标注意见 | `1d5f1570f89b` |
| `blind/score.json` | Borda、名次分布、severe 计数 | `a8d2927a6cee` |
| `adjudication/result.json` | Astra 对 6 条标记项的二次裁定 | `fe4e8e342478` |

复现：

```
# DeepSeek low/high + Terra high，复用 10/08 Opus 译文
.venv/bin/python experiments/layer2-translation-ab/terra_deepseek_opus_ab.py \
  --baseline artifacts/codex-cli-layer2-180s-20261005 \
  --opus-pairs artifacts/claude-opus55-vs-sol61-ab-20261008-cli2.1.286/pairs.json \
  --out artifacts/terra-ab-20261026/run

# 盲评（Sol）与计分
.venv/bin/python experiments/layer2-translation-ab/blind_rank_terra_ab.py \
  --translations artifacts/terra-ab-20261026/run/translations.json \
  --out artifacts/terra-ab-20261026/run/blind
```

脱敏收据见 [20261026-terra-deepseek-opus-translation-ab-receipt.json](20261026-terra-deepseek-opus-translation-ab-receipt.json)。
