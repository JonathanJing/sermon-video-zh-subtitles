# 2026-10-02 云端 mock TTS / DAG 生命周期实现记录

## 范围与基线

从 `dev@84e9d71d24ae86170efbb4c57755246f369ec9d9`（PR #210 合并）开始。该提交的 push CI `36974563854` 通过；干净工作树真实 Prefect 回归 3/3 通过。本实现随后正常集成 `dev@8a645e9f2572baaf98e22aaf0efc149be60e9958`，保留 PR #212 CI 路由 / 分片和 PR #213 本地日志 adapter。

本轮只在云端实现代码、离线夹具和真实本地 Prefect 引擎监管。TTS 输出为确定性、可解码的 PCM WAV fixture，不生成语音，不加载模型，不调用真实 provider/GPU，不部署设备、不发布生产页面。控制批次明确为 `independent_unit_jobs_v1`，不等于正式 TTS 的整窗口声学 batch，也不改变 PR #211 的正式 batch 恢复语义。

本记录区分三个里程碑：

1. `source.existing` 之后，真实 Prefect + 原有 strict text callbacks + durable mock TTS jobs / gates / joins 的 continuation 验收
2. 将 Fresh Source 五个真实阶段交给冻结 executable plan 与引擎逐阶段监管的 synthetic 验收
3. 实际 ASR / Source / MFA / TTS 的独立真实计算与质量验收

第一个里程碑不能代替后两个，mock 通过也不关闭完整 `DEV-DIAG-017` / `DEV-SPD-006`。

## 实现组成

- 沿用 canonical `sermon-workflow-accounting-v3` / `sermon-accounting-log-contract-v1`。新增 opt-in durable controller stream / keyed delivery sidecar；不改写旧合同事件。逻辑 run / producer / workflow 绑定跨正常重启保持，序号从原 ledger 与 pending facts 的已验证并集分配；相同 delivery key + intent 复用原 eventId、时间和事实，冲突拒绝。
- 新显式 stage outcome 支持 `completed` / `failed` / `outcome_unknown` / `cancelled`。事实发生处冻结 completedAt 和 monotonic end；profile 保留该时间。未显式完成不默认为成功。v1 Source completion 兼容保留；v2 synthetic completion 绑定真实 terminal、artifact、job、revision、attempt 和 evidenceMode。
- 固定 mock worker 通过现有 `sermon_workflow_jobs` 提交。launcher 在进程启动前清理环境，传递冻结 request hash 和 allowlisted accounting context。worker 验证 scope、policy、intent、输入绑定与代码身份，实际产生 received / queued / running / returned 或确认失败证据及有效 WAV。
- 控制器分别记录物理 job 状态、observer outcome 和 artifact / fixture admission。未知结果不重发；reconcile 只读取原 job、receipt、事件和 bytes。失败、旧观察和终态不覆盖；成功单元在重复调用中只读核验原证据。
- 校验与 fixture gate 使用独立 typed control leaves。fixture gate 只表明合成 bytes / hash / decode 等检查通过；human/listening 仍 pending 或 not_performed，formal audio / production / publication 均不合格。

## 已执行的组件证据

- 共享日志支持回归 132 tests 通过，覆盖既有 accounting / strict contract / replay / timeline / export，以及新增 durable stream、显式 outcome、v2 completion 与有界内容校验 cache。旧行为仍有独立回归。
- 实际 detached worker + client 初始 8 tests 通过。增加真实 verify/gate 正例后 9 tests 通过，覆盖普通成功、重复 key 零重新派发、显式 worker failure、有效 WAV、missing / invalid / hash mismatch 拒绝、普通 observer timeout 后原 receipt 对账，以及确认失败单元重试时成功邻居复用。
- 独立只读复核识别了 request 在 intent 后变化、成功 receipt 未绑定原 worker workload、observer receipt/terminal/state 的恢复间隙、worker completion acknowledgement 缺失和 frozen code closure 不完整。相应代码补强采用冻结 argv request hash、原 workload receipt hash、独立恢复 observer、新控制器派生证明及完整 closure；不得把后补证明写回成旧 worker 原事件。

- DAG 组件初始 6 tests 通过（553.019 秒）；最终核心代码下的显式失败单元恢复与普通 unknown 对账 2/2 通过（535.123 秒）。前者在第二次调用只派发失败单元的新 attempt，成功邻居保留原 job，text cache 增量调用为零；后者保持未知观察、拒绝未知重试，并通过原 receipt 对账恢复。组合 delay 上限 / 成员校验 2 tests 另行通过。组件测试替代了 clean-code identity 检查，因此不计作真实 SDK 验收。

## 真实 Prefect 验收（测量提交 `50608e8`）

干净工作树、独立正常退出的子进程、实际 Prefect 3.8.7：3/3 tests 通过，0 skip，耗时 919.293 秒。保存了 6 次 invocation 的原始结果、worker receipts / WAV 和 canonical logs；可提交的脱路径摘要及原结果 hash 见 [acceptance-summary.json](../evidence/2026-10-02-cloud-mock-dag/acceptance-summary.json)。

| 场景 | 首次 | 第二次 |
|---|---|---|
| 正常完成 / 正常进程重启复用 | 2 mock jobs、4 synthetic text calls；synthetic_complete | 0 jobs / 0 calls；原 bytes 不变 |
| 独立单元之一确认失败 | 一失败、一成功；join / final 阻断 | 显式选择原失败 request 后仅 1 新 job；成功邻居复用，0 text calls |
| observer 普通超时 | outcome_unknown；不得据此重试 | 读取原 job / receipt 对账；0 jobs / 0 calls 后完成 |

每次 14 个实际 SDK task records，验证持久化 taskRunId / flowRunId / task_inputs / 状态时间；正常完成时 14 条 typed observed edges。SDK Completed 与业务 succeeded / failed / unknown 分开。上述测量范围起点仍是 source.existing。

独立只读复核随后提出三项静态修正：恢复观察单独落盘时仍须能在下次调用进入 reconcile；received / queued / worker completion 必须使用各自准确 artifactKind；等价 outbox replay 的 original start 按 eventId 去重。这些修正在测量提交之后，最终 exact-head CI 另计，不能把旧提交的通过结果冒充最终提交。

补充兼容性检查发现普通 outbox 会在已冻结 Fresh 身份之后导入 durable 模块；现改为检测 opt-in sidecar 后才导入，普通路径不改变 loaded-module inventory。现有冷启动与 durable 回归 24/24 通过；独立 review 三项修正后的 worker / client 9/9 通过。最终冻结提交的真实 SDK 与 root 组件重跑仍待记录。

组件测试另外替代 engine-version 元数据为 component-only 标记，使没有可选 SDK 的 root CI 仍执行全部组件；真实 SDK 三例不使用这种替代。

## 当前受阻覆盖与保守边界

用于把独立复核的进程中断 / completion acknowledgement 丢失 / request 与 receipt 篡改复现保存成新增 controller crash-recovery 回归文件的任务，遇到工具安全筛查阻断。该测试编写动作已暂停，没有改名转移到其他 worker 或测试文件重试。因此不能声称这些新 controller crash-window 回归已执行通过；既有普通回归和先前独立复核结果分别保留。这是测试工具准入限制，不是缺少仓库开发授权，也不构成新增漏洞结论。

原 ledger 被截断、不可验证或存在冲突时，继续 fail closed。共享 durable stream 在 immutable delivery record 与 pending freeze 之间失去必要证据时明确 blocked，不猜测重建。未知 worker 生命周期保持保守资源/重试判断，不以断线或超时猜测未执行。

## 计量与后续

WAV duration 是 fixture 媒体长度；人为 delay、实际排队 / worker / controller / 日志处理时间分别记录。TTS 的 provider tokens / cost 为 null + not_applicable，不能充当真实模型性能。已有 offline Source/text transport 的 synthetic 调用另列，实际 provider 调用为零。

强一致日志 union 校验存在可观开销：同一 60-event 本地小测由约 16.43 秒降至约 7.25 秒，改动是按不可变 canonical bytes 的有界成功校验 cache，仍保留严格类型、schema/version 和冲突检查。这不是完整 pipeline 性能结论。resource/provider queue、跨域 clock、完整 CP/ETA 未获证明时保持 unknown/partial。

同一 frozen plan 的失败单元恢复已经实现；跨 plan 的 changed-text 子图迁移尚未实现。真实 Fresh 五阶段调度、全消费者一致性、外部 Hub/Spark speech mapping / bytes 合同，以及正式人工/发布资格继续沿原 backlog ID 留待独立证据；本轮不新建第二个远程 speech 接口。

## 复现

在干净的已提交 checkout 安装 `requirements-prefect.txt` 与现有音频验证工具后执行：

```sh
SERMON_TEST_PREFECT=1 python -m unittest tests.test_sermon_mock_tts_dag.ActualMockTTSPrefectTests -v
python -m unittest tests.test_sermon_mock_tts_worker tests.test_sermon_mock_tts_control tests.test_sermon_mock_tts_dag.MockTTSDAGComponents -v
```

CLI 为 `python -m scripts.sermon_mock_tts_dag`，只接受显式 `--offline-fixture`、原 plan / continuation、冻结 spec 和 fixture responses；恢复还需精确 `unitId → 原 request SHA256` 的 `--recovery-manifest`。这不是生产 TTS 入口。

## 外部审查补强与规模边界

- 修正 submit 的分派边界：capacity / retry / intent 等前置失败明确为 blocked，只有进入固定 launcher 后才可能记录 dispatch unknown；同 key 正常复用明确 `launchEntered=false`
- 成功功能测试使用显式 60 秒 worker / 45 秒 observation 预算，不把 8 秒微性能窗口当作成功语义。专门的短观察测试仍以 0.01 秒触发 unknown，并保留原 receipt 对账验证
- 当前新 mock v1 只接纳已验证的最多 2 个 unit；这是实验范围的 fail-closed 限制，**不是可扩展性修复**。39-unit 与 128-unit 的吞吐、deadline 和完整生命周期验收继续开放
- 精确内容/类型绑定的私有 schema snapshot 降低重复校验开销。相同正例 client profile 4.133 → 2.688 秒；256 events × 20 replay batches 2.548 → 0.155 秒。每 event 的 JSON/type/size/schema/semantic 与 replay 检查保留；实际 ledger bytes、delivery records、锁和 scope 仍全量校验
- 全量 ledger 校验仍为每 append O(N)、累计可能 O(N²)。本切片不宣称增量 prefix 校验已经实现；后续优化必须继续验证原字节、冲突、scope 与 sequence，不准用 mtime 或对象 identity 代替事实完整性

## 后续 correctness 修复与重新验收

PR #217 在 `ddff97e` 的可见 CI 曾全部通过，但后续独立 review 确认 generic `completion.validate()` 根据调用方 handle 自动接受 synthetic v2，会让既有 Source predecessor gate 失去 v1/v2 类型边界。离线负例复现了 generic 接受，以及实际 `prepare_source` 到达 gate 后第一步。修复将 generic API 固定为 v1，v2 只能显式走 `validate_synthetic()`；共享内部检查仍保留原 event/terminal/dependency/artifact/run/job/revision 约束，不改变 Source producer 文件或扩张 migration。

依赖 PR #218 的 `30704a8` required root CI 另有一个真实失败：确认 worker failure 的普通组件场景，observe 返回 `public_snapshot_changed_during_read` / blocked。它不是测试 job timeout；旧 hosted SDK 全部通过也不能覆盖这个失败。独立临时目录复现证明正常 hard-link publication 的临时 link 清理会改变同一 inode 的 ctime，payload/device/inode/size/mtime 均不变，严格 reader 因而可以在 writer 尚未结束时拒绝快照。原 CI 没保存具体文件 traceback，因此这证明机制而非追溯断言唯一原始文件。

观察与 reconciliation 现先检查原 physical job 是否仍 queued/running；active 时不提前读 terminal receipt。仍在原 deadline 内等待或返回 still_unknown，无重新派发、无放宽 strict snapshot/hash/terminal 检查、无吞掉 ContractError。两个普通状态顺序断言在旧代码失败，修复后控制器 8/8 通过。此前被阻断的新 crash/ACK/tamper 故障测试没有换文件重做。

这两项修改需要修正提交的独立复核和 genuine exact-head CI；旧通过记录保持历史属性，不能冒充新提交验收。全量 ledger 扫描 P1、39/128-unit 规模与 production 资格仍 open。CI 两个新增重模块的分片成本采用观察值，含失败 full-Fresh 模块时明确作为调度估计/下界；不删测试，不改 required gates 或 timeout。
