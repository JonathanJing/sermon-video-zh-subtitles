# 同行正式版 1.26.7

## 候选与授权

2026-10-01，用户确认“beta检查没有问题”，要求正式构建 `1.26.7`、补齐更新材料和更多截图、提交发布。Beta 真机验收来源是用户确认；本次 Agent 的模拟器验证与现场验收分开记录。

- dev 基线：`7e534bb6eaf2a414def5bbd99167d6898a07b5b5`。
- 已验收 Beta 48 源码：`fac0c9c4769ad25a86d97ae4fa82dfb1a5c49bd7`。
- 首轮 Build 49 归档源码：`86b506f4c2dd7126b66f95912b164a80e09b6c16`；分支 `codex/release-1.26.7`。该构建由 Apple 拒绝加入正式审核，保留独立记录；后续 Build 50 使用正式工具链重建。
- 用户指定本次 `1.26.7`，覆盖先前的 `1.26.1` 起步计划；未制造 `1.26.1` 至 `.6` 的历史构建。下一新候选使用 `1.26.8`，见 [版本约定](VERSIONING.zh.md)。
- 正式构建前观察到线上 `1.1.0`，正式 App 最高已上传 `1.2.0 (46)`，独立 Beta 最高 48；因此分配新的 Apple Build 49。

## 渠道差异

App、共享模型、扩展、Core 和 Infrastructure 功能源码与 Beta 48 一致。正式包从冻结源码重新归档，不重新签名 Beta IPA。

| 字段 | 已验收 Beta | 正式候选 |
| --- | --- | --- |
| 版本 / Build | `1.2.0 (48)` | `1.26.7 (50)` |
| Scheme / 配置 | `TongxingBeta / BetaRelease` | `Tongxing / Release` |
| 名称 | 同行-beta | 同行 |
| App Bundle ID | `com.jonathanjing.tongxing.beta` | `com.jonathanjing.tongxing.dev`（已注册的正式身份） |
| 扩展 Bundle ID | `com.jonathanjing.tongxing.beta.listening-activity` | `com.jonathanjing.tongxing.dev.listening-activity` |
| 返回链接 | `tongxing-beta` | `tongxing` |
| 内容源 | Firebase Dev | `https://ai-for-god-sermon-audio.web.app` |

Beta 配置明确保留 `1.2.0 (48)`，不重命名既有已分发包。签名、账号、Team 与设备唯一标识不进入 Git。

## 首轮 Build 49 归档与上传

使用进程级 Xcode 27.1 beta (`27A9269`) / iOS SDK 27.1。归档、App 与扩展身份核验、严格深度代码签名检查均通过，但这不代表该工具链具备正式审核资格。

```sh
apps/tongxing-ios/scripts/archive-channel.sh \
  --channel production \
  --expected-commit 86b506f4c2dd7126b66f95912b164a80e09b6c16 \
  --developer-dir /Applications/Xcode.app \
  --output-dir artifacts/tongxing-ios/2026-10-01/production-1.26.7/archive
```

- 归档 Manifest SHA-256：`b922e6788de9645a85fdbf6c2d5e885123da8931dc0ead9d2596a56d4d38727a`。
- 上传成功：2026-10-01 22:08:03 UTC，`xcodebuild -exportArchive` 退出 0，日志确认 upload/export succeeded。
- Apple 已处理完成；正式 App `6809255441` 的 `1.26.7` 更新草稿已选择 Build 49。
- 使用自动签名和既有上传配置，`manageAppVersionAndBuildNumber=false`，不由上传过程改版本号。

2026-10-01 约 22:25 UTC，实际点击 Add for Review 后，Apple 返回 `Unable to Add for Review`：App Store 不允许 beta 版本的 Xcode / SDK。49 已上传并完成处理，但未提交审核、未发布。错误页面证据为 `asc-build49-gm-required.png` / `.ax.txt`，已保存；不会通过改写 Archive 的 SDK 标识来绕过检查。

## 正式工具链 Build 50

找到本机此前保存的 Xcode 27.0 (`27A266a`)，与 [Apple 公开正式发行版本](https://developer.apple.com/news/releases/) 一致；`-showsdks` 包含正式 iOS 27.0，`-checkFirstLaunchStatus` 退出 0。采用进程级路径选择该工具链，不替换日常 Xcode 27.1 beta、不修改全局 `xcode-select`。

Build 50 保持用户指定的 `1.26.7` 和相同功能源码，仅为不具备正式审核资格的 Build 49 分配新的技术构建号。它是同一候选的工具链修正；不占用下一个产品迭代 `1.26.8`。准备重新归档、验证并上传，实际源码、归档哈希和 Apple 提交结果将在执行后补齐。

忽略目录 `artifacts/tongxing-ios/2026-10-01/production-1.26.7/` 保存归档、上传日志、`archive/release-record.json`、xcresult、原始截图与 Manifest。上述产物未提交 Git。

## 定向验证与商店材料

Release 模拟器检查使用 `ENABLE_TESTABILITY=YES` 使单元测试可导入优化后的 App 与 Infrastructure；这个命令行选项仅用于测试，未改变上传归档。

首轮三语检查在保留的 `00:03` 位置切换韩语，落在字幕空档：u002 为 1.39–2.79，u003 为 3.81–8.62。页面正确显示“等待下一段字幕…”，原测试却要求任何暂停位置都有当前英文。已修正测试前置步骤：通过实际全文时间按钮定位到已有 cue，再验证对应字幕和播放；没有把切换语言改成清零。另修正测试的页首语言菜单可点击性判断，避免把正文滚动区域的 16 点内缩用到页首控件。

更新说明、推广文字、审核说明及截图流程见 [App Store 材料](APPSTORE-1.26.7.zh.md)。截图来自 Release 配置、真实正式内容和正常 UI 操作，不使用合成 fixture。截图测试代码修订晚于归档，属于测试工具改进，App 功能源码未改变。

截图与定向测试工具 revision：`bc733fab9a9377c2b92a9328cbdf5b76b7d8ffc4`。iPhone 18 Pro Max / iOS 27.0 的正式身份单测、中英文截图测试、真实三语检查分别通过；三语最终结果为 1 passed / 0 failed / 0 skipped，运行时警告 0。初轮中文截图测试本身通过，从它导出 6 张附件；同一初轮 bundle 中另一个三语测试失败的附件未用于商店截图。

iPad Pro 13-inch (M5) 的中英文截图测试通过：2 passed / 0 failed / 0 skipped，运行时警告 0；系统版本按 xcresult 实测为 iOS 27.0。24 张原始 PNG 均为 RGB，无透明通道：iPhone 1320 × 2868，iPad 2064 × 2752。每种尺寸和界面语言各 6 张，按当前字幕、双语全文、英文定位、证道语言、证道目录、正式样音试听排列。`screenshots/manifest.json` 保存各图 SHA-256；该 Manifest 的 SHA-256 为 `23c968cee503ad5aa6914f10f0cdd7eac8e53267911a054f8d44fbfb2cafc2cf`。

当前正式内容仍通过 legacy 多音色试听目录提供独立样音：新 `speaker-clips-v2/catalog.json` 正式站返回 404，旧 `2026-09-21-v2/production-ko-es.json` 返回 200。审核材料明确说明不同文稿的独立试听与暂停/继续，不宣称 Dev 的同片段视频 Demo 已发布。

## 审核与验收状态

首轮 24 张截图已上传，简中与英文材料已保存。Build 49 因 beta 工具链未能加入正式审核；Build 50 的实际结果将在执行后更新。已选择审核通过后自动发布、向全部用户发布、保留现有评分。Apple 审批与正式商店可下载状态仍须分别观测；不把上传成功当作已上架。

用户已确认 Beta 检查通过；Agent 本轮未执行正式包真机、锁屏/耳机/来电或现场麦克风验收。模拟器检查和截图不替代这些证据。
