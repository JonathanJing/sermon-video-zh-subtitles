# 复盘：20261014-pr390-review-fix

数据见同目录 INDEX.md、manifest.json、outcome.json、summary.json 和 timings.tsv。

## 结论先行

- 高置信结论：在正确测试入口下，Node 定向测试 27/27、Python 定向测试 22/22 通过，最终状态为 `pass_after_entrypoint_retry`、退出码 0。
- 证据边界：首次仓库根 Python 入口因测试本地模块导入路径失败；报告只绑定提交 `ace03ce8ba8c2ebf015795162393f4f631e39b46`，生产部署、浏览器、真机和场地均未运行。
- 处置建议：本报告可在同步最新 `dev` 并确认检查保持绿色后转 Ready／合并；若要证明其他提交或线上行为，须另行运行并留证。

## 实际覆盖范围

本轮只验证 PR #390 review 修复及 dev 冲突处理的本地定向代码行为，不是 L1–L4 内容生产。Node 覆盖 `alignment-usage.test.mjs`、feedback API 的 `alignment.test.mjs` 和 `field-venue-benchmark.test.mjs`；Python 覆盖 `test_feedback_rollout.py`。被测身份由 outcome 绑定到提交 `ace03ce8ba8c2ebf015795162393f4f631e39b46`。没有执行生产部署、浏览器渲染、真实设备播放或场地验收。

## 结果和结束信号

`outcome.json` 为 `pass_after_entrypoint_retry`、退出码 0，起止时间为 2026-10-14 17:01:00–17:02:07 UTC。Node 27/27 通过、0 失败；Python 在正确测试目录重试后 22/22 通过、0 失败。首次仓库根 Python 入口失败保留在 `timings.tsv`，没有被最终通过覆盖。本轮不使用独占 Spark，因此没有 `round:` 结束信号。

## 耗时

`timings.tsv` 记录 Node 测试 2.79 秒、首次 Python 根入口失败 0.11 秒、正确测试目录重试 0.51 秒、`git diff --check` 0.20 秒，已记录阶段合计 3.61 秒。outcome 墙钟区间为 67 秒；报告没有 journal，剩余时间无法可靠拆成计算、等待或返工，也没有同口径上一轮可比较。

## 错误

首次从仓库根执行 Python 测试时无法解析测试目录内的模块，阶段在 0.11 秒后失败。按 summary 记录的 `retryReason`，从该测试文件使用的预期测试目录重跑后 22/22 通过。报告没有记录为此修改代码或测试环境，因此本复盘只把它归类为入口路径问题，不宣称已有新的代码回归修复。

## 占用资源之后才暴露的错误

入口路径问题在本地 Python 阶段 0.11 秒内暴露，发生在任何生产部署、浏览器、设备或场地阶段之前。报告没有远端计算、Spark 或付费模型派发证据；后续同类定向验证应直接使用测试文件预期的工作目录，或在预检中核对模块搜索路径。

## 遗留状态

manifest 完整复制了 outcome、summary 和 timings，没有列出被跳过文件。原始运行根仍在本地忽略目录。报告没有记录 Dev 文件、远端 job hold、构建号或清理收据；由于生产部署为 `not_run`，没有本轮发布产物可据此声明已清理。

## 外部可见的变化

`productionDeployment=not_run`；summary 另记 `browserRendering=not_run`、`realDevicePlayback=not_run`、`venueAcceptance=not_run`。TestFlight 和受保护分支推送未在导出 evidence 中记录，状态为未知，不能写成已执行或已通过。本报告只证明绑定提交的本地定向测试结果。

## 后续

维护者在 PR #390 的证据链中把本报告限定到提交 `ace03ce8ba8c2ebf015795162393f4f631e39b46`。若评审目标是不同提交或最终 head，应重新运行相同测试并导出新的绑定报告；部署、浏览器、真机和场地证据分别按各自流程补充，不由本报告推断。
