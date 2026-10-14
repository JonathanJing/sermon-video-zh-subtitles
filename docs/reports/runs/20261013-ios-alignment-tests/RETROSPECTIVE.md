# 复盘：20261013-ios-alignment-tests

数据见同目录 INDEX.md 和 manifest.json。对应 PR #395（commit a84ca4f8）。

## 实际覆盖范围

只跑了 iOS 单元测试：`ios.sh test --only-testing TongxingTests/AudioAlignmentControllerTests`、全部 `TongxingTests`（iPhone 16 模拟器，iOS 18.0），以及 SwiftPM `ListeningStatisticsTests`。不涉及 L1–L4 生产；没有跑真机、TestFlight、UI 测试或会场测试。

## 结果和结束信号

两次 `ios.sh test` 退出码都是 0。定位控制器测试：42 项执行，40 通过，2 项跳过（需要 Beta 身份、冻结资料）。全部 TongxingTests：130 项执行，114 通过，16 项按环境条件跳过，0 失败。SwiftPM 统计测试：10 项通过，1 项在线测试默认跳过。

## 耗时

定位控制器测试约 70 秒（含构建），全部测试约 2 分钟。

## 错误

无。

## 占用资源之后才暴露的错误

无。

## 遗留状态

模拟器 iPhone 16 由脚本启动；测试产物在被忽略的 worktree `artifacts/tongxing-ios/2026-10-13/cli/`。

## 外部可见的变化

无部署、无 TestFlight。真机与会场验收均为 `not_run`。

## 后续

- 递增版本号并上传 TestFlight，真机验证 15 秒检查点、启动看门狗和统计上报：用户执行，跟踪 `DEV-FIELD-001`／`FIELD-03`。
- Swift 版 `cmn-v1` 影子对照与真机声道数确认：`FIELD-10`／`FIELD-04`。
