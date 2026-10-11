# Beta 1.26.17（58）每周海报交付

日期：2026-10-07。归档源码：`e2c8f40c93e559060ce8eebf7fe3d5cc0d4a7ab1`，Beta bundle `com.jonathanjing.tongxing.beta`。正式 App 和正式 Hosting 未变更。

## 验证与发布

Xcode 27 / iOS SDK 27.0 构建、Archive 和同一 Archive 导出通过。IPA SHA-256：`6f9bc3611b211727a210de608be6e8b24053ee2efe27f873970984089972ca5d`。Core 3、Infrastructure 2、Python producer 3、UI 2、hosted 播放模型 3、真实 Dev Duo UI 1 项通过。

Dev Hosting 发布版本 `b3f972eb12785d0f`，仅加入 sidecar 与中、韩、西三张 PNG；原 461 文件 Hosting hash 全部保留。四个 URL 的 GET 与 SHA 读回通过，目录/default 页面不变。Duo iOS 27.1 截图经 Device Hub 实际显示后捕获，初始黑帧 XCTest 截图不作为视觉证明。

TestFlight 上传、处理、Rooted 组分发与 What to Test 读回通过；准确 build ID `f10259c3-901b-410e-bc3b-4773541f6663`，Apple 状态 `VALID` / `IN_BETA_TESTING`，未过期。上传证据 `20261007T192240Z-a552c68e`，处理证据 `20261007T192433Z-89f40a69`，分发证据 `20261007T193342Z-afeab72b`。

## 真机验证

1. 从 Rooted 内部 TestFlight 更新同行 Beta 至 1.26.17（58）。首次打开或刷新首页，确认出现本周更新与对应海报。
2. 关闭海报，退出再打开，同一页面/语言/release 不重复提醒；首页“本周海报”仍可重新打开。
3. 切换简体中文、韩语、西语，确认标题、海报及“打开本周内容”的语言匹配。
4. 开始播放，打开并关闭海报，确认继续播放且进度不重置。
5. 本机测试通知点击进入对应海报。远程 APNs 实发尚未接通，不能用本机通知替代验收。

真机安装、用户界面验收与远程推送实发：not_run。海报二维码沿用正式站，App 按钮进入 Dev。每周 sidecar 生成及完整站点部署仍须执行发布步骤。

APNs Key 由账户持有人或 Admin 在 Apple Developer 创建，步骤见 [APNS-SETUP.zh.md](../apps/tongxing-ios/APNS-SETUP.zh.md)。设备登记和服务器发送将在专用密钥配置后接通。

私有可复核证据位于本轮忽略目录 `artifacts/weekly-announcements/`、`artifacts/tongxing-ios/beta-1.26.17-58/` 和 `artifacts/tongxing-ios/testflight/`；凭据及媒体未提交 Git。

## 后续源码合并（2026-10-10）

PR #322 已将本页记录的海报功能带入 `dev`。PR #275 随后同步当前 `dev`，保留正式/Dev `1.26.18 (58)` 和 Beta `1.26.18 (59)` 的项目配置及 APNs 测试引用；本页的 `1.26.17 (58)` 仍是历史冻结候选。此次同步只归并源码历史，不产生新的归档、上传或发布回执。
