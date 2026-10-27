# 整篇双语 Spark TTS 内存曲线实测

目的：补上[内存汇总报告](../../docs/reports/20261026-spark-tts-memory-retrospective.zh.md)里缺的证据：中文整篇（419–461 句、53–58 窗）在现行内存策略下的最低可用内存，以及两种语言一起跑时整段时间的宿主内存曲线。只做诊断，不发布，不产生发布材料。

## 怎么“双语并行”

用现有的 `group_tasks.py lanes`：zh-Hans 一条线、ko 一条线。两个 8×8 渲染**轮流**占用 GPU，压缩等 CPU 步骤和另一种语言的渲染重叠。两个 8×8 池同时跑放不下：每池峰值约 63 GiB，合计约 127 GiB，而空闲只有约 116 GiB，第二个池会在准入时被拒（要求 96 GiB）。8 副本时 GPU 已经用到 96%，同时跑也不会更快。

## 步骤（在 Spark 上）

`RUN` 是本次运行目录，例如 `~/dgx-spark-benchmark/results/full-episode-mem-<日期>`。

1. 按 [runbook](../../docs/codex-local-production-runbook.zh.md) 开 Spark 独占会话（`spark_exclusive_session` 的 `begin`，`--preempt`）。会话会冻结 `job-reasoning-review.timer` 和 `llama-server`。开始前 `MemAvailable` 应在 110 GiB 以上。
2. 准备两条线：从 `config/group-l3-stages.draft.json` 各复制一份，给 zh-Hans 和 ko 填好本周 speech job 的路径；再从 `config/group-l3-lanes.draft.json` 复制，只留 zh-Hans（第一条）和 ko。先 `--dry-run`。
3. 启动采样器（每秒一行，只记内存和 GPU 利用率）：
   ```sh
   mkdir -p "$RUN/memory"
   nohup python3 experiments/spark-tts-memory-full-episode/sample_host_memory.py \
     --out "$RUN/memory/host.jsonl" > /dev/null 2>&1 &
   echo $! > "$RUN/memory/sampler.pid"
   ```
4. 跑 lanes：
   ```sh
   python tools/ops/group_tasks.py lanes --config "$RUN/l3-lanes.json" --out "$RUN/lanes"
   ```
5. 停采样器并出报告：
   ```sh
   kill "$(cat "$RUN/memory/sampler.pid")"
   python3 experiments/spark-tts-memory-full-episode/memory_curve_report.py \
     --samples "$RUN/memory/host.jsonl" --lanes-report "$RUN/lanes/lanes-report.json" \
     --runtime zh-Hans=<zh 渲染目录>/replica-runtime.json \
     --runtime ko=<ko 渲染目录>/replica-runtime.json \
     --asr-memory zh-Hans=<zh ASR 收据>.memory.json --asr-memory ko=<ko ASR 收据>.memory.json \
     --out "$RUN/memory"
   ```
   终端会打印一行摘要：宿主最低值，以及每种语言的窗数、最低值、每窗下降量、是否触线。
6. 结束独占会话。把 `$RUN/memory/memory-curve.json` 和 `memory-curve.svg` 拷回 Mac。

## 产出

- `memory-curve.json`：宿主曲线摘要（首值、最低值和时刻、末值、swap 增量、GPU 峰值利用率），每个 stage 期间的最低可用内存，每种语言渲染的准入、`pool_ready`、逐窗 `MemAvailable` 和 worker reserved，ASR 准入收据。
- `memory-curve.svg`：宿主 `MemAvailable` 曲线，叠加逐窗采样点、24 GiB 保留线和各 stage 的时间带。

两份文件都只含内存和时间数字，不含讲道文字或音频，可以入库到 `data/benchmarks/spark-tts-memory-full-episode/<日期>/`。

## 判读

- 现行策略下，每种语言的逐窗 `MemAvailable` 应基本持平（10/23 ko/es：最低约 53 GiB，首末差小于 2 GiB）。`drainGiBPerWindow` 明显大于 0 说明碎片又出现了。
- `reserveTripped=true` 时看 `reserveFailure` 和宿主曲线，判断是 TTS 本身还是同机其它进程。
- GB10 不报显存，所以这里没有 GPU 显存峰值。
