# 同行 Beta 1.26.34（79）：证道与播客分列两个 Tab

2026-11-15 从提交 `666102595d759935fa15c35092b15f828ea64f04` 归档独立 Beta；它只把 BetaRelease 的 App 与实时活动扩展从 `1.26.33 (77)` 改为 `1.26.34 (79)`。候选基于 dev `68936118`（合并 [PR #1584](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/1584)）。Build 78 已由正式 1.26.33 使用，Beta 跳过该号。BetaDebug 与正式渠道配置未变。

本包从当前 dev 归档，因此除本次选择面板改动外，还包含 `1.26.33 (77)` 之后合并到 dev 的其它改动；它们由各自的 PR 与 CI 覆盖，本轮没有为它们新增 iOS 验收。

## 改动：选择面板分列证道与播客

- 工具栏入口从「选择证道周次」+ `calendar` 改为「选择证道与播客」+ `list.bullet`；`choose-sermon` identifier 不变。
- 面板标题在两类内容都存在时为「证道与播客」，只有一类时为「选择证道」／「选择播客」，标题改为 inline。
- 顶部固定分段控件按目录 `mediaType` 分列：证道列保留 legacy `weekly.json` 周次，播客列只放播客；打开时落在当前正在收听内容所在的分类；只有一类内容时不显示控件。
- 无障碍字号下用上下两个整宽按钮替代固定 13 pt 的分段标签。
- 设计、验证范围与未做项见 [PICKER-CONTENT-TABS.zh.md](PICKER-CONTENT-TABS.zh.md)。

## 本地验证

- `TongxingUITests` 定向 5 项通过（iPhone 17 / iOS 27.2，合成夹具）：`ContentPickerUITests.testPickerSeparatesSermonsFromPodcasts`、`testPickerLargeTypeUsesLabeledButtons`、`ListeningFlowUITests.testPickerSourceCategoriesBelowDate`、`testRemoteCategoriesUseInterfaceLanguageForNewPageTypes`、`testRemoteCategoryRefreshWithoutRebuildPreservesPausedPlayback`。改前／改后截图见忽略目录 `artifacts/tongxing-ios/2026-11-15/picker-tabs/`。
- `TongxingTests`（同 commit，Debug，iPhone 17 / iOS 27.2）：176 项执行、16 项跳过、0 失败。
- `TongxingBeta / BetaRelease` 模拟器构建成功；未跑完整 `ListeningFlowUITests`（约 56 项，含已知时间敏感用例），未做真机验收。
- CI：[PR #1584](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/1584) 的 `contract-validation` 与分片 `test-group` 全部通过，`native-client` 通过；dev 目标不运行 `ios-validation`（工作流只在 `main` 或手动触发时执行）。
- 首轮归档失败：本 worktree 缺本机 `Config/Local.xcconfig`，签名找不到 development team；补回该私有文件后重新归档成功，失败日志保留在 `artifacts/tongxing-ios/beta-1.26.34-build79-archive-20261115/`。

## 归档与包身份

Xcode 27.1（`27A9275`）／iOS SDK 27.1（`24A94232`）的 `TongxingBeta / BetaRelease` Archive。iOS module tree `2c9309f4e31f45f48b6ec76e1013f96df63a5482`，Archive 清单 SHA-256 `33063028bb68450314cc741ed1c41eac4e42ab19b57eb992dbe21cf8490d8814`（33 个文件）。包内 App 与扩展均为 `com.jonathanjing.tongxing.beta` / `…beta.listening-activity` `1.26.34 (79)`，显示名「同行-beta」，URL scheme `tongxing-beta`，内容源 `https://ai-for-god-sermon-audio-dev.web.app`。

同一 Archive 导出的 IPA 为 10,903,238 bytes、SHA-256 `d6f4718a21d977aa7232659e344bf422b90def97757e106a789a03acf0999f16`。

中文研读手册 JSON 与两张插图的 SHA-256 为 `a527e23fbd693177b9589fc89cd3533b653f64918abb97213cf34172c36711f9`、`f1d2f517120099a38614c7c560c1fbe054ec3ea4d741284fbcef496a7dab73b5`、`30c3e5b82c024bad3e40122f330f6606d022c91d8c77a82f06d6f1d5fc987f1f`，与 Archive 内文件一致；收据仍为 `machine_translation_not_human_reviewed`、`humanApproval=false`，App 内披露不变。

## TestFlight

- 2026-11-16 01:46:08 UTC 上传返回 `Successfully uploaded the new binary to App Store Connect`（fastlane 2.241.1，退出码 0）；上传意图与 IPA 哈希绑定。
- Apple 处理完成：构建 ID `cbfa86f9-1acb-4e13-be37-2e7ced47650d` 读回为 `VALID`、未过期、内部状态 `IN_BETA_TESTING`。
- 2026-11-16 01:55:29 UTC 关联现有内部组 Rooted，组内 build ID 读回包含该构建；What to Test 已保存（`notesSHA256` `6004dbc5bd229802a1ad6ec4c36280fa671f3999c0fe94dca6941e7c85fe1a82`）。
- 本轮没有新增测试组或外部测试者，不触发外部 Beta 审核。

What to Test：

```text
本版把内容选择面板从「选择证道」改成「证道与播客」：右上角内容按钮打开后，顶部固定显示「周日证道｜播客」两个分类，播客不再和证道混在同一张列表里。

请重点检查：
1. 正在收听某篇证道或播客时打开面板：应自动停在对应分类，并给当前内容显示对勾。
2. 切换分类：证道分类里不应出现播客，播客分类里不应出现证道；「其他周次」仍在证道分类底部。
3. 点选一条内容：面板关闭并切换到该内容，播放位置、音轨与下载状态正常。
4. 大字号（设置 → 辅助功能 → 显示与文字大小 → 更大字体）：面板顶部应变成上下两个整宽按钮，而不是分段控件。
5. 常规回归：播放/暂停、字幕、语言切换、离线下载。

本包内容源为 Firebase Dev，包含 dev 上自 1.26.33 (77) 之后合并的其它改动。
```

## 状态

`archive_succeeded`、`upload=internal_testing`（Apple 处理完成并已关联 Rooted 内部组）；`device=not_run`、`venue=not_run`。真机下载、安装、双击检查与大字号实测仍待人工确认；TestFlight 可用不等于功能验收通过。

证据保存在忽略目录：`artifacts/tongxing-ios/beta-1.26.34-build79-archive-20261115b/`（`archive.log`、`release-record.json`、`export/`、`export.log`、`what-to-test.txt`）、`artifacts/tongxing-ios/testflight/20261116T013716Z-7a2f0531`（上传）、`…014616Z-a0980868`（处理等待）、`…015528Z-eb944209`（分发）。签名配置、Team 与凭据均未进入 Git。
