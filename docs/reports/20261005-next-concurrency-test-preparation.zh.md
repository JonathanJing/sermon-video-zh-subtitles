# 下一轮 605.5 秒并发测试准备

本轮交付代码、离线验证和真实运行前的冻结夹具；准备期间实际模型调用为 **0**，没有调用计费 API、Codex 推理或 GPU 模型。当前 PR 为 #248，目标分支 dev。本轮可开始诊断测试，不能据此判定正式发布或性能提升。

后续新增要求：真实测试／制作前须释放 Spark 竞争负载，整轮开发结束后恢复原服务。见[独占会话设计](../spark-exclusive-development-session.zh.md)。本报告的 ready 仅覆盖既有夹具及依赖预检；新增独占控制尚未实现，采用该要求后的实际开跑需先补齐 exclusive_ready，不能直接据本报告启动。

| 项目 | 已接入的配置与边界 |
|---|---|
| Codex 业务池 | 全部 L2 初译／复核、英文 judge、学习产品共用 23 槽；Luna 监督另保留 1 槽，总共 24。所有新调用使用同一 broker，缓存不占新槽 |
| 同 run 独立分支 | 单一持锁 owner，最多 4 条；依赖满足且证据核验通过才派发。owner 顺序提交，worker 不修改 owner 状态 |
| 来源 ASR | 新 v2 source 配置、预算账本支持 4 路，保留成功片段，未知结果占用预算及槽位；旧配置仍串行 |
| 英文机器复核 | 8 路，GPT-6.1 Sol high fast；固定源稿 114 句、batch15，8 批 |
| 多语言 L2 | zh-Hans、ko、es，3 个活动 locale。业务槽是全局 23，不是每语言各 23 个调用；三语进程可以各有 23 个组 worker，在共享池前等待 |
| 学习产品 | 大纲、默想独立依赖本语言文字，最多 2 条学习产品分支；三语言各有两项，不等待音频完成 |
| 本地配音 | Spark 既有 Eric checkpoint，8 驻留副本 × batch8；三语言 GPU job 顺序执行，与其他语言 L2／学习产品重叠 |
| 回转写 ASR | Qwen3-ASR-0.6B，单模型 batch8；每语言 46 组，共 6 批，不启动 8 个 ASR 模型 |
| CPU | 4 个真实 worker 保存 PCM、完整解码和 hash；有界队列 16 个单元，父进程按源顺序提交 |

初译使用 GPT-6.1 Sol high fast，独立复核使用 GPT-6.1 Sol medium fast，监督使用 Codex Luna medium fast，保留 ChatGPT 订阅认证。开发 API 仍从 `.env.openai` 通过 dev 启动器加载；CLI 不接收 API key，也没有自动 API fallback。本地配置检查和本地模型目录检查通过；没有付费验证当前 provider 权限。

## 固定样本与两条运行路径

母片 SHA `374662dc7c00993820360b2095e277ecd7ebf17bc4d873ccf7e2b76a6c7c7930`，取 63.32–668.820007 秒，共 605.500007 秒。固定夹具保留 **136 anchors、114 源句、46 组／语言**；三语共 138 组，基础 276 次译审调用。学习产品每种每语言 4 批，共 24 次生成调用，监督另计；返修不算在基础调用数中。

Ignored 准备根目录：`artifacts/next-concurrency-605s-20261005-r3/`。最终比较 DAG 的路径以 `command-preparation-final.json` 的 `comparisonDirectory` 为准；早期冻结的 DAG／r2 mock 保留历史证据，不能作为新版执行入口。

- **新转录探针**：`fresh-dag` 执行 4 路来源 ASR → Spark MFA → 新 anchors → 英文 judge8。它报告实际新单元数；不冒用固定夹具的 136／114／46。若后续采用新源稿，须重新冻结三语 policy、经文 span 和分组，旧候选不能自动沿用。
- **固定源稿对比**：最终 comparison DAG 重做英文 judge8，成功后并发三语 L2。judge 的 anchors 必须与固定夹具相同；拒绝、失败或新转录模式不能进入该比较。此路径来源 ASR=0、MFA=0，保留冻结 Source 身份，独立保存新英文复核证据。随后本语言大纲／默想及音频按依赖推进，共 13 个节点。

启示录 4:2–3 的两段原文完整保留，在各语种内绑定 pending 诊断译文片段、字符 span、来源 SHA、组及顺序。经文完整性检查实际执行；这些本地草稿不是经核实的指定圣经版本，不代表人审或引用批准。韩语／西语 Eric 能力仍为 registry 的 `unverified_poc`，只用于本轮诊断；中文已有既定音色身份。候选、学习产品、音频和结果始终 human pending、productionEligible=false，未准备正式发布动作。

## 已完成的验证

三语言固定样本全量 mock：**138 组、276 个新模拟响应**，每语言 136 个源单元精确有序覆盖；每语种实际语言插件检查 230 项通过。共享账本时间区间重算业务峰值 **23**，结束 held=0；恢复新增响应 **0**。所有模拟响应明确 `realModelCalls=false`、`qualityEvidence=false`；这证明链路和资源边界，不证明翻译质量或速度。

离线定向回归覆盖 source4/judge8、旧 source 配置、严格 policy、controller、共享监督槽、四分支 owner、两学习产品分支、依赖、未知结果停止新派发／保存成功邻居、缓存恢复、CPU4、46 组音频 8×8 和单 ASR batch8。各组日志分别保存在本地 `/tmp/tongxing-*-final.log`、`/tmp/tongxing-source-policy-regression.log` 及 ignored artifacts；不是远端 CI 通过的替代证据。旧 Fresh mock 的 `invalid_strict_policy_schema` 源于 v3 API 测试夹具继承新 CLI 默认，已将该历史夹具显式绑定其原 Astra／Sol 模型及 prompt，未放宽生产 schema。

最终定向结果包括 source／policy 129 项、共享池与新诊断链路 44 项、owner 恢复 37 项、并发 owner 37 项、音频 59 项、新 v2 controller 30 项，以及最终准备／监督／Spark wrapper 9 项通过；这些分组有重叠，不相加为独立测试总数。冻结源码后，历史 Fresh 的失败片段重试／成功邻居复用用例再次通过（175.89 秒，日志 `/tmp/tongxing-fresh-stable-code.log`）。本地未安装 Prefect SDK，完整 SDK 干净进程验收未运行；新提交的远端 CI 结果须单独核对。

Spark SSH、GB10、既有两镜像、checkpoint 和 ASR 权重、媒体工具已只读核验。镜像使用绝对 `/usr/bin/python`，避免 MFA PATH 覆盖模型环境；网络关闭，UID1000 读取私有收据。远端代码和 3 份 fixture 共 551 项 SHA 在 CPU-only 环境核验，真实 `load_fixture` 全部通过，没有导入 torch／Qwen 或载入 GPU 模型。最终远端目录和完整命令见 `artifacts/next-iteration-repair-20261005/spark-audio-r3-readiness.json`。音频 preflight 正确报告 `awaiting_layer2`，收到实际候选后还会重新执行当前 candidate admission。

## 执行方式

先检查已有准备，以下命令不调用模型：

```sh
.venv/bin/python scripts/experiments/run_concurrency_preflight.py preflight \
  --out-dir "$(.venv/bin/python -c 'import json; print(json.load(open("artifacts/next-concurrency-605s-20261005-r3/command-preparation-final.json"))["comparisonDirectory"])')"
.venv/bin/python scripts/run_with_openai_environment.py --environment dev --check
```

新来源探针的实际调用命令：

```sh
.venv/bin/python scripts/run_with_openai_environment.py --environment dev -- \
  .venv/bin/python scripts/experiments/run_concurrency_preflight.py run \
  --out-dir artifacts/next-concurrency-605s-20261005-r3/fresh-dag --execute
```

固定源稿完整比较命令（会调用 Codex CLI 与 Spark 本地模型）：

```sh
.venv/bin/python scripts/run_with_openai_environment.py --environment dev -- \
  .venv/bin/python scripts/experiments/run_concurrency_preflight.py run \
  --out-dir "$(.venv/bin/python -c 'import json; print(json.load(open("artifacts/next-concurrency-605s-20261005-r3/command-preparation-final.json"))["comparisonDirectory"])')" \
  --execute
```

另一个终端运行 Luna 只读监督；不接管派发、批准或未知槽释放。最多 24 个观察 turn、间隔 60 秒，结束或异常提前停止；预算耗尽时业务 DAG 可继续，监督状态单独报告。

```sh
.venv/bin/python scripts/experiments/monitor_concurrency_test.py \
  --out-dir "$(.venv/bin/python -c 'import json; print(json.load(open("artifacts/next-concurrency-605s-20261005-r3/command-preparation-final.json"))["comparisonDirectory"])')" \
  --execute --max-turns 24 --interval-seconds 60
```

所有启动脚本默认准备／预检不执行；`--execute` 或音频 `execute` 明确进入实际调用。输出根目录必须为 ignored artifacts；成功恢复核验原输入／输出，未知或 failed 的 node 不自动重发。源码变化会使冻结代码身份失配，需要创建新准备身份，不能覆盖旧调用目录。

## 复盘口径与未完成边界

逐角色记录 input／cached input／output／reasoning token、调用时间和 credit 估算，监督独立统计。usage 未暴露时保留 null，credit 是估算而非账单；并发后的输出 token/run wall 是系统吞吐，不是单模型纯生成速度。还须记录业务槽平均占用、排队／busy、p95、首次 candidate／audio 时间、三语 join、GPU 加载／墙钟、返修及未知数量。

在 8 副本预取模式，音频 manifest 的 `inferenceSeconds` 是 parent 取回结果的等待时间，不能当全部副本累计推理时间；实际副本 generationSeconds 从 `replica-runtime.json` 的 events 读取，阶段墙钟使用 `processWallSeconds`。没有根据 mock 耗时宣称速度提升。

共享池当前有界等待 180 秒，尚未实现公平轮询／任务老化；长任务可能出现 busy，须保留未发送证据而非解释成 provider 失败。正式 strict CLI token／美元硬上限适配、GPU 乱序补窗、跨 job 热驻留和完整生产长队列验收仍在 backlog。现有 formal budget、人审、听审及同步门禁保持有效；本轮诊断不能替代这些门禁。

相关实现：[配置](../../config/benchmarks/next-production-concurrency.json)、[共享池](../../scripts/codex_layer2_resources.py)、[DAG](../../scripts/experiments/run_concurrency_preflight.py)、[新来源](../../scripts/experiments/run_diagnostic_source.py)、[Spark 调度](../../scripts/experiments/run_spark_diagnostic_audio.py)、[设计](../production-concurrency-expansion-design.zh.md)。
