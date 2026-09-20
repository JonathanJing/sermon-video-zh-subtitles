# 每周配音：MacBook 优先，DGX Spark 后备

生产阅读稿的 MFA 入口见 [MFA 生产说明](../../docs/mfa-production.zh.md)。本目录的 Qwen ASR/ForcedAligner 是配音声学锚点与成品回听筛查，不能替换冻结英文稿，也不能把机器筛查标记为人工验收。

## 运行方式

`run_weekly_dubbing.py` 默认先尝试 MacBook：

```sh
python experiments/sermon-dubbing-poc/run_weekly_dubbing.py \
  --work /absolute/path/to/frozen-job \
  --local-checkpoint /absolute/path/to/same-speaker-checkpoint \
  --local-python /absolute/path/to/qwen-tts-env/bin/python \
  --speech-python "$HOME/.local/share/uv/tools/mlx-audio/bin/python" \
  --remote-checkpoint /home/achillesjing/dgx-spark-benchmark/results/sermon-voice-expansion-20260905/checkpoints/checkpoint-epoch-0
```

默认从仓库 `artifacts/model-routing/macbook-tts/{runtime,checkpoint}` 发现本地运行时和权重；显式参数或环境变量优先。

本地 TTS 使用 `qwen-tts` Torch MPS float32，必须使用与冻结 job 相同 SHA256 的 speaker checkpoint；不会自动替换成其他声音。`SERMON_LOCAL_TTS_CHECKPOINT`、`SERMON_LOCAL_TTS_PYTHON` 是对应参数的默认值。Saturday bridge 配置可设置 `localTtsCheckpoint`、`localTtsPython`、`mlxPython`（旧字段继续作为 MLX Python 路径，输出为 `--speech-python`）。缺少本地 checkpoint 或模型运行环境时，回执记录原因，再使用 Spark CUDA；checkpoint 不匹配、无效音频和语义校验失败直接停止。

MPS 未完成产物留在 `local-render-mps/`；只有完整产物才迁入 `render/`。Spark 重试使用独立的 `render/`，不会拼接 MPS/CUDA 音频。render identity 绑定 device、precision、checkpoint、renderer 代码和生成参数。已有 `render/` 优先恢复其原后端，避免重复生成。

语音检测默认 `SERMON_SPEECH_BACKEND=auto`：MLX ASR/ForcedAligner 优先，缺依赖、缺缓存、设备/内存故障才切换 Spark。可明确选择 `macbook`（失败即停）或 `spark`。两个后端的模型 ID、revision、实际执行位置写入每片段 `inferenceReceipt`；旧模型身份不匹配的缓存不会静默覆盖。Spark 使用官方 Torch 模型，MacBook 使用原 MLX 8bit 模型，不能声称两种数值结果完全一致。

## Spark 连接与隔离运行时

默认通过 `jonyopenclaw@100.73.116.52`（SSH HostKeyAlias `jonys-mac-mini.local`）转接 `achillesjing@192.168.1.152`，使用 Mac mini 上的 Spark SSH 凭据。`SERMON_SPARK_BRIDGE` 设为空仅适用于能直接连 Spark 的机器；`SERMON_SPARK_HOST`、`SERMON_SPARK_BRIDGE_ALIAS` 可覆盖语音客户端路由，TTS 主机使用 runner 的 `--host`。TTS SCP 临时中转目录由 UUID 隔离并清理。

Spark ASR/aligner 在独立 `/home/achillesjing/sermon-speech-runtime` 下安装，容器 `nvcr.io/nvidia/pytorch:26.06-py3` 挂载至 `/runtime`，不修改现有模型服务。venv 用容器内 `python -m venv --system-site-packages /runtime/venv` 创建，安装本次验证的 `qwen-asr==0.0.6`，模型在 `model-cache/`。仅预下载阶段联网，执行设置 `HF_HUB_OFFLINE=1` 与 `TRANSFORMERS_OFFLINE=1`，固定：

- Qwen/Qwen3-ASR-0.6B：`5eb144179a02acc5e5ba31e748d22b0cf3e303b0`
- Qwen/Qwen3-ForcedAligner-0.6B：`c7cbfc2048c462b0d63a45797104fc9db3ad62b7`

`SERMON_SPARK_SPEECH_COMMAND` 可用 argv JSON 指向另一已验证 CUDA 容器命令。每次请求默认 600 秒超时（`SERMON_SPARK_SPEECH_TIMEOUT`），按片段启动进程，当前会重复加载模型，尚未做吞吐优化。响应绑定音频 hash、模型 revision、实际模型文件 hashes、worker hash、依赖版本和 CUDA 设备；连接失败或无效输出不再自动降级到其他模型。

## 2026-09-19 样本验证边界

同一历史 A.wav：MacBook MLX ASR 820 字符、ForcedAligner 150 个词的真实运行成功；Spark CUDA ASR 820 字符、ForcedAligner 150 个词真实运行成功；其中一个词估计时长为零，保留诊断并要求人工复核，不能把该结果称为完整准确对齐。MacBook TTS MPS 使用正式 job 相同的扩展 speaker checkpoint（SHA256 `3b46fc0f5268c3bf14c55c0b11833125fbacc31c6a7ae8b7f1328a227ef8a4d0`），对原已审稿第 55 单元的 10 字样本真实生成 2.56 秒音频，模型加载后的生成计时约 14.16 秒；这不是完整讲道吞吐或音质验收。运行时与 checkpoint 已持久化到共享仓库 ignored `artifacts/model-routing/macbook-tts/`，`artifacts/model-routing/macbook.env` 包含实际本机配置，取证产物在 `artifacts/model-routing/verification/`。整周配音质量、人工听审和移动端验收需要独立进行。
