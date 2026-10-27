# 20261026 iOS Universal Links 交接

状态：**代码已合并、AASA 已上线、Beta 1.26.22 (65) 已归档；TestFlight 上传被 Apple 签名权限阻塞。**

## 代码与发布

- 功能 PR：[#1402](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/1402)，已 squash 到 `dev`，提交 `f146145e9b23800ed0ea342c5b6f9aa48fc5ffd4`。
- 归档源码：`64100cf5ccf25c309ae145e5bc173ecaa09e2325`（PR 合并前的 feature merge；归档记录以此为准）。
- 支持形式：
  - `https://ai-for-god-sermon-audio.web.app/?week=<pageId>&contentLang=<locale>&lang=<uiLang>`
  - `/pages/<pageId>/<locale>/`
  - `tongxing://page/<pageId>?contentLang=<locale>`
- 解析与路由：`apps/tongxing-ios/App/AppDeepLink.swift`、`AppModel.openDeepLink`、`TongxingApp` 的 `.onOpenURL` / `.onContinueUserActivity`。
- 正式 entitlement 同时包含生产推送和正式域名：`Config/ProductionPush.entitlements`；Beta 使用 `Config/BetaPush.entitlements`（Dev 域名）；Debug 使用 `Config/AssociatedDomainsDev.entitlements`。

## 生成物路径

以下均在本机仓库忽略目录，未提交 Git：

| 内容 | 路径 |
|---|---|
| Beta 1.26.22 (65) Archive | `artifacts/tongxing-ios/beta-1.26.22-65/Tongxing.xcarchive` |
| Archive 记录 | `artifacts/tongxing-ios/beta-1.26.22-65/release-record.json` |
| Archive 日志 | `artifacts/tongxing-ios/beta-1.26.22-65/archive.log` |
| IPA 导出配置 | `artifacts/tongxing-ios/beta-1.26.22-65/export/ExportOptions.plist` |
| Debug 构建 DerivedData | `artifacts/tongxing-ios/deeplink-build/` |
| AppDeepLink 测试 xcresult | `artifacts/tongxing-ios/deeplink-build/Logs/Test/Test-Tongxing-2026.10.26_19-33-32--0700.xcresult` |
| 正式 AASA 部署基线/回执 | `artifacts/aasa-deploy/production-baseline/` |
| Dev AASA 部署基线/回执 | `artifacts/aasa-deploy/dev-baseline/` |
| 深链二维码 | `artifacts/sentence-first-agent/20261026-jesus-wins-podcast-review/jesus-wins-deeplink-qr.png` |

Archive 实际身份：版本 `1.26.22 (65)`，archive manifest SHA-256 `2adda20beff4dfccdaad79656379189da89860cdec55404654bc4d1c5933a7e9`，状态 `archive_succeeded`；`upload`、`device`、`venue` 均为 `not_run`。

## AASA 与 Hosting

- 正式 AASA：https://ai-for-god-sermon-audio.web.app/.well-known/apple-app-site-association
  - appID：`G2P4DTQNBA.com.jonathanjing.tongxing.dev`
  - live version：`sites/ai-for-god-sermon-audio/versions/642d25fc58fe5c4e`
- Dev AASA：https://ai-for-god-sermon-audio-dev.web.app/.well-known/apple-app-site-association
  - appID：`G2P4DTQNBA.com.jonathanjing.tongxing.beta`、`G2P4DTQNBA.com.jonathanjing.tongxing.dev`
  - live version：`sites/ai-for-god-sermon-audio-dev/versions/9867502f35782585`
- 两者均返回 200，`content-type: application/json`。
- `baseline` 已改为保留 `.well-known/apple-app-site-association`，后续 Hosting 发布不会丢文件。

## 当前阻塞

`xcodebuild -exportArchive` 失败，原因不是代码：

- `No signing certificate "iOS Distribution" found`
- `Cloud signing permission error`（当前账号无 cloud-managed distribution 权限）
- Beta provisioning profile 还没有 `Associated Domains` 能力

需要 Account Holder/Admin：

1. 为 `com.jonathanjing.tongxing.beta` 和 `com.jonathanjing.tongxing.dev` 打开 Associated Domains；
2. 提供 iOS Distribution 证书或授予 cloud-managed distribution 权限。

完成后可直接对现有 xcarchive 重跑：

```sh
DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer \
xcodebuild -exportArchive \
  -archivePath artifacts/tongxing-ios/beta-1.26.22-65/Tongxing.xcarchive \
  -exportPath artifacts/tongxing-ios/beta-1.26.22-65/export \
  -exportOptionsPlist artifacts/tongxing-ios/beta-1.26.22-65/export/ExportOptions.plist \
  -allowProvisioningUpdates
```

然后用 `apps/tongxing-ios/scripts/testflight.py upload --record ... --ipa ...` 上传。不要重建 Archive，除非源码或版本变化。

## 接手注意

- Beta App 只关联 **Dev 域名**；这期新页面只在正式站，Beta 无法用正式二维码测试这一页。要测需把页面发布到 Dev，或等正式 App 下一版。
- 正式站二维码在正式 App 新版本安装前仍只会打开网页；当前正式 App 1.26.21 (64) 不含 Associated Domains。
- Archive 源码是 `64100cf5`；`dev` 的 squash 是 `f146145e`。若之后从 `dev` 重建，请保持或递增 `1.26.22 (65)`，不要把已有 65 当作新上传。
- 未做真机 Universal Link 验证；AASA 200 和 profile entitlement 都不等于真实设备行为。验证时至少覆盖：已安装/未安装、冷启动/前台、有效页/撤回页、Beta 与正式域名。
