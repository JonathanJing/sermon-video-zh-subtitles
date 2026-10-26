# Spark TTS 配音内存占用：历次复盘汇总与估算

2026-10-26。前半部分是只读汇总；同日晚补了一次整篇 zh + ko 的 Spark 实测（诊断，不发布），数字见[运行收据](../../data/benchmarks/spark-tts-memory-full-episode/2026-10-26/run-receipt.json)、[memory-curve.json](../../data/benchmarks/spark-tts-memory-full-episode/2026-10-26/memory-curve.json) 和下文“10/26 整篇实测”。汇总来源是 dev @ `f1ef8b5f` 已入库的复盘、基准收据和提交说明；凡是“估算”都标明了推导方式，实测部分单独标出。

## 结论

1. **10/11 到 10/23 之前的内存中止，主因是 PyTorch 缓存分配器碎片，不是泄漏，也不只是外部服务。** 10/23 的四臂对照里，基线 8×8 每个 worker 的 CUDA allocated 每窗后都回到 3.90 GiB，但 reserved 从 4.0 涨到 7.8–10.7 GiB 且不回落，8 个合计 73 GiB；主机可用内存每窗平均下降约 1 GiB，第 41 窗跌破 24 GiB 保留线。整篇 419–461 句（53–58 窗）在旧配置下单独跑也必然触线。10/11 的 `llama-server`（约 34.9 GiB）和前一语言容器未释放是叠加因素。
2. **#1331 以后的内存策略已经把曲线压平。** `expandable_segments:True` 加每窗 `empty_cache()` 后，8×8 跑满 48 窗，最低可用 52.9 GiB，worker reserved 每窗回到 3.9 GiB，生成耗时差 1% 以内，WAV 字节一致。10/23 lanes 实测 ko/es 各 402 句、51 窗，最低 53.0 / 53.1 GiB，首尾持平。
3. **每副本：加载后约 5.1 GiB，加载瞬时峰值约 7.7 GiB，生成阶段峰值约 7.0 GiB**（主机统一内存口径；峰值按 10/26 每秒采样拆分，见“估算”）。现行准入按 24 GiB 保留 + 9 GiB × 副本数，8×8 要求 96 GiB，余量约 1.3 GiB／副本。
4. **10/26 补上了整篇 zh 的实测：474 句、60 窗，逐窗最低 62.20 GiB，首末 66.75 → 66.72，没有触线。** 同一轮 ko 402 句（51 窗）最低 61.21 GiB，首末 66.67 → 66.66；两种语言的宿主最低值 53.68 GiB 出现在 ko 加载与 zh 压缩重叠的约 1 分钟里，仍高于 24 GiB 保留线。生成期间两条线都基本持平（0.001 / 0.000 GiB／窗），和 10/23 的结论一致。这是诊断运行：代码树、两套 job 和 ko 组装失败都在下方实测小节和运行收据里写明，不能当作发布证据。
5. **GPU 显存峰值仍然没有直接数字。** GB10 的 `nvidia-smi` 显示 N/A，所有收据的 `gpuPeakBytes` 都是 null；能用的是每个 worker 的 PyTorch allocated/reserved 计数和宿主 `MemAvailable`，两者在 UMA 上不能相加。

## 历次记录

| 日期 | 场景 | 配置 | 最低可用（宿主 MemAvailable） | 结果 | 来源 |
|---|---|---|---|---|---|
| 10/3 | zh 64 句选型 | 8×8 | 38.43 GiB（组件探针 38.51） | 完成；无 cgroup OOM、无新增 swap；GPU 96%、68°C | [8×8 报告](20261003-spark-production-8x8.zh.md)、[comparison.json](../../data/benchmarks/spark-production-8x8/2026-10-03/comparison.json) |
| 10/3 | 同上 | 16×4 同步／分批加载 | 23.65 / 22.73 GiB | 加载或 warmup 触发 24 GiB 保护 | 同上 |
| 10/4 | 正式周产 es 修订 | 8×8，reserve 24 | 失败瞬间未落盘；续跑最低 53.34 GiB | 2 次 `MemAvailable is below the TTS replica reserve`，非 CUDA OOM | [audio-and-resources](20261004-retrospective/audio-and-resources.zh.md)、[full-production](20261004-full-production-retrospective.zh.md) |
| 10/5 | 独占会话验证 | 无推理 | 停服务前约 71.1，停后约 117.2 GiB | `llama-server` 进程 35,695 MiB | [exclusive-control](20261005-spark-exclusive-control-verification.zh.md) |
| 10/7–10/8 | 3 分钟诊断 | 8×8，13 段 | 未记；恢复服务后约 80 GiB | 完成，每副本加载约 48 秒 | [round2](20261008-haiku-180s-8x8-round2-retrospective.zh.md) |
| 10/11 | 正式周产 | 8×8 | 未落盘 | zh 461 句首跑在组装前退出，zh 续跑、ko、es 共 3 次触线 | [resi-54475d42](20261011-weekly-release-resi-54475d42-retrospective.zh.md) L3-5 |
| 10/22–10/23 | 逐句线首期 | 单副本，batch 1 / batch 8 | 未记录 | 无内存问题记录 | [sentence-first 复盘](20261022-sentence-first-production-retrospective.zh.md)、[整期流程](20261023-sentence-first-full-episode-flow-review.zh.md) |
| 10/23 | 内存 A/B，64 句 × 6 轮 | 8×8 四臂 | 见下表 | 基线 41 窗触线，其余三臂 48/48 | [comparison.json](../../data/benchmarks/spark-tts-memory-ab/2026-10-23/comparison.json)，提交 `daf64f29` |
| 10/23 | lanes 诊断，ko/es 各 402 句 | 8×8 + 新策略 | ko 53.1 / es 53.0 GiB | 51 窗全完成，曲线持平 | [lanes-diagnostic-run.json](../../data/benchmarks/l3-lanes/2026-10-23/lanes-diagnostic-run.json)，提交 `7d3c2ce2` |
| 10/26 | 整篇 lanes 诊断：zh 474 句、ko 402 句，先后渲染，zh 压缩与 ko 渲染重叠 | 8×8 + 现行策略 | 宿主 53.68；zh 逐窗 62.20、ko 61.21 | 两个池 60/60、51/51 窗，无触线；zh 渲染+压缩完成，ko 组装因超片长 4.55 秒被拒（非内存） | [run-receipt.json](../../data/benchmarks/spark-tts-memory-full-episode/2026-10-26/run-receipt.json)、[memory-curve.json](../../data/benchmarks/spark-tts-memory-full-episode/2026-10-26/memory-curve.json) |

10/23 四臂对照（同一 checkpoint、种子和 64 句样本，8×8）：

| 臂 | 窗数 | 加载后 | 最低 | 首到末结果下降 | worker 最大 reserved | 生成中位 |
|---|---|---|---|---|---|---|
| 基线 | 41（触线） | 75.78 | 23.92 | 38.76 | 7.79–10.73，合计 73.4 | 51.6 秒 |
| expandable_segments | 48 | 75.74 | 44.30 | 20.69 | 6.33–7.45，合计 53.5 | 50.8 秒 |
| 每窗 empty_cache | 48 | 75.41 | 51.30 | 0.11 | 7.67–9.43，合计 65.7 | 50.7 秒 |
| 两者都开（现行） | 48 | 75.69 | 52.92 | −0.08 | 6.33–7.45，窗后回到 3.92 | 50.2 秒 |

单位 GiB。四臂加载前都约 116.3 GiB，关闭后回到约 116.3 GiB。每个 worker RSS 稳定在 2.3 GiB。

回转写 ASR（Qwen3-ASR-0.6B，batch 1）在 10/23 lanes 实测宿主占用 3.9 GiB、CUDA 峰值 1.8 GiB，准入预算从暂定 12 GiB 降到 6 GiB。10/26 在渲染池关闭后单独跑 zh 筛查，宿主占用约 4.1 GiB（准入时 116.51 → 运行后 112.42；加载约 2.9 GiB，运行中再占 1.2 GiB）、CUDA reserved 峰值 1.78 GiB，准入仍按暂定 12 GiB；这是单独运行的数字，不能当成与 8×8 池并存的余量证据。

## 10/26 整篇实测（诊断，不发布）

目的：补“还缺的证据 1”。做法：Spark 独占会话里用 `group_tasks.py lanes` 跑 zh-Hans、ko 两条线，一个 GPU 槽、8×8；宿主采样器每秒记 `MemAvailable`，结束后用 `experiments/spark-tts-memory-full-episode/memory_curve_report.py` 汇总成 `memory-curve.json` 和 SVG。

| 项 | zh-Hans | ko |
|---|---|---|
| 句数 / 窗数 | 474 / 60 | 402 / 51 |
| job | 10/4 人工批准（`1491cea2…`，eric_geiger） | 10/18 人工批准（`33eb47dc…`，steve_bang_lee） |
| 准入可用 | 116.05 GiB，要求 96 | 115.75 GiB，要求 96 |
| 池就绪 | 75.57 | 75.66 |
| 逐窗可用（首 / 最低 / 末） | 66.75 / 62.20 / 66.72 | 66.67 / 61.21 / 66.66 |
| 每窗下降 | 0.001 | 0.000 |
| worker reserved 最大 | 3.92 | 3.92 |
| 触线 | 否 | 否 |
| 渲染耗时 | 442.5 秒 | 491.9 秒 |

宿主曲线：116.62 → 53.68 → 116.60 GiB，1232 秒，swap 只增 0.01 GiB，GPU 峰值利用率 96%。最低点 15:12:05Z 出现在 ko 池加载、zh 压缩容器同时在跑的时候；生成窗口内的最低值是 62.20 / 61.21，说明池本身没有旧配置那种每窗约 1 GiB 的下降。

把每秒采样按池的 `admission`／`pool_ready`／最后一个 `result` 时间切开（复算用 `host-samples.jsonl` 与两份 `replica-runtime.json`，数据在 #1398）：

| 阶段 | zh-Hans | ko |
|---|---|---|
| 加载耗时 | 52.1 秒 | 47.3 秒 |
| 加载阶段宿主最低（距准入） | 54.47（41.6 秒） | 53.68（37.6 秒） |
| 生成阶段宿主最低（每秒采样） | 60.07 | 59.86 |
| 生成阶段 p5 / 中位 | 63.5 / 65.5 | 62.2 / 65.0 |

- **最低点主要来自模型加载的瞬时高峰，不是重叠。** zh 加载时同机没有别的任务，也降到 54.47 GiB；ko 加载叠上 zh 压缩只多降约 0.8 GiB。两个池都在开始加载约 40 秒时出现低谷，`pool_ready` 时回到约 75.6 GiB。
- **pool 的逐窗事件会高估最低值约 2 GiB。** 事件在窗口结束、释放缓存之后采样，生成中途的低谷（60.07 / 59.86）只有宿主采样器看得到；加载低谷更是完全不在逐窗事件里。以后判断余量应以宿主每秒采样为准。

边界（读这张表前必须知道）：

- 代码树是 `56c053a5`（dev + #1331 + #1332 + 2026-10-18 术语表），不是当天 dev。现有 job 都冻结在 10/20 术语表变更之前的策略上，现行表会拒绝它们；这个运行证明的是内存策略，不是当前术语表。
- zh 用 10/4 的人工批准 job；10/18 的 zh job 是旧 QC 实现下签发的机器豁免，现已无法准入。ko 用 10/18 的人工批准 job。两条线不是同一篇讲道。
- 渲染只到 wav：TTS 镜像里没有 ffmpeg，诊断工作树把 `--track-format` 改成 wav；MP3 封装没有验证。
- zh 的 `screen` 阶段在 lanes 里因配置错误（把 render 的输入参数传给了不接受它们的 `screen`）0.2 秒失败；lanes 结束后手工用正确参数重跑，exit 0，ASR 收据已写入。
- ko 的 402 句全部合成、池 51/51 窗正常关闭，但组装时第 368 句的计划终点 1899.55 秒超过片长 1895 秒（滞后 179.49 秒，阈值 240 秒），被渲染器拒绝。这是时间接受失败，不是内存失败；ko 的内存证据仍然完整。
- 独占会话按 `--preempt --allow-interrupted-restart` 停了 `llama-server` 等五个受管单元，结束已恢复并核验健康；会话 `l3-mem-curve-20261026`。

因此，“zh 整篇在现行内存策略下”的缺口已经补上；“当前 dev 树 + 当前术语表”的整篇 zh 仍没有跑过。

## 估算

以下由上面的数字推导，没有单独测过。

**每副本占用（UMA 宿主口径）。**
- 加载后：(116.3 − 75.7) ÷ 8 ≈ 5.1 GiB。10/3 的 16×4 分批加载给出 (117.8 − 36.47) ÷ 16 ≈ 5.1 GiB，两次一致。其中 CUDA allocated 3.89 GiB、reserved 4.02 GiB（10/3 16 个 worker 实测），其余是进程和 CUDA 上下文。
- 运行峰值（现行策略）：10/23 A/B 给出 (116.3 − 52.9) ÷ 8 ≈ 7.9 GiB，提交 `4ef787f4` 记为 8.1 GiB。10/26 每秒采样把它拆开：加载瞬时 (116.05 − 54.47) ÷ 8 ≈ 7.7 GiB，生成阶段 (116.05 − 60.07) ÷ 8 ≈ 7.0 GiB。准入取 9 GiB，余量约 1.3 GiB／副本。
- 旧配置峰值：10/3 的 8×8 只跑 64 句，(117.8 − 38.43) ÷ 8 ≈ 9.9 GiB，而且会随窗数继续增长。

**旧配置为什么整篇必然触线。** 基线从首个结果 63.7 GiB 到第 41 窗 23.9 GiB，约 1.0 GiB／窗。按线性外推，zh 419 句（53 窗）末尾约 12 GiB，461 句（58 窗）约 7 GiB，都低于 24 GiB 保留线。这与 10/11 zh 首跑“合成到 461 句、在组装前退出”吻合。

**同机余量（现行策略）。** 空闲约 116 GiB，8×8 峰值占约 62 GiB（加载瞬时），剩约 54 GiB，扣 24 GiB 保留后能再容纳约 30 GiB；加载完成后只占约 56 GiB，余量再多约 6 GiB：
- ASR 筛查（约 4 GiB）可以同时跑，lanes 正是这样排的。
- `llama-server` 27B（约 35 GiB）不能同时跑，会让可用内存降到约 18 GiB 并触线。独占会话已把 `job-reasoning-review.timer` 列入冻结单元（`spark_exclusive_session.py` 的 `UNITS`）。
- 两个 8×8 池不能同时跑（约 127 GiB > 116）。
- 副本数上限：10 副本约 79 GiB，最低约 37 GiB，但准入要 24 + 90 = 114 GiB，只比空闲少 2 GiB，实际不可用；12 副本约 95 GiB，最低约 21 GiB，会触线。GPU 在 8 副本已到 96%，加副本也不会更快。

**云 GPU 显存（修正 10/7 的估计）。** [云 GPU 文档](20261007-cloud-gpu-resources-and-concurrency.zh.md)当时估每副本 5–11 GB、8 副本 40–88 GB。按 10/23 数据，独立显卡上显存主要是 CUDA reserved（现行策略每 worker 最大 6.3–7.45 GiB，合计约 53.5 GiB）加每进程 CUDA 上下文（约 0.5 GiB，估），8 副本约 57–60 GiB，单张 80 GB 卡够用；worker 的 2.3 GiB RSS 落在系统内存。x86 镜像和 torch 版本不同，上线前仍要实测。

## 还缺的证据

1. **当前 dev/术语表下的整篇 zh。** 10/26 的实测用的是 10/23 诊断树（旧术语表），补上了 474 句的内存曲线，但没有走当前术语表的准入。下一次周产 zh 用当前树跑时，读出 `replica-runtime.json` 的每窗 `MemAvailable` 即可直接对照。
2. **ASR 与 8×8 池同时驻留时的占用。** 10/26 的 zh 筛查是在两个池关闭后手工重跑的，测到的是 ASR 单独占用。
3. **逐句线（tts_pool.py，两讲员 8×8）在 #1341 以后的内存曲线。** 每行 `tts-log.jsonl`／`tts-batches.jsonl` 已写 `memAvailableBytes`、`cudaReservedBytes` 等字段，但还没有入库的运行汇总。
4. **触线瞬间快照。** 10/23 起 `_guard` 会写 `reserve_failure` 事件（MemAvailable、各 worker RSS 和最近一次 CUDA 计数），但策略生效后还没有触线记录，所以这一路径没有真实样本。
5. **GPU 峰值。** GB10 不报显存；如需更接近“显存”的数字，可在 worker 结束时汇总 `max_memory_reserved` 合计，作为 UMA 上 CUDA 侧上界。
