# 20261026 Spark TTS 整篇内存曲线：完整实验数据

本目录是[运行报告](../INDEX.md)对应的实验数据。只含内存、时间和身份数字，不含讲道文本、翻译、音频或模型输出。

## 运行身份

| 项 | 值 |
|---|---|
| 主机 / 会话 | spark-38f8，独占会话 `l3-mem-curve-20261026`（`--preempt --allow-interrupted-restart`，结束已恢复服务） |
| 代码树 | `56c053a5`（dev + #1331 + #1332 + 2026-10-18 术语表，诊断树），远端 staged 为 `repo-56c053a5` |
| 渲染 | 8 副本 × batch 8，seed 42，`release_cuda_cache_expandable_segments_v1`，渲染只到 wav |
| zh-Hans | 10/4 人工批准 job，474 句，job sha256 `1491cea2…`，speaker `eric_geiger`，`maxEndLagSeconds` 62 |
| ko | 10/18 人工批准 job，402 句，job sha256 `33eb47dc…`，speaker `steve_bang_lee`，`maxEndLagSeconds` 240（诊断放宽） |
| 时间 | 2026-10-26 15:03:39Z（lanes 开始）— 15:19:14Z（lanes 结束）；zh 筛查在 15:20–15:22Z 手工重跑 |
| 结论摘要 | zh 60/60 窗最低 62.20 GiB、ko 51/51 窗最低 61.21 GiB，无触线；宿主最低 53.68 GiB（ko 加载与 zh 压缩重叠） |

方法、失败与边界见[运行收据](run-receipt.json) 和 [PR #1396](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/1396) 的报告小节。本次是诊断运行，`releaseEligible=false`、`humanApproval=false`。

## 文件

| 文件 | 内容 | 来源 / sha256 |
|---|---|---|
| `host-samples.jsonl` | 宿主采样器 1 秒一行（MemAvailable、MemTotal、swap、GPU 利用率），已裁剪到本次 lanes 窗口，1197 行 | Spark `memory/host.jsonl` 按 15:02:00Z–结束过滤；sha256 `c661429c…` |
| `replica-runtime-zh-Hans.json` | zh 渲染池的 `replica-runtime.json`：准入、pool_ready、60 个窗口的 MemAvailable/worker reserved、pool_closed | Spark `output/zh-Hans-curve2/speech-job/`；sha256 `d41dcc60…` |
| `replica-runtime-ko.json` | ko 渲染池的同一文件，51 个窗口 | Spark `output/ko-curve2/speech-job/`；sha256 `a7109a9a…` |
| `memory-curve.json` | `memory_curve_report.py` 的汇总：宿主曲线、各 stage 最低值、逐窗摘要、ASR 收据 | 由上面三个文件和 `lanes-report.json` 生成；sha256 `cfb65436…` |
| `memory-curve.svg` | 宿主 MemAvailable 曲线与 stage 时间带 | 同上；sha256 `1d5fbe59…` |
| `lanes-report.json` | `group_tasks.py lanes` 的报告：stage 时间线、1 次重叠、失败状态 | **路径已脱敏**（仓库路径→`<repo>/`，Spark home→`<spark-home>/`）；脱敏后 sha256 `dcb2a605…`，原始文件 sha256 `5f1e2675f739efb44e291129d3f2d7521853f131bc246fb6a40cc16430a676c9` |
| `asr-screening-memory-zh-Hans.json` | zh 回转写筛查的 `*.memory.json`（只有准入和 CUDA 计数） | Spark `output/zh-Hans-curve2-c/speech-job/`；sha256 `ca4ace68…` |
| `run-receipt.json` | 运行身份、输入、参数、失败、ASR 数字和曲线文件哈希 | sha256 `2a6be698…` |

完整 sha256：

```
ca4ace682544679a68740e9d37e6a4986d2597e02696ba9cc34d8da7718d3ab2  asr-screening-memory-zh-Hans.json
c661429ce236be395297ee7d3faa527a88b303013a88fa7881a58009f3115b0e  host-samples.jsonl
dcb2a605b8b777050952c20716dee033ab10e66787c5f786916c82c58887c8ad  lanes-report.json (redacted)
cfb654365f05f92c43077e0f7a22f1ac6d7afbca4b66c026db90250c61495d62  memory-curve.json
1d5fbe590bcd478523c05467c1d21850acdf7b6881d5e352add8b58ba77ccbe6  memory-curve.svg
a7109a9afb9e8f08b15c761b1d1456edbf0db58200f587e5d7d0ae3944e66d8d  replica-runtime-ko.json
d41dcc60241e33fa11bb1f2cb1cacd486f8343283b610594afbae608525ca7d1  replica-runtime-zh-Hans.json
2a6be698236572d939de7b24bd4f0f6a4cf555477f2bf1999cf1a9b927ce4d79  run-receipt.json
```

## 复算

在 Spark 或本机仓库根目录（`experiments/spark-tts-memory-full-episode/` 在 PR #1396 分支）：

```sh
python3 experiments/spark-tts-memory-full-episode/memory_curve_report.py \
  --samples host-samples.jsonl \
  --lanes-report lanes-report.json \
  --runtime zh-Hans=replica-runtime-zh-Hans.json \
  --runtime ko=replica-runtime-ko.json \
  --asr-memory zh-Hans=asr-screening-memory-zh-Hans.json \
  --out /tmp/memory-curve-check
```

输出的 `memory-curve.json` 应与本目录文件一致（`lanes-report.json` 用脱敏版时，stage 行和宿主摘要不变）。

## 不包含

- 讲道文本、翻译、ASR 转写、音频和渲染产物；ASR 的完整筛查收据（含转写）留在本机 `artifacts/`，没有复制。
- `llama-server` 的模型或显存峰值：GB10 的 `nvidia-smi` 显示 N/A。
- 发布材料或人工批准；本运行没有发布意图。
