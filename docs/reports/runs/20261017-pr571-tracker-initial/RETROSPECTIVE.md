# 复盘：20261017-pr571-tracker-initial

## 结论先行

交付类型：本地定向测试。`outcome.json` 记录 `failed`，测试摘要为 97 passed、2 failed、62 subtests passed。失败：两处 Tracker sidecar 行为回归，后续修复见 `20261017-pr571-tracker-repair`。这份报告由本地测试结果摘要补录，未保留完整 pytest 输出；只支持上述测试结论。本轮只执行离线本地 pytest；L1–L4 的真实生产、模型调用、发布、设备播放及场地验收均为 `not_run`。

## 总时间

本轮没有保存开始、结束时间或阶段计时，无法计算墙钟、计算、等待与返工时间，也无法与历史运行比较。

## 各层模型、耗时与速度

本轮没有调用模型或远端计算；L1、L2、L3、L4 生产阶段均为 `not_run`。模型、tier、token、音频秒数、费用和速度均不适用，也没有相关收据。

## 错误

| 阶段 | 现象 | 原因 | 发现时机 | 处理 | 回归测试 | 提交或 PR |
|---|---|---|---|---|---|---|
| Tracker 快照 / DAG 投影 | 缺失 sidecar 引用使公开投影变为 `unavailable`；非私有权限 sidecar 直接抛错 | 快照复制器先于规范读取器处理无效 sidecar，未留下损坏行诊断 | 本地定向测试 | 在 Tracker 分支修正复制器，缺失或无效 sidecar 留给规范读取器计数 | `tracker-repair`：37 passed、3 subtests passed | 本地提交 `c972c1cb`，代码分支尚未推送 |

## 可以改进的地方

| 类别 | 改进 | 依据 | 预期收益 | 负责人 | 跟踪 |
|---|---|---|---|---|---|
| 质量 | 为非私有 sidecar 增加公开投影回归断言 | 本轮 2 个失败，其中一个直接抛错 | 保持 `partial` 和受影响行数的可审计性 | Tracker 分支 | 本地提交 `c972c1cb`，代码分支尚未推送 |

## 实际覆盖范围

Tracker 快照、DAG 投影、记账与 sidecar 的五个测试文件：`.venv/bin/python -m pytest -q tests/test_build_four_layer_tracker_snapshot.py tests/test_build_tracker_dag_projection.py tests/test_accounting_log_contract.py tests/test_sermon_durable_accounting.py tests/test_verify_sermon_observability_sidecars.py`。本轮测试使用对应工作树的 Python 环境；这是代码回归覆盖，不是生产输入、提供商、质检、发布或设备验收。本轮只执行离线本地 pytest；L1–L4 的真实生产、模型调用、发布、设备播放及场地验收均为 `not_run`。

## 遗留状态

本轮未创建 Dev 发布、远端 job hold 或构建号。代码分支尚未推送；本地测试摘要与脱敏报告保留在忽略的 `artifacts/` 目录。

## 外部可见的变化

本轮没有 Dev 发布、TestFlight 构建、生产调用、设备播放或场地验收。文档报告草稿 PR 会单独发布；它不代表代码分支已推送或合并。
