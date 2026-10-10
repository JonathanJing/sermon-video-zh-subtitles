# iOS 旧 PR 合并边界（2026-10-10）

`dev` 已通过 #322 包含 1.26.18 的海报和 APNs 功能。此次依次收拢 #261、#263、#267、#275、#276 的剩余类别功能、历史发行记录和测试，不回退正式/Dev `1.26.18 (58)`、Beta `1.26.18 (59)`，也不重新归档、分发、发送推送或部署内容。

#275 同步当前 dev 后不再有产品代码增量；旧审核线程关闭表示历史 PR 已完成归并，不表示其中反馈的问题都已修复。下列事项保留为现有 dev 的后续修复范围，不能据本次合并宣称已通过对应场景验收：

- 海报 sidecar 的显式刷新、520 条上限、标题和最终 ID 长度，以及错误语言/announcementEligible=false receipt 拒绝。
- binding receipt 输出目录应与公开 Hosting 快照分离；本次不运行 sidecar 生产或发布。
- v2 reader 和与 weekly.json 重叠页面的海报内容按钮路由。
- 海报缓存清理、跨实例并发写入和多窗口通知落地。
- APNs sender 的 v4/release 路径兼容、旧或冷目录通知的 pending 重试，以及新增控件的多语言。

原始反馈和上下文保存在 [#275 审核](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/275#pullrequestreview-threads) 与 [#276 审核](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/276#pullrequestreview-threads)。后续修复需绑定其自己的 revision 和回归证据；既有单设备远程通知证据仍只证明记录中的设备、包和操作。
