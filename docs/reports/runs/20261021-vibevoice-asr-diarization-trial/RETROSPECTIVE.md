# 复盘：20261021-vibevoice-asr-diarization-trial

数据见同目录 INDEX.md 和 manifest.json。

## 结论先行

- 交付类型：**测试**（说话人区分模型试跑），不属于 `dual_pdf`、`live_session` 或 `four_layer_release`，不进入任何生产层。`productionEligible=false`，`humanApproval=false`，转写结果没有人审。
- 状态：两次运行都 **succeeded**，均正常结束（`eos_or_max`），没有触发防重复保护。
- 结果：同一份 40 分 12 秒的音频，两次运行都识别出 2 个说话人。以 Spark BF16 为参照，Mac 8bit 的说话人标签逐帧一致率为 99.66%（双方都判为有语音的 2389.6 秒内），只有 1 段超过 1 秒的不一致；文字差异约 0.85%（7882 词对 7867 词）。
- 证据边界：说话人名字没有核实，开场几句的归属看起来不一致，需要人工听一遍。Spark 跑的时候 GPU 上同时驻留着 llama-server，所以 Spark 的速度不是单独测得的基准。转写文字和媒体都不在本报告里。

## 总时间

墙钟 41m19s，按 outcome.json 算（Mac 第二次运行开始到 Spark 运行结束），两台机器的大部分时间是并行的。

- Mac MLX 8bit：1206.8 秒（约 20 分钟），约 2.0× 实时。
- Spark CUDA BF16：1834.7 秒（约 31 分钟），约 1.3× 实时。
- 返工：Mac 第一次运行因缺少 `jinja2` 失败，失败前已用掉约 5.5 分钟（下载 131 秒 + 编码 197 秒）。见下方「错误」。

这是第一次跑同类试验，没有上一轮可以比较。

## 各层模型、耗时与速度

本次不是生产运行，L1–L4 都是 not_run。这次试跑最接近的生产阶段是「L1 来源 ASR」，按那一行填：

| 层／阶段 | 模型或后端 | 推理强度／tier | 调用次数 | 计算耗时 | token 或音频秒数 | 速度 | 费用 | 证据 |
|---|---|---|---|---|---|---|---|---|
| L1 来源 ASR（试跑，Mac） | `mlx-community/VibeVoice-ASR-8bit`，mlx-audio 0.6.1，M1 Max 64 GB | 贪心解码，最多生成 32768 个 token | 1 | 1206.8 s（加载 14 / 编码 129.4 / 读入提示词 115.9 / 生成 1063.4） | 2412 s 音频；提示词 18156 + 输出 16196 个 token | 输出 17.1 token/s；2.0× 实时；内存峰值 32.25 GB | 0（本地） | `run-evidence/vibevoice-trial-receipt.json` |
| L1 来源 ASR（试跑，Spark） | `microsoft/VibeVoice-ASR` BF16，sdpa，GB10，`sermon-pytorch-ffmpeg:20260927` | 贪心解码，最多生成 32768 个 token | 1 | 1834.7 s（加载 106.5 / 编码和读入提示词 90.8 / 生成 1726.4） | 2412 s 音频；提示词 18153 + 输出 16338 个 token | 输出 10.0 token/s；1.3× 实时；已分配峰值 24.62 GB（预留峰值 30.14 GB） | 0（本地） | 同上 |
| 其余各层 | not_run | | | | | | | |

## 错误

| 层／阶段 | 现象 | 原因 | 发现时机 | 处理 | 回归测试 | 提交或 PR |
|---|---|---|---|---|---|---|
| Mac 试跑 | 音频编码完成后，在 `apply_chat_template` 报 `ImportError: jinja2` | mlx-audio 0.6.1 没有把 transformers 拼提示词所需的 `jinja2` 列为依赖 | 占用资源后（约 5.5 分钟） | 补装 `jinja2`，先用 20 秒片段跑通整条流程，再重跑全篇 | 20 秒片段试跑 | 无（临时环境） |

应补的预检：长音频运行前先拿 20 秒片段跑通完整流程。

## 可以改进的地方

| 类别 | 改进 | 依据（本报告的数值或错误） | 预期收益 | 负责人 | 跟踪 |
|---|---|---|---|---|---|
| 预检 | 长音频试跑前先跑 20 秒片段 | jinja2 缺失是在编码完 40 分钟音频之后才暴露的 | 少浪费约 5 分钟 | 执行试跑的 agent | 无 |
| 速度 | GPU 上没有其他驻留进程时，在 Spark 上重测；再测一次 flash_attention_2 | Spark 每秒只出 10 个 token，比 Mac 8bit 的 17.1 个还慢；上游 issue microsoft/VibeVoice#340 也反映 Spark 偏慢 | 弄清楚慢是因为和 llama-server 抢资源，还是 GB10 本身就慢 | 待定 | 无 |
| 质量 | 人工核对开场几分钟的说话人归属，确认说话人 0、1 分别是谁 | 开场几句的归属看起来不一致 | 确认说话人区分能否用于下游 | 用户 | 无 |

## 实际覆盖范围

- L1：没有生成正式的 L1 产物。只有两次试跑转写（`raw.txt`、`segments.json`），保存在被忽略的 `tmp/diarization/` 里，没有冻结，也没有绑定到任何 L1 身份。
- L2、L3、L4：not_run。

## 遗留状态

- Mac：`tmp/diarization/if-i-had-more-time/` 下的 WAV、转写和日志（被 Git 忽略）；临时 venv 在会话 scratchpad 里；HF 缓存里多了 `mlx-community/VibeVoice-ASR-8bit`（约 9.5 GB）。
- Spark：`~/diarization-eval/`，包括 VibeVoice 代码、音频副本、pip user 目录和结果；HF 缓存里多了 `microsoft/VibeVoice-ASR`（约 17.3 GB）。容器 `vv-full` 已退出（运行时加了 `--rm`）。没有改动任何服务，llama-server 一直在运行。

## 外部可见的变化

没有。没有 Dev 发布、TestFlight 或受保护分支推送，均为 not_run。本报告 PR 只包含文档。
