# 同行正式版 1.26.36（Build 82）

2026-11-16 从 dev `90e61df6` 归档正式候选；正式归档提交 `1e2eaf15` 只把 Release 的 App 与扩展从 `1.26.35 (81)` 改为 `1.26.36 (82)`。上一版 1.26.35 (81) 已上架（`READY_FOR_SALE`），本版是随后的小版本更新。

## 相对 1.26.35 的改动

- **戴蓝牙耳机时，听声对齐改用手机内置麦克风**：录音会话请求 `.allowBluetoothA2DP` 而不是 HFP，激活后请求内置输入，恢复播放分类时清除该偏好。[PR #1600](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/1600)，源码 `3e502941`；验证与设备证据见[运行报告](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/1599)（已合并）。
- 验证范围：iOS 27.2 模拟器全量 `TongxingTests` 178 项 0 失败；iOS 26.2 模拟器 `AudioAlignmentControllerTests` 48 项 0 失败；iPhone 17 Pro / iOS 27.2.1、蓝牙耳机连接时两条路由测试通过，App 日志 `[AudioSession] alignment capture route input=MicrophoneBuiltIn output=BluetoothA2DPOutput`。
- 未验：点击 → 8 秒采集 → 定位的整条 UI 流程、有线耳机、iOS 17 最低系统、实际听感与现场同步；本轮改动只涉及会话层路由。

## 构建与包

Xcode 27.1（`27A9275`）／iOS SDK 27.1（`24A94232`）的 `Tongxing / Release` Archive。Archive 清单 SHA-256 `8d14cea9…`（33 个文件），源码 `90e61df6…`，source tree `0056f3eb…`，iOS module tree `2e0e44b8…`。包内 App 与扩展均为 `com.jonathanjing.tongxing.dev` / `…dev.listening-activity` `1.26.36 (82)`，显示名「同行」／「同行播放状态」，内容源 `https://ai-for-god-sermon-audio.web.app`。

首次归档因工作区缺少被 Git 忽略的中文研读手册载荷而失败（`error: Release requires the verified weekly guide payload and SHA-256`），日志保留在 `production-1.26.36-archive-failed/`。随后复用与 1.26.35 同一份已核对手册候选后归档成功：payload `a527e23f…`、statue `f1d2f517…`、son-of-man `30c3e5b8…`，receipt 为 `machine_translation_not_human_reviewed`、`humanApproval=false`；手册内容与 1.26.35 相同，App 内披露不变。

## 上传

`xcodebuild -exportArchive`（`method=app-store-connect`、`destination=upload`、`signingStyle=automatic`、`manageAppVersionAndBuildNumber=false`，API Key 认证）于 2026-11-16 16:08:55 PDT 返回 `Upload succeeded` / `EXPORT SUCCEEDED`；未单独保留 IPA 副本，因此本轮没有 IPA 哈希。Apple 记录 Build 82 上传时间 00:10:02Z，`processingState=VALID`、`expired=false`。

## App Store Connect

- 版本 `2b8d79c9-2368-47a7-958c-946888d201af`（`1.26.36`），创建时继承五种语言（zh-Hans、en-US、es-MX、ko、vi）的商店文案与截图集（zh-Hans、en-US 各 4 套），发布方式 `MANUAL`。
- 关联 Build `5b77c03e-7d31-4c97-8c1d-06ac6bb57b92`（82，`VALID`）。
- 五种语言更新说明已写入并读回；审核备注说明本版只改录音输入路由，没有新增权限、数据收集或后台音频变化，中文手册仍为机器翻译、`humanApproval=false`。
- 2026-11-17 00:11:47 UTC 提交审核 `ba83dfec-65dd-40cb-8d85-5dca44c04fa4`；读回提交与版本均为 `WAITING_FOR_REVIEW`。

## 已知缺口

- 真机整条听声对齐流程（点击 → 采集 → 定位）与现场听感 `not_run`；`device`、`venue` 状态不因本版上传改变。
- Duo 商店截图沿用上一版，本版未更新。
- 通过审核后需人工在 App Store Connect 点发布（`MANUAL`）。

## 证据

忽略目录 `artifacts/tongxing-ios/production-1.26.36/`：`archive.log`、`release-record.json`、`Tongxing.xcarchive`、`upload.log`、`ExportOptions.plist`、`asc-version-localizations.json`、`asc-whatsnew.json`、`asc-build-attachment.json`、`asc-review-detail.json`、`asc-submission.json`、`asc-final-state.json`，以及本轮本地 ASC 操作脚本 `asc_release.py`。签名配置、Team 与凭据未进入 Git。
