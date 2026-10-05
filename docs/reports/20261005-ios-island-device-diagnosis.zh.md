# Beta 54 前台灵动岛实机排查

用户截图与设备查询确认：iPhone 17 Pro / iOS 27.0.1，安装 Beta 1.26.13（54）。采音期间没有显示定位活动内容。TestFlight 可用不等于这一功能实机验收通过；[Beta 记录](../../apps/tongxing-ios/BETA-RELEASE-1.26.13.zh.md) 已追加失败反馈。

## 实际观察与判断

用户再次定位并确认麦克风已经授权。Console 从目标真机观察：14:30:16 创建活动并发布，14:30:26 更新，14:30:34 结束，约 18 秒。descriptor 的 isMomentary=true，WidgetRenderer 活动渲染已运行；呈现选项含 Should Show System Aperture:false。当前证据指向呈现阶段，不能认定为麦克风权限未授予、没有请求 ActivityKit 或某个特定缺失配置。原始设备标识和账户不进入提交。

Apple [官方说明](https://developer.apple.com/documentation/activitykit/displaying-live-data-with-live-activities) 说明前台临时活动使用 request(...style:.transient)，外部点击、收起、锁屏等会结束活动；当前 Widget 提供 dynamicIsland 闭包。没有公开的 Show System Aperture 开关可直接修正日志选项。

## 已修复的独立竞态

首次麦克风权限 continuation 可先报告实际监听，UIKit 随后才恢复 active。原协调器会把 inactive listening 误判为用户离开并永久抑制。候选修复：未呈现的同次任务允许保存实际采音并等待 active，scene 恢复 active 重发最新状态；真实 background 仍抑制，已呈现后收起仍不重开。同步判断绑定任务与来源，旧任务的呈现状态不污染新任务。添加创建成功日志以便定位未创建与未呈现。此修复不能解释此次已经创建成功的真机重试，也不宣称恢复显示。

Xcode 定向结果：iOS 27.0 共 16 项执行通过、0 跳过（cli 20261005T143447-test-599ada5f）；iOS 17.5 共 12 项执行通过、4 项临时 API 专属跳过（cli 20261005T143533-test-3881a3d3）。独立只读审查修正旧任务污染后无剩余阻断；git diff --check 通过。未改变 Widget 布局、匹配算法或采音时长，网页 not_applicable。

## 真机对照待完成

忽略目录 artifacts/tongxing-ios/device-island-probe/ 保存独立诊断项目，直接使用同一 Widget／共享视图／attributes，仅创建静态活动，不录音、不播放，不覆盖 TestFlight Beta。Xcode 真机 build 成功；首轮安装远端连接关闭，重试安装成功。启动被系统明确拒绝，原因为设备锁屏，用户已收到解锁请求。待解锁后先检查无录音 transient 实际截图，再根据结果检查 alert update／standard 对照。当前系统呈现根因未确定，未上传新的 Beta，原 Beta 54 实机功能验收仍为 failed。
