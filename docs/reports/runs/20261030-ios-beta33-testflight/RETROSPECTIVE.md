# 复盘：20261030-ios-beta33-testflight

数据见同目录 INDEX.md 和 manifest.json。未填写的小节删掉前请写明原因。

## 结论先行

交付类型：iOS 内部 TestFlight 分发（测试）。独立 Beta `1.26.33 (77)` 从提交 `96d2bc00d0d2368bfdab85adba7c7835a2ecd884`（dev `eeef384d` + BetaRelease 版本号）归档、导出、上传、等待和分发，五个命令退出码均为 0。Apple 于 2026-10-30 17:53:08 UTC 读回 Build ID `201ec360-cb15-442c-be1b-ce8f5f5192e1`：`VALID`、未过期、`IN_BETA_TESTING`，Rooted 组包含该 Build；17:53:55 UTC 分发读回 What to Test。此结果不证明手机安装、真实麦克风对齐或现场测试通过。

## 总时间

约 17:39–18:21 UTC，计算与等待交错：Archive 约 3 分钟（17:39–17:42），导出约 1 分钟，上传 57 秒（17:43:49–17:44:46），Apple 处理约 8 分钟（17:45–17:53），分发读回 17:53:55。单元测试与 `ListeningFlowUITests` 并行进行，UI 套件 1,447 秒；两项失败的重跑与 1.26.32 基线对照另用约 20 分钟（基线冷构建）。无模型计算。

## 各层模型、耗时与速度

本次无模型调用；L1–L3 为 `not_run`。L4 客户端使用 Xcode 27.1／iOS SDK 27.1、fastlane 2.241.1 与 App Store Connect API。

## 错误

| 层／阶段 | 现象 | 原因 | 发现时机 | 处理 | 回归测试 | 提交或 PR |
|---|---|---|---|---|---|---|
| 预检 | 主 checkout 的 `GuideResources/` 为空 | 手册载荷被 Git 忽略，只在 1.26.32 的手册工作树中 | 预检 | 从同一候选复制五个文件，三项哈希与固定值核对后归档 | IPA 内哈希复核 | — |
| 单元测试 | `MachineDisclosureTests…StaleSelections` 在 iOS 26.2 首轮失败 | 播放器就绪等待上限 2 秒，冷启动模拟器且与归档并行 | 占用资源后（未影响上传） | iOS 27.0 单独重跑 1.73 秒通过，整套 169/0 失败 | 待放宽等待 | 待开 |
| UI 测试 | `testAccessibilityTextDockKeepsPlaybackControlsAvailable` 失败 | 宽度 43.999999999999986 pt，`>= 44` 无容差 | 占用资源后 | iOS 27.0 重跑与 1.26.32 基线同样失败，非本轮引入 | 待修测试 | 待开 |
| UI 测试 | `testReviewedStudyProductsAreNotDisplayed` 失败 | 等待的 `published-full-transcript` 标识已在 `3a799f0d` 从 App 移除 | 占用资源后 | 同上，基线同样失败；“不显示审核学习材料”的断言通过 | 待修测试 | 待开 |
| 分发 | `--notes` 收到正文报 File name too long | 参数要求文件路径 | 预检（Apple 未收到请求） | 改传文件路径 | — | — |

## 可以改进的地方

| 类别 | 改进 | 依据（本报告的数值或错误） | 预期收益 | 负责人 | 跟踪 |
|---|---|---|---|---|---|
| 质量 | 修正两项陈旧 UI 测试并放宽就绪等待 | 两项 UI 失败自 1.26.32 起存在 | 让 Beta 前的 UI 套件能给出干净结论 | iOS | 待开 |
| 预检 | 归档前检查 BetaRelease 的手册载荷是否在场 | 主 checkout 载荷为空时 BetaRelease 会静默不带手册 | 避免发出缺手册的 Beta | iOS | 待开 |
| 流程 | 测试用独立、未占用的模拟器，不与归档并行 | 首轮单元失败只在负载下出现 | 减少时间敏感误报 | 操作者 | — |

## 实际覆盖范围

L1–L3：`not_run`（客户端版本发布，不改内容）。L4 客户端：Archive、IPA 导出与严格签名检查、上传、Apple 处理、Rooted 分发均执行。IPA SHA-256 `d4a0ea39039ff4e9ed585df405f5b8cf9b862124fe3289be0002fcc4528f145c`，Archive 清单 SHA-256 `76b831c351cbddfd9996ea047b2229726ff25f23082b55b22307c50dde212dc2`。中文手册 JSON 与两张插图沿用 1.26.32 的同一候选（`humanApproval=false`）。`TongxingTests` iOS 27.0：169 执行，16 跳过，0 失败；`ListeningFlowUITests` iOS 26.2：56 执行，49 通过，5 跳过，2 失败（见上）。

## 遗留状态

已用构建号：Beta `1.26.33 (77)`；下一候选从 `1.26.34`、Build 78 起。本机 Archive、IPA 与收据在 `.claude/worktrees/ios-beta-1.26.33/artifacts/` 下，不进 Git。真机安装、真实麦克风对齐与自动播放、iPad／Duo 的 popover 位置与现场声学测试为 `not_run`。

## 外部可见的变化

Rooted 内部测试组现关联 `1.26.33 (77)`；What to Test 已保存并读回，SHA-256 为 `19e447f4a57557fee00eb9d0488335d6990a24b767c1f500a7493665011a7170`。源码与发行记录见 PR #1506。正式 App 与 App Store 提交均为 `not_run`。
