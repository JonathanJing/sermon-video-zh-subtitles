# Saturday Temporal 本地持久化编排

Temporal 接管等待、活动调度与恢复历史；现有 Saturday harness、Supervisor、bridge、lease、素材指纹与审批验证器继续决定实际能做什么。默认提交只有只读检查。已有阅读 PDF/GCS 合同、对话内容审核和发布关口仍由原流程执行。

这是**单机、loopback、SQLite 持久化的本地部署**。CLI 的 `server start-dev --db-filename` 支持重启后保留历史，但不是高可用生产集群；未验证多机容灾、升级迁移或开机自启动。部署能力与限制依据 [Temporal CLI server 文档](https://docs.temporal.io/cli/command-reference/server)。

## 安装、启动与停止

在仓库根目录运行。根项目 `.venv` 保持原有生成依赖；Temporal SDK 单独装在 ignored `artifacts/temporal/runtime/venv`。安装器固定 SDK `1.32.0`、CLI `1.8.3`，校验官方 release checksum；不全局安装，也不覆盖不同版本的现存 CLI。

```bash
.venv/bin/python -m scripts.sermon_temporal.bootstrap
artifacts/temporal/runtime/venv/bin/python -m scripts.sermon_temporal server start
artifacts/temporal/runtime/venv/bin/python -m scripts.sermon_temporal server status
```

gRPC：`127.0.0.1:17233`；[本地 Temporal UI](http://127.0.0.1:18233)；namespace：`default`。`server start` 可重复调用；端口已由其他进程占用时拒绝启动，不清理其他服务。

在另一个终端启动正式只读 worker；该终端 `Ctrl-C` 可停止 worker。`--profile production` 队列与测试 fixture 队列隔离。

```bash
artifacts/temporal/runtime/venv/bin/python -m scripts.sermon_temporal worker --profile production
```

本次保留的是**后台只读 worker**，可通过以下管理入口操作。收据位于 `artifacts/temporal/production-worker.json`，日志位于 `artifacts/temporal/production-worker.log`；`stop` 核对 PID 的启动/命令指纹再发送信号，不直接使用文档中的旧 PID。`start` 固定关闭生产执行，已有同身份 worker 时返回现状；status 只确认进程身份，实际 Activity 成功仍需查看 workflow 和收据。代码更新后先 stop 再 start 以加载新代码。

```bash
artifacts/temporal/runtime/venv/bin/python -m scripts.sermon_temporal worker-service status
artifacts/temporal/runtime/venv/bin/python -m scripts.sermon_temporal worker-service stop
artifacts/temporal/runtime/venv/bin/python -m scripts.sermon_temporal worker-service start
```

停止 server 保留 `artifacts/temporal/server/temporal.sqlite`；重启使用同一目录和固定版本。服务管理记录进程启动时间与命令指纹，只停止自己创建、且身份仍相符的进程组。

```bash
artifacts/temporal/runtime/venv/bin/python -m scripts.sermon_temporal server stop
artifacts/temporal/runtime/venv/bin/python -m scripts.sermon_temporal server start
```

数据库、worker-state、config、approval 和原生产目录都需要保留。Temporal 历史不包含完整媒体或密钥，也不能替代原始媒体、审批、job manifest、PDF 和候选音频的恢复副本。升级前停服务并备份完整 server 目录，不能只复制运行中的单个 SQLite 文件。

## 固定一次源和配置

配置使用 `sermon-temporal-operator-v1`。以下值需对应实际已识别来源；相对路径由仓库根目录解析，生产运行建议使用绝对路径。`bridgeConfigSha256` 是现有 bridge JSON 的文件 SHA-256。密钥字段保留 Secret Manager 资源名，不放密钥内容。

```json
{
  "schemaVersion": "sermon-temporal-operator-v1",
  "sunday": "2026-09-06",
  "sourceKey": "live_archive:l8ucqF9uA9A",
  "expectedPdfSlug": "sermon_l8ucqF9uA9A",
  "expectedSources": {"live_archive": "l8ucqF9uA9A"},
  "bridgeConfigSha256": "REPLACE_WITH_ACTUAL_64_CHARACTER_FILE_SHA256",
  "harnessArgv": [
    "--sunday", "2026-09-06",
    "--state-file", "artifacts/post-live-fallback-runs/2026-09-06/live-source-state.json",
    "--work-root", "artifacts/post-live-fallback-runs",
    "--supervisor-report", "artifacts/post-live-fallback-runs/2026-09-06/supervisor-report.json",
    "--bridge-config", "artifacts/sermon-dubbing/saturday-bridge.json",
    "--gcs-bucket", "sermon-zh-artifacts-ai-for-god",
    "--gcs-prefix", "sundays",
    "--api-key-secret", "projects/ai-for-god/secrets/openai-api-key/versions/latest",
    "--youtube-api-key-secret", "projects/ai-for-god/secrets/youtube-data-api-key/versions/latest",
    "--skip-source-refresh"
  ]
}
```

该配置必须显式 `--skip-source-refresh`：来源发现仍走原 operator 工作流，已入 Temporal 的请求不能通过刷新偷偷换源。不可传 `--mode` / `--out`。提交时固定 config SHA-256；后续修改 config 或 bridge 字节会停止检查并要求恢复/新请求，而不会追认原请求。workflow ID 由 profile、日期、source key、config hash 决定；更换文件位置、执行开关或超时不产生第二个 ID。相同 ID 在运行中与完成后都拒绝重复提交（限 Temporal 保留该历史的期限）；不同 config 请求仍由原 lease、恢复状态与审批守护，不能把 Temporal ID 当作所有外部副作用的永久去重账本。

```bash
artifacts/temporal/runtime/venv/bin/python -m scripts.sermon_temporal client submit \
  --profile production --config artifacts/temporal/production-inspect-20260906/config.json
artifacts/temporal/runtime/venv/bin/python -m scripts.sermon_temporal client status \
  --workflow-id WORKFLOW_ID
artifacts/temporal/runtime/venv/bin/python -m scripts.sermon_temporal client result \
  --workflow-id WORKFLOW_ID --timeout 10
```

`status` 同时显示 Temporal server 状态和业务 scope。`COMPLETED` 可能只是只读检查结束或候选交接完成；`workflow_complete=false`、`audio_published=false` 不会被 Temporal 改为正式生产完成。`candidate_handoff_only` 仅说明已有候选通过原 bridge 的完整性检查、等对话审核，不能推导双 PDF、内容正确性或发布已通过。

## 人工审阅等待与恢复

原审批仍由原入口写入，绑定 source、timeline 与媒体证据；此模块没有生产审批写入工具。`resume` 只把“证据已经变化，请重查”信号交给工作流。执行前再次调用原验证器并检查新计算的 `source_binding`。signal 和 query 的语义参照 [Python message passing](https://docs.temporal.io/develop/python/workflows/message-passing)。

```bash
artifacts/temporal/runtime/venv/bin/python -m scripts.sermon_temporal client resume \
  --workflow-id WORKFLOW_ID --binding CURRENT_SOURCE_BINDING \
  --reason '已通过原工作流完成源绑定审阅，请重查证据'
```

`signalAcceptedByServer=true` 只表示 server 收到信号。必须随后查询 `accepted_signals`、`rejected_signals` 和 `observation`。旧 source/timeline 信号被拒绝；当前绑定的信号也不能代替缺失审批。同一 signal ID 重发只处理一次。初次 inspect 失败没有 observation 时，仅能用 `initial_inspection_binding` 唤醒只读重查；恢复出的真实 binding 仍需新的信号，不能凭初始 binding 直接执行。

每次执行结果不明会递增 `recovery_epoch` 并清空待处理信号；执行期间的信号直接拒绝。信号同时绑定当前恢复代数，因此事故前排队或延迟到达的旧信号不能自动恢复新故障。CLI `resume` 默认查询当下代数并在结果中展示，也可用 `--recovery-epoch` 显式固定。自动调用者必须读取新状态后发出新的恢复决定，不能重放旧信号。

已授权的实际执行需**同时**启用 worker `--allow-production-execute` 和首次提交的 `--allow-execute`。两者缺一时不会调用生产 harness。正式执行仍可能调用原流程的付费阶段或 PDF 上传；本轮验证没有开启此路径。只读请求完成后不能通过切换开关重交相同 config 来规避重复 ID；需要明确记录新的操作配置及意图，再由原证据关口决定动作。

## 心跳、取消与执行结果不明

inspect 最多安全重试 3 次；execute Activity 明确 `maximum_attempts=1`。心跳丢失、worker 退出或执行异常后先只读重查本地收据与原恢复状态。若结果仍未知，停在 `waiting_reconciliation`，等待绑定信号；不会自动重跑有副作用的 Activity。完成收据可恢复为已完成；仍活跃的 actor 由 PID 加启动/命令指纹识别并阻止重复调度。

每个 Activity 在独立的项目 Python 进程组执行，并保存 request、stderr、PID 身份与收据；SDK worker 每秒以内发送一次心跳。默认活动上限 25,260 秒、心跳期限 20 秒，可在首次提交调整；心跳期限必须同时短于活动上限和只读 inspect 的 300 秒上限。取消等待当前 Activity 响应并清理它的本地进程组；远端生成结果仍按原 recovery/未知状态检查，不能宣称撤回已发生的外部动作。参考 [Python SDK](https://github.com/temporalio/sdk-python) 和 [错误处理说明](https://docs.temporal.io/develop/python/best-practices/error-handling)。

外层取消给 adapter 10 秒 TERM 清理时间，再进行外层强制清理。Temporal adapter 显式设置 `SERMON_HARNESS_GUARDED_CHILDREN=1`，使每层 `bounded_process` 都带独立的父进程存活管道；中间 owner 被强杀时，管道 EOF 级联清理下层组，避免相同宽限期相互抢先结束。该开关只用于 Temporal 路径，原有非 Temporal worker-loss 恢复语义保持不变。真实集成创建三层嵌套、最内层忽略 TERM 的子任务，并检查每层进程身份均停止。

```bash
artifacts/temporal/runtime/venv/bin/python -m scripts.sermon_temporal client cancel \
  --workflow-id WORKFLOW_ID
artifacts/temporal/runtime/venv/bin/python -m scripts.sermon_temporal client status \
  --workflow-id WORKFLOW_ID
```

## 验证与证据

根 Python 测试无需安装 SDK。真实集成使用已安装的 SDK 和原生 Temporal CLI，不用 mock server 或跳时环境；自动选择隔离 loopback 端口、全新 SQLite、fixture worker 与假素材。结束只停自己的测试进程，保留报告与数据库。

```bash
.venv/bin/python -m unittest tests.test_sermon_temporal
artifacts/temporal/runtime/venv/bin/python -m scripts.sermon_temporal.integration_check
```

集成检查依次覆盖：等待人工证据时 server+worker 重启并保持同一个 run；运行中/完成后重复 ID 拒绝；旧绑定拒绝、signal 不能代替审批、timeline 改变使旧审批无效；有心跳的真实 Activity 取消并停止 actor；worker 被强杀后不自动重复 execute，保留 actor 完成后通过收据恢复；初次 inspect 失败通过仅检查的初始绑定恢复。所有 synthetic approval 只允许写入 `artifacts/temporal` 内显式 fixture，使用原窗口验证器但绝不作为生产授权。

2026-09-06 已实际启动 CLI 1.8.3 / server 1.31.2 / UI 2.50.1 / Python SDK 1.32.0。最终真实集成报告 `artifacts/temporal/integration-d07c41455578/integration-report.json` 为 PASS（SHA-256 `dd27b947d3863486c3d1a3477139b61512d4069e9976c91ee6d111bee27ec4ab`），包含三层取消和旧 recovery epoch 拒绝；报告在启动前记录源码/依赖哈希，运行后与最终代码逐项一致。根 Temporal 单测 7 项通过。

最终代码加载后，正式只读 workflow `sermon-saturday-v1-2026-09-06-a237a5b71b454c3ae8fcf24b` 检查已有 `l8ucqF9uA9A` fallback 候选，历史中只有一次 `sermon.inspect.v1`、执行次数为 0，返回 `candidate_handoff_only`。证据 `artifacts/temporal/production-inspect-20260906-final/verification.json` 保存实际 source media/job/config 哈希。同时保留原 Supervisor 的“未找到 timeline report / run_timeline_probe”观察，不能据此宣称 PDF 或整周流程完成。实际配置、活动收据和完整 inspection 留在 ignored `artifacts/temporal/`。后续复测状态以各次生成的 `integration-report.json` 为准。

相关入口：[统一 Saturday harness](saturday-harness.zh.md)、[执行恢复合同](sermon-execution-harness.zh.md)、[工作流地图](workflows/README.zh.md)。
