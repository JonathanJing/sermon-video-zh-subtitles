# Beta 前台灵动岛未显示：未解决（2026-10-03）

用户报告真机定位时没有看到灵动岛效果，机型 iPhone 17，iOS 27.0.1。用户未提供已安装的 Beta build，也未确认普通播放活动是否显示。此前 `1.26.9 (50)` 的 TestFlight Testing 记录仍成立，但不能视为定位展示验收。

## 已确认的问题与候选

已上传源码使用普通实时活动，而听声定位需要 App 前台；普通活动不保证在自身 App 前台展示。暂停定位的终态调用 `end(.after(8))`，其中 8 秒影响锁屏保留，灵动岛在 end 时已移除。[Apple HIG](https://developer.apple.com/design/human-interface-guidelines/live-activities)、[ActivityKit 生命周期](https://developer.apple.com/documentation/activitykit/displaying-live-data-with-live-activities)。

本分支加入待验证候选，尚未归档或上传：

- Beta 的 iOS 18+ 使用独立 `.transient` 定位活动；普通播放活动保持独立，iOS 17 保留既有活动与 App 内反馈。
- 麦克风实际开始采集后才创建，避免首次权限弹窗提前移除临时提示；每次明确开始生成事务 UUID，取消后重开即使状态更新合并也可区别新事务。
- 用户收起当前活动后同事务不强制重建；结果更新后等待原有 8 秒清理，而非立即 end。后台、换源、手动操作与销毁清理沿用播放器链路。
- 展开布局突出定位状态，紧凑布局显示监听／匹配／结果；定位 relevanceScore 为 100，普通播放为 50，避免普通播放优先占用。
- 请求错误与活动禁用有系统日志；日志不记录音频、媒体路径或用户内容。

上述公开 API 是 Apple 文档指定的前台临时活动路径，但不代表当前系统已实际展示。

## 实测与限制

| 验证 | 结果 |
| --- | --- |
| BetaDebug 构建 | 通过 |
| Core | 76 通过 |
| iOS 27 对齐事务／活动 payload／播放器回归 | 54 通过，0 跳过，runtime warnings 0 |
| 显式启用真实 ActivityKit，iPhone 18 Pro / iOS 27.0 模拟器前台系统展示 | **失败：创建与更新成功，但系统截图没有定位提示** |
| 诊断性 alertConfiguration 的第二轮系统展示 | **失败：仍未显示**；该诊断已移除，不增加提示音 |
| 真机新候选、真实麦克风与现场定位 | 未运行 |

普通测试仍禁用系统活动；本次新增 `ListeningActivityUITests` 必须显式 opt-in，失败不以创建成功替代。首次工程未重新生成导致 0 项测试的 run 不计通过。系统日志记录 `isMomentary:true`、`Should Show System Aperture:false`、自身 App 前台及 alert suppression；这些是观察，不足以判定 Apple 系统缺陷。

复现命令（选已有带灵动岛模拟器）：

```sh
TONGXING_LIVE_ACTIVITY_SMOKE=1 TEST_RUNNER_TONGXING_LIVE_ACTIVITY_SMOKE=1 \
  apps/tongxing-ios/scripts/ios.sh test --scheme TongxingBeta \
  --configuration BetaDebug --developer-dir /Applications/Xcode.app/Contents/Developer \
  --simulator "$TONGXING_SIMULATOR_UDID" \
  --only-testing TongxingUITests/ListeningActivityUITests
```

使用明确的 DEBUG 合成事务及静音媒体，不访问麦克风；系统提示由真实 ActivityKit／Springboard 渲染。不能代替真机现场验收。成功条件是实际观察前台监听→匹配→结果、新事务重开和清理；不能只看返回的 activity ID。

私有证据在本工作树 `artifacts/tongxing-ios/2026-10-03/`：`island-smoke-failed/manifest.json` 与已读取的原始 PNG；CLI `20261003T103846-test-e81d5f9e`、`20261003T104148-test-f08200cc` 为失败 run，`20261003T104324-test-9dc6f443` 为 54 项回归 run。前台可见问题仍未解决，新 Beta 上传暂缓、版本号未递增，正式晋升不执行。按 iOS AGENTS 的两轮定向修复边界保留候选及失败证据，下一步需要不同系统或真机的实际呈现证据定位剩余抑制条件。
