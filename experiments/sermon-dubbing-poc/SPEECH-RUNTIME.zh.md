# 每周配音：DGX Spark 默认，MacBook fallback

生产阅读稿的 MFA 入口见 [MFA 生产说明](../../docs/mfa-production.zh.md)。本目录的 Qwen ASR/ForcedAligner 是配音声学锚点与成品回听筛查，不能替换冻结英文稿，也不能把机器筛查标记为人工验收。

## 运行方式

2026-10-01 起，`run_weekly_dubbing.py` 新任务默认先尝试 Spark，MacBook 作为 fallback；已有 render 继续原设备恢复，不因默认值改变重算。`--tts-backend auto`／`SERMON_TTS_BACKEND=auto` 为默认，`spark`／`macbook` 为强制选择。全项目边界见[计算策略](../../docs/local-production-compute-policy.zh.md)。

```sh
python experiments/sermon-dubbing-poc/run_weekly_dubbing.py \
  --work /absolute/path/to/frozen-job \
  --tts-backend auto \
  --local-checkpoint /absolute/path/to/same-speaker-checkpoint \
  --local-python /absolute/path/to/qwen-tts-env/bin/python \
  --speech-python "$HOME/.local/share/uv/tools/mlx-audio/bin/python" \
  --remote-checkpoint /home/achillesjing/dgx-spark-benchmark/results/sermon-voice-expansion-20260905/checkpoints/checkpoint-epoch-0
```

fallback 默认从仓库 `artifacts/model-routing/macbook-tts/{runtime,checkpoint}` 发现本机运行时和权重；显式参数或环境变量优先。两端均须事先配置，本次策略不自动部署运行环境。

MacBook TTS 使用 `qwen-tts` Torch MPS float32，必须使用与冻结 job 相同 SHA256 的 speaker checkpoint；不会自动替换成其他声音。`SERMON_LOCAL_TTS_CHECKPOINT`、`SERMON_LOCAL_TTS_PYTHON` 是对应参数的默认值。Saturday bridge 配置可设置 `localTtsCheckpoint`、`localTtsPython`、`mlxPython`（旧字段继续作为 MLX Python 路径，输出为 `--speech-python`）。Spark 的明确环境／资源故障在核对远端已结束后，auto 才可回本机；checkpoint 不匹配、无效音频和语义校验失败直接停止。SSH 执行中断、timeout 或未知远端结果先 reconcile，不能启动第二份本机计算。

MPS 未完成产物留在 `local-render-mps/`；只有完整产物才迁入 `render/`。Spark 重试使用独立的 `render/`，不会拼接 MPS/CUDA 音频。render identity 绑定 device、precision、checkpoint、renderer 代码和生成参数。已有 `render/` 优先恢复其原后端，避免重复生成。

语音检测默认 `SERMON_SPEECH_BACKEND=auto`：Spark ASR/ForcedAligner 优先，明确基础设施／运行资源故障才切换 MacBook MLX。可明确选择 `macbook` 或 `spark`，强制模式失败即停。两个后端的模型 ID、revision、实际执行位置与 fallback 原因写入每片段 `inferenceReceipt`；旧模型身份不匹配的缓存不会静默覆盖。Spark 使用官方 Torch 模型，MacBook 使用原 MLX 8bit 模型，不能声称两种数值结果完全一致。

## Spark 连接与隔离运行时

默认通过 `jonyopenclaw@100.73.116.52`（SSH HostKeyAlias `jonys-mac-mini.local`）转接 `achillesjing@192.168.1.152`，使用 Mac mini 上的 Spark SSH 凭据。`SERMON_SPARK_BRIDGE` 设为空仅适用于能直接连 Spark 的机器；`SERMON_SPARK_HOST`、`SERMON_SPARK_BRIDGE_ALIAS` 可覆盖语音客户端路由，TTS 主机使用 runner 的 `--host`。TTS SCP 临时中转目录由 UUID 隔离并清理。

Spark ASR/aligner 在独立 `/home/achillesjing/sermon-speech-runtime` 下安装，容器 `nvcr.io/nvidia/pytorch:26.06-py3` 挂载至 `/runtime`，不修改现有模型服务。venv 用容器内 `python -m venv --system-site-packages /runtime/venv` 创建，安装本次验证的 `qwen-asr==0.0.6`，模型在 `model-cache/`。仅预下载阶段联网，执行设置 `HF_HUB_OFFLINE=1` 与 `TRANSFORMERS_OFFLINE=1`，固定：

- Qwen/Qwen3-ASR-0.6B：`5eb144179a02acc5e5ba31e748d22b0cf3e303b0`
- Qwen/Qwen3-ForcedAligner-0.6B：`c7cbfc2048c462b0d63a45797104fc9db3ad62b7`

`SERMON_SPARK_SPEECH_COMMAND` 可用 argv JSON 指向另一已验证 CUDA 容器命令。一次受限调用默认 600 秒超时（`SERMON_SPARK_SPEECH_TIMEOUT`）。`screen_weekly_audio.py` 与 `align_weekly_source.py` 提供 `--speech-batch-size 1|2|4|8`／`SERMON_SPEECH_BATCH_SIZE`，默认 4；每批最多 8 个输入、32 MiB 音频，一次 SSH/Docker/权重 hash/模型加载，随后逐单元计算并输出回执。这是批次内驻留，不是长期常驻服务。单请求接口保持兼容。响应绑定音频 hash、模型 revision、实际模型文件 hashes、worker hash、依赖版本和 CUDA 设备；auto 仅在可归因且无未知远端执行结果的基础设施故障时回 MacBook，无效输出不换机绕过。

两个 caller 在模型启动前检查 `speech-dispatch/batch-<hash>.json`。派发以非阻塞文件锁保护并持久化 started、已保存单元及 complete/confirmed_terminal/unknown/failed_invalid 状态；已确认终止的资源失败允许补缺失单元，未知、正在执行或无效结果则下次先停止。timeout/断链中已验证的前缀保留，但剩余不能自动重派，必须核对远端和现有收据后对账；不要删除记录强制恢复。低层 `generate` 单请求仍沿原合同，不声称已成为统一跨机调度器。

legacy `render_weekly_audio.py` 维持 `--batch-size 4` 默认；新增 `--cpu-workers 0|1|2`（默认 1）及 `--cpu-queue-batches 1|2|3|4`（默认 2）。模型调用保持单线程，输出 buffer 复制后交给有界 CPU 队列保存、验证及 hash，队列满时等待；所有写入 drain 后才流式组装整轨和写完成报告。已有有效回执单元不重新合成，全缓存组装不加载 TTS 模型；异常保留诊断，已确认的多个坏单元可由原有限 repair 流程逐个恢复，未知未收据音频仍须检查。代码变化进入 render identity，旧缓存需原版本恢复或独立新运行，不能静默跨身份复用。具体开发和性能边界见[提速 backlog](../../docs/local-production-speed-backlog.zh.md)。

## 2026-09-19 样本验证边界

同一历史 A.wav：MacBook MLX ASR 820 字符、ForcedAligner 150 个词的真实运行成功；Spark CUDA ASR 820 字符、ForcedAligner 150 个词真实运行成功；其中一个词估计时长为零，保留诊断并要求人工复核，不能把该结果称为完整准确对齐。MacBook TTS MPS 使用正式 job 相同的扩展 speaker checkpoint（SHA256 `3b46fc0f5268c3bf14c55c0b11833125fbacc31c6a7ae8b7f1328a227ef8a4d0`），对原已审稿第 55 单元的 10 字样本真实生成 2.56 秒音频，模型加载后的生成计时约 14.16 秒；这不是完整讲道吞吐或音质验收。运行时与 checkpoint 已持久化到共享仓库 ignored `artifacts/model-routing/macbook-tts/`，`artifacts/model-routing/macbook.env` 包含实际本机配置，取证产物在 `artifacts/model-routing/verification/`。整周配音质量、人工听审和移动端验收需要独立进行。
