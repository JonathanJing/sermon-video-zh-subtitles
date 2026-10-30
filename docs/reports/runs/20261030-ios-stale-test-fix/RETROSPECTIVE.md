# 复盘：20261030-ios-stale-test-fix

数据见同目录 INDEX.md 和 manifest.json。未填写的小节删掉前请写明原因。

## 结论先行

交付类型：测试（只改测试代码，PR #1508，提交 `230d3d3b3b69825e05f427eece06ce4d69580149`）。修正后的三个用例在 iPhone 17 / iOS 26.2 与 iPhone 17 Pro Max / iOS 27.0 上均通过：`MachineDisclosureTests` 2/2，`testAccessibilityTextDockKeepsPlaybackControlsAvailable` 与 `testReviewedStudyProductsAreNotDisplayed` 2/2。修改前，这两项 UI 测试在同两台设备及 1.26.32 提交 `f596924b` 上均失败。整套测试未在本分支重跑。

## 总时间

两台设备并行运行，各自增量构建加测试约 3–5 分钟（18:31 UTC 起）。无模型计算，无等待。

## 各层模型、耗时与速度

本次无模型调用；L1–L4 生产均为 `not_run`。只运行 Xcode 27.1 的模拟器测试。

## 错误

| 层／阶段 | 现象 | 原因 | 发现时机 | 处理 | 回归测试 | 提交或 PR |
|---|---|---|---|---|---|---|
| UI 测试 | `testReviewedStudyProductsAreNotDisplayed` 恒失败 | 等待的 `published-full-transcript` 已在 `3a799f0d` 从阅读器移除 | 占用资源后（Beta 1.26.33 测试） | 改为等待韩语当前字幕并核对文本 | 本用例 | #1508 |
| UI 测试 | `testAccessibilityTextDockKeepsPlaybackControlsAvailable` 恒失败 | 43.999999999999986 pt 与 `>= 44` 无容差比较 | 同上 | 允许 0.01 pt | 本用例 | #1508 |
| 单元测试 | `MachineDisclosureTests…StaleSelections` 偶发失败 | 播放器就绪只等 2 秒 | 同上 | 改为 15 秒 | 本用例 | #1508 |

## 可以改进的地方

| 类别 | 改进 | 依据（本报告的数值或错误） | 预期收益 | 负责人 | 跟踪 |
|---|---|---|---|---|---|
| 流程 | 删除界面元素时一并搜索 UITests 中的标识 | `published-full-transcript` 移除后测试失效约两天 | 避免陈旧断言掩盖真实失败 | iOS | — |

## 实际覆盖范围

只运行三个修正用例；其余 `TongxingTests` 与 `ListeningFlowUITests` 未重跑（本分支未改 App 代码）。

## 遗留状态

无新构建号、无 TestFlight 变化。PR #1508 待合并。

## 外部可见的变化

无。仅推送分支 `claude/ios-fix-stale-tests` 与 PR #1508；TestFlight、App Store 与网页均为 `not_run`。
