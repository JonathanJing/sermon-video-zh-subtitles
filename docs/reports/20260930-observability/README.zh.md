# Dry run 日志充分性复跑（2026-09-30）

已修复并用真实本地媒体/缓存重跑。现在日志可以独立解释本次有限样本的执行、缓存来源、历史用量和逐单元验证；**还不能据此宣布整条生产流水线的日志完整**。没有新付费推理、人工审批、发布或 Stage 1 放行。

执行代码：`fd788ac8517d381d24bb1a834689e88bcfa4f6c7`，三个正常实际样本均在干净工作区运行。PR：[#161](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/161)。原始媒体、缓存、已有审批与音频未改；新候选仍是 human review pending。本文属于观测/汇总修复，未改变翻译策略、请求、渲染内容或拒绝条件。

## 实际运行及独立对账

| 路径 | 本次实际行为 | 从日志重建与独立记录比较 |
|---|---|---|
| 138 秒已批准窗口，三语 L2 | 3×11 组缓存校验及候选重建，0 次新 transport 尝试 | 66 个 Astra/Sol 历史响应的模型、缓存/原 raw receipt/请求 payload/原 response ID hash 与原件逐项一致；33 组校验小计 0.118539s |
| 本地 ASR，处理 178.16 秒窗口 | 新运行 `mlx-community/whisper-large-v3-turbo-q4`，实际 ASR 10.738793s | checkpoint、输入 WAV、输出转写 hash 可由日志取得；输出与较早实际 ASR 一致，不代表人工质量验收 |
| 历史三语音频验证 | 33 个单元重新全解码，无新 TTS | 33 starts / 33 completions、3 个 job hash、全部 audio hash 与独立音频包吻合；实际单元验证小计 6.304529s |
| 插件绑定阻断 | 用原来的跨 checkout 插件路径重新触发已有拒绝条件 | 三个语言均记录 `plugin_implementation_mismatch` 及预期/实际实现 hash；0 次 transport；不是放宽 validator |

L2 ledger wall 为 2.814694s，外部 monotonic 包含外围设置/校验为 2.866510s。两者边界不同，差额不命名为调度开销。3 个 locale 在此诊断驱动中串行运行；记录的依赖图表达前置关系，不是生产并发吞吐基准。本轮 ASR/缓存/音频诊断曾并行启动，不用于前后性能优劣结论。

历史 input/output/reasoning 分别为 **49600 / 34989 / 12916**；reasoning 是输出中的明细，不再相加。历史 cached input 为明确回执值 0，cache-write 明细缺失 0 条。本次新 provider receipt 为 0；零传输另由禁网守卫计数确认。历史 token 不是本次消费，历史美元费用/账单仍为 null。本地 ASR 的 provider token/cost 不适用，不填零费用。

旧 138 秒 trace 没有 66 条缓存身份/用量观测，source duration 为 null；旧音频验证只有 3 个粗粒度 wrapper。不能用后来 #160 的 renderer 测试追认这些旧日志已完整。本轮音频路径是实际 builder/validator，新增单元观测也没有把粗粒度 wrapper 的其余时间丢掉。

## 每个验收问题的覆盖

| 问题 | 分类 | 证据/限制 |
|---|---|---|
| 程序、当前模型、历史模型区分 | measured | executor spans + local model / historical cache typed observations |
| 精确模型、输入输出、代码身份 | measured | 模型/checkpoint/payload/artifact hashes、Git SHA、dirty flag、已加载项目模块 hashes；不是全部第三方运行时证明 |
| wall 与片段运行时间 | measured | 起止时间、elapsed、33 个缓存准备 span、33 个音频验证 workload；小计不能等同端到端总量 |
| 历史 tokens 与当前 spend | measured / missing | 原回执用量可验证；历史账单和新付费 provider telemetry 未验证 |
| 本地 ASR provider tokens | not_applicable | 本地推理没有 provider receipt；字段 null |
| 真实生产队列/ready 时间、调度开销 | missing | 没有实际采集；不从 start time 或 wall 差值推算 |
| 依赖、并行/中断 | measured（限当前记录） | 完整依赖/时间保留；并行与中断另有明确标为 synthetic 的 trace；跨进程 critical path missing |
| run/span/workflow/provider correlation | measured | 当前 IDs、parent workflow、span、原响应 hash；此 L2 直接诊断没有 durable job，not_applicable；L3 有原 job hash |
| durable worker 的跨进程 job→span 关联 | missing（实测） | 已补 worker metadata 且有本地集成测试，本次直接回放不冒称 durable worker 实跑 |
| 缓存/拒绝/未知结果原因 | measured（所列案例） | 缓存 bound/missing/unbound 标识，插件固定拒绝码；进程中断未知结果为 synthetic；并非所有异常路径都已实测 |
| 重复和冲突用量 | measured（synthetic） | 同/不同 event ID、跨 run、direct + SDK、反序；冲突为 null，所有 reader 对齐 |
| human/external/engineering 时间 | not_observed | 0 仅是已结束叶 span 小计；完整总时间仍 null，不证明这些工作不存在 |
| pageReady / 完整流水线 / 设备现场 | not_observed | 没有本轮交付或人工/设备/现场验收，不能由 projected 推导 |

## 可直接检查的证据

- [紧凑代表事件](representative-events.json)：真实 cache/local ASR/audio/refusal，以及 synthetic interrupted 标记。
- [逐项对账结果](reconciliation.json)、[独立历史缓存 oracle](independent-cache-oracle.json)、[实际执行记录](independent-execution.json)、[ASR 记录](independent-local-asr.json)、[音频记录](independent-audio-validation.json)。
- [完整 L2 safe trace](l2-cache-replay/events.jsonl)、[JSON report](l2-cache-replay/report.json)、[可读报告](l2-cache-replay/report.md)。报告仅从导出的事件重建，未读取媒体、缓存或业务 artifact。
- [ASR trace/report](local-asr/report.json)、[33 单元 trace/report](audio-unit-validation/report.json)、[实际绑定失败 trace/report](blocked-plugin-binding/report.json)。各目录 `export.json` 有同一次读锁快照的原/导出 hash 与数量。
- [故障对账](controlled-fault-reconciliation.json)：[equivalent](synthetic-equivalent-receipts/report.json)、[conflicting](synthetic-conflicting-receipts/report.json)、[同 event ID 冲突](synthetic-same-event-conflict/report.json)、[真实子进程退出的模拟未知结果](synthetic-interrupted/report.json)、[模拟并行图](synthetic-parallel/report.json)。这些是 controlled synthetic，不是付费服务或真实生产故障。
- [实际命令/driver hash](command-identities.json)。主机私有路径用环境变量替换；媒体/原文、凭证、模型正文不入库。

Reviewer 可以直接重新投影：

```sh
python scripts/weekly_pipeline_report.py \
  --accounting-dir docs/reports/20260930-observability/l2-cache-replay \
  --out-dir /tmp/new-observability-projection
```

本轮无需新增费用批准。若要验证新付费 provider 的真实 request/response/usage telemetry，仍需单独获准的小额实际调用；这项窄缺口不阻塞本次离线日志对账。真实媒体分阶段及人工、设备、现场门槛继续保留。

最终完整 Python 集成验证：本地快照 `cd08cdf350f6e0bf20620092e233dd09ba96746c`，2077 项 reported / 6 项 conditional skipped / 2071 项实际通过，见 [机器可读证据](integration-validation.json)。该快照包含至 #161 的全部 runtime 改动，没有合并到 dev/main。远端 draft iOS/contract jobs 的 skip 不算 native 验收。
