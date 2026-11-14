# DeepSeek 云 TTS 与我们 Spark 配音的速度对照

实测日期：2026-11-14（America/Los_Angeles）。同一批 460 个中文单元、同一份我们自己的分句文本，分别用 DeepSeek 云 TTS 和我们生产上的 Spark/Qwen3-TTS 合成，记录速度、时长和按现有排程规则会出现的滞后。**实验性质**：没有人工听审，不签发、不豁免、不替换任何讲员声音，也不改现有配音政策。

## 结论先行

- **速度：串行慢一倍，8 路并发快约四倍。** 460 单元逐句请求，云 TTS 墙钟 753.0 秒（RTF 0.351），我们 Spark 单进程 batch 8 是 382.9 秒（RTF 0.210）；云 TTS 开到 8 路并发后 95.5 秒完成（RTF 0.045），约为 Spark 的 1/4。
- **每次调用有约 1.1 秒固定开销。** 首字节 p50 1.10 秒、整句完成 p50 1.53 秒，且与句长关系不大：19.6 字的短句也要 1.5 秒左右。所以云 TTS 的瓶颈在请求数，不在字数和时长——并发才有意义。
- **成本：每期 $0.38。** 17,010 计费字符，限时 5 折 $0.3827，标价 $0.7654；我们 Spark 是本机 GPU，没有按次计费。
- **时长：云语音更长。** 同样 460 句，云 TTS 音频共 2142.6 秒，Spark 1819.8 秒，长 17.7%（389/460 句更长，中位 +0.56 秒）。其中约 110 秒是句尾静音（均值 0.286 秒 vs Spark 0.048 秒），纯语音部分长 14.4%。
- **同步：原样排程不可用，去掉边缘静音后可用。** 按生产的英文锚点放音（`merge_track.py` 规则，gap 0.05）时，云 TTS 原样把最大滞后推到 **42.9 秒、362 句超 8 秒**；同一排程下 Spark 是 2.14 秒、0 句超 8 秒。只把句首句尾静音裁到与 Spark 相当（不改语速、不切句内语音）后，云 TTS 最大滞后 6.3 秒、0 句超 8 秒，整轨 2143.5 秒，和 Spark 的 2143.5 秒基本重合。
- **判断：速度上云 TTS 可以作为我们 Spark 之外的候选；直接接入现有排程不行。** 先要确定性地处理每单元边缘静音，或者换一个语速更贴合英文时长的声音。这两条都不属于本报告的范围，本报告也没有做听感结论。

## 输入

| 项 | 取值 |
|---|---|
| 运行 | `artifacts/sentence-first-agent/20261108-jesus-is-just-zh`（2026-11-07 周六 17:30 场，Eric Geiger，启 15–16） |
| 分句 | 我们的 Layer 1 `anchor-manifest.json` 单元（`clause_stable`），461 句合并 3 处切句残片后 460 句；中文按单元逐句翻译 |
| 文本 | `speech.jsonl` 460 行，8,997 字，平均 19.6 字/句；5 句含拉丁字母或数字 |
| 视频窗口 | 0.000–2155.060 秒 |
| 单元粒度 | 每单元一次合成（与 `docs/multilingual-production-interfaces.zh.md` 的 L3 约定一致），不改写、不合并、不拆句 |

## 两个引擎

| | DeepSeek 云 TTS | 我们的 Spark 配音 |
|---|---|---|
| 模型 | `POST /v1/tools/tts`，`voice_id=tide`（男声） | Qwen3-TTS 12Hz 1.7B Base，讲员 checkpoint，DGX Spark CUDA/BF16 |
| 并行 | 本次测串行与 8 路并发 | 单进程、batch 8 逐批串行、seed 7（单讲员不起副本池；`spark_queue.py` 逐语言串行） |
| 音频 | 24 kHz 单声道 PCM16 WAV | 24 kHz 单声道 PCM16 WAV |
| 计时来源 | 本次实测 | `tts-run.log` 批级墙钟 + `tts-log.jsonl` 单元时长（该 run 第二次 TTS，2026-11-08 04:54:09–05:01:05Z） |

Spark 那一次不是今天复跑，是同一份文本在 11-08 的生产记录；两边不是同分钟 A/B。

## 方法

- 分句直接取 `speech.jsonl` 的 `spokenText`，每行一次请求，服务端没有语言参数、不做提示词。
- 计时口径：`requests` 会话保持连接；`ttfb` 是发出请求到收到第一块音频，`latency` 是发请求到读完整个音频；音频时长由 WAV 数据块长度计算。
- 服务返回的 WAV 头没有回填长度（data 块写 `0xFFFFFFFF`），脚本先把 RIFF/data 长度改对再落盘，否则播放器和我们的合并工具读不出长度。
- Spark 的 RTF 用批级墙钟（含每批 CUDA 缓存释放，约 2.1 秒合计）除以音频时长；阶段墙钟 416 秒的差约 33 秒是容器与模型加载，单独列出。
- Spark 这一个 run 是单进程 batch 8：`tts-log.jsonl` 里 `cudaAllocatedBytes` 全程 4.2 GB、批序号 0–57 顺序推进，说明没有开副本池；生产队列单讲员默认也是单任务单进程。
- 排程对照直接调用 `experiments/sentence-first-agent/merge_track.py`（实际开始 = max(英文起点, 游标)，`--gap 0.05`），和 11-08 那次生产同一套规则。

## 速度

| 条件 | 请求 | 墙钟秒 | 音频秒 | RTF | 单句 p50 / p95 秒 | 首字节 p50 秒 | 计费 |
|---|---|---|---|---|---|---|---|
| DeepSeek 串行 | 460 | 753.0 | 2142.6 | 0.351 | 1.53 / 2.50 | 1.10 | $0.3827 |
| DeepSeek 8 路并发 | 460 | 95.5 | 2143.1 | 0.045 | 1.52 / 2.55 | 1.11 | $0.3827 |
| Spark 单进程 batch 8（11-08 生产） | 460 | 382.9（阶段 416.0） | 1819.8 | 0.210 | 0.82 / 1.12（摊到每单元） | — | 本机 GPU |

- 云 TTS 串行 460 次请求 0 次重试、0 次失败；并发 8 同样 0 失败。这不是长跑稳定性结论。
- 并发把 RTF 从 0.351 压到 0.045，是因为服务端每次调用约 1.1 秒的固定开销可以重叠；单句延迟几乎不变（p50 1.52 秒），说明没有排队恶化。
- 云 TTS 8 路并发比我们 Spark 单进程 batch 8 快约 4 倍；单请求串行慢约 2 倍。两边并行结构不同（服务端按请求并行 vs 我们本地按 8 句一批），所以这不是「谁算得快」的直接结论，而是「整期多久拿到音频」的结论：值不值得切换取决于能否接受 1.1 秒/句的固定开销和 $0.38/期的费用。

## 时长

| 指标 | DeepSeek | Spark | 差 |
|---|---|---|---|
| 音频总长 | 2142.6 秒 | 1819.8 秒 | +322.8 秒（+17.7%） |
| 纯语音（去掉首尾静音） | 1890.0 秒 | 1651.6 秒 | +238.4 秒（+14.4%） |
| 句尾静音均值 / 中位 | 0.286 / 0.280 秒 | 0.048 / 0.040 秒 | +109.5 秒合计 |
| 句首静音中位 | 0.280 秒 | 0.360 秒 | − |
| 单句时长比 中位 | 1.172 | 1.000 | 389/460 句更长 |
| 超出英文时槽（`budgetSeconds`） | 255 / 460 句 | 104 / 460 句 | — |
| 单句差值 p50 / p95 / 最大 | +0.56 / +2.60 / +4.64 秒 | — | 最长 s0133：6.72→11.36 秒 |

差值最大和最小时刻都集中在长句（s0133、s0281、s0159 偏长；s0357、s0074 偏短），不是整体匀速放大。

## 同步

同一批英文锚点和 gap 0.05，只换单元音频：

| 变体 | 整轨秒 | 最大滞后秒 | 滞后 >8 秒句数 | 滞后中位秒 |
|---|---|---|---|---|
| A 云 TTS 原样 | 2169.7 | 42.9 | 362 | 12.93 |
| B 句尾静音裁到 0.05 秒 | 2143.8 | 16.9 | 75 | 2.40 |
| C 首尾静音都去掉，只放语音 | 2143.5 | 6.3 | 0 | 0.19 |
| D Spark 实测 | 2143.5 | 2.14 | 0 | 0.00 |

- 原样接入会把滞后一路累加到 43 秒：游标只前进不后退，每句多出的 0.28 秒句尾静音会不断叠加。
- 只裁句尾不够（B 仍 75 句超 8 秒），因为句首静音（中位 0.28 秒）同样让语音入点晚于英文锚点；首尾都裁之后（C）才回到 Spark 的轨道长度。
- **C 是诊断，不是已批准的打包改动。** 它只删静音、不改语速、不切句内语音，但仍然是音频改动，要落地必须按 L3 产物记录（哪些帧被裁、阈值、改动后时长）并重新走人工整轨听审；阈值 0.004 振幅（约 −48 dBFS）是这次分析用的，不是政策值。
- 没有做任何变速或拉伸来凑时长，符合现有 L3 政策。

## 成本与容量

- 计费字符 17,010（中文按 2 计），限时价 $0.3827/期，标价 $0.7654/期；三期/周（zh/ko/es，字符数不同）按此数量级估约 $1.1–2.3/周。
- 服务限制：单请求最多 10,000 计费字符、64 KiB，单次最多 30 分钟音频；账户最多 50 个并发请求；不支持语速控制，也不支持中断后续传。
- 我们 Spark 的成本是 GPU 占用时间（本次 383 秒合成 + 模型驻留），没有按次费用；云 TTS 的成本是每期固定 $0.38 且不占本机 GPU。

## 观察与限制

- **声音身份不同。** `tide` 不是我们授权的讲员 checkpoint，这次没有克隆、没有换声提案，也没有任何听感结论。要评估质量必须另做人工听审。
- **语言自动检测。** 服务没有语言参数，460 句里 5 句含拉丁字母或数字。用 DeepSeek ASR 转写 60 秒预览（前 17 句，0–58.44 秒，第 18 句在 60 秒处被截断）后，转写内容与文本一致、没有整句串成英文，但这只是一次抽查，不是系统评估。
- **只做了机器检查。** ASR 能认出是中文、内容对得上，只证明音频可识别；发音、语气、断句、长短句听感都未评估。
- **失败面没有被测到。** 今天 460+460 次调用 0 失败、0 重试，说明不了 429/503 在真实生产队列里的表现；也没有测长时间跑、并发上限附近的行为。
- **基线是历史记录。** Spark 数字来自 11-08 那一次生产 run，不是今天同条件复跑；云 TTS 数字是今天在本机 MacBook 上通过公网请求测的，含跨境网络延迟。
- **音频头需要修。** 服务返回的 WAV 长度字段是占位值，落盘前必须回填；直接保存会在我们的合并和播放链路里读成未知长度。
- **本报告不改变任何现有政策。** 不改变「每单元一次自然语速合成」「不拉伸」「人工整轨听审是唯一音频结论」这三条。

## 复现

```bash
set -a; . ~/.config/tongxing/deepseek.env; set +a
RUN=artifacts/sentence-first-agent/20261108-jesus-is-just-zh
OUT=artifacts/deepseek-tts-speed

# 串行，每单元一次请求（约 12.5 分钟、$0.38）
.venv/bin/python experiments/deepseek-tts-speed/bench_deepseek_tts.py synth \
  --speech $RUN/speech.jsonl --out $OUT/seq-tide --voice tide --concurrency 1

# 8 路并发（约 1.6 分钟）
.venv/bin/python experiments/deepseek-tts-speed/bench_deepseek_tts.py synth \
  --speech $RUN/speech.jsonl --out $OUT/c8-tide --voice tide --concurrency 8

# 时长与 Spark 对照
.venv/bin/python experiments/deepseek-tts-speed/bench_deepseek_tts.py compare \
  --timing $OUT/seq-tide/timing.jsonl --spark-log $RUN/tts/tts-log.jsonl \
  --out $OUT/compare-seq-vs-spark.json

# 按生产规则排程，量滞后
.venv/bin/python experiments/sentence-first-agent/merge_track.py \
  --sentences $RUN/sentences.jsonl --tts $OUT/seq-tide \
  --out $OUT/deepseek-track.wav --schedule $OUT/deepseek-schedule.json --gap 0.05

# 连续拼接（用于试听）与 A/B 交叉
.venv/bin/python experiments/deepseek-tts-speed/bench_deepseek_tts.py assemble \
  --speech $RUN/speech.jsonl --wavs $OUT/seq-tide --out $OUT/deepseek-tts-seq-full.wav --gap 0.05
.venv/bin/python experiments/deepseek-tts-speed/bench_deepseek_tts.py ab \
  --speech $RUN/speech.jsonl --a $RUN/tts --b $OUT/seq-tide --out $OUT/ab-spark-vs-deepseek.wav --count 8
```

## 产物

都在忽略的 `artifacts/deepseek-tts-speed/`：

| 文件 | 内容 |
|---|---|
| `seq-tide/` | 460 个逐句 WAV + `timing.jsonl` + `summary.json`（串行） |
| `c8-tide/` | 460 个逐句 WAV + 计时（8 路并发） |
| `deepseek-tts-seq-full.wav` / `.mp3` | 按分句顺序连续拼接，gap 0.05，36.1 分钟 |
| `deepseek-tts-60s-preview.mp3` | 前 60 秒试听 |
| `ab-spark-vs-deepseek.mp3` | 8 组同句 Spark → DeepSeek 交叉，63.9 秒 |
| `deepseek-track.wav` / `deepseek-schedule.json` | 按英文锚点排程的结果与逐句滞后 |
| `compare-seq-vs-spark.json`、`lag-variants.json` | 时长对照与四种排程变体 |
