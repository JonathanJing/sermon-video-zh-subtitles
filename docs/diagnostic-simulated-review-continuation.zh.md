# 隔离诊断中的模拟人工审核

仅供用户明确授权的 mockup/dry run。真实 Source、人审和 terminology 状态保持 pending，机器 Generator、独立 Reviewer 和结构插件仍运行真实检查；失败不能被改成 pass。新建 `sermon-diagnostic-context-v1` 不是生产审批收据，生产默认入口及 Gate 不接受它。

## 原运行保持不变

`run_bounded_diagnostic_continuation` 读取已有 run-plan 和已有 provider state，验证同一个 runId、原 config、store、source/anchor 及窗口。原代码身份继续由原计划保留；新 continuation 单独绑定当前干净提交的 executionIdentity。不得重置 startMonotonic、$40 总上限或已预留费用。先前 unknown/reserved 结果、过期时限或代码身份不匹配均阻止执行。

命令：

```sh
python -m scripts.run_bounded_diagnostic_continuation \
  --plan PRIVATE/run-plan.json --continuation PRIVATE/continuation.json \
  --phase preflight --input PRIVATE/zh-Hans.spec.json
# 通过预检、固定代码审查和 CI 后，由已授权私有 FD 传入现有 key：
python -m scripts.run_bounded_diagnostic_continuation \
  --plan PRIVATE/run-plan.json --continuation PRIVATE/continuation.json \
  --phase locale --input PRIVATE/zh-Hans.spec.json --key-fd 3
```

只有 locale 阶段，没有 ASR/source-check 重跑、发布或生产审批命令。全部模型调用继续经过同一 DiagnosticProvider；不允许 legacy HTTP 或其他子进程逃逸。模型后续审核 payload 在各自请求前检查大小/额度，初始所有组在首次调用前预检。

## 模拟范围和未模拟范围

- 仅 Source 人审待办、绑定的 9 秒可复核 clause 警告，以及 terminology 两类人审待办可在显式 context 下继续。媒体、窗口、派生身份、schema、alignment 错误和其他 policy 阻塞不豁免。
- `diagnostic-structural-v1` 是单独的诊断插件。它检查实际目标文字、术语表面匹配、数字、纯文本结构及 reference-only 边界；不声称 native fluency 或经文逐字审核。原生产语言插件和默认模型策略保持不变。
- 每组真实 Generator / Reviewer 的调用、latency、token 和 verdict/rework lineage 沿用生产 accounting。`simulatedHumanGate`、context hash、`humanAcceptancePending` 明确记录。
- Source、候选及 policy 的原待审字段不改为已审，revision/operation/locale 绑定 context，生产 speech admission 仍拒绝。

## TTS 和本地交付预检

复用 speculative preview lane，传入 strict rubric、diagnostic context 和原始 `deadline_monotonic`；仍要求真实机器 pass、现有声线授权及精确 checkpoint。v2 preview manifest 绑定 context/rubric，产物不具生产或正式 Layer 3 资格。父进程必须以原始剩余秒数对本地 worker 施加 subprocess timeout；渲染器也在各边界检查同一个绝对 deadline。

逐单元记录模型耗时、checkpoint/input hash、缓存验证及完整解码。不可返回的本地模型 provider tokens/cost 保持 null/not applicable；不借用历史 API usage。未完成、超时或日志失败后的 scoped attempt marker 阻止盲目重新合成。本地交付预检应展示真实缺失审批，不能将预览包装成 production-ready。

## 验证范围

136 项相关离线测试通过，覆盖 context/生产隔离、真实 strict 路径的 mock transport、重放不新增调用、失败语义审核、deadline/unknown 拒绝、三语诊断结构规则、声线/模型身份和 preview 新旧路径。它们不构成真实媒体、声音、设备或人工验收。
