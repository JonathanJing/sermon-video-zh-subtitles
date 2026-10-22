# DeepSeek Flash 速度测试：13 组中文初译（2026-10-21）

**状态：** `experimentOnly=true`、`productionEligible=false`、`humanApproval=false`。这是端点速度测量，不是生产运行，也不是质量准入。

## 结论

- **DeepSeek Flash high 是这轮最快的初译臂。** 13 组 39 段，两次重复测量合计 54.985 秒和 56.276 秒，中位 3.765 / 3.867 秒每组。
- **对比 20261008 的同批 Sol / Opus：** Sol 中位 14.480 秒/组，Opus 5.717 秒/组；按中位用时，Sol 是 DeepSeek high 的 **3.8 倍**，Opus 是 **1.5 倍**。
- **high 与 low 的初译墙钟几乎一样。** high 比 low 只慢 2.0%（合计）和 3.7%（中位）；在这个 3 段小批次上，推理强度没有带来可感知的翻译延迟。
- **审核阶段仍可能更慢，且这轮的快速审核偏浅。** 5 组 high 审核中位 6.619 秒/组，但它把 Sol 的“沙箱”“AI”等问题全部判为 pass；速度数字不能当作质量证据。
- **口径限制：** 这是 DSH headless 端到端时间，包含进程启动、agent 初始化、API 调用和 JSON 解析；Sol/Opus 来自另一套 CLI harness。不是供应商原始延迟，也不是同机同时刻的随机对照。

## 测量设置

| 项目 | 值 |
|---|---|
| 端点 | DSH headless，provider `deepseek-official`，model `deepseek-flash` |
| 强度 | `reasoningEffort=high`（A/B 两轮）与 `low`（一轮对照） |
| 调用方式 | `dsh --profile headless --patch model-high.patch.yml "<prompt>"` |
| 批次 | 13 次调用，每次 3 段，共 39 段；与 [翻译/审核 A/B](20261021-deepseek-sol-opus-review-ab.zh.md) 使用同一批 `fresh-g001`–`fresh-g013` |
| 计时 | Python `time.monotonic()` 包住整个子进程；不含人工等待 |
| token | 第二轮加 `--json`，从 `status.step_end.usage` 汇总 |
| 凭据 | 运行时从本机 DSH 凭据库读取 `DEEPSEEK_API_KEY` 并注入子进程；未打印、未提交 |
| 顺序 | 13 次串行；服务负载未控制 |

**为什么用 headless：** 当前会话实际以 `reasoningEffort=low` 运行，无法在会话内切到 high；headless profile 加 `agent-default-model` patch 可以显式指定 high，并给出可复核的进程级墙钟。

## 初译结果

| 臂 | 日期 | 调用 | 合计秒 | 中位秒/组 | 最快 | 最慢 |
|---|---|---:|---:|---:|---:|---:|
| DeepSeek Flash high（A，纯文本） | 2026-10-21 | 13 | **54.985** | **3.765** | 2.371 | 7.740 |
| DeepSeek Flash high（B，`--json`） | 2026-10-21 | 13 | 56.276 | 3.867 | 2.424 | 6.675 |
| DeepSeek Flash low | 2026-10-21 | 13 | 53.905 | 3.631 | 2.414 | 6.084 |
| Sol `gpt-6.1-sol` high | 2026-10-08 | 13 | 187.698 | 14.480 | 8.698 | 21.253 |
| Opus `claude-opus-5-5` high | 2026-10-08 | 13 | 81.524 | 5.717 | 4.221 | 9.387 |
| DeepSeek Flash high 审核 | 2026-10-21 | 5 | 43.669 | 6.619 | 2.802 | 16.400 |

两次 high 初译合计 26 次调用，中位 **3.806 秒/组**。按每 13 次的可比口径：

| 对比（分母为 DeepSeek high） | 合计用时倍数 | 中位用时倍数 |
|---|---:|---:|
| Sol / DeepSeek high | **3.41×** | **3.85×** |
| Opus / DeepSeek high | **1.48×** | **1.52×** |
| DeepSeek high / low | 1.02× | 1.04× |

### token 与吞吐

第二轮 `--json` 的 13 次调用合计：

| 指标 | 值 |
|---|---:|
| 非缓存输入 | 2,906 |
| 缓存读取 | 103,168（每次 7,936） |
| 输出（含推理） | 7,175 |
| 输出 token/s | **127.5** |
| 失败/重试 | 0 |

缓存读取占输入侧约 97%，说明 headless 的系统提示和工具清单在 13 次调用间高度复用；这也是 2–4 秒级延迟的一部分原因。没有取得供应商金额收据。

## high 与 low 的译文差异

速度接近，不代表输出一样。抽查发现 high 并非全面更好：

| 段 | low 输出 | high 输出 | 判断 |
|---|---|---|---|
| g007/u020 | 一切都会好起来，世界上所有的问题…… | 一切都会……世界上所有的问题…… | high 保留了原文的停顿，更好 |
| g009/u026 | 目标是奥匈帝国那位将要继位的王储——也就是未来的国王或领袖 | 奥匈帝国那位即将成为国王或领袖的王储遭到了一场暗杀 | high 更简洁，信息完整 |
| g010/u029 | 加快了我们彼此之间不满的积累 | 加速了我们彼此之间的不满 | high 重新出现 Opus 式的搭配问题 |
| g006/u017 | 《超级绽放》（Super Bloom） | 《Super Bloom》 | high 丢了中文书名，和 Sol 一样 |
| g013/u038 | 因为我们有一位统管万有的 | 我们有一位统管万有的 | high 丢了“因为”，因果连接变弱 |
| g003/u009 | 你们还记得…… | 你还记得…… | high 从复数改成单数，讲道称呼变窄 |

因此，**不能用这轮 high 输出直接替换 [质量 A/B](20261021-deepseek-sol-opus-review-ab.zh.md) 的 low 臂排名**；high 的质量需要重新逐段审。速度报告只回答“多快”，不回答“更好”。

## 审核速度

对 Sol 的前 5 组草稿做 high 审核，输出 3 段修正结果：

| 指标 | 值 |
|---|---:|
| 调用 | 5 |
| 合计 | 43.669 秒 |
| 中位 | 6.619 秒/组 |
| 最快 / 最慢 | 2.802 / 16.400 秒 |
| 失败 | 0 |

这 5 次审核把 Sol 的“沙箱”（项目基准为“沙盒”）、“AI”混用等已知问题全部判为 `pass`，没有提出修正。它比 20261017 那次 6 段 high 审核（167.036 秒、15,731 推理 token）快很多，但**审核深度明显更浅**。审核延迟高度依赖 prompt、schema 和输出要求，不能用一个数字概括 DeepSeek 的审核速度，更不能把这个快速审核当作质量门禁。

若按这轮 13 组初译加 5 组审核中位粗算，13 组“初译+审核”约 141 秒；仍低于 Sol 初译单独的 188 秒，但这个比较没有意义，因为审核质量不达标。

## 偏差与限制

1. **不是同 harness 对照。** Sol/Opus 来自 20261008 的 Codex/Claude CLI，DeepSeek 来自 DSH headless；系统提示、工具清单、启动开销都不同。
2. **端到端包含启动。** 2.371 秒的最快值里含 DSH 进程启动和 agent 初始化；供应商原始首 token/总延迟没有单独测量。
3. **单批、串行、负载未控制。** 13 组来自同一段讲道，服务端负载没有随机化或重复对照。
4. **high/low 只各一轮。** 两轮 high 的差异（54.985 vs 56.276 秒）说明噪声约 2%；不足以区分更小的差异。
5. **审核样本只有 5 组，且偏浅。** 不能据此给 DeepSeek 审核质量下结论。
6. **没有金额收据。** token 数来自 DSH 事件，不是供应商发票；缓存计价未折算。
7. **会话质量报告已更正。** 该报告的 DeepSeek 臂实际是 low；high 只在本速度报告中出现，未重做质量排名。

## 复现

```bash
# 不要把 key 写进仓库或日志
export DEEPSEEK_API_KEY="$(...)"
dsh --profile headless \
  --patch artifacts/deepseek-speed-20261021/model-high.patch.yml \
  --json "<translation prompt>"
```

批量脚本：`artifacts/deepseek-speed-20261021/run_speed.py`、`run_speed_json.py`、`run_speed_low.py`、`run_review_speed.py`。原始事件和 stderr 留在被忽略的 `artifacts/deepseek-speed-20261021/`。

## 证据

| 文件 | 内容 | SHA-256（前 12 位） |
|---|---|---|
| `timings.json` | high 初译 A 的逐组墙钟 | `f32458777715` |
| `timings-json.json` | high 初译 B 的墙钟与 token | `44f719e00d78` |
| `timings-low.json` | low 初译墙钟 | `4b841374671b` |
| `review-timings.json` | high 审核 5 组墙钟 | `9cce44c1ffe0` |
| `speed-summary.json` | high A 汇总 | `7931cf8bf912` |
| `speed-summary-json.json` | high B 汇总与 token | `135a4561d6af` |
| `review-speed-summary.json` | 审核汇总 | `7391879e06eb` |

脱敏收据见 [20261021-deepseek-speed-test-receipt.json](20261021-deepseek-speed-test-receipt.json)。
