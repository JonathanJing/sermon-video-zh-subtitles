# MacBook Pro M1 Max 本地翻译 Benchmark V1

更新日期：2026-09-04
状态：`four_translation_only_runs_and_qwen_milmmt_live_soak_completed_other_candidates_pending`

## 目标

这版 Benchmark 专门筛选能够在 `MacBook Pro / Apple M1 Max / 64 GB unified memory` 上通过 Ollama 或 MLX 运行的证道英译中模型。MacBook 是主部署与性能目标；DGX Spark 结果只作为研究参考。

机器可读协议位于 `data/benchmarks/live-sermon-translation-v1/macbook-text-benchmark-v1.json`，硬件和资源门禁位于 `macbook-m1-max-64gb-profile.json`。

## 数据集复用结论

现有数据集可以并且应该复用：

- 复用同一批 5 篇 `test / untouched_test` 完整证道、239 个冻结英语语义段；
- 生成阶段只读取 `segments.en.reference.jsonl`，这些文件不含中文译文；
- `segments.zh.sol-reviewed.jsonl` 只在 239 段生成结束后用于 BLEU、chrF2 和术语命中评分；
- 不得用这 239 段选择 prompt、量化、上下文参数或做训练；开发和调参必须使用 train/dev 或另建 MacBook smoke 开发集；
- 复用数据集不等于复用性能数字。Ollama、MLX、DGX 的 tokens/s、延迟、内存和 RTF 必须分别实测；
- 同一模型分别通过 Ollama 和 MLX 运行时，使用独立 run ID 和独立性能行，不能挑选两者最好的单项拼成一个结果。

## 当前环境

- Ollama App 服务已升级并运行官方 `0.33.3`；Homebrew CLI 为 `0.33.2`；当前已安装 `sermon-hymt2-1.8b-q8:benchmark`；
- MLX 已通过隔离的 `uv tool` 环境安装：`mlx 0.32.2`、`mlx-lm 0.31.3`；GPU 运算和 `mlx_lm.server` CLI smoke 均已通过；
- `Hy-MT2-1.8B Q8_0`、`MiLMMT-46-4B-v1.0 Q8_0`、`Qwen3.5-4B-Base BF16` 和 `Qwen3.5-9B-Base BF16` 均已完成 239/239 Ollama translation-only run。只有当前 POC 组合 MiLMMT Q8 + Qwen3-ASR 已进一步完成 10 分钟共存和修复后的 60 分钟浏览器长测；其余三个翻译候选的同协议 ASR 共存 replay/soak 仍待执行。
- 本地 ASR 已完成 60 段、29.811 分钟七模型质量 bakeoff，并对其中 13 段、6.5 分钟执行独立 GPT-Transcribe 重听校准，见 [MacBook 本地英文 ASR Benchmark V1](./local-asr-benchmark.zh.md)。`Qwen3-ASR-0.6B MLX 8-bit` 以 MRQS 96.893 暂列第一，`small.en` 以 96.244 排第二且速度、内存更优；两者已完成连续 10 分钟 replay，Qwen 还完成 MiLMMT 共存与 60 分钟 POC 长测。Distil-Whisper 与 MLX Turbo 均因静音口语幻觉失败；正式晋级仍等待人工 Gold 和现场彩排。

这些环境版本描述来自 2026-09-03 的本机检查，运行证据更新到 2026-09-04；任何新 run 仍必须重新记录运行时版本、模型 digest/revision 和 artifact SHA-256。

## 执行顺序

1. 固定模型 artifact、上游 revision、量化、许可证和运行时版本。
2. 在 Ollama 或 MLX 上执行 10 段 reference-blind smoke。
3. 只有 10/10 非空中文、0 请求错误且没有 runaway output 才执行 239 段。
4. 生成结束后运行独立评分脚本；评分脚本会核对 239 个 ID 以及冻结英文是否完全相同。
5. 同时记录模型进程树 RSS、swap、memory pressure 和 thermal 状态。
6. translation-only 通过后，再执行 ASR 共存、1.0× 完整证道 replay 和 50–60 分钟 soak。
7. 通过资源、实时、安全和许可证门禁后，才进入 Sol High 全量语义审核及 A1–A3。

## Ollama 运行入口

正式运行前先用 `ollama list` 和本地 `/api/show` 固定模型身份。当前 Homebrew CLI 不支持 `ollama show <model> --json`，不要把该形式写入自动化。模型的创建、拉取或 GGUF 导入是独立步骤，不属于本协议自动执行的动作。

```bash
python3 scripts/run_macbook_sermon_text_benchmark.py \
  --backend ollama \
  --base-url http://127.0.0.1:11434 \
  --model <ollama-model-name> \
  --model-id <canonical-upstream-model-id> \
  --revision <pinned-upstream-revision> \
  --artifact-sha256 <artifact-sha256> \
  --runtime-fingerprint <ollama-version-and-model-digest> \
  --prompt-profile <sermon-a0-or-hymt2> \
  --input data/benchmarks/live-sermon-translation-v1/reference/8u9B8u_5ISI/segments.en.reference.jsonl \
  --input data/benchmarks/live-sermon-translation-v1/reference/hAWaaBVaMzY/segments.en.reference.jsonl \
  --input data/benchmarks/live-sermon-translation-v1/reference/hoeJTwl-EJg/segments.en.reference.jsonl \
  --input data/benchmarks/live-sermon-translation-v1/reference/qvImKpmvgaM/segments.en.reference.jsonl \
  --input data/benchmarks/live-sermon-translation-v1/reference/z_UoOx-6mz4/segments.en.reference.jsonl \
  --output-dir data/benchmarks/live-sermon-translation-v1/runs/macbook-text-baselines/<run-id> \
  --limit 10
```

移除 `--limit 10` 才进入正式 239 段运行。Smoke 与正式运行必须使用不同目录，防止混合身份。

## MLX 运行入口

MLX 使用本地 OpenAI-compatible server。MiLMMT 是纯 completion 翻译模型，不套 chat template；因此 MiLMMT 的正式 MLX run 必须调用 `/v1/completions`，不得调用 `/v1/chat/completions`。MLX 与 MLX-LM 已安装，`mlx_lm.server` CLI 已验证；选择并固定 MLX 模型 artifact 后，可按当前 CLI 契约启动仅监听 loopback 的 server：

```bash
mlx_lm.server \
  --model <mlx-model-path-or-id> \
  --host 127.0.0.1 \
  --port 8080 \
  --temp 0 \
  --top-k 1
```

随后运行：

```bash
python3 scripts/run_macbook_sermon_text_benchmark.py \
  --backend openai-completion \
  --base-url http://127.0.0.1:8080/v1 \
  --model <mlx-server-model-name> \
  --model-id <canonical-upstream-model-id> \
  --revision <pinned-upstream-revision> \
  --artifact-sha256 <artifact-sha256> \
  --runtime-fingerprint <mlx-and-mlx-lm-versions> \
  --prompt-profile milmmt \
  --temperature 0 \
  --top-k 1 \
  --repeat-penalty 1 \
  --input <non-test-dev-English-files> \
  --output-dir data/benchmarks/live-sermon-translation-v1/runs/macbook-text-baselines/<run-id> \
  --limit 10
```

启动后先用单句 probe 核对输出、EOS 和请求契约。MiLMMT 的 generation config 应同时接受 EOS token `1` 与 `<end_of_turn>` token `106`；如当前 MLX server 没有读取该配置，则停下修正运行时，不能靠放大 `max_tokens` 掩盖 runaway output。

MLX/GGUF 量化和后端选择阶段只能传入非 test 的 dev 文件；五篇 239 段冻结文件只在主/备运行时和量化已经锁定后做一次最终验收。

## 评分与资源记录

生成完成后，使用固定 sacreBLEU 版本运行评分：

```bash
uv run --quiet --with sacrebleu==2.5.1 python scripts/score_sermon_text_benchmark.py \
  --predictions data/benchmarks/live-sermon-translation-v1/runs/macbook-text-baselines/<run-id>/predictions.jsonl \
  --reference data/benchmarks/live-sermon-translation-v1/reference/8u9B8u_5ISI/segments.zh.sol-reviewed.jsonl \
  --reference data/benchmarks/live-sermon-translation-v1/reference/hAWaaBVaMzY/segments.zh.sol-reviewed.jsonl \
  --reference data/benchmarks/live-sermon-translation-v1/reference/hoeJTwl-EJg/segments.zh.sol-reviewed.jsonl \
  --reference data/benchmarks/live-sermon-translation-v1/reference/qvImKpmvgaM/segments.zh.sol-reviewed.jsonl \
  --reference data/benchmarks/live-sermon-translation-v1/reference/z_UoOx-6mz4/segments.zh.sol-reviewed.jsonl \
  --system-id <system-id> \
  --output data/benchmarks/live-sermon-translation-v1/runs/macbook-text-baselines/<run-id>/automatic-reference-metrics.json
```

资源采样器接受一个或多个已核实 PID，并自动包含其子进程：

```bash
python3 scripts/sample_macbook_resources.py \
  --pid <verified-server-pid> \
  --duration-seconds <run-duration> \
  --output data/benchmarks/live-sermon-translation-v1/runs/macbook-text-baselines/<run-id>/resource-samples.jsonl
```

不得把 PID 示例直接硬编码到正式 run；每次启动后重新解析并核实进程命令。

## 第一轮候选顺序

1. `tencent/Hy-MT2-1.8B` 官方 Q8_0 GGUF，优先验证 Ollama；
2. `xiaomi-research/MiLMMT-46-4B-v1.0`，固定社区转换 Q8_0 GGUF，使用官方纯翻译 prompt；
3. `Qwen/Qwen3.5-4B-Base`，固定 BF16 GGUF 已完成 A0 可比运行；生产量化版另建独立 run；
4. `Qwen/Qwen3.5-9B-Base`，固定 BF16 GGUF 已完成 A0 可比运行；生产量化版另建独立 run。

30B Heretic 继续保留为 DGX 研究对照：即使能够装入 64 GB，也因安全去对齐和生产资格问题不进入 MacBook 生产候选主榜。

## 下一阶段主优化路线

MacBook 下一阶段主模型固定为 `MiLMMT-46-4B-v1.0`。Q8_0 Ollama run 作为未后训练零点；后训练从官方未量化权重开始，不在 Q8 GGUF 上训练。数据记录、`contentText` 规则、LoRA/SFT 路线、MLX 4/5/6/8-bit 与 GGUF Q4/Q5/Q6/Q8 实验矩阵见 [MiLMMT 后训练与 MacBook 优化计划](./milmmt-sermon-post-training-plan.zh.md)。

在 source training rights 与教师输出蒸馏授权解除前，训练数据状态保持 blocked。现有 239 段 `untouched_test` 只做最终验收，不能用于选择模板、训练参数、MLX 后端或量化版本。
