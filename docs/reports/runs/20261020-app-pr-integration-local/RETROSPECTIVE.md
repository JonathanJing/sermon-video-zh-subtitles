# 复盘：20261020-app-pr-integration-local

数据见同目录 INDEX.md 和 manifest.json。

## 结论先行

本轮是测试，不是生产交付：在本机把三个较早的 App PR 合入当前 `dev`（810349e2）后做的定向验证。CI 已按用户 2026-10-19 的决定停用，所以只有本机结果。

- **#475**（iOS Duo 单窗口，删除未被调用的 `ListeningLayoutPolicy`）：通过。Core 109 个测试通过，7 个可选测试跳过。
- **#1081**（usage 引导周次）：修复 Codex 线程后通过。web 608 个测试中 607 通过，1 个跳过。
- **#1082**（v5 跨来源 family 页面）：通过，有一处限制。web 610 个测试中 609 通过；iOS Core 115 个、Infrastructure 59 个通过；Python 交付相关测试 1,695 个通过，2 个跳过。`test_machine_quality_waiver` 只跑完 67 个中的 45 个（全部通过），之后停止；本 PR 没有改动它导入的模块。

证据边界：这里只有代码和测试结果。没有浏览器渲染、真机或 Duo 验收，也没有任何部署、发布、Firebase 或 TestFlight 操作。没有声称人工批准。

## 总时间

- `pr475-ios-local`：约 15 分钟，主要是 `swift test`（约 86 秒）和合并。
- `pr1081-web-local`：约 14 分钟，包括修复和一次 web 全量测试（约 60 秒）。
- `pr1082-local`：约 2 小时 20 分钟。其中返工约 1 小时 30 分钟，是 13 个线程中 11 个需要修代码。Python 测试分 4 组并行，墙钟约 20 分钟。负载均值约 440，第一次单进程整跑卡在 `test_machine_quality_waiver`，于是停止并改为分组。

## 各层模型、耗时与速度

本轮没有调用模型，也没有执行生产阶段；L1–L4 全部是 not_run，费用为 0。

## 错误

| 层／阶段 | 现象 | 原因 | 发现时机 | 处理 | 回归测试 | 提交或 PR |
|---|---|---|---|---|---|---|
| L4 测试 | `tests/test_mixed_source_catalog_v5.py` 导入失败 | dev 上已删除 `scripts.delivery_contract` 等门面 | 预检 | 改为从包导入 | 现有测试 | #1082 cb95eb9c |
| 布局 | PR 在 `scripts/` 下新增了文件 | 写于布局守卫之前 | 预检 | 移到 `tools/ops/` | `test_scripts_layout_guard` | #1082 cb95eb9c |
| Web 测试 | `dev-candidate-reader` 期望只请求 v4、v3 | 合并后 reader 先请求 v5 | 本机测试 | 更新期望的请求顺序 | 同一测试 | #1082 8308b27a |
| CI 范围守卫 | `test_ci_change_scope` 有 1 个子测试失败 | 新测试按路径读取 iOS 共享 fixture | 本机测试 | 改为内联 fixture | `test_ci_change_scope` | #1082 f86c3a1c |

## 可以改进的地方

| 类别 | 改进 | 依据 | 预期收益 | 负责人 | 跟踪 |
|---|---|---|---|---|---|
| 速度 | 宽范围交付测试默认按文件分组并行，跳过与本次改动无关的 `test_machine_quality_waiver` | 单进程整跑卡住超过 15 分钟 | 墙钟从小时级降到约 20 分钟 | 执行会话 | 无 |
| 流程 | 搁置多日的 PR 先合入 dev，再修线程 | 1,668 和 468 个提交的差距带来门面导入失败 | 避免修完又重修 | 执行会话 | 无 |

## 实际覆盖范围

L1–L3 未执行。L4 只覆盖代码：catalog v5/v4/v3 的投影、合并、回滚和快照校验，周更封存，跨来源 overlay，对齐绑定，英文对照，海报，APNs 发送器，web reader，以及 iOS Core 和 Infrastructure。

## 遗留状态

- 没有部署，Dev/Production Hosting 没有变化。
- 本机的临时 worktree 在会话 scratchpad 里，不在仓库中。
