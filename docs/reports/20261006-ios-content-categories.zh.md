# 最近证道与播客的类别行

## 改动

两篇已确认归档证道（`resi-20261004-69ba7a66` 与 `2026-09-27-weekend-sermon-drive-530`）显示“正式播放版”，明确 `mediaType: podcast` 的页面显示“播客”。主页面与选篇列表复用既有日期下方 caption 样式；“播客”补齐 en/ko/es/vi 翻译。

旧实现仅识别 9 月 27 日的页面 ID，遗漏 10 月 4 日与播客类型。现在分类规则在 Core 中集中处理。未知视频、未知 resi 页面和模拟/诊断条目不推断为正式版；保留旧标题后缀的显示兼容。类别是来源类型，不代表新的发布审批。未改变上游目录、字幕、音频或发布包。

## 验证

- 产品 revision：`3bc45b5f62454f398d6e3f230e9b3103c12251f6`；后续仅将截图测试的系统 sheet 展开，使三个条目完整可见。
- Xcode 27.1（27A9269），TongxingBeta / BetaDebug 通用 Simulator build 退出 0。
- Core 定向测试：20 项、2 个 suite 通过，覆盖已知两篇归档、明确播客、未知条目及模拟条目。
- iPhone 18 Pro / iOS 27.0：`testPickerSourceCategoriesBelowDate` 与 `testSermonHeadingAndPickerUseTitleSeriesDateSpeakerWithoutSeeking` 两项通过。前者断言三个类别及其位于日期下方；后者检查标题层级并验证打开/关闭选篇列表不改变暂停播放位置。
- 独立只读审核产品 revision 未发现阻塞问题；实际 after 截图已查看，三项类别均完整显示。
- 网页：`not_applicable`，本轮只修复原生客户端已有类别显示；没有网页交付变更。

本地证据（均不进 Git）：

- build：`/tmp/tongxing-category-after/20261006T215958-build-592d0207/`
- after test：`/tmp/tongxing-category-after/20261006T220321-test-5aa2b393/test.xcresult`
- before：`/tmp/tongxing-category-before-expanded/20261006T220109-test-4711212e/test.xcresult`
- 前后 PNG：`artifacts/tongxing-ios/20261006-content-categories/{before,after}.png`

前后使用同一模拟器、三个真实页面 ID/标题/日期/讲员与相同 sheet 展开操作；UI 内容/静音音频为隔离夹具，哈希重新绑定。before 仅关闭新增类别断言以采集旧行为，不计入修复测试通过数。after 执行全部类别断言。未上传新 TestFlight，也未进行真机验收；当前手机 Beta 不会因源码修复自动更新。
