# 本地制作四项提速开发

2026-10-01 用户授权四项并行开发。顶层归属 [DEV-SPD-001／004](backlog.zh.md)，关联 `DEV-L2-001`、`DEV-L3-001`、`DEV-TRACK-001`；本页只展开稳定子项、文件边界与验收，不建立另一套顶层排期。依据为 [Spark 默认策略](local-production-compute-policy.zh.md)和 [时长／GCP 调研](gcp-production-feasibility-20261001.zh.md)。沿用隔离工作分支，原 `dev` 中的无关提交和现有生产产物不变。

| ID | 项目与 Owner | 开发状态 | 写入边界 | 必须交付 |
|---|---|---|---|---|
| `SPD-OPT-01` | Spark 语音批次驻留；语音 worker 开发者 | `component_verified` | legacy Spark speech client/worker、speech backend、screen/align callers 及专属测试 | 一次受限远端调用处理多个冻结输入，模型 hash/load 每批一次，逐单元身份和结果回执；单请求兼容；执行未知不自动重做；真实正反序减少73%–75%，转写相同 |
| `SPD-OPT-02` | Layer 2 有限并发；文字 producer 开发者 | `bounded_sample_measured` | L2 runner/controller、实验并发策略生成／评估入口、专属测试 | 正式Astra/Sol八组/档、48次响应全部返回，worker2/3实测44.96/30.40s；原13响应审计复用，串行恢复段不冒称完整基线；独立$6硬预算，usage费用上界$0.871，账单未核验；整周尚未测 |
| `SPD-OPT-03` | 正式 TTS／回转写批处理；正式音频开发者 | `component_measured_quality_pending` | formal TTS renderer、canonical back-ASR、专属测试 | batch 1/2/4/8 有界、完整单元映射、返回与覆盖检查；生成设置进入身份；batch=1 保持现有格式兼容；缓存命中不重新生成；三语短长句有实测，一处西语回转写待听审；mixed4/8仅引擎诊断 |
| `SPD-OPT-04` | CPU/GPU 重叠与精确续跑；主开发者 | `runtime_correctness_verified_speedup_unproven` | legacy weekly renderer 的 CPU 保存／核验流水线、新有界 helper 和专属测试 | 两端CPU0/1/2真实PCM/cues一致；单 GPU 合成与 CPU 保存/hash 重叠，有界内存／背压、错误传播与 drain；已收据单元不被覆盖；失败后只重做未提交单元；短样本CPU收尾不足0.1s，未证实可重复提速 |

四项可分别开发；整合时按代码依赖合并测试。01 不修改 formal 音频文件；03 不修改 legacy renderer；04 不修改 ASR transport/worker 或 L2。跨项需要接口变化时先给主开发者消息，不并发改同一文件。

## 共用验收

- 可恢复入口默认 Spark，Mac fallback 只用于已确认基础设施故障；内容、身份、审核、损坏缓存和未知远端结果不换机绕过。
- 先冻结输入，缓存绑定 source/text/checkpoint/model/runtime/生成设置；批处理不能丢失 unitId、locale 或旧收据，不把候选输出当正式人审批准。
- 串行与并发／批处理用相同工作量比较；测试验证有界重叠、单模型装载次数、逆序完成仍正确映射、短批、失败／取消、缓存命中、错 hash、未知请求与局部恢复。线程并行的计时 fixture 不冒称 GPU 实测加速。
- 不重新切碎已审自然句、不用变速凑同步，不逐片跳过完整语言包的人审／发布门禁。
- 不重启 Spark 现有服务，不创建 GCP，不恢复已暂停的 180 秒诊断。开发阶段未调用付费 API；随后用户明确授权正式 Astra/Sol 受限小样本，独立48calls/$6预算与账本。真实性能试验使用独立目录与受限资源，单列运行和质量证据。

## 完成证据

`offline_verified` 仅指代码及离线行为通过，不等同实际吞吐或生产部署。顶层 `DEV-SPD-001` 仍为 `in_progress`；[本轮组件验收](local-production-performance-acceptance-20261001.zh.md)已取得正式checkpoint三语短长句、正反序ASR驻留、两端CPU正确性及正式Astra/Sol受限小样本证据。新增56项验收回归通过。TTS听审、10分钟／整周性能和生产rollout仍未完成，不能据短样本改写之前7h15／3h15的整周估算。

| 子项 | 入口与恢复行为 |
|---|---|
| 01 | legacy screen/align 的 `--speech-batch-size 1/2/4/8`，默认 4；一批一次 SSH/Docker/hash/load，逐单元计算和保存。输入上限 8 个、32 MiB，已有缓存不进入推理。`speech-dispatch` 持久化 started/完成单元/最终状态，非阻塞文件锁覆盖派发；started/unknown/failed_invalid 下次先停止。批次内驻留不等同常驻服务，仍需每批启动 |
| 02 | `scripts.experiments.layer2_concurrency freeze/inspect` 只准备／检查独立 workers1/2/3 配置；已有生产 runner 保持有限排队、按源顺序聚合。整批 started marker 预检在任何新增请求前阻止未知结果重放；成功组与返回 raw 仍可局部恢复 |
| 03 | formal renderer 与 back-ASR 均有 `--batch-size 1/2/4/8`，默认 1；固定窗口只生成缺失单元，每批核对数量、索引和身份。TTS 非1使用新 batch/设备/代码/seed/全窗口输入身份；ASR 可用 `--unit-cache` 写不可覆盖逐单元缓存，全部命中不加载模型 |
| 04 | legacy renderer 的 `--cpu-workers 0/1/2`，默认1；`--cpu-queue-batches 1..4`，默认2。GPU 调用仍在主线程，CPU 队列满则背压；所有写入 drain 后流式组装整轨。已有回执不覆盖，多个已诊断坏单元绑定 hash/identity 后逐个进入旧 repair 链 |

离线回归覆盖有界并发、逆序完成、有界背压、短尾批、混合缓存、错误映射、缓存篡改、异常传播、逐单元 commit 及多单元失败恢复。CPU 串行／异步 fixture 生成的 PCM 字节与 cues 相同；Qwen 采样在 missing-only 恢复时批成员可能改变，不宣称与不中断运行的音频逐字节相同。Qwen 高层 API 不返回 EOS/finish-reason，完整返回／可解码／数量匹配不是正常 EOS 的证明，实测需检查截断、回转写和人工听审。

legacy 已验证返回的前缀可保存；只有远端明确终止的基础设施／资源错误才可 Mac 补缺失单元。timeout、断链及未知状态均保留派发记录，需核对远端运行与本地 receipts 后人工对账；本轮没有提供自动清除未知记录的命令，不能删 marker 强行续跑。文件锁只保护带 dispatch_dir 的 caller 路径；直接低层单请求 API 继续原有调用合同，不代称全局常驻服务或统一 Supervisor。

### 离线验证记录

- 01＋04 整合回归 **120 tests**：旧／新 Spark speech、真实 caller 的假模型批次、CPU 队列与 PCM 组装、repair identity、same-video、缓存恢复、执行／导入恢复、会计和 Spark-first TTS，全通过（3.543 秒）。输出中的 candidate 来自 fixture，不是本周制作产物。
- 02 定向回归 **90 tests**：并发实验、生产 runner、leaf accounting、controller、cache recovery、reconciliation、large fan-in，全通过（43.106 秒）。
- 03 完整回归 **52 tests**：formal TTS、back-ASR 及新 batching 回归，全通过（30.253 秒）；两个 CLI `--help` 入口通过。未来已缓存单元的完整质检收据在模型调用前校验，损坏收据不触发任何新增合成。

三组共 **262 项**离线测试，交叉审查发现的多坏单元恢复、未知执行被缓存异常掩盖、未来缓存收据预检问题均已修复并回归。`git diff --check`、17 个变更 Python 文件语法、200 条文档本地链接检查通过。系统 Python 缺少 `jsonschema`，相关测试使用现有项目 `.venv/bin/python`，未安装新环境。

复现三组回归（项目依赖 Python 已配置）：

```sh
PRODUCTION_PYTHON=/absolute/path/to/production-env/bin/python
PYTHONPATH=experiments/sermon-dubbing-poc "$PRODUCTION_PYTHON" -m unittest \
  test_spark_speech_batch test_legacy_speech_batch_callers test_spark_speech \
  test_cpu_render_pipeline test_retry_identity test_same_video \
  test_resume_integrity test_execution_recovery test_remote_import_resume \
  test_weekly_accounting test_spark_first_tts -q
"$PRODUCTION_PYTHON" -m unittest tests.test_layer2_concurrency_experiment \
  tests.test_run_target_language_models tests.test_layer2_leaf_accounting \
  tests.test_canonical_layer2_controller tests.test_canonical_layer2_cache_recovery \
  tests.test_canonical_layer2_reconciliation tests.test_layer2_large_fan_in -q
"$PRODUCTION_PYTHON" -m unittest tests.test_formal_audio_batching \
  tests.test_render_formal_target_language_speech \
  tests.test_screen_target_language_audio_units -q
```

### 新实验入口

使用已安装项目依赖的 Python；系统 `python3` 若没有 `jsonschema` 无法加载四层 producer，不为此额外安装环境。以下路径均为操作员已冻结输入的模板，新实验目录不能已存在：

```sh
PRODUCTION_PYTHON=/absolute/path/to/production-env/bin/python
"$PRODUCTION_PYTHON" -m scripts.experiments.layer2_concurrency freeze \
  --english-source-package /absolute/path/to/english-source-package.json \
  --anchor /absolute/path/to/anchor-manifest.json \
  --policy /absolute/path/to/current-policy.json \
  --plugin /absolute/path/to/language-plugin.py \
  --out-dir /absolute/path/to/new-workers-experiment
"$PRODUCTION_PYTHON" -m scripts.experiments.layer2_concurrency inspect \
  --experiment-dir /absolute/path/to/new-workers-experiment
```

`--group-plan` 可沿用已有审定分组。freeze 不调用 API、不生成批准、不调度收费任务；manifest 中的 `executionArgv` 是后续实验命令。旧 policy 文件不变，worker1 保留同 hash 基线，worker2/3 只改 batching 与其 component hash，各自运行／账本目录隔离，跨策略不共享付费调用缓存。

实际9/27三语的完整frozen experiment已准备在ignored `artifacts/local-production-speed-20261001/layer2-concurrency/{zh-Hans,ko,es}/experiment.json`：419/420/420组，完整计划三种worker均`not_run`。另在`artifacts/local-production-acceptance-20261001/layer2-run/real-3`完成中文原八组/档受限API验收，不能代称完整计划。正式音频参数见[renderer runbook](formal-layer3-renderer.zh.md)；legacy参数见[语音运行合同](../experiments/sermon-dubbing-poc/SPEECH-RUNTIME.zh.md)。

### 下一阶段性能验收

下一次Dev测试已固定[主流程参数与候选对照步骤](local-production-next-dev-test-parameters.zh.md)，并保存[机器可读参数表](../data/benchmarks/local-layer-latency/2026-10-01/next-dev-test-profile.json)：Spark、语音驻留4、文字worker3/group batch1、正式TTS/回转写batch1、legacy CPU1/queue2；随后分别验收TTS2与同WAV回转写1/4/8。参数表当前由操作员传入，runner不自动加载，执行状态`not_run`。

本轮组件实测的cold/warm、load、推理、CPU保存/解码、总墙钟、内存与文字独立预算及质量回执见[验收报告](local-production-performance-acceptance-20261001.zh.md)。先处理西语样本听审，再做10分钟及整周关键路径；一次只改变worker/batch/CPU队列之一。正式默认batch仍1，不切换原冻结音频身份，不启动已暂停诊断；CPU项需更长样本和重复顺序控制后才宣称时间收益，文字完整串行与并发仍需代表性重复实测。
