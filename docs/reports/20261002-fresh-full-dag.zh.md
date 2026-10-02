# 2026-10-02 单一 Fresh 全链 DAG / 统一日志实验合同

## 与历史结果分开

[既有 Source continuation](20261002-cloud-mock-dag-lifecycle.zh.md) 与 [六任务 Source engine](20261002-fresh-source-engine.zh.md) 的成功结果保留为各自的证据，不相加冒充同一次全链执行。

新入口 `sermon_fresh_full_dag.run` 在 intake 前冻结一个完整计划，再由同一个真实 Prefect flow 调度：

`source.preflight → transcription.initial → source.initial → source.alignment → source.package → locale.freeze → text → group mock input/submit/observe/verify/gate → locale join → final.readonly`

当前实验只接纳已校验的 synthetic transport、unchanged alignment fixture、一个或最多两个 mock units。实际模型/API/GPU调用为零；Source alignment 明确为 prior-alignment cache，不称 fresh MFA。Layer4 是只读 synthetic final projection，不创建正式发布包、不授权发布、不代替人工或听辨验收。

## 冻结与资格

- 运行前确定全部节点、group/source-unit membership、原 provider plan、输入/draft/plugin/code hashes、resource policy、明确声明的未来 artifact 路径与 schema
- 未来实际 Source/candidate/WAV hashes 在原 producer 完成后绑定；不得猜测或回填未来产物证据
- 只有一个 durable canonical stream / productionRunId，原 Source预算、时间起点、deadline与最坏成本预留保留
- 复用真实 Source V1叶子，独立 V2 control receipt证明当前验证/落盘；Prefect futures和持久化 task_inputs证明实际调度边
- 每个下游边界重新通过现有 Source gate。Layer2当前候选/对应unit input与原严格review/plugin/receipt链相符，才允许 submit与artifact admission/join
- mock jobs继续使用现有durable job控制；unknown不授权重试，只有原receipt对账或确认失败后的显式同输入选择可前进
- TTS返回实际可解码PCM WAV fixture。hash/bytes/format/typed completion全部通过才进入fixture gate；human/listening/formal/production资格分别保留

## 统一日志的验证方法

沿用 `sermon-workflow-accounting-v3` / `sermon-accounting-log-contract-v1`，不添加未经版本化的新canonical字段。

冻结的layer-map sidecar绑定outer plan、node与实际canonical span/workUnit：

1. Source五个阶段
2. locale.freeze与strict text
3. mock输入、dispatch/received/queued/running/观察/校验/gate
4. locale join与readonly final

真实Source和text业务叶子使用production workKind + synthetic evidenceMode；控制叶子保持control。整次workflow的包含计时单独保存在containerSpans，不能硬分给某一层，更不能与叶子重复计费。

现有summary、logs inspector与weekly report消费者应在同一原始ledger上得到相同的direct receipt数量；重复执行复用原证据，不新增direct model receipt。模型的requested/returned身份分别核验：合成ASR响应没有returned model时保留null，不能补造为请求模型。mock TTS的tokens/cost均为null + not_applicable。

## 必须通过的验收矩阵

真实SDK类为 `ActualFreshFullPrefectTests`，每个场景用两个干净、正常退出的独立进程运行同一冻结计划，不patch代码身份或引擎：

| 场景 | 所需证据 |
|---|---|
| Fresh全图与正常复用 | 首次实际Source2 + text4 synthetic calls / 2 mock jobs；第二次0新增calls/jobs，原产物不变 |
| 已确认单元失败与显式恢复 | 成功邻居保留；失败下游/join阻断；只对选定失败request开1个新attempt |
| 普通observer timeout与对账 | 原unknown保留；只查原job/receipt，完成后0新增calls/jobs |

每个完整成功invocation具有19个实际SDK任务、19条已验证typed observed edges。组件测试使用清洁身份/SDK版本占位只验证控制代码，不算SDK证据。精确运行版本、计数、耗时与CI以对应PR的最终验收记录及保存的run/receipt/hash为准。

## 已执行的本地真实引擎验收

测量提交 `5048daa38567e4f700d58aa450cb12f6642b8bab`，tree `1b976a02b561c946cd112b5a48e48923002d59c0`，Prefect 3.8.7。干净工作树前后未变，三个实际 SDK 场景全部通过（0 skip），unittest 用时 724.476 秒。这是六次完整 invocation 的验收总时长，不是三分钟真实音频的处理速度。独立只读复核在本地测量前确认了完整图、依赖、资格、统一日志与后续 scope guard；组件 5/5 与最后 layer/accounting case 也分别通过。

| 场景 | 两次 invocation 总时长 | 结果 |
|---|---:|---|
| 已确认失败与选定单元重试 | 246.502 秒 | 首次一失败一成功；第二次只开 1 个新 job，成功邻居不变 |
| 完整成功与正常独立进程复用 | 260.474 秒 | synthetic calls 6→0；mock jobs 2→0；原产物不变 |
| 普通超时与原 receipt 对账 | 217.499 秒 | 原 unknown 保留；第二次无新 calls/jobs 后完成 |

保存并只读复核：6 个 flow / 114 个唯一持久化 task records、3 个一致 canonical streams、15 个原 V1 Source leaves、101 个有效 V2 control completions、7 个原 worker jobs（6 成功 / 1 声明故障）及 6 个完整解码、hash 验证的成功 WAV。全部 6 个 invocation workflow 已正常结束；每次 accounting projection 的 hash 对应原 ledger 的精确前缀，optional CI-style copies 与原 run bytes 一致。

每个场景的原 direct synthetic receipt 是 Layer1=2、Layer2=4，重复与恢复不新增调用。故障记录仍让原 logs inspector 保持 needs_attention，不为最后恢复成功抹去历史。脱路径摘要及 result hashes 见 [acceptance-summary.json](../evidence/2026-10-02-fresh-full-dag/acceptance-summary.json)。

这份本地证据属于上述测量提交；后续仅报告/证据变更及 GitHub 发布提交的 exact-head CI 另行记录。当前代码建立在 PR #217 上；只有该依赖正常通过合并门后，才可称 dev 已集成。

## 仍开放

- 当前two-unit资格不证明39或128-unit吞吐/deadline；缩小准入不是可扩展性修复
- 全量ledger byte reread与完整性校验仍可能累计O(N²)，不得用mtime或对象identity豁免事实校验
- controller crash-window / missing-ACK等被阻断的新故障测试仍未执行；不得把正常重启/普通timeout对账等同于这些窗口
- 跨plan changed-text子图迁移、外部Hub/Spark speech与artifact-bytes合同、真实模型质量与生产发布资格仍开放

```sh
python -m unittest tests.test_sermon_fresh_full_dag.FreshFullDAGComponents -v
SERMON_TEST_PREFECT=1 python -m unittest tests.test_sermon_fresh_full_dag.ActualFreshFullPrefectTests -v
```
