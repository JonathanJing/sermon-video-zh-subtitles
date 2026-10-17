# 复盘：#661 旧 dev 基线 Python CI

## 结论先行

测试交付；CI 运行 [39049502001](https://github.com/JonathanJing/sermon-video-zh-subtitles/actions/runs/39049502001) 在 #661 的 `f43b562f4f7ba0d9df4e534fbc8847827aaa3185` 上终态为 **failure**。8 个 Python 分片中 7 个成功、root-7 失败；汇总 `unittest` 门禁随之失败。此运行不能证明 #661 迁移通过，也不能证明它与 #571 合并后的结果。未执行生产运行。

## 总时间

GitHub Actions 记录 2026-10-17 16:27:43–16:48:18 UTC，墙钟 20 分 35 秒。root-7 单元测试自身 877.497 秒；阶段间等待和返工未单独计量。

## 各层模型、耗时与速度

L1–L4 均为 `not_run`。这轮仅执行 CI，模型调用 0、费用 0，无 token 或音频速度数据。

## 错误

| 阶段 | 现象 | 判断与边界 |
|---|---|---|
| root-7 账本写入 | 3 项测试在 `workflow_started` 事件写入时遇 `ContractError: event_size_limit`，上抛为 `AccountingWriteError`。涉及 strict locale preflight、clock handshake、telemetry 008。 | 该 CI head 不含 #571 的 sidecar 修复；调用栈在 `observability/accounting.py`、`outbox.py`、`log_contract.py`，与已知基线依赖问题一致。这不能作为 #661 搬移自身的失败定论。 |
| root-7 unified CLI | 2 项断言看到调用序列只到 `media`，未到预期 `audio-zh`，其中一项也未到 `release-zh`。 | 是当前旧基线上的真实失败；日志未单独证明其根因，也未证明它一定由前三项错误连带产生。组合后仍需验证。 |
| `unittest` 汇总门禁 | `TEST_GROUP_RESULT=failure`，汇总 job 退出 1。 | root-7 失败的下游门禁结果，不是另一组独立单测失败。 |

root-7 汇总：729 项，2 failures、3 errors、7 skipped。其他 7 个 Python 分片成功；Native and shared client contracts 按本轮选择器跳过。

## 可以改进的地方

在 #661 依赖接入 #571 后，针对同一组合重新执行受影响测试和 CI，并分别核对三处账本错误与两个 unified 调用序列。负责人：#661 集成者；跟踪：[代码 PR #661](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/661) 与 [#571](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/571)。本报告没有触发重跑。

## 实际覆盖范围

执行 Python tests workflow 的 8 个分片；未执行真实 L1–L4、Spark 校准、发布、浏览器或设备验收。此报告只描述旧 dev 基线 `f43b562f` 的 CI 运行。

## 遗留状态

#661 仍为草稿；旧基线 CI 失败。#571 sidecar 修复不在本轮 head 中，组合后的测试状态未知。没有本轮生产作业状态或模型费用。

## 外部可见的变化

本轮只形成 GitHub Actions 失败记录和本 docs-only 报告 PR；没有 dev 合并、发布、设备播放或场地验收。
