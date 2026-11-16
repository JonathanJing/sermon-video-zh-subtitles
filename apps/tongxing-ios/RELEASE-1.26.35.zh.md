# 同行正式版 1.26.35（Build 81）

2026-11-16 从 dev `f49a136f` 归档正式候选；正式归档提交 `ecb821a68523c7d7c6d6f4356c2fb869d581e4be` 只把 Release 的 App 与扩展从 `1.26.34 (80)` 改为 `1.26.35 (81)`。上一版 1.26.34 (80) 已上架（`READY_FOR_SALE`），本版是随后的小版本更新。

## 相对 1.26.34 的改动

- **内容分类统一**：目录 `multilingual-v3/v4/v5.json` 增加 locale 无关的 `contentKind`（sermon／podcast／clip），`mediaType` 只作技术标记；客户端优先按 `contentKind` 分组，旧目录退回 `mediaType`。同期修复线上目录把 4 篇周日证道标成 `mediaType: podcast` 的问题（[目录内容类型](../../docs/catalog-content-kind.zh.md)）。
- **选篇面板每个 Tab 只有一张列表**：去掉「已发布页面／其他周次」分组，legacy `weekly.json` 周次并入证道列表按日期排序；Dev 构建用列表 footer 标注（[PR #1593](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/1593)）。
- **默认分类每次打开都跟随当前页面**，不再受上一次停留的 Tab 影响（[PR #1595](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/1595)）。

## 构建与包

Xcode 27.1（`27A9275`）／iOS SDK 27.1（`24A94232`）的 `Tongxing / Release` Archive。Archive 清单 SHA-256 `6b2b0b8b9686239731d0c3f04e175ee5cc85fa67f9b5a5e20d2f29787cc85cb0`，源码 `ecb821a6…`。包内 App 与扩展均为 `com.jonathanjing.tongxing.dev` / `…dev.listening-activity` `1.26.35 (81)`，显示名「同行」，内容源 `https://ai-for-god-sermon-audio.web.app`。

本轮用 `xcodebuild -exportArchive`（`destination=upload`）直接上传，2026-11-16 18:03:03 UTC 返回 `Upload succeeded` / `EXPORT SUCCEEDED`，退出码 0；未单独保留 IPA 副本，因此本轮没有 IPA 文件哈希。Apple 于 18:04Z 读回 Build 81 为 `VALID`。

中文研读手册沿用同一候选（`a527e23f…`、`f1d2f517…`、`30c3e5b8…`），收据仍为 `machine_translation_not_human_reviewed`、`humanApproval=false`，App 内披露不变。

## 商店截图

用 `Tongxing / Release` 模拟器构建（生产内容源）在 iPhone 18 Pro Max（1320×2868）上截取，状态栏统一为 9:41：

- 简中、英文各 3 张：①当前字幕 ②证道与播客面板（新界面）③字幕全文；替换了 `APP_IPHONE_67` 原 6 张旧素材（旧素材仍是两段式面板之前的样子）。
- `APP_IPHONE_61`（2）、`APP_IPAD_PRO_3GEN_129`（8）、`APP_IPHONE_DUO`（2）沿用上一版继承的素材。
- 截图由 API 逐张 reserve／upload／patch 上传，读回全部 `COMPLETE`；旧截图集在全部完成后删除。

**Duo 屏幕截图未更新**：本机的 Xcode 安装不含 `Simulator.app`（`/Applications/Xcode.app/Contents/Developer/Applications` 不存在），Duo 模拟器以展开状态运行且无法在无 GUI 下折叠；`simctl io screenshot --display=1`（外屏 LCD，1398×2034）返回全黑，只有 `--display=3`（内屏，2007×2853）有画面。因此没有替换 `APP_IPHONE_DUO` 的两张旧图，也没有把内屏尺寸硬塞进外屏槽位。

## App Store Connect

- 版本 `0d1c993f-b331-4cfc-88f8-5c207aefca20`（`1.26.35`，创建时继承五种语言的商店文案），关联 Build `5235c453-d3f1-49a2-9fff-057a37a5bb1e`，发布方式 `MANUAL`。
- 五种语言更新说明已写入并读回一致；审核备注说明本版只调整内容选择面板，没有新增权限、麦克风行为或数据收集，中文手册仍为机器翻译、`humanApproval=false`。
- 2026-11-16 18:11:42 UTC 提交审核 `cbfaf5e0-ed81-4ada-8eb3-f57764358164`；18:12Z 读回版本与提交均为 `WAITING_FOR_REVIEW`。

## 已知缺口

- 真机安装、真实听感与现场验收 `not_run`；本地证据为模拟器与合成/线上目录数据。
- Duo 外屏截图与内屏正式素材待补（需要可折叠的 Simulator GUI 或真机）。
- 通过审核后需人工在 App Store Connect 点发布（`MANUAL`）。

## 证据

忽略目录 `artifacts/tongxing-ios/production-1.26.35/`：`archive/`（`archive.log`、`release-record.json`、`Tongxing.xcarchive`、`upload.log`）、`shots/`（全部原始截图）、`final/`（上传的三张成品与收据 `zh-receipt.json`、`en-receipt.json`）、`final-state.json`、`shots-12634.json`。签名配置、Team 与凭据未进入 Git。
