# 同行-beta 1.26.9 (50) 分发记录

后续验收：用户报告 iPhone 17 / iOS 27.0.1 真机定位时没有看到灵动岛。当前前台展示仍未解决，见 [诊断与失败证据](BETA-ISLAND-DIAGNOSTIC.zh.md)；Testing 不代表此项验收通过。后续源码候选尚未上传，以下冻结来源与上传记录保持原绑定。

2026-10-03，用户授权「检查设计，写 PR，推送到 Beta TestFlight」。正式 App 与正式内容部署继续等待 Beta 人工核对。本轮使用独立 branch/worktree，PR [#232](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/232) 指向 dev，未合并。

## 冻结来源与包身份

- 归档源码：`a74a1b3256116390a2a6ccdde5ea983c58a55ddf`，分支 `codex/ios-beta-alignment-notifications`，上传前已核远端 commit。
- 版本／Build：`1.26.9 (50)`，App 与扩展一致；正式配置仍为 `1.26.7 (50)`。
- 原 Beta `1.26.8 (49)` 保留；本次纳入其既有 `40522e1` Dev 播客候选读取功能，防止升级倒退。
- 配置：`TongxingBeta / BetaRelease`；App `com.jonathanjing.tongxing.beta`，扩展 `com.jonathanjing.tongxing.beta.listening-activity`，返回链接 `tongxing-beta`，名称「同行-beta」。
- 内容源：`https://ai-for-god-sermon-audio-dev.web.app`。
- 工具链：Xcode `27.1 / 27A9269`，iOS SDK `27.1 / 24A94403`。
- 最终 Archive manifest SHA-256：`5bbbf8bcf6f6c58cdef5f27742d42e1846d33f5868fbd978ab8c99428d8d500f`。

`archive-channel.sh` 核对实际包内版本、App/扩展身份、URL scheme 和内容源；最终归档成功。`codesign --verify --deep --strict` 通过。较早的 `b541c59` Archive 保留但未上传；最终包包含已翻译的错误弹窗标题。本记录为归档后的分发证据，不改变上述源码绑定。

## 设计与验证

设计与修改见 [设计检查](BETA-DESIGN-REVIEW.zh.md)。最终精确源码已独立只读复审，无上传阻塞项；语言键、内容选择、权限／操作反馈和约 5 秒触发语义已修正。Demo 保留同片段 Beta 信息层级；通知内容语言和界面语言独立。

| 实际验证 | 结果 |
| --- | --- |
| Core 完整测试，含 Beta49 候选读取与通知契约 | 76 通过 |
| 本轮基线正常／大字 Demo 和通知退出 UI | 3 通过 |
| 修复后通知默认关闭／退出、English UI／中文内容、系统通知显示与点击、Demo 布局 | 4 通过，0 失败；首次 live 未开开关 1 跳过 |
| 显式开启后的真实 Dev Eric 原声进度、App 内同片段视频及返回暂停 | 1 通过，0 跳过 |
| Python 原生／共享／归档契约定向 suite | 59 通过 |
| 成功 UI xcresult 的 runtime warnings | 0 |

Core/UI 测试对应功能源码 `b541c59`；最终源码相对它只有归档夹具版本和弹窗复用已翻译标题，已复审并重新签名归档。本轮最初系统 Python 和 bundled Python 缺 `jsonschema`，依赖环境失败不记作通过；最终使用现有 repo venv 执行完整 59 项通过。CI 最初失败来自归档 fixture 硬编码旧 Beta 48，已修复；远端 iOS `native-client`／`contract-validation` 已通过，`ios-validation` 按 dev 策略跳过；归档 fixture 变更触发的仓库全量 Python CI 尚在运行，不记为通过，状态以 PR 最新检查为准。

初版 `927f73e` 的 Beta 对齐／活动内容／Demo 32 项（另 1 跳过）、播放器 31 项、最低 iOS 17.5 对齐／活动内容 23 项、正式身份与不显示通知实验入口 2 项均通过；本轮未为未改逻辑重跑这些项目。系统 ActivityKit 在自动测试中禁用，不能据此认定真实灵动岛、麦克风或锁屏通过。

## 分发状态

2026-10-03 **17:07:00 UTC**，`xcodebuild -exportArchive` 上传退出码 0，日志含 `Upload succeeded` 与 `EXPORT SUCCEEDED`。上传成功与 Apple 处理／测试组状态分别记录。Apple 随后完成处理，构建已关联现有 Rooted 内部组（1 个现有测试账户）；What to Test 已保存。组内 readback 已确认 **1.26.9 (50) / Testing**，同组保留之前 3 个构建；没有增加测试账户。测试说明界面显示 `Saved`。这证明 Apple 内部测试分发状态，真机下载／安装与功能验收仍待人工确认。

不提交外部 Beta 审核，不更新正式 App，不部署正式 Firebase，不发送远端 APNs 或海报附件。真机安装、通知冷启动、灵动岛／麦克风／锁屏及真人听感为 `not_run`。

## 人工测试重点

1. 在 TestFlight 更新「同行-beta」，核对 `1.26.9 (50)`，正式 App 与 Beta 共存，内容为 Dev。
2. 更多选项 → Demo → Eric，核对同片段原声／视频、中韩西样音、译文与来源；切语言停止旧声音，视频返回保持暂停。
3. 使用已具备同来源指纹的内容启动现场对齐：准备→真实采集后监听→本机匹配→成功／取消／失败；核对灵动岛和锁屏、暂停或切内容、退后台与立即再试。
4. 更多选项 → Beta 通知测试：默认关闭，独立内容语言，显式允许系统通知，选择有该语言的内容，安排一条本机通知；约 5 秒是最早触发，实际显示时间由系统决定。前台／后台／锁屏分别核对。
5. 点击通知确认正确 Dev 内容和语言；测试已结束进程的冷启动。退出或改语言后不再安排旧通知；同版本重复提示，主动清除后可重试。
6. English／韩／西／越界面与内容语言分开切换；大字、深色、VoiceOver 检查。现有 Dev ES／KO 播客候选仍可读取，不代表新增人工内容批准。

正式晋升遵循 [Beta 晋升](BETA-PROMOTION.zh.md)，还需同源正式 V2 Demo 内容及媒体部署验证；本次仅 Beta 分发。

## 私有证据

本工作树忽略目录：`artifacts/tongxing-ios/beta-1.26.9-build50-final/` 保存最终 Archive、归档／上传日志、ExportOptions 与 `release-record.json`；较早未上传归档在 `beta-1.26.9-build50/`。不提交签名、Team、账号、设备或凭据。

本轮截图与 manifest：`artifacts/tongxing-ios/2026-10-03/design-audit/{before,after,live-dev}/`；逐张读取核对后的视觉报告为 `design-audit/report.md`，测试摘要为 `beta50-validation.json`。本轮 UI run：`20261003T092317-test-2bc59e5f`、`20261003T092737-test-608b62a2`、`20261003T092949-test-fe6b156b`。原始 `.xcresult` 与状态位于对应 `cli/` run；这些路径不假设其他 checkout 存在。

TestFlight 状态原始截图与 AX：`testflight-internal-testing.jpg`、`testflight-internal-testing.ax.txt`；测试说明 `testflight-notes-saved.jpg`、`testflight-notes-saved.ax.txt` 和 `what-to-test.txt` 均在最终归档证据目录。
