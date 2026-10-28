# 复盘：20261028-ios-hide-alignment-runner-fail

数据见同目录 `INDEX.md`、`manifest.json` 与脱敏 `run.log`；精确运行产物保留在本机忽略目录。

## 结论先行

交付类型：iOS 界面测试。UI 测试重跑：失败。iPhone 17 Pro / iOS 26.2：UI Runner 未启动，xcodebuild 退出码 65；用例断言未执行。

## 总时间

日志未给出可信的各阶段计算／等待拆分，本报告不估计完整墙钟时间，也不与前一轮比较。

## 各层模型、耗时与速度

L1–L3：`not_run`。L4 iOS UI 测试重跑：失败，使用本机 Xcode 与 iOS Simulator。未调用模型；token、音频速度和模型费用不适用。

## 错误

Simulator 的 SBMainWorkspace 返回 Busy / Application failed preflight checks；随后改用 iOS 27.0 模拟器重跑并通过。

## 可以改进的地方

保留每次 `xcresult` 的实际执行数、失败数和跳过数；Simulator Runner 启动失败时先检查结果包，再在可用设备上定向重跑。负责人：iOS 开发执行者。

## 实际覆盖范围

此失败发生在 Runner 启动阶段，不作为 UI 行为失败或通过的证据。

## 遗留状态

没有本轮内容生产或远端 job。测试产物和截图保存在本机忽略目录；真机与现场验收均为 `not_run`。

## 外部可见的变化

本运行没有发布 App、内容页面或 TestFlight 构建。代码提交与 PR 单独记录。
