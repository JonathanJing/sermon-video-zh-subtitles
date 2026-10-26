# 同行 Beta 1.26.22（63）：字幕段落复制与多语言商店资料

本候选在 PR #1383 的字幕全文段落长按复制功能基础上，递增 Beta 版本为 `1.26.22 (63)`。源码、归档和 Apple 处理状态在实际构建后补记；此候选使用独立 Beta 身份与 Dev 内容源。

## 候选身份

- 渠道：Beta (`com.jonathanjing.tongxing.beta`)
- 版本 / Build：`1.26.22 (63)`；App 与实时活动扩展一致
- 功能来源：PR #1383，字幕段落长按复制；可用时提供双语对照复制
- 完整源码 commit、iOS module tree、Xcode / SDK、归档 Manifest SHA-256：待归档后记录

## 验证与分发

- 定向 UI 测试：iOS 27.0 / iPhone 18 Pro，`testFullTranscriptChineseParagraphOffersLongPressCopy` 通过（1 项、0 失败）；脱敏报告见 [PR #1389](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/1389)
- Archive：待执行
- IPA 上传、Apple 处理、Rooted 组分发：待执行并分别读回
- 真机和现场验收：未执行
- App Store Connect：1.26.22 草稿已读回年龄分级 `FOUR_PLUS`，新增 `ko`、`es-MX`、`vi` 的商店名称、简介、关键词、描述、宣传文字与更新说明；草稿状态 `PREPARE_FOR_SUBMISSION`，未提交审核。现行已发布版本不会因草稿变更而自动更新。
