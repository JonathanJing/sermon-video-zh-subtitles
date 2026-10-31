# MacBook 两路 1×8 配音启动与种子一致性

## 用途与边界

需要在本机（MacBook Pro，Apple Silicon）做 TTS 配音、又不想等 Spark 时，用 **两个独立进程，各 1 个模型副本 × batch 8**。这是离线 WAV 生产/基准路径，不是正式 renderer：

- 只生成逐句 WAV，不创建 speech job、音频包或发布包；
- 不做 ASR 初筛；音频接受仍只由人工整轨听审决定；
- 与 Spark CUDA/BF16 的输出不要求字节一致，MPS/FP32 是独立执行身份。

实测（2026-10-28，M1 Max 64 GiB，Eric `75d28…` checkpoint）：两路对 107 句合计 **1.74×** 于单路（184 s vs 320.7 s），合并 RTF 0.51；第三路不再增加吞吐。单进程 batch 8 的 MPS 驱动分配约 **11.45 GiB**，推荐工作集上限 51.8 GiB，因此**最多两路**。

## 前提

- Mac 运行时：`artifacts/model-routing/macbook-tts/runtime/bin/python`（torch 2.14、qwen-tts）。
- 与任务匹配的 checkpoint；当前 Eric 为 `75d28ce6022b3df3a72df3dd6dbc01e53f584d685770d60ea04b341920968c9a`。启动器可用 `--expected-checkpoint-sha256` 校验 `model.safetensors`。
- 逐句口播表 `speech.jsonl`（每行至少 `id`、`spokenText`、`language`、`speaker`）。
- 预计至少 24 GiB 的 free+inactive+speculative；低于阈值启动器拒绝。两路运行中可用内存约 20 GiB，已接近舒适下限。

## 启动

在仓库根目录，用 Mac 运行时解释器（不是 `.venv`）：

```sh
RT=artifacts/model-routing/macbook-tts/runtime/bin/python
RUN=artifacts/mac-tts-benchmark/weekly-$(date +%Y%m%d-%H%M)

# 1) 先 dry-run：只分片、写 manifest、打印两条 worker 命令，不加载模型
$RT experiments/mac-tts-benchmark/run_two_way.py \
  --speech artifacts/sentence-first-agent/<run>/speech.jsonl \
  --checkpoint artifacts/model-routing/macbook-tts/checkpoint-75d28 \
  --out "$RUN" \
  --expected-checkpoint-sha256 75d28ce6022b3df3a72df3dd6dbc01e53f584d685770d60ea04b341920968c9a \
  --dry-run

# 2) 检查 "$RUN/shards/manifest.json"：窗口数、每片 seeds、句数
# 3) 正式跑（复用 dry-run 的目录即可；已有 worker 输出会拒绝）
$RT experiments/mac-tts-benchmark/run_two_way.py \
  --speech artifacts/sentence-first-agent/<run>/speech.jsonl \
  --checkpoint artifacts/model-routing/macbook-tts/checkpoint-75d28 \
  --out "$RUN" \
  --expected-checkpoint-sha256 75d28ce6022b3df3a72df3dd6dbc01e53f584d685770d60ea04b341920968c9a
```

输出：

```text
<out>/
  shards/manifest.json        原始窗口、seed、worker 分配
  shards/shard-0.jsonl        worker 0 的完整窗口
  shards/shard-1.jsonl        worker 1 的完整窗口
  worker-0/units/<id>.wav     按原句 id 命名
  worker-1/units/<id>.wav
  worker-0/summary.json  worker-1/summary.json
  two-way-summary.json        两路合并墙钟、音频秒数、合并 RTF、种子校验结果
```

单独审计分片（可选）：

```sh
$RT experiments/mac-tts-benchmark/split_windows.py --speech <speech.jsonl> --out-dir <dir> --workers 2 --batch-size 8 --seed 42
```

## 种子一致性

正式批策略是 **`seed = 基础种子 + 原始窗口起点`**（基础 42，窗口大小 8）。两路不能按“句子对半分”或“每片从 0 重新计窗口”，否则同一句的 seed 会变。

启动器与分片器的保证：

1. **按完整窗口轮转**：原始第 0 个 8 句窗口给 worker 0，第 1 个给 worker 1，第 2 个给 worker 0……每片是若干完整窗口按原顺序拼接；只有最后不足 8 句的尾窗口允许不完整，且整体只属于一个 worker。
2. **原始索引计 seed**：每行带 `_originalIndex`、`windowStart`、`seed`；`seed = 42 + windowStart`，与单进程完全相同。
3. **不重编号**：输出 WAV 仍用原句 `id`；worker 内部窗口顺序不影响原始身份。
4. **双重校验**：
   - 启动器按 manifest 检查每个 worker 的 `summary.seeds` 与该片窗口 seed 集合完全一致，并核对写出的 WAV 数等于该片句数；
   - 每个 worker 在合成前复核：同一窗口内所有行声明的 seed 相同，且 `seed == 42 + windowStart`，否则直接退出。
5. **合并失败不拼**：任一 worker 非零退出，启动器报错且不写 `two-way-summary.json`；不要手工把不同 seed/目录的 WAV 混在一起。

`tests/test_mac_tts_two_way.py` 用 20 句样本验证：窗口完整性、worker 轮转、每句 seed 与单进程映射一致、尾窗口归属，以及非法分片被拒绝。

## 质量检查（诊断，不是门禁）

```sh
# 回转写（MLX ASR；仅测试诊断）
~/.local/share/uv/tools/mlx-audio/bin/python experiments/mac-tts-benchmark/transcribe_units.py \
  --run <out>/worker-0 --checkpoint ~/.cache/huggingface/hub/models--mlx-community--Qwen3-ASR-0.6B-8bit/snapshots/<snap>

# 打分（.venv，需绑 host）
PYTHONPATH=".:packages/production/src" .venv/bin/python experiments/mac-tts-benchmark/evaluate_quality.py \
  --run <out>/worker-0 --speech <speech.jsonl> --checkpoint <checkpoint> --transcripts <out>/worker-0/transcripts.jsonl
```

两路各跑一次后，合起来看 `quality.json`；最终仍以人工整轨听审为准。

## 限制

- 正式 renderer 在 Mac 仍只支持 1 副本；两路是两个独立任务，必须由启动器/外部队列协调，不能指望单个 renderer 自己开两路。
- 不支持 8 副本：8 × 11.45 GiB 超过推荐工作集和物理可用内存。
- 第三路实测无吞吐增益（185 s vs 184 s），只增加内存压力；不要开第三路。
- 失败或换 checkpoint 时用新的 `--out`；不要复用旧目录或把不同 seed 的片段拼接。
