# Beta 54 锁屏双语字幕停滞排查

用户在 iPhone 17 Pro／iOS 27.0.1 的 Beta 1.26.13（54）报告黑色 Live Activity 卡片的中英字幕没有随播放更新。附图同时有系统媒体卡片和 App Live Activity；卡片计时由系统计时视图推进，不能仅据时间变化证明字幕发布链路在执行。此项实机验收记为用户报告失败，尚未完成受控连续播放复现。

## 检查结果

PlaybackController 的 0.25 秒 periodic observer 更新当前位置并调用 publishLiveActivity；currentSystemSubtitle 使用当前加载音轨绑定的明确时间区间。协调器 shouldPublish 比较字幕 ID、中英文，句子变化不会被 15 秒心跳节流。既有 Activity.update 没有 foreground 限制。Widget 直接读取 context.state，未发现正文缓存或后台清空播放字幕的明确缺陷。独立只读审查与上述结果一致。

Apple [update 文档](https://developer.apple.com/documentation/activitykit/activity/update(_:)) 支持后台更新；[论坛中的类似音频后台停更报告](https://developer.apple.com/forums/thread/822999) 是其他开发者经验，不能作为 Apple 已确认本案原因的证明，也不能据此保证 FrequentUpdates 配置或后台任务能解决。没有修改音频 category、添加虚假后台模式、增加推送基础设施或改变字幕时间映射。

## 候选诊断与验证

跨句提交前与 Activity.update 返回后记录活动 ID、字幕 ID 的短 SHA-256、播放位置和 App 状态；不记录字幕正文、URL 或源身份。返回后的 Activity.content 只是客户端数据，不证明 SpringBoard 实际渲染。已安装 Beta 54 不含新日志，本轮候选尚未上传。

新增测试使用真实 AVPlayer 连续播放跨第一句／间隙／第二句，没有 seek；另一项真实 ActivityKit 测试确认既有播放活动在协调器 background 状态下清除间隙字幕并接受第二句中英文本。后者只覆盖后台决策，未真正锁屏，不能代替真机呈现。

- iOS 27.0：10 项执行全部通过，0 跳过，cli `20261005T144427-test-1f694aae`。
- iOS 17.5：两项受影响测试执行通过，0 跳过，cli `20261005T144459-test-88aa634b`。
- 独立只读审查无阻断；git diff --check 通过。

用户已收到“播放后锁屏约 1 分钟”复现请求，Console 已开启诊断。额外读取当前锁屏截图时没有活动播放卡片，因此该截图不能验证字幕停滞；私人壁纸仅保存忽略目录，不发布到 PR。等待受控播放后核对新活动的更新事件。当前没有确认具体根因，也没有行为修复，不宣称锁屏字幕恢复；网页 not_applicable。
