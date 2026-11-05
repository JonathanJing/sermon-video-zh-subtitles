# 2026-11-04 最近四次周日生产与播客生产的 token 审计

本报告回答三个问题：最近四个周日（10-11、10-18、10-25、11-01）的三语证道页生产各消耗多少 token、按阶段怎么分布；播客各期生产消耗多少；哪些数字拿不到、为什么拿不到。

统计方法与 [2026-10-04 制作耗时与 token 审计](20261004-production-time-tokens.zh.md) 一致，直接读实际账本，不按模型单价反推，也不把「缺失」记成 0。

## 一、统计口径

- **数据源：** `artifacts/` 下的 accounting 账本（`accounting/events.jsonl`），以及逐句优先路线的本地收据（`translate/usage-*.json`、`audit/usage-*.json`、`cost.json`、`audit-cost.json`、运行目录 `events.jsonl`）。
- **去重：** 按 `eventId` 去重；模型用量只取 `api_attempt` 事件里的 `usage`；同一 `responseId` 不重复计。
- **token 口径：** `inputTokens` 与 `outputTokens`。`cachedInputTokens`、`cacheWriteTokens`、`reasoningTokens` 是明细字段，不再次累加（它们与提示缓存是两种机制，混加会重复计数）。
- **Claude CLI 收据的处理：** CLI 的 `inputTokens` 只记未缓存部分（常为个位数），真实输入在 `cacheReadInputTokens` 与 `cacheCreationInputTokens` 里。凡 CLI 行，本报告写「真实输入 = 未缓存 + 缓存读 + 缓存写」，并单列三者，方便按不同计费口径重算。
- **不含：** 本地 Spark TTS/ASR、MFA 对齐、发布部署、人工审核阅读与听审时长，以及编排对话（Codex/Claude 主会话与子代理）。这些要么没有 API token 计费，要么不在生产账本口径内。
- **金额：** 只有收据里明确写了 `costUsd` / `total_cost_usd` 的地方才给金额，且是列价估算，不是发票。
- **缺失不是 0：** 没有用量收据的调用单独列为「未记录」，不与有收据的数字相加。

库存扫描（`artifacts/` 全量）：555 份 accounting 账本、1,401,494 条唯一事件、50,303 次 API 尝试，其中 823 次缺完整用量字段（多为失败请求或本地服务，失败不是 0 token 的证据）。

## 二、周日生产总表

| 周日 | 证道 / 页面 | 路线与后端 | 输入 token | 输出 token | 合计 |
|---|---|---|---:|---:|---:|
| 10-04 | 已有报告，作对照 | canonical API | 22,579,732 | 2,367,642 | **24,947,374** |
| 10-11 | Jesus warns · `resi-20261011-54475d42` | canonical API，`gpt-6.1-sol` | 19,862,039 | 3,068,528 | **22,930,567** |
| 10-18 | `resi-20261018-15030286` | canonical API，`gpt-6.1-sol` | 19,361,130 | 3,015,345 | **22,376,475** |
| 10-25 | Jesus wins · `revelation-jesus-wins-20261025` | 逐句优先，CLI 子代理 | 未记录 | 未记录 | **未记录** |
| 11-01 | 耶稣为属祂的人盖印 · `revelation-jesus-marks-his-own-20261101` | 逐句优先，Claude CLI Opus 5.5 + DeepSeek | 854,912（含缓存） | 114,885 | **969,797** |

11-01 另有 11 次 DeepSeek 同步精简调用（6,564 输入 / 42,239 输出 = 48,803），合计约 **1,018,600 token**；Opus 分片精简没有落盘收据，见第五节。

结论先行：**路线切换把同样的三语整期生产从约 2,240 万 token 降到约 102 万 token，约 22 倍**；老路线的开销大头是逐组审核与多轮改译，不是初译。

## 三、分阶段明细

### 10-11 · Jesus warns（22,930,567）

45 份账本、9,868 次 API 尝试、100 次缺完整用量（集中在未产出 token 的 Layer 1 失败尝试）。

| 阶段 | 输入 | 输出 |
|---|---:|---:|
| L1 来源准备 `unified_source_preparation` | 438,523 | 143,605 |
| L2 初译 zh-Hans | 5,552,820 | 803,915 |
| L2 初译 ko | 1,873,895 | 309,756 |
| L2 初译 es | 1,851,789 | 229,052 |
| L2 独立审核 zh-Hans | 6,059,762 | 950,890 |
| L2 独立审核 ko | 2,055,883 | 336,950 |
| L2 独立审核 es | 2,029,367 | 294,360 |
| L3 TTS（Spark 本地 GPU） | 0 | 0 |
| L4 发布（确定性程序） | 0 | 0 |
| **合计** | **19,862,039** | **3,068,528** |

初译 9,278,504 / 1,342,723，审核 10,145,012 / 1,582,200：审核比初译多约 9%。

### 10-18 · `resi-20261018-15030286`（22,376,475）

57 份账本、9,674 次 API 尝试、34 次缺完整用量。当天除主页面外还重出了同一周次的「正式播放版」（广播版，仅中文），两部分分开列。

主页面（48 份账本，16,574,973 / 2,537,546）：

| 阶段 | 输入 | 输出 |
|---|---:|---:|
| L1 来源准备 | 189,289 | 62,704 |
| L2 初译 zh-Hans | 2,679,833 | 420,071 |
| L2 初译 ko | 2,447,940 | 411,655 |
| L2 初译 es | 2,669,584 | 346,546 |
| L2 独立审核 zh-Hans | 2,948,874 | 452,303 |
| L2 独立审核 ko | 2,703,281 | 425,738 |
| L2 独立审核 es | 2,936,172 | 418,529 |
| L3 / L4 | 0 | 0 |

广播版重出（9 份账本，仅 `zh-Hans`，2,786,157 / 477,799）：L1 来源准备 191,823 / 63,290，L2 初译 1,253,707 / 203,570，L2 独立审核 1,340,627 / 210,939。

### 10-25 · Jesus wins（未记录）

该周走逐句优先路线：上线页面三语各 447 句（v1 的 418 句按新录音重建为 v2），三语翻译由 Claude Code 子代理完成（4 段 × 3 语），TTS 在 Spark 本地。产物齐全（页面已发布并 HTTP 核验），但**翻译没有写任何用量收据**：运行目录只有 `translate/input-*.jsonl`、`output-*.jsonl` 与审计结果，没有 `usage-*.json`、`cost.json`。这批调用的 token 只存在于编排会话的 CLI 转录里，不属于生产账本口径，本报告不猜数。

### 11-01 · 耶稣为属祂的人盖印（969,797 + 48,803）

477 句 × 3 语。翻译用 Claude CLI `claude-opus-5-5`，每语 4 个分片并行；复核用 Opus 另起 1 次请求/语；同步精简先用 DeepSeek 再补 Opus 分片。

| 阶段 | 调用 | 未缓存输入 | 缓存读 | 缓存写 | 输出 | 估算成本 |
|---|---:|---:|---:|---:|---:|---:|
| 翻译 zh-Hans | 4 | 8 | 49,160 | 168,485 | 33,565 | $2.03 |
| 翻译 ko | 4 | 8 | 49,160 | 168,343 | 40,005 | $2.16 |
| 翻译 es | 4 | 8 | 91,984 | 125,509 | 34,610 | $1.72 |
| 复核 zh-Hans | 1 | 2 | 12,290 | 52,712 | 2,080 | $0.47 |
| 复核 ko | 1 | 2 | 12,290 | 57,586 | 3,220 | $0.53 |
| 复核 es | 1 | 2 | 12,290 | 55,073 | 1,405 | $0.47 |
| **Claude CLI 小计** | **15** | **30** | **227,174** | **627,708** | **114,885** | **$7.37** |
| 同步精简 zh-Hans（DeepSeek flash） | 11 | 6,564 | — | — | 42,239 | 未记金额 |
| 同步精简 ko / es（Opus CLI） | — | 未入账 | — | — | — | — |
| TTS / 发布 | — | 0 | 0 | 0 | 0 | — |

真实输入 855k 里有 73% 是提示缓存写入、27% 是缓存读取、未缓存输入只有 30 个 token——这正是 token 总量降下来的机制，而不是模型变短。

## 四、播客生产

| 生产日 | 剧集 | 语言 | 阶段 | 输入 | 输出 | 合计 |
|---|---|---|---|---:|---:|---:|
| 10-02~03 | Jesus is worthy | zh / ko / es | L2 初译 + 审核 + 模型层 | 16,261,825 | 2,929,323 | **19,191,148** |
| 10-21 | Jesus sends and resurrects His own | 仅 zh-Hans | L2 初译 + 审核 | 16,495,667 | 2,146,715 | **18,642,382** |
| 10-23 | Jesus promises | zh / ko / es | 子代理翻译 | 未记录 | 未记录 | **未记录** |
| 10-26 | Jesus wins | zh / ko / es | Opus CLI 翻译 + DeepSeek 术语/审核 | 缓存输入未入账；DeepSeek 257,146 | Opus 367,779 + DeepSeek 684,440 | 收据不全；成本 $22.67 |
| 11-01 | Jesus Marks His Own | zh / ko / es | DeepSeek flash 翻译 + 审核 | 3,242,325 | 3,236,171 | **6,478,496**（$4.86） |

分阶段说明：

- **Jesus is worthy**：初译 1,079,313–1,913,645 / 语，审核 1,231,107–2,246,661 / 语，另有 `layer2_models` 5,700,338 / 798,808。
- **Jesus sends and resurrects His own**：账本只有中文——初译 8,038,222 / 1,113,196，审核 8,457,445 / 1,033,519，是返工最多的一期；韩、西语译文由逐句优先实验的 8 个子代理完成，没有进这份账本。
- **Jesus wins**（10-26）：每语 72–77 次 Opus 调用、输出 108,672 / 147,942 / 111,165；DeepSeek 术语表 57,285 / 24,978（zh）与 50,726 / 35,992（ko），审核只有 zh 有收据（148,685 / 255,691）。成本 zh $7.66、ko $8.14、es $6.88，合计 $22.67；Opus 的缓存输入没有落进 token 字段。
- **Jesus Marks His Own**（11-01，940 句）：zh 1,342,624 / 740,586（$1.29），ko 1,188,817 / 1,611,948（$2.29），es 710,884 / 883,637（$1.27）。

**最近一期播客约 648 万 token、约 4.86 美元**；换 DeepSeek 之前的完整三语老路线每期在 1,864 万–1,919 万 token。

## 五、缺口与不可归因

| 项目 | 现有证据 | 缺什么 |
|---|---|---|
| 10-25 Jesus wins 三语翻译 | 产物、`translate/input-*.jsonl` 与 `output-*.jsonl`、审计 jsonl、已发布页面 | 用量收据；只有编排会话的 CLI 转录，口径不同 |
| 10-23 Jesus promises 播客 | 946 句产物、发布驱动 | 同上，子代理翻译无收据 |
| 11-01 同步精简（Opus） | `trim_opus.py`、`trim-raw-*.txt`、`review.json` 的 revisions | 脚本只把 `total_cost_usd` 打在终端，没有落盘；输入 token 完全没算 |
| 10-26 Jesus wins 播客 | `cost.json` 的 `translator`/`glossary`、zh 的 `audit-cost.json` | Opus 缓存读/写 token、ko/es 审核收据 |
| 主会话与子代理对话 | 本地 `~/.claude` 转录 | 按仓库口径不计入生产账本；若要计入需单独立项，且缓存重读会显著放大口径 |
| 本地 TTS/ASR/MFA | 渲染收据、音频哈希 | 不产生 API token，本地模型内部序列 token 未记录 |

这些缺口影响的是「完整口径」而不是已给出的数字：上表所有数字都来自实际收据，没有用单价或字数反推。

## 六、判断

1. **同样的三语整期，token 降了约 22 倍**：10-18 是 2,237 万，11-01 是 102 万。机制是分片（4 片 × 3 语）+ 长提示缓存 + 一次复核，而不是把审核省掉（11-01 仍有每语一次独立复核）。
2. **老路线的成本重心在审核**：10-11 审核 / 初译 = 1.09，10-18 主页面 = 1.10。要再省老路线的钱，先看审核的分组与缓存，而不是把初译模型换小。
3. **播客是更大的单项开销**：老路线播客一期（双人整期）1,864 万–1,919 万 token，接近一次周日页面的全部开销；新路线 648 万，仍是新路线周日页面（约 102 万）的 6.4 倍，因为 940 句 × 三语且逐句审核。
4. **返工是账面波动的主因**：10-11 的 zh 审核 606 万 vs 初译 555 万，来自 r1–r12 多轮修订；10-21 播客中文返工（1,864 万，仅中文）单语量就与整期三语正常成本相当。要控成本，应先按 source/policy/plugin 身份变化分析为什么需要重跑，而不是只提并发。
5. **先补收据再谈优化**：10-25、10-23 与 11-01 的精简环节连输入 token 都没有记录。在这三处补上用量收据（例如把 `trim_opus.py` 的 `usage` 写进运行目录），才能让「路线切换省了多少」这句话对每一周都成立。

## 七、复算

本次审计的脚本没有入库（它是审计脚本，不是生产入口）；下面是完整实现，在仓库根目录用 `.venv/bin/python` 运行即可复现第二、三节的数字。它只读账本，不发起任何模型调用。

```python
import collections, datetime, json
from pathlib import Path

LA = datetime.timezone(datetime.timedelta(hours=-7))

def scan(path):
    """Return per-ledger (la_date, attempts, missing, {stage: [in, out]})."""
    seen, date, attempts, missing = set(), None, 0, 0
    stages = collections.defaultdict(lambda: [0, 0])
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        event_id = row.get("eventId")
        if event_id:
            if event_id in seen:
                continue
            seen.add(event_id)
        if row.get("event") == "run_started" and row.get("recordedAt"):
            day = datetime.datetime.fromisoformat(row["recordedAt"]).astimezone(LA).date()
            if date is None or day < date:
                date = day
        elif row.get("event") == "api_attempt":
            attempts += 1
            usage = row.get("usage") or {}
            if usage.get("inputTokens") is None:
                missing += 1                      # missing is not zero
                continue
            stage = (row.get("stage") or "unknown").split(".group-")[0]
            stages[stage][0] += usage["inputTokens"]
            stages[stage][1] += usage.get("outputTokens") or 0
    return date.isoformat() if date else None, attempts, missing, dict(stages)

ledgers = [(path.relative_to("artifacts").parts[0], scan(path))
           for path in Path("artifacts").glob("**/accounting/events.jsonl")]

def report(dates, top):
    stages, tin, tout, att, miss, n = collections.defaultdict(lambda: [0, 0]), 0, 0, 0, 0, 0
    for area, (date, attempts, missing, found) in ledgers:
        if area != top or date not in dates:
            continue
        n += 1; att += attempts; miss += missing
        for stage, (i, o) in found.items():
            stages[stage][0] += i; stages[stage][1] += o
            tin += i; tout += o
    print(f"{sorted(dates)} ledgers={n} attempts={att} missing={miss} "
          f"in={tin:,} out={tout:,} total={tin + tout:,}")
    for stage, (i, o) in sorted(stages.items()):
        print(f"  {stage:34s} in={i:>10,} out={o:>8,}")

report({"2026-10-10", "2026-10-11"}, "weekend-live")
report({"2026-10-17", "2026-10-18"}, "weekend-live")
```

逐句优先路线与播客的收据用另一段脚本读 `translate/usage-*.json`、`audit/usage-*.json`、`*/cost.json`、`*/audit-cost.json` 与运行目录 `events.jsonl`（`label` 为 `translate` / `audit` / `trim`，字段为 `promptTokens` / `completionTokens`）；`cost.json` 的 token 可能嵌在 `translator` 块里，需要先判断再取。

校验：同一账本的 `events.jsonl` 与 `stages.csv` 必须一致。抽查 `weekend-live/layer2-15030286-20261017`，两者都是 16,385,684 输入，无差异。

## 八、数据来源

- 周日页面：`artifacts/weekend-live/layer1-*`、`layer2-*`、`layer3-*` 下的 `accounting/events.jsonl` 与 `stages.csv`；逐句优先运行在 `artifacts/sentence-first-agent/20261101-jesus-marks-{zh,ko,es}`。
- 播客：`artifacts/podcasts/*/pipeline/accounting/events.jsonl`（老路线），`artifacts/sentence-first-agent/20261026-jesus-wins-podcast-*`、`20261101-jesus-marks-podcast-*`（新路线）。
- 对照：[2026-10-04 制作耗时与 token 审计](20261004-production-time-tokens.zh.md)；路线背景见[逐句优先生产路线](../sentence-first-agent-production.zh.md)与[运行时模型策略](../production-model-runtime-policy.zh.md)。

本报告是一次只读审计：没有发起付费调用，没有修改任何账本或产物，所有数字都能由第七节的脚本在未删除本地 `artifacts/` 的前提下复算。
