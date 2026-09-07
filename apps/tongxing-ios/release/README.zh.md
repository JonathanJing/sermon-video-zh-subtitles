# 同行 App 发布材料包

更新日期：2026-09-07。当前目标为 **0.1.0 (5)**。build 4 已上传，但正式 Add for Review 被 beta Xcode 限制拒绝；build 5 只有 beta 模拟器的定向 UI 验证，没有正式 Archive / IPA、Cloud 运行或审核提交。

## 当前材料

- [中英文案](../APP-STORE-METADATA.zh.md)与[结构化字段](metadata.json)：已按当前 6 篇中文目录更新，审核样例为 09-06 普通播放并跳至 00:30；当前没有英文对照块或听音对齐数据。中英商店描述/宣传文本逐字已保存 ASC，中文关键词已改为证道字幕并保存；审核说明语义相符，两种语言副标题已逐字保存；build 5 TestFlight 文案待正式构建后回填。
- [已发布隐私政策](https://ai-for-god-tongxing-support.web.app/privacy.html)与[支持页面](https://ai-for-god-tongxing-support.web.app/support.html)：中英 URL 已填 ASC。`public-policy/` 的四个公开文件与 HTTP 校验字节相同；保留原文件名的[政策正文](privacy-policy-draft.md)及[支持正文](support-draft.md)也已同步批准和公开联系状态。
- [App Privacy 依据](public-policy/app-privacy-declaration.json)：ASC 已 Published；Hosting IP 分类依据和 Apple 服务边界保留。
- [内容权利记录](content-rights-review.json)：用户确认当前内容及声线许可，绑定 6 篇目录；ASC Yes 已保存。权利确认不等于人工质量验收。
- [截图清单](../SCREENSHOTS.zh.md)、[发布状态](../RELEASE-READINESS.zh.md)、[历史 Beta 证据](../BETA-TESTING.zh.md)。

ASC 当前已核验软件版权 `2026 Jonathan Jing`、Education、18+、USD 0.00，Availability 仅美国 1 个地区，其他 174 地区 Not Available；美国状态为 Available on App Release。再次 Add for Review 仅显示 beta Xcode 同一根因的两个错误，没有其他材料错误。该结果不是正式审核提交成功。

旧 `artifacts/tongxing-ios/2026-09-07-release/Tongxing-0.1.0-4-submission-materials.zip` 保留为 build 4 历史包，不覆盖或冒充 build 5 当前材料。旧文本的 3 篇目录、原声定位样例和双语画面不再作为本次审核依据。

## 当前截图组合

当前 8 张已在 ASC 保存并核验。上传目录为 `artifacts/tongxing-ios/2026-09-07-current-catalog-screenshots/upload/`：每个设备/语言组包含 build 4 原有 `01-listen.jpg` 与 build 5 新采集的 `02-transcript.jpg`。四张新全文页路径为：

- `iphone-6.9/zh-Hans/02-transcript.jpg`
- `iphone-6.9/en/02-transcript.jpg`
- `ipad-13/zh-Hans/02-transcript.jpg`
- `ipad-13/en/02-transcript.jpg`

四张新原件位于 `artifacts/tongxing-ios/2026-09-07-current-catalog-screenshots/` 的上述路径，显示当前中文全文及未提供英文的说明。`01-listen.jpg` 沿用历史原件，主收听页没有因新隐私入口改变。8 张组合文件与各自原件字节相同，尺寸/哈希定向检查通过；[截图清单](../SCREENSHOTS.zh.md)分别记录 build 4 / 5 及其目录来源。旧目录的双语全文图保留历史证据。素材准备与实际 ASC 替换分别记录。

## 正式构建与提交续接

1. 先审查本次应用/材料差异，向用户给出具体范围；取得本次 Git commit / push 的明确请求后再执行，不触碰来源未明的 `Tongxing.xcodeproj/xcshareddata/xcodecloud/manifest.json`。
2. Xcode Cloud 当前仍是 Get Started，尚未初始化可运行 workflow。完成初始化、源码连接和正式 SDK 配置后，生成 build 5；不能把此前 Xcode Cloud 的历史观察当作当前可运行配置。
3. 在兼容正式工具链上验证 App/扩展版本、最低系统、签名、隐私资源、Archive / IPA 和 Apple 处理。MacBook 的 macOS 27 与正式 Xcode 26.6 不兼容；本机 beta 模拟器成功不能消除正式提交限制。不要重复导出或上传旧 build 4 来尝试绕过它。
4. 将当前 6 篇版本的中英文案和所需新截图与 ASC 比对回填，关联正式构建，复核已保存的政策/权利/18+/免费美国配置，再按授权推进正式审核。首次发布方式仍为审核后手动发布。

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
