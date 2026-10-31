# 同行正式版 1.26.33（Build 78）

## 候选身份

正式候选从[独立 Beta 1.26.33 (77)](BETA-RELEASE-1.26.33.zh.md) 晋升，沿用同一数字版本。Beta 冻结提交为 `96d2bc00d0d2368bfdab85adba7c7835a2ecd884`（`validatedBetaCommit`）；正式归档提交为 `f74093fe748b0dd81b83c38cf49f03ab302aa381`。两者的 App／Core／Infrastructure／Shared／实时活动扩展／Config 文件没有差异；正式提交只多出 Beta 发行文档，以及把 Release 的 App 与扩展从 `1.26.32 (76)` 改为 `1.26.33 (78)`。Beta 保留 Build 77。正式 App 的 Bundle ID 为 `com.jonathanjing.tongxing.dev`。

晋升时 Beta 只有 TestFlight 分发与模拟器测试证据，用户在 2026-10-30 指示直接构建并发布正式版；真机安装和真实麦克风对齐未在晋升前验证。

## 内容与构建

本地中文研读手册 JSON 与两张插图的 SHA-256 分别为 `a527e23fbd693177b9589fc89cd3533b653f64918abb97213cf34172c36711f9`、`f1d2f517120099a38614c7c560c1fbe054ec3ea4d741284fbcef496a7dab73b5`、`30c3e5b82c024bad3e40122f330f6606d022c91d8c77a82f06d6f1d5fc987f1f`，与 1.26.32 正式包、Beta 77 及本次 IPA 内文件一致。手册在 App 内标为“中文机器翻译 · 未经人工审校”，并注明非教会官方译本；`humanApproval=false`。

Xcode 27.1／iOS SDK 27.1 的 `Tongxing / Release` Archive 与 App Store IPA 导出成功。Archive 清单 SHA-256 为 `65608c0311e3548c2415854d149cd4a7770e304f3b03955cf9578004fcc1824d`，iOS module tree 为 `88d92b57b17a81bb5d1079e38086530f5bd7387e`；IPA 为 10,812,115 bytes、SHA-256 `65fe87a204ef44aca3518105ae0418948a0398fe62d7bd8cbf73e017ea4e08aa`。实际包内 App／扩展均为 1.26.33 (78)，显示名「同行」，内容源 `https://ai-for-god-sermon-audio.web.app`；严格签名检查通过，权限为 `aps-environment=production`、`get-task-allow=false`。

测试沿用 Beta 记录：同一功能源码的 `TongxingTests` 在 iOS 27.0 上 169 执行、0 失败；`ListeningFlowUITests` 的两项失败与 1.26.32 相同，已由只改测试的 [PR #1508](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/1508) 修正。本次没有单独运行 Release XCTest。

已知小缺口：新提示“正在载入听声对齐资料…”在 `Localizable.xcstrings` 中没有 en／ko／es／vi 译文，非中文界面会在载入时短暂显示中文。修正会改变功能源码，留给下一候选。

## App Store Connect

上传前读回：1.26.32 为 `READY_FOR_SALE`，正式 App 最大 Build 为 76，无进行中的审核提交。IPA 于 2026-10-30 19:00:42 UTC 上传命令成功返回，上传意图与 IPA 哈希绑定；首次运行因 Ruby 以 US-ASCII 读取记录在任何 Apple 请求前停止，未产生上传。Apple 于 19:02:51 UTC 将准确的构建 ID `27fa80a4-a930-41d8-9d1e-da855562ae4d` 读回为 `VALID`、未过期。

1.26.33 版本页 ID 为 `f10bf3f1-49c2-4e81-9838-629c06782c75`，已关联 Build 78，发布方式为 `MANUAL`：审核通过后不会自动上架。五种语言（简中、英文、韩文、西班牙文、越南文）的更新说明与审核备注已写入并于 19:03:40 UTC 读回一致；审核备注说明麦克风只在用户点按后短暂收听，并保留手册机器翻译披露。中、英截图各 18 张从上一版继承，未按新界面更新；审核联系信息存在，不需要演示账号。

Apple 于 19:04:05 UTC 收到审核提交 `d008f658-b101-4582-883c-725530f63791`；19:04:15 UTC 读回提交与 1.26.33 版本均为 `WAITING_FOR_REVIEW`，提交绑定上述版本 ID 与 Build 78。审核批准与实际上架尚未发生。

更新后的本机 `release-record.json` SHA-256 为 `b9ba96ea50fa0d055b58131af94909fdf5c62b68beb9140f9270f137cd1f43da`。

## 验收边界

真机安装、真实麦克风听音对齐与自动播放、iPad／Duo 上 popover 的位置、完整收听和现场声学效果仍未验证；`WAITING_FOR_REVIEW` 只证明已收件，不代表审核批准或上架。批准后需单独发出手动发布请求并读回 `READY_FOR_SALE`。本机 Archive、IPA、Apple 上传与提交回执均位于 worktree `.claude/worktrees/ios-beta-1.26.33/artifacts/tongxing-ios/` 下，不进入 Git。
