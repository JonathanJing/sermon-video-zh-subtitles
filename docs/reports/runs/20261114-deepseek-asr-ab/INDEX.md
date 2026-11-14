# 20261114 DeepSeek ASR 与 OpenAI gpt-transcribe：60 段冻结音频 A/B

日期：2026-11-14（PST）。范围：`experiments/deepseek-asr-ab/` 新增 4 个脚本；不改生产转录链路、不改 prompt、不改模型策略。这是一次离线对照实验，不是生产选型结论。

## 结论

- **准确度上 OpenAI `gpt-transcribe` 更好，但差距不大。** 在 60 段各 30 秒、合计 29.811 分钟的冻结英文证道音频上，DeepSeek ASR 的参考 WER 为 2.81%，`gpt-transcribe` 为 0.84%；独立盲听（rubric v2，只计意义错误）判定 OpenAI 赢 15 段、DeepSeek 赢 6 段，其余 28 段并列、6 段两次顺序不一致、5 次判定失败。
- **DeepSeek 的关键术语召回 97.10%，高于未注入术语提示的 `gpt-transcribe`（94.20%），低于注入提示的 98.55%。** 它漏的是 `Mariners`（004 段写成 `Maranis`）和歌词里的 `Christ`；未注入提示的 `gpt-transcribe` 则把 3 段的 `Mariners` 写成 `Mariner's`、把 004 段写成 `America's congregation`，两者都丢了同一批专名，只是错法不同。
- **DeepSeek 的成本约为 OpenAI 的 1/4.7，延迟约为 1/1.9。** 29.811 分钟音频：DeepSeek $0.0288（限时价 $0.058/小时；原价 $0.0576），OpenAI $0.1342（$0.0045/分钟）；单请求 p50 2.57s 对 4.90s，p95 3.29s 对 6.09s。
- **不建议现在切生产主链路。** DeepSeek ASR 每次请求上限 120 秒 / 8 MiB，没有 prompt、术语或语言参数，只返回整段文本（无词级时间戳），也不支持流式；本轮的机器裁判不是人工 Gold，人工听审队列已生成但尚未执行。

## 实验设计

- 数据：`data/benchmarks/live-sermon-translation-v1/local-asr-gpt-reaudited-reference-v1.json`，60 段精确 30 秒片段，来自 2026-08-23 与 2026-08-30 两场 post-live 证道，manifest SHA-256 `35af38c4…`。60 个源音频 SHA-256 全部逐一校验通过。
- 音频：每个片段转成 16 kHz 单声道 16-bit PCM WAV 后**三个 arm 使用同一份字节**，转换参数写入 `audio/<id>.json`；DeepSeek 文档要求 PCM WAV 或 Ogg Opus、16 kHz 在其支持采样率内，`gpt-transcribe` 生产请求构造器同样只接受 PCM WAV。
- 三个 arm，每片段一次 API 调用，无重试（0 报错、0 空输出）：
  1. `deepseek-asr`：`POST https://api.deepseek.com/v1/tools/asr`，无任何提示词（该端点不接受）。
  2. `openai-gpt-transcribe-nohint`：`model=gpt-transcribe`、`language=en`、空 prompt、无 keywords，即与 DeepSeek 可获得同样信息量的对照。
  3. `openai-gpt-transcribe-hinted`：同一模型加项目重审 prompt 与片段关键术语 keywords，代表 DeepSeek 无法接受的领域提示上限。
- 评分：冻结参考 WER / 关键术语召回 / 完整输出 / 静音纪律与 MRQS 沿用 `experiments/local-asr/compare_local_asr_quality_runs.py` 的公式；该脚本对同一批 run 目录重算的结果与本报告一致（`gpt-transcribe` 97.758、`deepseek-asr` 97.446）。
- 偏差控制：参考文本本身由 GPT-Transcribe 生成（47 段 model_reviewed、13 段 gpt_reaudited），所以「OpenAI 与参考逐字相同 46–50/60、DeepSeek 仅 13/60」既是准确度也是自洽度。为此增加独立盲听：Gemini 3.8 flash 只拿音频与两份匿名文本（X/Y 每片段换位两次），判哪份更贴近音频。它不是人工 Gold。

## 冻结参考结果

| Arm | MRQS / 100 | WER | 关键术语召回 | 有效输出 | 静音幻觉 | 与参考逐字相同 | p50 | p95 | 平均 RTF | 估算成本 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `openai-gpt-transcribe-hinted` | 99.100 | 0.78% | 98.55% | 60/60 | 0/1 | 50/60 | 4.78s | 5.88s | 0.1593 | $0.1342 |
| `openai-gpt-transcribe-nohint` | 97.758 | 0.84% | 94.20% | 60/60 | 0/1 | 46/60 | 4.90s | 6.09s | 0.1633 | $0.1342 |
| `deepseek-asr` | 97.446 | 2.81% | 97.10% | 60/60 | 0/1 | 13/60 | 2.57s | 3.29s | 0.0868 | $0.0288 |

硬门禁：`nohint` 因关键术语召回 <95% 判 FAIL，另两臂 PASS。配对词错（同一片段谁错得更少）：OpenAI `nohint` 赢 43 段、DeepSeek 赢 2 段、15 段相等。

静音纪律一项三个 arm 都是 0 次幻觉：唯一的无语音片段（30 秒音乐）三者都返回空文本，DeepSeek 没有编造歌词。

## 独立盲听

| 对照 | rubric | DeepSeek 片段胜 | OpenAI 片段胜 | 并列 | 两次顺序不一致 | 失败判定 |
|---|---|---:|---:|---:|---:|---:|
| DeepSeek vs `nohint` | v1（宽松） | 20 | 12 | 17 | 11 | 0/120 |
| DeepSeek vs `nohint` | v2（严格，主口径） | 6 | 15 | 28 | 6 | 5/120 |
| DeepSeek vs `hinted` | v2 | 3 | 15 | 29 | 5 | 8/120 |

两个 rubric 的差别是本轮最值得记录的方法学结果。v1 要求「保留口吃、重复词、口头语」，于是 DeepSeek 因为保留了 `it's a it's a psalm`、`with, with`、`to to` 而大量得分；v2 明确把这些算噪音、只计改变意义的错误，结论随即反转。这说明**「哪个 ASR 更好」在未定义口吃是否保留时没有唯一答案**：对阅读版 PDF 应清洗，对逐字稿应保留。生产链路当前是阅读版，所以 v2 是主口径。

v2 判定在抽查里站得住：`gold_004` 两轮都指出 OpenAI 把 `a Mariners congregation` 读成 `America's congregation`；`gold_016` 指出 DeepSeek 把 `this psalm` 写成 `the psalm`；`gold_044` 指出 OpenAI 漏掉 `every knee will bow` 并编造了 `There's no other name but Jesus` 式的歌词行。这些是机器判断，仍需人耳确认。

## 能力与限制

| 维度 | DeepSeek ASR | OpenAI `gpt-transcribe`（本项目构造器） |
|---|---|---|
| 单请求时长 | ≤120 秒 | ≤180 秒（`transcription_request.MAX_DURATION_SECONDS`） |
| 单请求大小 | ≤8 MiB | ≤25 MiB |
| 提示词 / 术语注入 | 不支持 | prompt + keywords（`hinted` arm 用了） |
| 语言参数 | 无，自动检测（19 种语言） | `language=en` |
| 输出 | 整段 `text` + `duration_ms` | 整段 `text` + `usage.seconds` |
| 词级时间戳 | 无 | 无（下游仍需对齐步骤） |
| 流式 | 不支持 | 不支持（实时链路另有 provider） |
| 立体声 | 仅左声道 | 整文件 |
| 计费 | 按秒，$0.116/小时（限时 $0.058） | 按分钟，$0.0045/分钟 |

## 未验证与残留

- **未做人工听审。** 全部准确度结论来自机器裁判；`artifacts/deepseek-asr-ab/human-review-queue.md` 给出全部 6 段 DeepSeek 判定胜出、4 段 OpenAI 判定胜出与 6 段两次换位判断不一致的片段清单与原文，每段 30 秒，全听完约 8 分钟。听完之前的任何「DeepSeek 更好/更差」都只是机器意见。
- 只覆盖两场证道的 60 个 30 秒区块，没有覆盖长音频切块拼接、跨段术语一致性、西班牙语歌词混唱、强噪声或远场麦克风。
- 未测 DeepSeek 在 120 秒上限附近的行为（本轮片段固定 30 秒），也未测限流（文档写每账号最多 50 并发）。
- 成本是按时长乘公开单价估算，未与账单核对（`invoiceVerified=false`）。
- Gemini 盲听在 v2 下有 5%（DeepSeek vs nohint）与 7.5%（vs hinted）的判定失败，失败项不计分；两次换位后仍不一致的片段也单独列出，没有强行归边。

## 复现

```bash
# 三个 arm，60 段，约 2 分钟
.venv/bin/python tools/ops/run_with_openai_environment.py --environment dev -- \
  .venv/bin/python experiments/deepseek-asr-ab/run_provider_ab.py --confirm-billable --workers 4

# 独立盲听（两个 rubric，各两次换位）
.venv/bin/python experiments/deepseek-asr-ab/adjudicate_clip_pairs.py \
  --arm-a deepseek-asr --arm-b openai-gpt-transcribe-nohint --rubric v2 --thinking MEDIUM \
  --output-dir artifacts/deepseek-asr-ab/adjudication-v2 --confirm-billable --workers 6

# 排行榜、人工队列与逐段文本差异
.venv/bin/python experiments/deepseek-asr-ab/score_ab.py
.venv/bin/python experiments/deepseek-asr-ab/build_review_artifacts.py
```

已完成的 run 目录重跑会命中请求缓存，不重复计费。

## 证据

| 文件 | SHA-256（前 16 位） |
|---|---|
| `artifacts/deepseek-asr-ab/leaderboard.json` | `c3c87d2a407f94a6` |
| `artifacts/deepseek-asr-ab/runs/deepseek-asr/run-report.json` | `3f4c55e1a904e270` |
| `artifacts/deepseek-asr-ab/runs/openai-gpt-transcribe-nohint/run-report.json` | `277f88daf7681497` |
| `artifacts/deepseek-asr-ab/runs/openai-gpt-transcribe-hinted/run-report.json` | `122e8283c2241329` |
| `artifacts/deepseek-asr-ab/adjudication-v1/summary.json` | `a84f0da4c6db726b` |
| `artifacts/deepseek-asr-ab/adjudication-v2/summary.json` | `d8ab7d6843f78ce8` |
| `artifacts/deepseek-asr-ab/adjudication-vs-hinted-v2/summary.json` | `ba56041db80575cd` |

`artifacts/` 不入库；上述哈希可在本机复算。密钥来自 `tools/ops/run_with_openai_environment.py`（OpenAI dev 项目）与 `~/.config/tongxing/deepseek.env`，产物不含任何凭据或认证头。
