# iOS 完整文稿：回到当前句候选

本轮落实 [backlog PR #243](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/243) 的 IOS-11，保留其余内容、锁屏与系统控件事项。

## 行为与身份

在「字幕全文」中手动阅读其他位置后，点固定工具栏的「回到当前句」按钮，将当前音频对应段落滚到阅读区域；保留全文模式、音频位置及播放／暂停状态。legacy cues 与 published captions 使用各自真实行 ID；间隙／结尾取上一句，开头前取第一句，无字幕时禁用。published 播放工具栏的现有入口也接入相同行为。

基线为 `ecbc92151587c187ebe25cc78a221591cc042842`。初版 `a53550a55af9809f25655ce1c33760324237af20` 未通过强化测试；最终实现 `acc606671559fba43ccc21599632c7496d3073e0` 统一了 ForEach 数据身份与滚动锚点，保留懒加载、Core 数据及播放器行为。未修改内容、schema 或发行号码。构建配置为 `1.26.10 (51)` 的本地开发构建，不代表新的分发包。

## 证据

真实执行设备：iPhone 18 Pro Simulator、iOS 27.0、Xcode 27.1 (27A9269)、竖屏、简体中文界面及音轨、合成测试音频。

本地产物均在忽略目录 `artifacts/tongxing-ios/2026-10-04/`，并非 PR 附件；截图已读取检查。以下路径相对该目录：

| 项目 | 产物与实际结果 |
| --- | --- |
| 构建 | `cli/20261004T160108-build-a1b57a7a/build.xcresult`，退出 0 |
| 改前预览 | `preview/20261004T155931-b0a63112/manifest.json`，浅色与深色大字 PNG |
| 改后预览 | `preview/20261004T160317-86e2a068/manifest.json`，退出 0；同条件 PNG 已检查 |
| 首次 UI 测试 | `cli/20261004T160214-test-a536cf84/test.xcresult`，1 通过、0 失败；截图发现短样本未将当前句滚出屏幕，因此不作为完整找回证明 |
| 加强测试 | `cli/20261004T160348-test-9d9e22f7/test.xcresult`，1 失败：默认字号下三句仍同时可见，点击前不可见断言失败；保留失败产物 |
| 大字强化测试 | `cli/20261004T160503-test-400c10b6/test.xcresult`，1 失败：当前句已离屏，点击后未找回；暴露初版懒加载身份问题 |
| 修复后构建 | `cli/20261004T160818-build-6b3d0f19/build.xcresult`，退出 0 |
| 修复后 UI 测试 | `cli/20261004T160838-test-390afe66/test.xcresult`，退出 0，2 通过、0 失败、0 跳过 |
| 最终预览 | `preview/20261004T161059-f5a35997/manifest.json`，退出 0；浅色／深色大字 PNG 已检查，源文件对应 `acc6066` |

最终 UI 测试包括 `testFullTranscriptReturnToCurrentKeepsPausePositionAndReadingMode`（大字号 published 样本：先断言当前句不可见，再点击固定入口，确认当前句可见、00:12 暂停和全文模式保留）及既有 `testOpeningTranscriptWhilePlayingLocatesCurrentCueOnlyOnce`（legacy 大字号：播放中打开全文定位，手动阅读不随播放抢滚动，暂停后再打开保留阅读入口）。

实际离屏／找回截图分别为 `cli/20261004T160838-test-390afe66/attachments/6032F733-9349-42CA-AA85-D67854FCEF1F.png` 和 `843B4B1C-60BF-4FB5-B87A-BCE17A726AF9.png`；已读取，两图属于同一最终实现及样本的操作前后，不是改前代码截图。

预览 Manifest 如实记录执行时基线 commit、dirty 状态与源文件 SHA-256；改后 `ContentView.swift` SHA-256 为 `99779b5e7d6917745c99adcbb78c49f170ea6f403b356a81cc02181c2faa6e1b`。预览是「现场收听」样本的布局对照，不冒充改前／改后完整文稿交互对照。

最终预览记录 `acc6066`，dirty 只包含尚未提交的本报告，源文件 SHA-256 为 `f70432dc21a8b0566a9d326a4001c114995818849ec1465405226a0917126815`。交互通过数不包含预览截图测试。

独立审核者初次静态审核未发现问题；实际大字测试失败后撤回此结论，协助定位 ForEach 与锚点身份差异。对最终实现 `acc6066` 重新只读审核后未发现需修复问题。机器审核不代替人工 UI 确认。

## 剩余验收与网页

人工 iOS 确认、真机、最低支持系统、小屏、横屏、VoiceOver 实际操作、legacy 固定入口及 published 播放中回中：`not_run`。深色大字预览为截图证据，不代表完整文稿在这些条件下交互通过。现有深色大字播放 dock 遮住部分滚动内容，未在本轮处理。

网页为 `deferred`：待 IOS-11 原生交互人工确认后检查 Firebase 网页对应定位意图，不照搬原生工具栏。锁屏标题／双语字幕、系统播放控件、灵动岛和提纲／反思仍在 #243 中，未宣称完成。

本轮不包含合并、TestFlight、App Store、网页部署、生产内容重跑或现场验收。
