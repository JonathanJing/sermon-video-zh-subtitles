# 同行 Beta 1.26.22（63）：字幕段落复制与多语言商店资料

本候选包含 PR #1383 的字幕全文段落长按复制功能，中文段落可复制；有双语内容时可复制对照文本。使用独立 Beta 身份与 Dev 内容源。

## 候选身份

- 源码 commit：`534ff94a796fbca78454d6ea69a63035e47b9df5`；源码树：`4f8675bdb25d20727cfb2ffc9b9c4fed4b5dc111`
- iOS module tree：`970a5f23e13c72191225b75c9d0e3e1a28276673`
- 渠道 / scheme / configuration：Beta / `TongxingBeta` / `BetaRelease`
- App 与实时活动扩展版本 / Build：`1.26.22 (63)`
- App Bundle ID：`com.jonathanjing.tongxing.beta`；扩展：`com.jonathanjing.tongxing.beta.listening-activity`
- 内容源：Dev
- Xcode 27.1（27A9275）；iOS SDK 27.1（24A94232）
- Archive Manifest SHA-256：`5c3f71630ade2e52a9abc151a635f633ba6aa77f4a00172550d6d34e5d198589`

## 验证与 TestFlight

- iOS 27.0 / iPhone 18 Pro 定向 UI 测试 `testFullTranscriptChineseParagraphOffersLongPressCopy` 通过（1 项、0 失败）；脱敏报告见 [PR #1389](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/1389)。
- App Store Connect Build ID `9504f199-5bb6-4c7b-a693-54a016356ff8` 于 2026-10-26 01:43 UTC 读回为 `VALID`、未过期、`IN_BETA_TESTING`。
- Rooted 内部测试组读回包含该 Build；What to Test 已保存，且通过 API 读回核对与本轮文本一致。
- IPA SHA-256：`20b2c517b04f60681d2772fb8ff6bc865af93496780e0d1a8e2793d2679f6614`。
- 真机和现场验收：未执行。TestFlight 内测可用不代表已安装或通过设备验收。

## App Store 草稿

App Store Connect 已创建 1.26.22 草稿（`PREPARE_FOR_SUBMISSION`），年龄分级问卷读回 `FOUR_PLUS`；新增韩文 `ko`、墨西哥西班牙文 `es-MX` 与越南文 `vi` 的名称、简介、关键词、长描述、宣传文字和更新说明。草稿尚未提交审核，线上现行商店页与年龄分级仍以已发布版本为准。
