# 复盘：20261121-mac-tts-offload-verification

## 结论先行

交付类型：**测试／验证**（`component_verification`），不是生产发布，也不签发任何音频接受。日期 2026-11-21，America/Los_Angeles。三台机器：Spark（退役候选主机）、mbp16（M1 Max 64 GiB）、mbp14（M5 Max 36 GiB）。机器只写代号，不写私有地址。

1. **Spark → mbp16 备份完成，哈希核对一致。** A 集合 16 GiB：`sentence-first-agent` 62 个 run 目录、`spark-agent` 全量（含 `.git` 与未提交快照）、benchmark 证据目录、`sermon-speaker-clips-20261001-v2`、`sermon-live-training/runs`。B 集合 39 GiB：7 位讲员的 Qwen3-TTS checkpoint。逐个 `model.safetensors` SHA-256 与 Spark 原文件相同（`3f722b17…`、`3b46fc0f…`、`75d28ce6…`、`480bc27e…`、`010b54bc…` 等）。
2. **mbp16 可按 sentence-first 生产路径出音频。** `tts_sentences.py --device mps --dtype float32 --batch-size 8 --seed 7`，checkpoint `75d28ce6…`：120 句 15 批，合成墙钟 344.2 秒、音频 424.1 秒、RTF **0.812**，MPS driver 峰值 16.29 GiB，`MemAvailable` 全程约 26 GiB 未下滑。8 句冒烟 25.177 秒／25.76 秒。
3. **mbp14 运行时可用，但默认内存门限未通过。** 环境为 CPython 3.12.16、torch 2.14.0、qwen-tts 0.1.1、transformers 4.57.3、numpy 2.5.4，checkpoint `75d28ce6…` 校验通过。门限检查三次读数 11.6／15.0／15.3 GiB，低于脚本在 36 GiB 机器上的 **20 GiB** 要求（Chrome 单进程约 8 GB）。只有显式把门限降到 12 GiB 的诊断运行完成 2 句 batch 1（RTF 1.00／0.92，运行中可用内存降到 9.0 GiB）。**判定：mbp14 现况不具备该生产门限，必须先腾出 ≥20 GiB（退出 Chrome 或重启）再按默认门限开工。**
4. **两台 Mac 不是同一执行身份。** 同一 checkpoint、seed=7、batch=1、`mps`、float32 下，mbp16 与 mbp14 的 WAV 字节不同（`de88acd9…`／`9c2b3335…` vs `1c3ff062…`／`787a1f07…`），时长完全一致（3.28／8.32 秒，24 kHz 单声道 16-bit）。MPS 输出随芯片架构变化，不能把两台机器的 WAV 拼成同一条正式音轨。
5. **正式 Layer 3 renderer 仍只认 CUDA 8×8。** `audio/renderer.py` 的准入要求 `batchSize=8 and device="cuda:0" and dtype="bfloat16"`；Mac 上目前只有 sentence-first 线有实测证据，正式 renderer 走 MPS 需要另立执行身份与验收。

## 总时间

- 备份：A 集合约 2 分钟（16 GiB）、B 集合约 6 分钟（39 GiB），局域网直连，另加一次 root-only checkpoint 经容器导出。
- 运行时：mbp16 复用既有 venv（约 0 分钟安装）；mbp14 新建 venv 并装 torch 2.14.0＋qwen-tts 0.1.1 约 8 分钟（含一次 Python 3.15 失败重来）。
- 冒烟与正式规模：8 句 25 秒；120 句 344 秒；诊断 2 句 17 秒。**不含**整期 460 句、压缩、排程、整轨听审。

## 各层模型、耗时与速度

| 机器 | 路径 | 硬件 | 运行时 | 句子 | batch | 墙钟 | 音频 | RTF |
|---|---|---|---|---|---|---|---|---|
| mbp16 | `tts_sentences.py` | M1 Max 64 GiB | torch 2.14.0, Python 3.12.8, MPS/float32 | 120 | 8 | 344.2 s | 424.1 s | 0.812 |
| mbp16 | 同上（冒烟） | 同上 | 同上 | 8 | 8 | 25.177 s | 25.76 s | 0.977 |
| mbp14 | 同上（诊断，门限 12 GiB） | M5 Max 36 GiB | torch 2.14.0, Python 3.12.16, MPS/float32 | 2 | 1 | 10.96 s | 11.60 s | 0.95 |
| Spark（历史基线） | `spark_run.sh` + `tts_sentences.py` | GB10 | torch 2.13, CUDA/BF16 | 460 | 8 | 382.9 s | 1819.8 s | 0.210 |

Spark 行来自 2026-11-08 生产记录（[云 TTS 速度对照](../../deepseek-tts-speed-ab-20261114.zh.md)），不是本轮复跑。本轮的 120 句来自播客 zh 字幕包的 Eric 台词，不是整期。

## 错误与本轮修正

- **mbp14 首次建 venv 用了 Homebrew Python 3.15**，`qwen-tts` 依赖的 `onnxruntime` 没有该解释器轮子，直接失败。改用 uv 的 CPython 3.12.16 重建后通过。
- **PyPI 上没有 torch 2.14.0**（只有 2.15.0）。改用 PyTorch 官方 wheel 源固定 `torch==2.14.0`，与 mbp16 对齐。
- **John Thomas checkpoint 是 root 拥有、`-rw-------`**，用户态 rsync 无法读取；经其既有容器以只读挂载导出后哈希核对为 `3f722b17…`。
- **mbp16 第二次加载模型被门限拒绝**（19.3 GiB 可用）：当时 120 句任务仍持有模型，说明双副本并发在 64 GiB 上也不宽裕。
- **SoX 未安装**：`qwen-tts` 导入时提示，本轮不影响 WAV 生成与解码。

## 可以改进的地方

1. mbp14 的生产使用需要一条「先确认 ≥20 GiB 再开跑」的显式步骤（或把浏览器移到另一台机器），否则每次都要人工清理内存。
2. 两台 Mac 需要各自冻结执行身份（芯片＋torch 版本＋checkpoint 哈希），正式 run 的收据里不能只写「mac mps」。
3. `tts_sentences.py` 的门限提示可以区分「batch 8 生产」与「batch 1 诊断」，避免为了冒烟而降门限的操作被误当成生产开跑。
4. 正式 renderer 若要在 Mac 上跑，需要独立的 device/dtype 准入分支与对应验收，不能直接复用 `--spark-production`。

## 本轮未做

整期 460 句合成、压缩、排程、整轨人工听审、任何发布或部署；Spark 服务停止、磁盘删除、凭据轮换；mbp16 上的 `spark-agent` 迁移。以上均需单独授权与证据。

## 证据与位置

- 备份根：mbp16 `~/Backups/spark-offload-20261121/`（`A-only-copy`、`B-checkpoints`、`manifests/`，含 `backup-A.log`、`backup-B.log`、`spark-agent-WIP-20261121.txt`）。
- 运行时：mbp16 `~/tts-runtime/{venv,checkpoint-75d28}`（venv 指向 `~/tts-ab-20261109/venv`）；mbp14 `~/tts-runtime/{venv,checkpoint-75d28}`，并已链接到仓库 `artifacts/model-routing/macbook-tts/` 的文档路径。
- 输出：`~/tts-runtime/smoke/{mbp16-b8-zh,mbp16-b8-zh-120,mbp16-b1-zh-2,mbp14-diag-b1}`（含 `tts-log.jsonl`）。

## 同日后续：Spark 退役与清理（2026-11-21 下午）

用户在同一天确认：A 集合里有用的部分提交 PR、其余可删；D 里所有服务可清理；Spark 直接退役；磁盘各层都删。以下是实际执行与结果。

**保留进 Git 的两份证据**：本仓 PR #1611 收录 `experiments/sentence-first-agent/spark_tts_koes.sh` 与 `unbind_removed.py`（本轮前只存在于 Spark）；`spark-agent` 的未提交工作以快照分支 `recovered/spark-wip-20261121` 推到其仓库（draft PR #13，提交 `288250d`），不包含 `.env`、state 与日志。

**服务退役**：停止并禁用 `spark-agent`、`spark-api`、`llama-server`、`llama-performance-collector`、`llama-fable-sidecar`、`h3-image-studio`、`tensorfold-flashnext`、`job-reasoning-review.timer`、`kimi-k3-p32-p33-parallel`；41 个 unit 文件打包进备份后删除；crontab 的 dashboard 任务删除。停止后 `MemAvailable` 从 71 GiB 升到 118 GiB，GPU 占用归零，8000／7070 端口关闭。mbp16 上两个从 Spark 拉取状态与 digest 的 LaunchAgent 在最后一次同步成功后卸载并归档。

**磁盘清理**：删除实验室目录、模型库与 HF 缓存、本项目产物后，`/` 从 2.9 T 已用降到 **155 G 已用**（3.4 T 可用，5%）。多项首次 `rm -rf` 因容器写出的 root 属主文件失败，改由只读挂载的 root 容器删除；journal 清到 0 B；Docker 镜像／容器／构建缓存清空。仍保留 `account-video-transcript-collector`（15 G，非本轮范围）。

**凭据**：`~/.config/tongxing/openai.env` 与 `spark-agent/.env` 随目录删除；`~/.docker/config.json` 内的 ghcr PAT 已删；GitHub deploy key「DGX Spark spark-agent」（id 158812632）已通过 API 吊销。**这些密钥仍需在各自平台轮换**——删除文件不等于吊销。

**访问状态（如实记录）**：清空 `~/.ssh/authorized_keys` 之后，Spark 的 SSH 对两台 Mac 都不再可用（`Permission denied (publickey,password)`）。这与退役方向一致，但剩余约 20 G 与整机擦除必须到机器控制台执行；恢复远程访问只需在控制台追加两台 Mac 的公钥。

**未做**：整机擦除／交还、磁盘取证级抹除、Tailscale 节点移除（该机已无 `tailscale` 命令）、mbp14 按默认门限的正式复跑。
