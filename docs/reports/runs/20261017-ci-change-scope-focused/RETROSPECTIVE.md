# 复盘：20261017-ci-change-scope-focused

## 结论先行

交付类型：本地测试。`python3 -m unittest tests.test_ci_change_scope tests.test_docs_change_gate -v` 退出码 0，16 个测试通过、无失败或跳过。证据为本报告的 `outcome.json` 与 `summary.json`；未执行完整 CI 或生产流程。

## 总时间

测试命令耗时 5.306 秒，来自命令执行结果。没有 journal，等待与返工未单独计量；没有可比的上一轮同范围运行。

## 各层模型、耗时与速度

本轮只运行 Python 标准库测试；L1–L4 模型、音频、发布均为 `not_run`，没有模型调用或费用。

## 错误

本轮未观察到测试失败。

## 可以改进的地方

本批不扩展测试范围。后续切换工作流调用路径时，须重新核对 required check 路由和完整 CI 结果。

## 实际覆盖范围

验证旧脚本、工具实现脚本和旧模块入口在临时非仓库 Git 工作目录中的 docs/native/full 分类；覆盖删除、重命名、空变更与无效 SHA 的保守回退。迁移前后 `tests.test_ci_change_scope` 的 7 个测试 ID 一一对应，未增删。`scripts.docs_change_gate` 的定向测试也执行。L1–L4 均未运行。

## 遗留状态

代码 PR #711 已开为草稿；完整 CI、PR 评审及合并尚未完成。本报告另开文档 PR，单独记录 16 项定向测试。

## 外部可见的变化

无 Dev 发布、TestFlight、受保护分支推送或设备验收。
