# 同行 App 发布材料包

2026-09-13 最新：**TestFlight 1.0.0 (17)** 已完成上传，Xcode Cloud Build/Archive 均成功，中英文测试说明已保存；具体源码与分发边界见 [1.0.0 发布回执](testflight-1.0.0-2026-09-13.zh.md)。主线同步与 69 项验证见 [Build 16 同步记录](testflight-build16-2026-09-13.zh.md)。下文 2026-09-07 的 Build 5 / App Review 状态是历史记录，不能作为当前审核结论。

更新日期：2026-09-07。当前目标为 **0.1.0 (5)**。正式 Xcode Cloud build 5 已成功，Archive / App Store 导出 / Prepare Build 全部通过，ASC 已处理为 Ready to Submit，Binary State = Validated。**正式 App Review 已提交，当前 Waiting for Review**；审核后手动发布，尚未公开上线。本机未下载 Cloud Archive / IPA。build 4 的 beta Xcode 拒绝保留为历史。

## 当前材料

- [中英文案](../APP-STORE-METADATA.zh.md)与[结构化字段](metadata.json)：已按当前 6 篇中文目录更新，审核样例为 09-06 普通播放并跳至 00:30；当前没有英文对照块或听音对齐数据。中英商店描述/宣传文本逐字已保存 ASC，中文关键词已改为证道字幕并保存；审核说明语义相符，两种语言副标题已逐字保存；build 5 中英 What to Test 已保存为与本地长稿语义一致的摘要版，非逐字相同。
- [已发布隐私政策](https://ai-for-god-tongxing-support.web.app/privacy.html)与[支持页面](https://ai-for-god-tongxing-support.web.app/support.html)：中英 URL 已填 ASC。`public-policy/` 的四个公开文件与 HTTP 校验字节相同；保留原文件名的[政策正文](privacy-policy-draft.md)及[支持正文](support-draft.md)也已同步批准和公开联系状态。
- [App Privacy 依据](public-policy/app-privacy-declaration.json)：ASC 已 Published；Hosting IP 分类依据和 Apple 服务边界保留。
- [内容权利记录](content-rights-review.json)：用户确认当前内容及声线许可，绑定 6 篇目录；ASC Yes 已保存。权利确认不等于人工质量验收。
- [截图清单](../SCREENSHOTS.zh.md)、[发布状态](../RELEASE-READINESS.zh.md)、[历史 Beta 证据](../BETA-TESTING.zh.md)。

ASC 当前已核验软件版权 `2026 Jonathan Jing`、Education、18+、USD 0.00，Availability 仅美国 1 个地区，其他 174 地区 Not Available；美国状态为 Available on App Release。此前 build 4 Add for Review 的两个 beta Xcode 错误属于历史；build 5 已通过 Apple 处理并正式提交 App Review，当前 Waiting for Review。

旧 `artifacts/tongxing-ios/2026-09-07-release/Tongxing-0.1.0-4-submission-materials.zip` 保留为 build 4 历史包，不覆盖或冒充 build 5 当前材料。旧文本的 3 篇目录、原声定位样例和双语画面不再作为本次审核依据。

## 当前截图组合

当前 8 张已在 ASC 保存并核验。上传目录为 `artifacts/tongxing-ios/2026-09-07-current-catalog-screenshots/upload/`：每个设备/语言组包含 build 4 原有 `01-listen.jpg` 与 build 5 新采集的 `02-transcript.jpg`。四张新全文页路径为：

- `iphone-6.9/zh-Hans/02-transcript.jpg`
- `iphone-6.9/en/02-transcript.jpg`
- `ipad-13/zh-Hans/02-transcript.jpg`
- `ipad-13/en/02-transcript.jpg`

四张新原件位于 `artifacts/tongxing-ios/2026-09-07-current-catalog-screenshots/` 的上述路径，显示当前中文全文及未提供英文的说明。`01-listen.jpg` 沿用历史原件，主收听页没有因新隐私入口改变。8 张组合文件与各自原件字节相同，尺寸/哈希定向检查通过；[截图清单](../SCREENSHOTS.zh.md)分别记录 build 4 / 5 及其目录来源。旧目录的双语全文图保留历史证据。素材准备与实际 ASC 替换分别记录。

## 正式构建与提交续接

1. 已审查并按授权提交/push 23 个文件；分支 `codex/tongxing-ios` 的远端已核验为 `539e916f904c9191ebd6ecb9708eaae1880b0a44`。来源未明的 `Tongxing.xcodeproj/xcshareddata/xcodecloud/manifest.json` 仍排除。
2. 现有 Default workflow 原来仅有 Build、无分发，现已关联既有 App `com.jonathanjing.tongxing.dev` 并补充 Archive → App Store Connect；固定正式 Xcode `26.6 (17F113)`；macOS 选项保持 Latest Release，本次实际运行版本为 `26.6.2 (25G83)`。Cloud build 5 `e20f505c-9f37-4689-b022-3b4f5489eaff` SUCCESS，耗时 4 分钟，源码 commit 与推送一致。
3. Archive、App Store 导出、Prepare Build 全部通过；ASC build 5 `2b66dd36-203a-4be9-bcb1-2230870783e0` 已为 Ready to Submit，Binary State = Validated，版本 `0.1.0 (5)`、最低 iOS 17、SDK build `23F81a`、Encryption = No。本机未下载 Cloud Archive / IPA；Cloud 成功解决正式构建路径，不改写本机 macOS 27 的历史不兼容记录。
4. 商店版本已从 build 4 切换到 build 5 并保存。2026-09-07 11:16 PDT，Add for Review 成功进入 Ready for Review，Submit for Review 成功；门户显示 `0.1.0 Waiting for Review`、`1 Item Submitted`、`Draft Submissions (0)`；审核提交 ID 为 `8ad36924-ad49-4ca7-ba7a-6cfab0f0e725`。中英 What to Test 已以语义一致的摘要保存。政策/权利/18+/免费美国配置和当前截图已保存；首次发布仍为审核后手动发布，尚未公开上线。

本次证据：`artifacts/tongxing-ios/2026-09-07-app-store-build5/cloud-build5-receipt.json`。早前 `cloud-dispatch.json` 记录成功构建步骤；新记录补充后续 Apple 处理与 TestFlight 文案状态。

历史 build 4 的导出、上传及旧材料保存已完成，证据保留在[发布准备](../RELEASE-READINESS.zh.md)。私有账号、证书、Team、设备唯一标识和审核联系人不进入 Git；用户明确批准的公开支持邮箱可以发布。

## 本地材料检查

在仓库根目录执行以下定向检查；它不上传或修改 ASC：

```sh
python3 apps/tongxing-ios/scripts/verify-release-materials.py \
  --screenshots artifacts/tongxing-ios/2026-09-07-current-catalog-screenshots/upload \
  --output artifacts/tongxing-ios/2026-09-07-app-store-build5/combined-screenshot-material-check.json
```

该脚本验证核心文案字段长度及组合目录的 8 张图片尺寸/哈希；本轮另核对全部 16 个字段限制、JSON 与 Markdown 文案逐字一致、新目录哈希/审核样例/能力、公开页面字节与链接、JSON 语法及 `git diff --check`。每张图保持其真实构建和目录来源，不把保留的 build 4 主屏改记为新目录截图。

本地检查不是内容许可、声学输入、正式签名、Cloud 运行或 Apple 审核的替代证据。

此前定向材料检查已通过：16 个本地化字段、37 个本地 Markdown 链接、6 篇目录的哈希/能力/00:30 样例、4 个已发布文件的字节一致性。报告：`artifacts/tongxing-ios/2026-09-07-app-store-build5/release-material-check.json` 与 `release-consistency-check.json`。新组合截图检查另已通过：`artifacts/tongxing-ios/2026-09-07-app-store-build5/combined-screenshot-material-check.json`，共 8 张、无错误；ASC 四张全文图替换已完成，四组均核验为 2 张。

最新截图目录 SHA-256 为 `e88ac7c163307388dc1ee334d393c87f6c6ab9ffb6cf0171807d5c1d908b49ee`。与上述已审计快照比较，仅六篇的 `title` / `sourceLabel` 共 12 个字段改变；来源 URL/ID、全部中文 cues、音轨、媒体哈希和时长均相同。差异证据：`artifacts/tongxing-ios/2026-09-07-current-catalog-screenshots/catalog-diff.json`。保留原快照作为权利和年龄分级审计依据。
