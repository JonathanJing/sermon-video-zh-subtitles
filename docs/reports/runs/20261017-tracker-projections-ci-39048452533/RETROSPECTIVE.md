# 复盘：20261017-tracker-projections-ci-39048452533

证据见同目录 `INDEX.md`、`manifest.json`、`outcome.json`、`summary.json` 和选取的 `root1.log`。完整日志留在 [GitHub Actions run 39048452533](https://github.com/JonathanJing/sermon-video-zh-subtitles/actions/runs/39048452533)。

## 结论先行

交付类型为测试。手动全量 Python 工作流在 Tracker PR #573 的提交 `bed0d841` 上终态 `failure`。八个 root shard 中七个成功，root1 失败；聚合 `unittest` 因 `TEST_GROUP_RESULT=failure` 失败。root1 仅有同一 strict Layer 2 测试的三个 HTTPError 子用例失败，均为全局 `sleep.assert_not_called()` 观测到其他线程的 `sleep(0.05)` 调用。原生客户端检查按工作流配置跳过。这是代码测试证据，不代表生产或设备验收。

## 总时间

工作流从 16:13:14 UTC 创建到 16:33:15 UTC 终态，约 20 分 1 秒，含排队与并行 shard；报告没有 journal，无法可靠拆分计算、等待和返工。root shard 各自报告的测试耗时不能相加当作墙钟时间。与之前局部测试的范围不同，不作速度比较。

## 各层模型、耗时与速度

L1–L4 均为 `not_run`。没有模型调用、token、音频秒数或费用；运行的是 CI Python 测试。

## 错误

| 阶段 | 现象 | 原因 | 发现时机 | 处理 | 回归测试 | 提交或 PR |
|---|---|---|---|---|---|---|
| root1 strict Layer 2 测试 | `test_ambiguous_http_and_transport_failures_stay_unknown_without_retry` 的 HTTPError index 0/1/2 在 `sleep.assert_not_called()` 失败；root1 701 项中 3 失败、1 跳过 | 测试在旧 head 上监视全局 `time.sleep`，并行运行的其他线程触发 `sleep(0.05)`；日志中分别记录 440889、504951、44880 次调用 | CI 预检 | #571 后续提交 `dba3fe06` 已把计时探针限定到 transport 模块，但不在本次测试的 `bed0d841` 中；本报告不把该提交视为本轮通过证据 | 尚无本 head 的复测结果；七个其他 shard 均成功 | #571 `dba3fe06`，#573 |
| 聚合 `unittest` | `TEST_GROUP_RESULT=failure`，exit 1 | root1 失败触发 full scope 的必需检查 | CI 预检 | 待后续准确 head 的 CI 证据 | 未复测 | #573 |

## 可以改进的地方

| 类别 | 改进 | 依据 | 预期收益 | 负责人 | 跟踪 |
|---|---|---|---|---|---|
| 质量 | 并行 CI 测试只 mock 被测 transport 的 sleep 引用 | root1 三个断言捕获大量无关 `sleep(0.05)` | 避免全局 mock 干扰并保留不重试行为断言 | #571 维护者 | #571 `dba3fe06` |

## 实际覆盖范围

root0、root2–root7 均成功；root1 运行 701 项后失败 3 项。八个 shard 总执行 5742 项（包括各自跳过的 38 项），这是分片执行次数，不是唯一测试数。L1–L4 真正执行、复用和发布均为 `not_run`。

## 遗留状态

当前被测 head 没有通过全量 CI 的收据。未执行新全量测试；没有远端 job hold 或生产产物需要清理。

## 外部可见的变化

仅 GitHub Actions 测试状态与本报告 PR 可见。Dev 发布、TestFlight、浏览器、设备和场地验收均为 `not_run`。
