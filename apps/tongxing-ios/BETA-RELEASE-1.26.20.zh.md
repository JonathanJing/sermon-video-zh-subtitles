# 同行 Beta 1.26.20（61）：10 月 18 日页面与海报验证

2026-10-21 从 `0699720fa3be8459d871944c04025d3dbb52022e` 归档独立 Beta。此源码包含上一候选已核查的听音定位改进：一次录音在 7／10／12／15 秒检查，可靠命中后早停，最多录 15 秒。本轮把 Beta App 和实时活动扩展一同递增至 `1.26.20 (61)`，并修正通知 UI 测试对长表单中屏幕外控件的滚动时机；正式渠道版本配置未变。冻结的 iOS module tree 为 `da3a0f26cd6c475675f0c6a83b095589cc001b28`。

## 内容与实际验证

- Firebase Dev Hosting 版本 `bbf84fd1e6451414` 已将 v5 默认页改为 10 月 18 日三语言家庭页 `resi-20261018-15030286`，v4 默认页改为同日中文广播版；公告侧车含三条对应海报。六个变更文件的公网 SHA-256 回读均通过，v3 原本已指向同日中文投影，未改字节。[Dev 脱敏报告 PR #1250](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/1250) 记录发布边界。
- Beta 模拟器构建成功。iOS 27.1 上显式连接 Dev 的 UI 测试实际打开并校验了中文、韩文、西文海报；中文截图可见 `2026.10.18`。成功 `.xcresult` 在 `artifacts/tongxing-ios/2026-10-21/cli/20261021T171151-test-eb988ab1/`，脱敏报告见 [PR #1256](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/1256)。截图留在本机忽略目录 `artifacts/tongxing-ios/2026-10-21/live-poster-attachments/`。
- iOS 26.2 模拟器的 Beta 本机通知测试实际看到系统通知，点击后打开绑定的页面与语言，退出码为 0；见 [PR #1254](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/1254)。iOS 27.1 的另一模拟器未进入通知权限已允许状态，该轮通知用例失败；不能把它写作 27.1 通知通过，失败见 [PR #1253](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/1253)。初次滚动断言失败与运行器启动 Busy 也分别保留在 [PR #1251](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/1251)、[PR #1255](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/1255)。
- 单设备 APNs 发送器对当前 Dev v5 默认页进行了只读内容预检：中文、韩文、西文三条通知都绑定到 `resi-20261018-15030286`，各自 release 哈希与线上发布包一致；没有设备 token、私钥或 APNs 请求。见 [PR #1261](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/1261)。
- 2026-10-21 晚间在 iPhone Duo／iOS 27.1 上补验同一 Beta 源码：听音定位的早停、全部未命中、超时后命中、迟到结果、取消、运行预算和本地化提示共 7 项实际通过、0 失败、0 跳过，见 [PR #1267](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/1267)；真实麦克风与现场声学效果仍待真机测试。本机通知用例两次仍未通过：点击申请权限后状态保持“尚未申请”，Duo 双屏截图均未出现系统授权弹窗，故没有完成安排、显示或点击跳转。首次测试退出码 65，见 [PR #1265](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/1265)；复验的 XCTest 用例失败，运行器清理阶段停顿并终止，退出码 130，见 [PR #1266](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/1266)。授权弹窗缺失原因尚未确认，不能把 iOS 26.2 的通知通过外推为 iOS 27.1 通过。

## 签名、上传与 Apple 读回

- Xcode 27.1、iOS SDK 27.1 的 BetaRelease Archive 成功，App 和扩展实际版本均为 `1.26.20 (61)`，内容源为 `https://ai-for-god-sermon-audio-dev.web.app`。Archive 文件清单 SHA-256：`8660febcda99aa6b6a10fdf9c7fa872749e786e1a088dc07a2717b1b57a86402`。首次归档因新工作树缺少本机忽略的签名配置，在签名预检停止；补回既有本机配置后于新目录成功，失败报告见 [PR #1257](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/1257)。
- 同一 Archive 的 App Store Connect IPA 导出成功，IPA SHA-256：`a38422ed2687872a5e2f910c52aeea3ae7b5b656b4cc3d0950a053afed364d0e`。导出包中 App 与扩展身份及版本一致；分发 profile 的 `aps-environment=production`。归档与导出脱敏报告见 [PR #1259](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/1259)。
- TestFlight 上传命令成功返回。Apple 于 2026-10-22 00:24:28 UTC 读回准确 Build ID `8d552fff-34e4-44da-8da9-18da4e92151f` 为 `VALID`、未过期、`IN_BETA_TESTING`；Rooted 内部组包含该 Build。What to Test 已保存并读回，SHA-256 `75b2abf60eb5fbf8cc5f30db1e6bb5cfe6ca0d7a597d54f971acccd71d25970c`。脱敏交付报告见 [PR #1260](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/1260)。

本机私有收据：归档与 IPA 在 `artifacts/tongxing-ios/beta-1.26.20-build61-r2/`；上传、Apple 处理、分发分别在 `artifacts/tongxing-ios/testflight/20261022T001815Z-178a70fb/`、`20261022T001932Z-61651157/`、`20261022T002422Z-a760ff1f/`。这些目录不进 Git。上传、处理、内部组关联是三个收据，均不代替设备验收。

## 下一步验收边界

Rooted 内部 TestFlight 现可安装。本人真机上的 10 月 18 日页面、三语言海报、真实麦克风听音定位、通知显示与点击尚未验收。远端 APNs 仍是仅限本人设备的手动单次发送路径，需安装此 Build 后自愿登记并导出本机设备收据；本轮没有远端发送或群体推送。正式 App 重建、Production 内容源验收、App Store 提交与现场验收均为 `not_run`；待用户确认 Beta 手工测试结果后按正式渠道发行流程继续。
