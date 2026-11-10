# 复盘：20261109-local-tts-ab（Mac M5 Max 与 DGX Spark 的 TTS 速度 A/B）

诊断级组件基准，**不是**正式生产、不是发布验收、不是质量晋级。没有创建 speech job、音频包或发布产物；没有人听审；`releaseEligible=false`。

## 结论先行

- **交付类型**：测试（Layer 3 TTS 组件计时 A/B），不是 `dual_pdf`／`live_session`／`four_layer_release`。
- **最终状态**：`complete_diagnostic`（`outcome.json`）。两臂各完成 32 个 warm trial（8 条件 × 1 预热 + 3 次测量）与 8 个 cold 条件（每条件新进程）。全部输出非空、完整解码通过、单元覆盖与顺序校验通过。
- **结束信号**：Mac 套件打印 `mac suite complete`；Spark 侧 `suite exit=0` 且独占会话 `finish` 返回 `closed`。会话 `tts-ab-20261109` 于 UTC 05:44:25 创建、05:57:36 关闭；关闭后 `inspect` 显示四个受管 unit 全部 `active`、`llama-server` 模型健康 `healthy`、GPU 上重新出现 `llama-server`，`memAvailable` 回升到 80.3 GiB。**服务已恢复**。
- **主要结果**：同一 checkpoint、同一冻结输入清单、同一渲染器身份下，Spark（CUDA BF16）warm 合成总耗时 **77.36 s**，MacBook Pro 14（M5 Max，MPS FP32）**118.44 s**，Spark 约为 Mac 的 **1.53×**；同一批 8 条件逐项为 1.39×–1.69×。两臂总音频秒数几乎相同（172.08 s vs 173.36 s），说明差距不是内容长度造成的。
- **反向项**：模型加载 Spark 明显更慢（30.39 s vs 4.63 s；cold 进程 31–37 s vs 2.4–3.3 s）。小任务（单句）的 cold 首批两者接近，甚至个别 b1 条件 Mac 更快；但一旦进入多句/批量，Spark 稳定领先。
- **证据边界**：两侧运行时不同（Mac torch 2.14.0 MPS FP32；Spark torch 2.13.0a0+8145d630e8.nv26.06 CUDA BF16），所以比值是「硬件＋运行时」差异，不是纯硬件加速比。OS 缓存未清、样本只有一台机器、没有人听审、没有与生产整篇对齐。Spark 测量期间 `llama-server` 等既有服务按独占会话要求被停止，结束后恢复；这不是「服务照常运行」的并发基准。

### warm 合成中位数（秒）与加速比

| 条件 | Mac MPS FP32 | Spark CUDA BF16 | Spark/Mac | Mac RTF | Spark RTF |
|---|---|---|---|---|---|
| zh-Hans-b1 | 17.943 | 11.377 | 0.63× | 1.063 | 0.726 |
| zh-Hans-b2 | 13.471 | 9.653 | 0.72× | 0.872 | 0.612 |
| ko-b1 | 13.694 | 9.386 | 0.69× | 1.031 | 0.729 |
| ko-b2 | 10.736 | 7.696 | 0.72× | 0.860 | 0.576 |
| es-b1 | 10.205 | 6.912 | 0.68× | 1.046 | 0.732 |
| es-b2 | 8.561 | 5.087 | 0.59× | 0.892 | 0.553 |
| mixed-b4 | 26.716 | 15.831 | 0.59× | 0.556 | 0.322 |
| mixed-b8 | 17.119 | 11.415 | 0.67× | 0.368 | 0.238 |

汇总：Mac 合成 118.44 s／音频 172.08 s（0.688 RTF，约 1.45× 实时）；Spark 合成 77.36 s／音频 173.36 s（0.446 RTF，约 2.24× 实时）。

### cold 首批（新进程、未清 OS 缓存）

| 条件 | Mac 加载 s | Mac 首批 s | Spark 加载 s | Spark 首批 s |
|---|---|---|---|---|
| zh-Hans-b1 | 3.28 | 3.59 | 36.96 | 3.91 |
| zh-Hans-b2 | 2.42 | 14.19 | 34.17 | 11.24 |
| ko-b1 | 2.42 | 3.02 | 30.95 | 4.24 |
| ko-b2 | 2.43 | 11.84 | 31.85 | 9.53 |
| es-b1 | 2.51 | 2.64 | 32.33 | 3.36 |
| es-b2 | 2.57 | 8.08 | 35.49 | 6.91 |
| mixed-b4 | 2.45 | 14.09 | 33.55 | 11.80 |
| mixed-b8 | 2.86 | 15.53 | 36.84 | 13.48 |

## 总时间

- 从环境准备到结果落盘约 **30 分钟**：`.venv` 创建与依赖安装约 6 分钟（含 torch 2.14.0、qwen-tts 0.1.1、仓库 requirements），4.2 GB checkpoint 从 Spark 传到本机约 4 分钟，代码/输入暂存约 2 分钟；Spark 独占会话 13m11s（含 warm 353 s、8 个 cold 41–57 s、job/gateway 开销）；Mac 套件约 16.5 分钟；两次「跑起来才发现」的脚本路径错误与重跑约 8 分钟（见错误表）。
- 与上一轮同类运行比较：2026-10-01 组件验收是 Mac M1 Max 与 Spark 的单句 A/B（TTS 7.045 s vs 1.328 s，约 4.5× 代理比），使用当时未加会话门禁的代码、单句与不同 batch 设计。本轮换了 Mac 硬件（M5 Max）、批量条件与当前代码，**1.53× 不能与历史 4.5× 直接相减或排名**；两者只能各自作为其冻结身份的观测值。

## 各层模型、耗时与速度

| 层／阶段 | 模型或后端 | 推理强度／tier | 调用次数 | 计算耗时 | token 或音频秒数 | 速度 | 费用 | 证据 |
|---|---|---|---|---|---|---|---|---|
| L1 来源 ASR | not_run | — | 0 | — | — | — | 0 | — |
| L1 词级对齐（MFA） | not_run | — | 0 | — | — | — | 0 | — |
| L1 英文机器评审 | not_run | — | 0 | — | — | — | 0 | — |
| L2 初译 | not_run | — | 0 | — | — | — | 0 | — |
| L2 独立审核 | not_run | — | 0 | — | — | — | 0 | — |
| 文本质检（回写） | not_run | — | 0 | — | — | — | 0 | — |
| L3 配音（TTS） | Mac：Eric checkpoint／Qwen3-TTS 1.7B，torch 2.14.0，MPS FP32；Spark：同一 checkpoint，torch 2.13.0a0 nv26.06，CUDA BF16 | 固定 temperature 0.7、repetition 1.05、maxNewTokens 768、SDPA、seed 42+窗口起点 | warm 32 trial／条件 8、cold 8 次（每条件新进程）；每臂 160 个 WAV | Mac warm 118.44 s；Spark warm 77.36 s | Mac 172.08 s；Spark 173.36 s | Mac 1.45× 实时；Spark 2.24× 实时（Spark 比 Mac 快 1.53×） | 0（本地 GPU） | `summary.json`、`macbook/warm.log`、`spark/suite.log` |
| L3 回转写筛查（ASR） | not_run（2026-10-28 起已退役） | — | 0 | — | — | — | 0 | — |
| 音频质检 | not_run（仅完整解码检查，非听审） | — | 0 | — | — | — | 0 | `result.json` 内 `fullDecode=pass` |
| L4 构建与发布 | not_run | — | 0 | — | — | — | 0 | — |

模型身份：checkpoint 权重 `75d28ce6022b3df3a72df3dd6dbc01e53f584d685770d60ea04b341920968c9a`，config `9dd6cf2c1b1fdfb1c90dcee20ab81ee5367925bb7a8123b6046af9bce8b2941c`，speaker `eric_geiger`／`eric_pilot`；输入清单 `477271f3d7fa1e46578cfa167ddc1ed52f0a6b396bc22ec9916a6f4b96dde48b`（8 个冻结案例，`releaseEligible=false`）；renderer `78861f56e040905fc654d168fc9bc38db91d41fdc46e639f7b57ced8da44c35e`（两臂相同）。harness 身份不同：Spark 用生产未改文件 `dbcd9bcddfab1b775c2cb9bd41058f957aa12f32e5cc7c133a6d3b4efc216e2c`，Mac 用一行诊断补丁副本 `6fc09092e375ebeb7efdc2d00eb6d4108c7de496110ed15d2f122b12b5ff2eb3`（见「错误」第 3 条与附录）。

资源点观察：Mac 加载峰值 driver allocated 8.52 GB、进程 RSS 5.12 GB（MPS 精确峰值不可得）；Spark CUDA 峰值 allocated 4.18 GB／reserved 4.31 GB、进程 RSS 4.90 GB。

## 错误

| 层／阶段 | 现象 | 原因 | 发现时机 | 处理 | 回归测试 | 提交或 PR |
|---|---|---|---|---|---|---|
| 准备／传输 | `rsync` 立即失败：`unrecognized option --info=progress2` | 本机 macOS rsync 是 openrsync（协议 29），不支持该选项 | 预检（正式传输前） | 改用 `ssh tar -cf - | tar -xf -` 流式复制，4.2 GB 校验后 SHA 与清单一致 | 复制后比对 `model.safetensors`／`config.json` SHA | 仅本地工具脚本 |
| 编排／Spark 派发 | 第一次派发在启动 job 前 `FileNotFoundError: .../artifacts/experiments/spark-tts-memory-ab/spark_runner.py` | 派发脚本 `ROOT` 取了 `parents[2]`（解析到 `artifacts/`），应为 `parents[3]` | 预检（尚未创建 job hold，无 GPU 工作） | 修正 `ROOT`；当时已开的会话立即 `finish`，服务恢复后重开新会话 | 第二次派发 job/容器正常 | 仅本地工具脚本 |
| 编排／Spark 运行时 | 生产 harness 在构造 `QwenSynthesizer` 时 `spark_exclusive_session_required` 失败 | 当前生产 renderer 要求「绑定 Spark 独占会话」的活父进程；2026-10-01 的旧代码没有该门禁 | 占用资源前（容器启动、模型未加载） | Spark 臂改为真实 `begin` → job hold → admission gateway → 容器内跑**未修改**生产 harness → `finish`；Mac 臂无法满足 Spark 会话，改用仅本机的诊断 verifier 补丁并在报告与摘要中列明 | 两臂均完整跑完；Spark 门禁路径为生产代码原路径 | 本报告 |
| 编排／Mac 套件 | 第一次启动立即退出，`artifacts/local-tts-ab-20261109/...` 找不到 | `run_mac_suite.sh` 里 `cd "$(dirname "$0")/../.."` 少一层，落在 `artifacts/` | 预检（无 trial 产生） | 改为 `../../..` 后重跑 | 第二次 `mac suite complete` | 仅本地工具脚本 |

需要补的预检：在「准备 Spark 独占会话并派发容器」的前置检查里加入「派发脚本 `ROOT` 解析出的 `spark_runner.py` 存在」与「生产渲染器是否要求会话门禁」两项；Mac 侧加入「套件脚本的工作目录解析到仓库根」检查。以上四项都属于占资源前可拦截的类型。

## 可以改进的地方

| 类别 | 改进 | 依据（本报告的数值或错误） | 预期收益 | 负责人 | 跟踪 |
|---|---|---|---|---|---|
| 流程／质量 | 让 `benchmark_formal_tts.py` 在非 Spark 主机上有明确的诊断模式（例如显式 `--diagnostic-unbound-session`），而不是让操作员各自打 verifier 补丁 | 第 3 条错误：生产 harness 在 Mac 上必然被门禁拒绝 | 两臂 harness 身份一致，减少「补丁副本」解释成本 | 本地模型开发者 | 待建 backlog |
| 预检 | 把「派发脚本路径/工作目录自检」加入 TTS 基准的新运行检查，或复用 `check_run_start.py --spark-stages` | 第 2、4 条错误，合计约 8 分钟返工 | 每轮省一次失败启动 | 本地模型开发者 | 待建 backlog |
| 速度 | 冷启动差距主要来自 Spark 容器与模型加载（30–37 s），可评估预热常驻或容器预留 | cold 表：Spark 加载 30.95–36.96 s，Mac 2.42–3.28 s | 短任务整篇墙钟收益有限，但对多 locale 串行队列有意义 | Spark 侧 | 待评估 |
| 成本 | 本轮为 0 付费 API；后续若把 A/B 扩到整篇，需要按既有预算合同登记 | 报告与摘要中费用列为 0 | 避免把诊断运行计入生产预算 | 操作员 | — |

## 实际覆盖范围

- 执行：仅 Layer 3 TTS 组件计时（Mac MPS FP32 与 Spark CUDA BF16 两臂，warm 32 trial／臂、cold 8 条件／臂），含模型加载、合成、CPU 转换、WAV 写入与完整解码校验。
- 复用：冻结输入清单 `477271f3…`（8 个已审案例，含 2 个 batch-fill 案例）、Eric checkpoint `75d28…`、生产 `QwenSynthesizer`（Spark 未改；Mac 仅门禁一行补丁）、生产渲染器的 `write_pcm16` 与完整解码实现。
- 未执行：L1、L2、L4；没有 speech job、音频包、发布；没有人听审；没有整篇或整周生产；没有改变任何 `productionEligible` 状态。

## 遗留状态

- Spark 独占会话 `tts-ab-20261109` 已 `closed`，四个受管 unit 与 `llama-server` 已恢复（结束核对：`modelHealth.healthy=true`）。
- Spark 上的暂存目录 `~/dgx-spark-benchmark/results/local-tts-ab-20261109/`（代码、输入、输出含 160 WAV）**保留**，供复核；未删除、未上传。
- 本机 `artifacts/local-tts-ab-20261109/` 内含 4.2 GB checkpoint 与 MPS venv（已被 `.gitignore` 忽略），本轮未清理。
- MacBook Pro 16（arm C）暂存目录 `~/tts-ab-20261109/` 正在准备（仓库快照、清单、harness、checkpoint、venv）；**臂 C 本轮未运行**，因此本轮只有 A/B，不是 ABC。
- 无 Dev 发布、无构建号、无绕过分支保护的推送。

## 外部可见的变化

- 本报告以 docs-only PR 发布到 `docs/reports/runs/20261109-local-tts-ab/`，供云端会话复核；除此之外没有发布、部署、TestFlight 或站点改动。

## 附录：复现命令与 Mac 诊断补丁

仓库提交 `00d8d195d7967aee5ae33fddff42fac2da623437`（`dev`）。输入清单来自 2026-10-01 组件验收的同一冻结文件（`shared-tts.json`，SHA `477271f3…`）；checkpoint 从 Spark 的 `checkpoint-epoch-0` 复制，SHA 校验与 registry 一致。

Mac 臂（MPS FP32，torch 2.14.0）：

```sh
.venv/bin/python artifacts/local-tts-ab-20261109/venv/bin/python  # 该 venv 含 torch/qwen-tts
.venv/bin/python artifacts/local-tts-ab-20261109/tooling/benchmark_formal_tts_local.py \
  --inputs artifacts/local-tts-ab-20261109/inputs/shared-tts.json \
  --checkpoint artifacts/local-tts-ab-20261109/inputs/checkpoint-eric \
  --renderer-root . --device mps --dtype float32 --phase warm --condition all --repeats 3 \
  --out artifacts/local-tts-ab-20261109/macbook/warm-all
```

Spark 臂（真实独占会话 + admission gateway + 未修改生产 harness）：

```sh
export SPARK_EXCLUSIVE_SESSION_ID=tts-ab-20261109 SPARK_EXCLUSIVE_SESSION_OWNER=local-tts-ab
.venv/bin/python tools/ops/run.py compute.spark_exclusive_session begin \
  --session-id tts-ab-20261109 --owner local-tts-ab --minimum-available-gib 96
.venv/bin/python artifacts/local-tts-ab-20261109/tooling/run_spark_suite.py   # 见本地工具脚本（未入库）
.venv/bin/python tools/ops/run.py compute.spark_exclusive_session finish \
  --session-id tts-ab-20261109 --owner local-tts-ab
```

容器命令（由 `spark_runner.py` 在会话 job hold 下执行；镜像、voice site-packages 与 checkpoint 均为既有冻结身份）：

```sh
docker run --rm --gpus all --ipc=host --network none --read-only --user 1000:1000 \
  -e SPARK_EXCLUSIVE_SOCKET=/spark-session-gateway/admission.sock \
  -v "$GATEWAY":/spark-session-gateway:ro -v "$STAGE":/work:rw -v "$CHECKPOINT":/checkpoint:ro \
  -v "$VOICE":/voice-packages:ro \
  -e PYTHONPATH=/work/repo/packages/production/src:/work/repo:/voice-packages \
  -e HF_HUB_OFFLINE=1 -e TRANSFORMERS_OFFLINE=1 --entrypoint /usr/bin/python \
  nvcr.io/nvidia/pytorch:26.06-py3 \
  /work/repo/tools/benchmarks/benchmark_formal_tts.py --inputs /work/inputs/shared-tts.json \
  --checkpoint /checkpoint --device cuda:0 --dtype bfloat16 --phase warm --condition all \
  --repeats 3 --out /work/outputs/warm-all
```

Mac 臂相对生产 harness 的唯一差异（`dbcd9…` → `6fc090…`），仅用于本机诊断，不用于生产：

```diff
-            engine = formal.QwenSynthesizer(checkpoint, device=args.device, dtype=args.dtype, attention='sdpa')
+            # DIAGNOSTIC LOCAL PATCH (not production): operator-run Mac MPS timing harness.
+            engine = formal.QwenSynthesizer(checkpoint, device=args.device, dtype=args.dtype, attention='sdpa',
+                                            session_verifier=lambda: {'diagnosticOnly': True,
+                                                                      'hostRole': 'local-mps-timing'})
```

臂 C（MacBook Pro 16）暂存脚本：`artifacts/local-tts-ab-20261109/tooling/setup_mbp16_abc.sh`——把同一提交快照、同一清单与 checkpoint、同一 harness 文件、Python 3.12 + torch 2.14.0 + qwen-tts 0.1.1 venv 放到 `~/tts-ab-20261109/`。检查 Python 解释器路径后即可按 Mac 臂同一命令运行。
