# 本周海报默认周次修复

用户报告 iOS 本周海报仍打开上周。根因为生产 v4 catalog.defaultPageId 仍指向 resi-20261004-69ba7a66，尽管 announcement 已有本周三语。WeeklyUpdates.load 使用 catalog 默认页，而非 sidecar 插入顺序或发布时间。图片缓存按 SHA 绑定，不是新图覆盖成旧图。

本轮只将 v4 默认页设为 resi-20261011-54475d42，其他公开文件、Firebase 配置及 v3 人工投影保持原字节；不修改审核状态或任何上游产物。正式 1.26.18 冻结源码支持 v4 与 machine_checked，无需为该目录修复新增 App 构建。发布版本 c10d222bd231b959，基线23e73e929047d76a，部署15:59:39–15:59:54 UTC。远程租约已释放。

部署后 v4/v3/海报索引的完整 HTTP 字节与哈希一致；按 App 选择规则检验三语均选中本周 announcement，三个图片 hash 通过。实际手机刷新显示尚未核验。此次遗漏说明海报发布后必须检查 catalog.defaultPageId 与 sidecar 的组合，不能只检查图片和 release hash。

用户同时授权向正式 App 用户发送本周更新，点击打开海报。只读核对当前及冻结发行源码：BetaNotifications 限定 Beta bundle；APNs entitlement 仅在 Beta；BetaRemotePush 是本人设备手动登记与导出，现有 sender 仅单设备 Beta。正式用户登记、订阅及群发通道未接入。已准备三语通知文案与本周release/poster绑定；没有发送任何推送，也没有改发给Beta设备。后续需要实现并发布正式客户端推送登记和受控发送端，再向已订阅用户发送。

无代码修改、无新增模型生产调用、无设备安装或权限变更。所有本地运行证据保存在 ignored artifacts；本报告供云端复核，未声称云端已经复核。
