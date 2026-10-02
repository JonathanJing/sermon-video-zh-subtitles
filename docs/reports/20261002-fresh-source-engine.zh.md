# 2026-10-02 Fresh Source 引擎接管的有界切片

## 边界

延续 [mock TTS continuation 验收](20261002-cloud-mock-dag-lifecycle.zh.md)，本切片把 `source.preflight → transcription.initial → source.initial → source.alignment → source.package → locale.freeze` 交给真实 Prefect task futures。

本入口只接受现有明确标记的 synthetic transport 和已校验的 prior-alignment fixture；`run_mfa` 必须为 false。实际 ASR / Source / MFA / TTS 调用为零。这个六任务里程碑不含 text、TTS、locale join 或发布接管，结果显式保留 `downstreamEngineTakeover=false`。它与先前从 `source.existing` 开始的 continuation 不能相加冒充同一个已验证全流程。

## 已实现的合同

- Source adapter 将既有 alignment 与 package builders 分为独立调用；原 `prepare_source` 保留相同同步组合和历史 evidence schema
- `FreshSourceStages` 在每一阶段保存不可变的版本化结果，完整验证已完成的 typed causality prefix；不是只看返回容器或推测数组
- Provider completion 仍是实际 provider/receipt-validation leaf。Source response 语义形状校验发生在将 Source-check 节点判为 ready 之前；machine receipt 不升级为 human approval
- 完整既有 Source package 可只读核验并采用其原 package handle，不重做 builder 或回填原 terminal。该 acknowledgement 间隙的新增故障注入覆盖仍未获得验证
- 新 producer extraction migration 精确约束前后 Source 模块 hash，旧 migration/pins 保留；不扩大为任意旧代码豁免
- 运行前冻结全部六任务、原 provider plan、recipe 文件 hash、locale drafts/plugin、声明输出路径和预期 group membership。未来输出的实际 source/anchor hash 只在 producer 完成后绑定，不虚构预计算的产物证据
- 一个 durable canonical stream 贯穿 Source 与 locale freeze，保留原 productionRunId；outer executable-plan SHA 与原 provider-plan SHA 分开绑定
- V1 Source leaves 与 V2 当前结果校验 leaf 分开；SDK task IDs / task_inputs / persisted states / UTC timestamps 可与控制层依赖对应
- 失败结果清除 ready/completion；日志或 durable transition 写入失败直接中止，不能降级为允许下游继续的普通 Source 错误
- 原 provider ledger、截止时间和最坏成本预留继续负责 unknown/retry；引擎不添加自动重试

## 验证矩阵

现有 Fresh/MFA 回归在 stage extraction 基线上 54/54 通过。加入六任务控制器与精确 migration pin 后，普通 stage / controller / compatibility 7/7 通过；这部分替代 clean-code/version 门，不能计作 SDK 证据。

真实 SDK 类 `tests.test_sermon_fresh_source_prefect.ActualFreshSourcePrefectTests` 要求干净已提交 checkout，使用独立正常退出进程，不替代 code identity：

| 场景 | 必须证明 |
|---|---|
| 六任务成功后正常进程重启 | 第一次仅 2 synthetic Source calls；第二次 0 calls、同一计划、原 stage receipts 不变 |
| Source preflight 失败 | 0 provider dispatch；ASR、review、alignment、package、locale 全部阻断 |
| ASR 普通未知结果 | 原 unknown 保留；review、alignment、package、locale 阻断；不推断未执行 |

精确最终 head 的本地运行和 CI 结果以对应 PR 验收记录为准。后续单一 fresh→text→mock TTS outer plan/stream 的独立实现与验收见 [Fresh full-DAG 记录](20261002-fresh-full-dag.zh.md)；它不改写这个六任务历史里程碑。未获验证的 controller crash-window 场景继续留在 backlog。

```sh
python -m unittest tests.test_sermon_fresh_source_stages tests.test_sermon_fresh_source_prefect.FreshSourceEngineComponents tests.test_sermon_completion -v
SERMON_TEST_PREFECT=1 python -m unittest tests.test_sermon_fresh_source_prefect.ActualFreshSourcePrefectTests -v
```
