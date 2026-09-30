# Stage 0 组件证据与待签字文件

在 clean checkout 中运行（输出放到 checkout 外，目录必须尚不存在）：

```sh
python scripts/evaluate_canonical_stage0.py \
  --base <已核实的基线commit> \
  --out /tmp/tongxing-stage0-new-run
```

工具仅运行固定的本地/synthetic unittest 集合：canonical package inspection、
三语 planner、bounded decision、legacy deterministic controller/crash windows、
accounting、weekly report 与真实 producer 的合成计时/cache 回归，再执行既有 backend dry-run failure matrix。
它不接收任意 shell/module，不启动真实生产模型，也不部署或改写现有证据。
已有输出目录或 log 会报错；失败、timeout、零测试和 skipped tests 均不能变成 pass。

输出 `stage0-report.json`、`stage0-signoff.json` 与各 suite log。报告包含前后
commit/clean 状态、各测试数量、结果和 log hash，以及同一 head 的兼容性快照。
dirty checkout 或运行中 git 状态变化使检查失败。组件全通过时状态也只是
`component_checks_passed_stage_incomplete`；退出码 0 不表示 Stage 0 sign-off。

`stage0-signoff.json` 是绑定该 report 字节 hash 的待签字文件，所有人工角色
保持 pending/not_evaluated，`automaticApproval=false`，`stage1PromotionAllowed=false`。
当前固定 Layer 2 adapter 已有 producer dispatch；完整 canonical durable dispatch、生产 Decision runner、group/unit 选择性恢复、
deploy/HTTP 故障不重跑上游的集成证据、stage-specific retry/heartbeat/backpressure
仍是明确 blocker。legacy controller 与 synthetic fixture 的通过不能替代这些条件。
新 runtime 未经兼容性分类时，即使受保护 client tree 不变，仍保留 compatibility review。

runtime Codex 为 0 的证据来自指定 shadow/legacy 测试断言，不是对生产端到端运行
或工程 Codex token 的计量。真实小片段、10 分钟、完整历史视频及各角色签字仍按
[冻结阶段计划](codex-orchestration-pipeline-design.zh.md#10-stage-0synthetic--existing-short-fixture) 顺序推进。
