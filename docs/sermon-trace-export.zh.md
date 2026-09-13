# 周六 OpenTelemetry 导出、接收与展示

[export_sermon_trace.py](../scripts/export_sermon_trace.py) 把现有 `sermon-workflow-accounting-v2` 的已完成 run / workflow / stage 转成独立的 OTLP JSON `ExportTraceServiceRequest`。只读原始 `events.jsonl`，不调用模型、网络或 Collector，不增加 SDK 依赖。

```sh
python3 scripts/export_sermon_trace.py \
  --accounting-dir artifacts/本次任务/accounting \
  --out artifacts/本次任务/trace.otlp.json \
  --diagnostics artifacts/本次任务/trace-diagnostics.json
```

将示例目录换成实际账本目录。两个输出路径必须彼此不同，且不能指向输入账本。退出码 `0` 表示本次导出未发现所支持 span 的结构缺口；`1` 表示部分导出，必须检查 diagnostics；`2` 表示输入或文件操作失败。此状态不表示原流程 QA 通过、费用完整或已经发布。

## 导出的关系与边界

- 同一 `runId` 映射成同一 trace；每个 `(runId, 类型, 原始ID)` 确定性映射成 span ID。不同 run 中重复的 workflow/span ID 不会串线。
- run 是根；workflow 按 `parentWorkflowId` 或所属 run 连接；stage 优先沿 `parentSpanId`，没有时连接所属 workflow。缺失或无法导出的父节点只记 diagnostic，不猜测其他父节点。父子耗时重叠，不能相加当作总耗时。
- 只有恰好一对开始/结束事件且结束状态明确的 span 才进入 OTLP。使用账本真实时间戳；stage 使用 `startedAt`，结束使用 `recordedAt`。未结束、缺开始、重复边、未知状态、时钟倒退等只写 diagnostics，不填当前时间或虚构时长。
- API 只汇总到已有所属 stage 的调用/失败次数，以及明确存在的非负整数 Token 数；没有 API 细分 span，不推算缺失 Token 或费用。日志、资源快照、正文证据等不是本适配器的导出范围。

## 隐私白名单

输出只含已知代码阶段名称、哈希后的身份、时间、成功/失败码、cacheHit、选定哈希以及调用/Token 计数。阶段/工作流名称采用源码内固定白名单；未知名称替换成 `redacted_label` 并保留其摘要。原始 run/workflow/span ID 不直接导出。

不会复制 metadata 整体、模型提示词、正文、命令、URL、文件路径、异常消息或 stack frame。只有 `jobSha256`、`checkpointSha256`、`inputManifestSha256`、`timingReportSha256` 字段且值确为 64 位十六进制时允许输出。损坏行只记录行号与哈希。导出文件权限设为 `0600`。

## 本机接收、持久化与展示

[sermon_observability.py](../scripts/sermon_observability.py) 安装固定版本 **Jaeger 2.20.0**，核对官方 macOS arm64 压缩包 SHA-256，仅提取指定可执行文件。Jaeger v2 自身是 OpenTelemetry Collector 的发行版，包含 OTLP receiver、存储及查询 UI，因此本机不再额外启动第二个 Collector。部署范围及 Badger 单实例限制见 [Jaeger 官方架构](https://www.jaegertracing.io/docs/2.20/architecture/)。

```sh
.venv/bin/python scripts/sermon_observability.py start
.venv/bin/python scripts/sermon_observability.py status
.venv/bin/python scripts/sermon_observability.py send \
  --accounting-dir artifacts/本次任务/accounting --site macbook
```

- UI：`http://127.0.0.1:16686`；OTLP HTTP：`http://127.0.0.1:14318/v1/traces`。
- 服务、下载回执和进程身份在 `artifacts/observability/`；Badger 数据持久保存在其 `badger/`，停止或重启不删除。
- 所有端口只绑定 loopback。投递器禁用 HTTP 代理和重定向，运行服务禁用自身 SDK 自动遥测，不把账本送到云端。
- `--site` 是明确的账本执行地点标签，允许 `macbook`、`spark`、`cloud`、`test`。历史 MacBook 账本中的远端命令耗时仍是客户端观察的阶段，不冒充 Spark GPU 内部 span 或云服务端 span。不同地点导出的账本可沿原 `runId` 关联；新增地点接入要提供实际对应账本。

`send` 在原账本旁的 `telemetry/` 保存脱敏 payload、结构诊断及投递回执。网络断开、非对象响应、Collector 拒收部分 spans 均保留待核对输出并返回失败；不会重新执行模型。重送使用原 trace/span ID，Collector 中同一 span 不应因重送增加；实际重送与重启检查见下方验证入口。

## 持续观察新账本

```sh
.venv/bin/python scripts/sermon_observability.py observer-start \
  --scan-root artifacts/post-live-runs \
  --scan-root artifacts/post-live-fallback-runs \
  --scan-root artifacts/sermon-dubbing/weekly-bridge \
  --accounting-dir artifacts/sermon-dubbing/2026-09-06-live-fallback-v3-numbers/accounting
.venv/bin/python scripts/sermon_observability.py observer-status
```

观察器只在显式根目录中发现 `accounting/events.jsonl`，也支持逐个指定账本。文件变化后重导出已有完成的 spans；未完成阶段留在原账本和 Temporal 当前状态中，不虚构结束时间。一份账本不可读或无法写回执，不影响其他账本，下一轮仍会重试。重启观察器会重新送出当前快照，稳定 ID 保持关联。

`observer-start` 和 `start` 都以保存的启动时间、PID 和完整命令核对本任务进程。重复启动不会创建第二个同配置进程；停止只操作已核实的进程组。修改观察目录时先停止观察器再启动新配置：

```sh
.venv/bin/python scripts/sermon_observability.py observer-stop
.venv/bin/python scripts/sermon_observability.py stop
```

这些是本机常驻进程，不会修改既有 Codex 定时任务，也没有新增开机启动项。Mac 重启后运行上述 `start` 和 `observer-start` 即可从保存的数据库及账本恢复。

## 协议

本实现遵循 [OTLP JSON 协议](https://opentelemetry.io/docs/specs/otlp/#json-protobuf-encoding)：`resourceSpans → scopeSpans → spans`；字段使用 lowerCamelCase；trace/span ID 使用十六进制；枚举使用整数；纳秒时间和 int64 attribute 用十进制字符串。trace ID 为 16 字节、span ID 为 8 字节，具体字段来自 [官方 trace.proto](https://github.com/open-telemetry/opentelemetry-proto/blob/main/opentelemetry/proto/trace/v1/trace.proto)。

`trace.otlp.json` 本身是纯协议请求体，diagnostics 单独保存。本机接收链使用 `/v1/traces` 与 `application/json`；原始离线导出命令仍保持零网络行为，只有显式 `send` 或已启动观察器才进行本地投递。

```sh
python3 -m unittest tests.test_sermon_trace_export tests.test_sermon_observability -v
```

测试覆盖父子关系、跨 run 隔离、错误状态、缺少结束、时钟异常、脱敏、协议字段形式和原账本保护，以及实际 loopback HTTP、拒收/非法响应、代理/重定向隔离和旧 PID 保护。Trace 是执行观察视图；原账本继续作为费用与执行收据来源，生产质量与人工验收仍走原有门槛。

实际服务验证使用 [verify_sermon_observability.py](../scripts/verify_sermon_observability.py)，会停止再恢复本任务 Jaeger，因此应在没有其他操作员正在观察时运行。它验证真实账本快照送达、断线保留、Badger 重启恢复、稳定 ID 重送，以及观察器自动发现新完成阶段。验证报告保存在 `artifacts/observability/verification/`。2026-09-06 已在 Jaeger UI 目视确认原周六任务的 14 个父子 spans、生成阶段及缓存标签，另一个 trace 包含 4 个 spans。

最终实际验证收据为 `artifacts/observability/verification/2026-09-06T203308.050644_0000-8e4b71b0/receipt.json`：11 步通过，2 个真实 traces、18 个 spans 在重启后无需重发即可查询，重送不重复；运行中的测试观察器自动发现并送达新增账本的 4 个 spans。原始账本 SHA 不变。测试观察器已停止，正式观察器按上面列出的三个扫描根和 v3 数字修正版账本运行。
