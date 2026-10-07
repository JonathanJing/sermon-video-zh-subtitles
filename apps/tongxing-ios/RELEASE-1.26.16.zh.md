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

当前 Apple 处理与审核状态须以后续追加收据为准，不能以本节上传成功称为正式发布完成。


Apple 已处理正式 Build 57 为 `VALID`，构建 ID `de4cd7e4-5156-4b52-92b0-31ad1830fec7`，营销版本读回为 1.26.16，已关联正式版本 `fd6b404a-2ec8-4c5b-a666-8cfb473970d8`，非豁免加密字段为 false。处理和关联收据保存在主任务工作树 `artifacts/tongxing-ios/production-1.26.16-preflight/`。
