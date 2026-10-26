# Spark TTS 配音内存占用：历次复盘汇总与估算

2026-10-26。只读汇总，不跑 Spark，不改代码。来源是 dev @ `f1ef8b5f` 已入库的复盘、基准收据和提交说明。凡是“估算”都标明了推导方式，没有单独实测。

## 结论

1. **10/11 到 10/23 之前的内存中止，主因是 PyTorch 缓存分配器碎片，不是泄漏，也不只是外部服务。** 10/23 的四臂对照里，基线 8×8 每个 worker 的 CUDA allocated 每窗后都回到 3.90 GiB，但 reserved 从 4.0 涨到 7.8–10.7 GiB 且不回落，8 个合计 73 GiB；主机可用内存每窗平均下降约 1 GiB，第 41 窗跌破 24 GiB 保留线。整篇 419–461 句（53–58 窗）在旧配置下单独跑也必然触线。10/11 的 `llama-server`（约 34.9 GiB）和前一语言容器未释放是叠加因素。
2. **#1331 以后的内存策略已经把曲线压平。** `expandable_segments:True` 加每窗 `empty_cache()` 后，8×8 跑满 48 窗，最低可用 52.9 GiB，worker reserved 每窗回到 3.9 GiB，生成耗时差 1% 以内，WAV 字节一致。10/23 lanes 实测 ko/es 各 402 句、51 窗，最低 53.0 / 53.1 GiB，首尾持平。
3. **每副本估算：加载后约 5.1 GiB，运行峰值约 7.9–8.1 GiB**（主机统一内存口径）。现行准入按 24 GiB 保留 + 9 GiB × 副本数，8×8 要求 96 GiB。
4. **GPU 显存峰值仍然没有直接数字。** GB10 的 `nvidia-smi` 显示 N/A，所有收据的 `gpuPeakBytes` 都是 null；能用的是每个 worker 的 PyTorch allocated/reserved 计数和宿主 `MemAvailable`，两者在 UMA 上不能相加。

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

10/23 四臂对照（同一 checkpoint、种子和 64 句样本，8×8）：

| 臂 | 窗数 | 加载后 | 最低 | 首到末结果下降 | worker 最大 reserved | 生成中位 |
|---|---|---|---|---|---|---|
| 基线 | 41（触线） | 75.78 | 23.92 | 38.76 | 7.79–10.73，合计 73.4 | 51.6 秒 |
| expandable_segments | 48 | 75.74 | 44.30 | 20.69 | 6.33–7.45，合计 53.5 | 50.8 秒 |
| 每窗 empty_cache | 48 | 75.41 | 51.30 | 0.11 | 7.67–9.43，合计 65.7 | 50.7 秒 |
| 两者都开（现行） | 48 | 75.69 | 52.92 | −0.08 | 6.33–7.45，窗后回到 3.92 | 50.2 秒 |

单位 GiB。四臂加载前都约 116.3 GiB，关闭后回到约 116.3 GiB。每个 worker RSS 稳定在 2.3 GiB。

回转写 ASR（Qwen3-ASR-0.6B，batch 1）在 10/23 lanes 实测宿主占用 3.9 GiB、CUDA 峰值 1.8 GiB，准入预算从暂定 12 GiB 降到 6 GiB。

## 估算

以下由上面的数字推导，没有单独测过。

**每副本占用（UMA 宿主口径）。**
- 加载后：(116.3 − 75.7) ÷ 8 ≈ 5.1 GiB。10/3 的 16×4 分批加载给出 (117.8 − 36.47) ÷ 16 ≈ 5.1 GiB，两次一致。其中 CUDA allocated 3.89 GiB、reserved 4.02 GiB（10/3 16 个 worker 实测），其余是进程和 CUDA 上下文。
- 运行峰值（现行策略）：(116.3 − 52.9) ÷ 8 ≈ 7.9 GiB；提交 `4ef787f4` 按加载前到运行最低点记为 8.1 GiB，准入取 9 GiB，余量约 1 GiB／副本。
- 旧配置峰值：10/3 的 8×8 只跑 64 句，(117.8 − 38.43) ÷ 8 ≈ 9.9 GiB，而且会随窗数继续增长。

**旧配置为什么整篇必然触线。** 基线从首个结果 63.7 GiB 到第 41 窗 23.9 GiB，约 1.0 GiB／窗。按线性外推，zh 419 句（53 窗）末尾约 12 GiB，461 句（58 窗）约 7 GiB，都低于 24 GiB 保留线。这与 10/11 zh 首跑“合成到 461 句、在组装前退出”吻合。

**同机余量（现行策略）。** 空闲约 116 GiB，8×8 峰值占约 63 GiB，剩约 53 GiB，扣 24 GiB 保留后能再容纳约 29 GiB：
- ASR 筛查（约 4 GiB）可以同时跑，lanes 正是这样排的。
- `llama-server` 27B（约 35 GiB）不能同时跑，会让可用内存降到约 18 GiB 并触线。独占会话已把 `job-reasoning-review.timer` 列入冻结单元（`spark_exclusive_session.py` 的 `UNITS`）。
- 两个 8×8 池不能同时跑（约 127 GiB > 116）。
- 副本数上限：10 副本约 79 GiB，最低约 37 GiB，但准入要 24 + 90 = 114 GiB，只比空闲少 2 GiB，实际不可用；12 副本约 95 GiB，最低约 21 GiB，会触线。GPU 在 8 副本已到 96%，加副本也不会更快。

**云 GPU 显存（修正 10/7 的估计）。** [云 GPU 文档](20261007-cloud-gpu-resources-and-concurrency.zh.md)当时估每副本 5–11 GB、8 副本 40–88 GB。按 10/23 数据，独立显卡上显存主要是 CUDA reserved（现行策略每 worker 最大 6.3–7.45 GiB，合计约 53.5 GiB）加每进程 CUDA 上下文（约 0.5 GiB，估），8 副本约 57–60 GiB，单张 80 GB 卡够用；worker 的 2.3 GiB RSS 落在系统内存。x86 镜像和 torch 版本不同，上线前仍要实测。

## 还缺的证据

1. **zh 整篇在新策略下的实测。** 现行策略只有 ko/es 402 句（51 窗）的整篇证据；zh 常见 419–461 句（53–58 窗），最长的一次还没跑过。下一次周产 zh 的 `replica-runtime.json` 和 pool 事件里已带每窗内存，读出最低值即可补上。
2. **逐句线（tts_pool.py，两讲员 8×8）在 #1341 以后的内存曲线。** 每行 `tts-log.jsonl`／`tts-batches.jsonl` 已写 `memAvailableBytes`、`cudaReservedBytes` 等字段，但还没有入库的运行汇总。
3. **触线瞬间快照。** 10/23 起 `_guard` 会写 `reserve_failure` 事件（MemAvailable、各 worker RSS 和最近一次 CUDA 计数），但策略生效后还没有触线记录，所以这一路径没有真实样本。
4. **GPU 峰值。** GB10 不报显存；如需更接近“显存”的数字，可在 worker 结束时汇总 `max_memory_reserved` 合计，作为 UMA 上 CUDA 侧上界。
