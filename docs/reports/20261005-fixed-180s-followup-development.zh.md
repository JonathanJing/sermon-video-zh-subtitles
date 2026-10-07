# 固定三分钟片段复盘后的开发改进

2026-10-05，沿用 PR #248 工作分支。基于[上一轮真实测试](20261005-fixed-180s-mock-codex-local-rerun.zh.md)开发三个增量；本轮没有新增真实 Codex、API、TTS 或 ASR 调用，没有改生产配置、内容批准或发布状态。

## 时间诊断与修复计划

新增只读 `target_audio_timing_plan.py`，调用未修改的正式 Layer 3 scheduler。旧 v1 将源句超长列为独立发布 blocker，忽略了正式排程允许借用后续余量；新 `fixed-clip-local-model-assessment-v2` 将其改为警告，分开计算实际 end lag 与片尾溢出。旧 assessment.json 保留；新结果为 ignored `artifacts/fixed-180s-codex-local-real-20261005/assessment-v2.json`。

重新核验同一媒体、13 个 WAV 的哈希、时长及完整解码；音频和文字未改：

| 指标 | 实际结果 |
|---|---|
| 源片段 | 180.013167 秒 |
| 自然配音 | 185.92 秒 |
| 长于自身源窗 | 8 组，仅作警告 |
| 超过正式 8 秒 end lag | g007、g008、g009、g011、g012、g013，共 6 组 |
| 按源锚点排程片尾 | 189.73 秒，溢出 9.716834 秒 |
| 音频＋组间隔＋最早起点的串行下限 | 186.57 秒，至少需回收 6.556833 秒 |

最后一项只是必要下限，不能保证满足源锚点和 end lag。纯排程不能消除自然音频总长超限；计划只提出测量真实边缘静音及整组听审等行动，没有自动剪音、变速、改译文或批准。正式同步、人工内容审核仍未完成，不能发布为正式可播放内容。

## CLI 与 GPU 准入

固定片段真实 CLI transport 新增可选 `--resource-policy`，每调用预留一个 `codex_cli` 槽。共享模型循环在写 started 前准入，容量忙不会留下假 unknown 标记；cache/raw 恢复不占槽。终态事件／response 私有原子写入、文件与目录 fsync 后保存资源 outcome，再归还槽。超时、终态不明、证据写入失败继续 held；未增加重试或孤立 reservation 自动回收。

独立 TTS／ASR worker 新增同参数，整个 job 保守共用 `spark_tts=1`。成功完成后先 dispose、删除内部模型引用、gc、CUDA synchronize/empty_cache，保存身份绑定 gpu-cleanup 收据，再保存最终 manifest/outcome 并释放。清理失败不生成最终 manifest；完整批次缓存若缺清理证明，不能恢复释放。审查发现的“模型尚驻留便归还槽”和“终态未 fsync 便释放”两项 P2 均已修复，复核无新增具体 P1/P2。

这些是显式启用的诊断入口；同一协调主机须共用 brokerRoot。没有实现跨主机全局额度，也没有将正式 canonical L2 改为 CLI。canonical.audio 已持 GPU 许可时不能嵌套独立 job 许可。测试入口容量上限不创建并发 worker，仍保持 workers=1。

## 单模型驻留实验接口

新增 LocalModelSession 并接入本地 Python producer 的可选 factory 路径。最多一个缓存模型／一个活动借用；精确权重树、checkpoint、设备、dtype、attention、冻结运行时和实现身份匹配才复用。切换先清理旧模型；加载、清理或借用失败禁止后续复用。测试两个不同输出 job 同身份时加载一次、复用一次，各批次仍完整执行。

没有部署 daemon 或改变 Spark 服务；fake factory 验证不等于实际提速。跨 job 驻留不能与每 job GPU 许可同时开启，尚需整个 session 生命周期的持久 GPU 许可，之后才适合做真实冷暖对照。

## 本轮验证与后续

12 个相关测试模块共 162 项回归通过，覆盖共享翻译循环、CLI transport/fixture、资源 broker/runtime、TTS/ASR 诊断 worker、单模型 session、正式 renderer、时间评估与恢复。随后新增清理失败恢复测试，相关两个模块 20 项通过（包含前述重复测试）；合计覆盖 163 个不同测试。额外只读审查确认释放順序及未知结果保护。

当前实现新目录 `artifacts/fixed-180s-improvements-mock-20261005/` 完成同一 39 English units、13 组、26 个历史响应回放，结果 `fixture_replay_pass_test_only`、`realModelCalls=false`。历史 token 不计作本轮速度；本轮未新增模型性能结论。

后续按顺序推进：先实现驻留 session 级 GPU 许可和真实冷暖验收，再接正式 CLI→语言插件→candidate 链；同 run 多 worker、公平 DAG、跨主机调度分别验收。实际内容仍需按时间计划完成无损静音测量／整组同步修复与人审。相关操作参数见[测试说明](../codex-layer2-test.zh.md)和[资源说明](../unified-resource-admission.zh.md)。
