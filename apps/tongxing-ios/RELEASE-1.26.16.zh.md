# 正式 1.26.16（57）晋升记录

2026-10-07（洛杉矶），用户授权将 Beta 1.26.16（57）按同一数字版本与 Build 发布正式版。正式 App 的既有最高本地 Build 为 51（另有 Xcode Cloud Build 46）；真实 API 查询确认正式 App 未占用 Build 57。因此保留用户指定的 57，独立正式 IPA 从相同功能源码重新归档，不修改或重新签名 Beta IPA。

## 冻结与配置

- Beta 冻结 commit：`a1e64190f5af33104a3b8839562d8901955031bb`。
- Beta iOS module tree：`769ef87d50e46193ce4179044719c26a59fc9291`。
- 正式归档 commit：`5dd46ce6481c71e5b13323c67b98f5ba9a826451`。
- 相对 Beta 功能代码没有修改；仅 `project.yml` 正式 App/扩展的版本与 Build 由 1.26.10（51）改为 1.26.16（57），并重新生成工程。Beta 配置保持 1.26.16（57）。
- 正式渠道：`Tongxing / Release`，历史正式 Bundle ID `com.jonathanjing.tongxing.dev`，扩展为 `.listening-activity`，返回链接 `tongxing`，内容源 `https://ai-for-god-sermon-audio.web.app`。
- Xcode 27.0 / `27A266a`、iOS SDK 27.0 / `24A430`。工具链使用显式进程路径，没有修改全局 xcode-select；不使用 Beta57 的 Xcode27.1 beta 来提交正式审核。Apple [正式发行记录](https://developer.apple.com/cn/news/releases/?id=09142026h)支持该工具链身份。

## 归档与上传

成功归档记录位于忽略目录 `artifacts/tongxing-ios/production-1.26.16-build57/archive-final/release-record.json`；实际 App/扩展版本、身份、正式内容源以及 SDK 字段均核对通过，`codesign --verify --deep --strict` 通过。

首次两个归档尝试因新工作树缺少本机私有签名配置而失败，保留各自日志；补齐仓库外来源的本机配置后成功，未提交签名资料。Release UI 测试首次因 `@testable` 模块未启用 testability 失败，测试构建加入 `ENABLE_TESTABILITY=YES` 后继续；正式归档不含该测试覆盖设置。

`xcodebuild -exportArchive` 上传于洛杉矶 00:16:32 返回 `Upload succeeded` / `EXPORT SUCCEEDED`，退出码 0。上传成功不等于 Apple 处理、审核或线上生效。App Store Connect 正式版本记录为 1.26.16；中英文更新说明及审核说明已保存，配置审核通过后自动发布。

## 内容与验证边界

生产多语言目录包含 10月4日、9月27日两篇，各有中、韩、西三语。六 release、六 content、六 captions 实际 HTTP 读取及哈希匹配；发布包为 `published_http_verified / human_reviewed`。两篇没有远程 displayCategory，但既有 ID 兜底显示正式播放版。10月2日播客及新的远程类别配置仍在 Dev，本轮 App 发布不部署它们。生产学习资源依实际内容缺省路径显示，不能宣称已有完整学习产品。

GM Release 实际 `ListeningFlowUITests/testLiveProductionCurrentWeekNativeThreeLanguages` 通过，覆盖9月27日三语播放、英文对照和原视频返回；不冒充10月4日完整三语UI验收。GM Debug 三项定向测试全部通过：返回当前句保留暂停位置、手动拖动与跟随恢复、远程类别刷新保留暂停状态。初次启动正式 Release 包另确认10月4日西语标题、正式播放版类别、当前字幕和英文对照正常显示；未将此静态画面当作该篇三语播放验收。Beta57 历史测试仅作相同功能源码的既有证据，不代替这轮正式身份、工具链和生产内容验证。

锁屏字幕为最近同步快照与更新时间，App 内逐句更新；真机灵动岛恢复、手机安装与现场验收仍未证明。本次发布授权不改变其证据状态。Header 和 Duo Beta/Dev 截图已上传素材库但未因本轮晋升自动选入正式页或送审。

当前正式版本为 `WAITING_FOR_REVIEW`，已经成功送审，尚未正式上线。


Apple 已处理正式 Build 57 为 `VALID`，构建 ID `de4cd7e4-5156-4b52-92b0-31ad1830fec7`，营销版本读回为 1.26.16，已关联正式版本 `fd6b404a-2ec8-4c5b-a666-8cfb473970d8`，非豁免加密字段为 false。处理和关联收据保存在主任务工作树 `artifacts/tongxing-ios/production-1.26.16-preflight/`。

## 审核提交受阻

00:23 左右实际点击 Submit for Review 后，Apple 返回当前平台已达到最大同时审核提交数。App Review 页面显示两个 00:07 提交仍在 Waiting for Review；已查看其中 `d126e441-fd60-4549-8191-51537f716c98`，其唯一项目为素材库截图 `01-main-listening-caption-sidebar.png`。没有撤回或删除这些既有素材审核。正式 App 独立草稿 `44ecdcf7-b5c5-4e75-8249-80e8713e84ec` 包含唯一 App 项目 1.26.16（57），可在审核名额释放后继续提交。真实 API 再读回确认 `READY_FOR_REVIEW / AFTER_APPROVAL`；本次失败不能称为已提交审核。已请求用户选择是否撤回上述单项截图审核以优先提交 App；未获答复前保留原审核。

## 最终送审收据

2026-10-07 08:12:32（洛杉矶），用户授权撤回一项素材审核。已通过 App Store Connect 的 Cancel Submission 撤回截图 `01-main-listening-caption-sidebar.png` 的提交 `d126e441-fd60-4549-8191-51537f716c98`，未删除素材。另一素材提交 `e959324e-f780-4099-b1f0-7a5e8cb1f9c9` 保持 `WAITING_FOR_REVIEW`。

随后正式 App 1.26.16（57）独立提交 `44ecdcf7-b5c5-4e75-8249-80e8713e84ec` 成功，页面显示 1 Item Submitted，并在详情确认唯一 App Version 项目为 1.26.16（57）/ Waiting for Review。真实 API 再读回确认版本与提交均 `WAITING_FOR_REVIEW`，提交时间 `2026-10-07T15:12:32.586Z`，发布方式仍为 `AFTER_APPROVAL`。尚未获得审核批准或线上发布收据。JSON 与截图 `submitted-for-review.png` 保存在主任务工作树的忽略目录 `artifacts/tongxing-ios/production-1.26.16-preflight/`。本收据取代上节容量阻塞状态，保留该节作为历史。

## 上线与后续素材审核

2026-10-07 09:43（洛杉矶），用户告知正式版已批准并发布。真实 API 核对 1.26.16 为 `READY_FOR_SALE`，正式版本审核提交为 `COMPLETE`。

继续用户授权的素材审核：复用草稿 `410239bb-1499-4745-acc4-15d3be8779e1`，保留原有一张 Duo 替代截图，并加入撤回的主截图、其余七张 Duo 截图及英文、韩文、西文三个 Header，共 12 项。Apple API 要求 platform 与 submitted 分开 PATCH；拆为两个请求后于 `2026-10-07T16:43:01.636Z` 成功提交，状态 `WAITING_FOR_REVIEW`。逐项读回九张 Duo 截图和三条新增 Header 均等待审核；中文 Header 的既有独立提交保持等待审核。没有将素材指派到正式产品页，没有改动已上线二进制。收据在主任务忽略目录 `artifacts/tongxing-ios/asset-library-upload-20261007/submitted-assets-readback.json` 与 `submission-response.json`。
