# 复盘：PR #395 iOS 对齐定向验证

## 实际覆盖范围

在本地 iOS 模拟器运行 `AudioAlignmentControllerTests`，并在 SwiftPM 运行 `ListeningStatisticsTests`。只验证客户端对齐和匿名统计的代码行为；没有执行 L1–L4 生产、真实设备、会场、TestFlight 或发布。

## 结果和结束信号

`ios-test-summary-pr395/outcome.json` 记录 `passed`、退出码 0，原始 Xcode 日志的 SHA-256 可供本机核对。模拟器测试执行 43 项，跳过 2 项，失败 0 项；SwiftPM 定向测试通过。Xcode 输出 `TEST SUCCEEDED`。

## 耗时

模拟器 CLI 从 15:53:25 UTC 启动，约 15:55:00 UTC 结束。Xcode 报告测试操作耗时约 64 秒，43 项测试执行约 7.9 秒；本轮没有 `timings.tsv`，未与旧轮做逐阶段比较。

## 错误

没有测试失败。模拟器日志含测试桩 `example.invalid` 的预期网络错误；相关测试仍通过。提交 `852ec418` 修正暂停播放时的结果标记，以及匿名统计收到永久 4xx 后重用被拒绝凭据的问题。

## 占用资源之后才暴露的错误

没有观察到需要新增预检的错误。

## 遗留状态

本地 `artifacts/tongxing-ios/2026-10-14/cli/20261014T085325-test-33b8970c/` 保留日志和 xcresult；没有已知 Dev 文件、远端 job 或待清理构建号。

## 外部可见的变化

此测试没有发布、TestFlight 构建或受保护分支推送。真实设备与会场验收为 `not_run`。

## 后续

由当前维护者在 PR #395 合入前复核其 CI；真实设备及场地验收依既有发布流程另行进行。
