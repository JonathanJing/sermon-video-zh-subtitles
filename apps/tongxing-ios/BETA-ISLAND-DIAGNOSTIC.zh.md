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
- 兼容性测试发现 SDK 的 `.transient` 枚举缺少正确的旧系统符号边界：首次 iOS 17.5 启动发生 dyld missing symbol。App 对 ActivityKit 使用 weak framework 链接，并保留 iOS 18 运行时判断；重新实际启动测试后 23 项通过，`nm` 确认 transient 符号为 weak external。

上述公开 API 是 Apple 文档指定的前台临时活动路径，但不代表当前系统已实际展示。

## 实测与限制

| 验证 | 结果 |
| --- | --- |
| BetaDebug / BetaRelease 未签名模拟器构建 | 通过 |
| Core | 76 通过 |
| iOS 27 对齐事务／活动 payload／播放器回归 | 54 通过，0 跳过，runtime warnings 0 |
| 显式启用真实 ActivityKit，iPhone 18 Pro / iOS 27.0 模拟器前台系统展示 | **失败：创建与更新成功，但系统截图没有定位提示** |
| 诊断性 alertConfiguration 的第二轮系统展示 | **失败：仍未显示**；该诊断已移除，不增加提示音 |
| 加入活动优先级后的最终前台系统复核 | **失败：仍未显示**，不继续改公开展示路径或使用私有 API |
| iOS 17.5 对齐与活动状态兼容性回归，修复 weak linking 后 | 23 通过，0 跳过；首次 dyld 崩溃 run 保留、不计通过 |
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

私有证据在本工作树 `artifacts/tongxing-ios/2026-10-03/`：`island-smoke-failed/manifest.json`、`island-alert-failed/manifest.json`、`island-final-failed/manifest.json` 与已读取的原始 PNG；CLI `20261003T103846-test-e81d5f9e`、`20261003T104148-test-f08200cc`、`20261003T104722-test-09ce2228` 为系统呈现失败 run，`20261003T104324-test-9dc6f443` 为 54 项回归 run，`20261003T104912-test-3be09505` 为 iOS 17.5 兼容性通过 run；`20261003T105019-build-91ec2677` 为 BetaRelease 构建。候选仍有普通活动状态被隐藏的降级风险：当前无法从 active 状态判断 transient 是否真正显示；App 内状态保留，但不能宣称系统展示降级已完成。

前台可见问题仍未解决，新 Beta 上传暂缓、版本号未递增，正式晋升不执行。按 iOS AGENTS 的两轮定向修复边界保留候选及失败证据，下一步需要不同系统或真机的实际呈现证据定位剩余抑制条件。

## PR #232 评论与合并修复

后续评审指出 iOS 17 普通活动的 `end(.after(8))` 仍保留锁屏卡，但 coordinator 丢失引用。现单独保留结束活动；立即重试、播放、换源、清空或销毁先立即移除旧卡，串行等待结束并检查 revision 后才能请求替代活动。重复暂停终态仍保留原延迟，不把 App 主动结束视作用户移除。

合入最新 `dev` 时保留 Beta 通知和 Dev 候选的全部翻译；目录校验按 `dev` 完整逻辑合并，去掉自动合并产生的重复变量声明。Core 83 项通过；iOS 17.5 显式开启真实 ActivityKit 的重试／播放／清空三项生命周期回归通过，其他对齐／活动状态 24 项通过、1 项冻结 Dev 资料未提供而跳过。iOS 27 同组 24 项通过、1 跳过。两系统成功回归的 runtime warnings 为 0。

新回归须设置 `TONGXING_ACTIVITY_DISMISSAL_SMOKE=1` 和 `TEST_RUNNER_TONGXING_ACTIVITY_DISMISSAL_SMOKE=1`，通过 `ios.sh test --scheme TongxingBeta --configuration BetaDebug --only-testing TongxingTests/ListeningActivityDismissalTests` 在已有 iOS 17 模拟器执行。普通测试默认不创建系统活动；这些检查验证结束引用与替代流程，**不代表真机锁屏卡视觉或前台灵动岛已验收**。此轮不递增版本、不归档、不上传，仍等待合并到 `dev` 后统一构建新 Beta。
