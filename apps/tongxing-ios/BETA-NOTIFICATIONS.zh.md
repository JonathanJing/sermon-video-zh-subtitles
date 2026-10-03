# Beta 通知实验

本次只增加「同行-beta → 更多选项 → Beta 通知测试」。默认关闭，选择**订阅内容语言**后由使用者主动申请系统权限、选择 Dev 内容，安排最早约 5 秒后触发的单设备本机通知。界面语言不会改变订阅语言。正式 App 不显示此入口，也不安装通知 delegate。本次没有 APNs 登记、sender、FCM SDK、群体发送、Service Extension 或生产部署。

本机通知使用 UserNotifications；它不需要 APNs token。预览只接受 Dev 的 v3 目录中已有、内容状态 `human_reviewed` 的独立双稿页面，同一语言的音频不存在时正文明确「暂无音频」。点击绑定 `environment + pageID + locale + releaseSHA256`，重新核对当前目录及订阅。旧版本、错误语言、退出订阅或正式环境不会切换内容。页面与音频继续沿用原有哈希校验；客户端目录标记不替代内容人工批准。

## 文案与发送方式

这轮通知用通用多语言文案：标题「[Beta 测试] 新内容已上架」，正文「日期 · 打开同行 Beta 查看并试听」，文字版为「打开同行 Beta 阅读文字。此语言暂无音频」。English、한국어、Español、Tiếng Việt 有相应文案。通用标题避免拿中文目录标题当成其他语言标题；后续个性化标题须从对应语言的已验证内容提取，翻译及真人审核后再使用。

建议正式通知只在新内容可交付时发送，内容包含标题/日期/内容语言和真实音频可用状态。目录刷新、短暂网络失败、现场麦克风状态变化不主动推送；现场状态使用 App/Live Activity。更正通知应另列原因、版本及人工决定，不能自动将去重失败转成再次群发。频率、静默时段与正式订阅默认值在本机实验之后确定。

现阶段先用本机通知验证授权、语言、外观与点击；下一阶段建议 APNs 直连单台明确指定的 Beta 设备，减少新增 SDK。只有需要 Android/web 统一订阅及发送管理时再评估 FCM。两者都需要受控 sender、设备登记/退出同步与凭据管理，不能凭 Firebase Hosting 已存在推断推送已接通。

APNs 实发前需补充：Beta App ID 的 Push Notifications 能力和实际签名 `aps-environment`；仅本人指定设备的安全登记；sender 的环境与 bundle topic 绑定、订阅语言、内容版本/落地校验、服务端去重、退出和 token 更新；传输失败保留未知结果而非自动扩大收件人。TestFlight Beta 可能使用 production APNs，不能按「Beta」名字推断 sandbox；内容环境仍为 `beta-dev`，不得混用正式收件群体。token 与 key 不进入 Git、日志、截图或 PR。本次不读取或输出这些值。

## 本机人工验收

1. 用 `TongxingBeta` 新候选安装，记录实际版本、Build、iOS 与机型；确认内容 origin 是 Firebase Dev，正式 App 同时存在。
2. 在更多选项打开 Beta 通知测试，确认默认关闭。先选内容语言，再开测试开关，按「允许系统通知」；拒绝则显示原因，可前往系统设置。退出/后台回来会重新读取系统权限。系统权限与安排／退出结果分别展示，权限刷新不会覆盖操作结果。
3. 选一条已有该语言版本的 Dev 独立双稿页面，核对预览文字和音频状态。按「安排本机测试通知（约 5 秒后）」，先留前台再单独测后台/锁屏。记录「已安排」与「设备可见」为两项证据；前者不能证明后者。
4. 点通知，确认更多面板关闭、打开正确内容/语言，原有阅读及音频完整性检查仍执行。记录标题、语言、文本/音频可用状态与实际播放；无音频不冒充试听成功。
5. 同版本/语言再次安排应提示已测试。更换语言会清除旧语言的本机通知，退出会清除本机测试通知并拒绝新安排；测试中快速退出/改语言不应留下迟到通知。清除本机测试记录是明确的重试操作。
6. 删除/替换目录版本、错误 environment/locale/hash 的通知不能切换当前内容。无该语言页面时只说明不可测试，不自动改发另一语言。
7. 正式 scheme 不显示实验入口；本次通知修改不代表正式版发布批准。

自动 UI 测试保留 App 进程的合成来源参数，以后台返回验证点击路径；不使用 `terminate` 后的 OS 冷启动冒充 fixture 路由。真机另测 App 被结束后的通知点击、无网启动/目录加载失败及后续恢复。5 秒是本机通知最早触发时间，系统调度及模拟器负载可能延后显示，不承诺 5 秒内可见。

当前去重只保存在 App 本机，键为环境、page、语言、release hash 和随机安装实例，保留最近 200 次安排。卸载或主动清除测试记录会重置；它是实验防重复，不是可靠远端投递账本。远端 sender 需另实现持久幂等记录。关闭不会撤销已经被系统显示的远端通知，本次清除只针对本机实验通知。

## 模拟器 payload 路由检查

`simctl push` 绕过 APNs provider，只证明模拟器通知显示/点击处理。先在 Beta 打开本机测试开关并选择相同语言；从当前 Dev v3 目录取得真实 `id` 和该语言 `releasePackageJsonSha256`，不要使用占位 hash。将以下 JSON 保存到被忽略的 artifacts 目录，填入绑定值：

```json
{
  "aps": {
    "alert": {"title": "[Beta 测试] 路由检查", "body": "打开同行 Beta 核对内容语言与版本。"},
    "sound": "default"
  },
  "tongxing": {
    "schemaVersion": "tongxing-beta-notification-v1",
    "environment": "beta-dev",
    "pageID": "填写当前 Dev 页面 ID",
    "locale": "zh-Hans",
    "releaseSHA256": "填写当前目录该语言的完整 SHA-256"
  }
}
```

选择当前任务使用的单个模拟器执行，不使用 `booted` 指向不明的多台设备：

```sh
DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer xcrun simctl push \
  "$TONGXING_SIMULATOR_UDID" com.jonathanjing.tongxing.beta "$TONGXING_BETA_PAYLOAD_PATH"
```

分别保存有效绑定、错语言、改 hash、production environment、退出后的结果。`simctl` 返回成功不是 APNs 接收，也不是实际 iPhone 收件；本次尚未执行这项人工操作。

## 自动验证与远端限制

Core 定向测试覆盖五种语言、文本版文案、绑定往返、旧 hash/错误页面/环境拒绝、退出/错语言/正式渠道拒绝及去重维度。UI 的第一项验证独立实验入口、默认关闭、显式 opt-in 与退出状态，不申请系统权限；第二项只在 Beta scheme 使用显式 `--ui-testing-notification` 和隔离状态复用合成 v3 目录，申请模拟器系统权限、实际安排本机通知、切后台、核对 Springboard 可见通知、点击并检查页面/语言路由。它验证模拟器本机路径，不经过 APNs，不能替代真机收件。Core 本轮定向 5 项已通过；模拟器 UI 的最终结果由本轮主 Agent 记录。

```sh
DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer swift test --package-path apps/tongxing-ios/Core --filter BetaNotificationTests
apps/tongxing-ios/scripts/ios.sh test --scheme TongxingBeta \
  --only-testing TongxingUITests/BetaNotificationUITests --simulator "$TONGXING_SIMULATOR_UDID"
```

远端 APNs、真机锁屏收件/点击、后台权限变化及听感未完成。没有登记和 sender 安全配置时不宣称「推送通过」，也不申请/读取凭据来凑验收。后续单设备实发记录必须分别列 provider accepted、设备可见、点击正确 Dev 页面与同语言播放。正式通知仍要先完成 Beta/Dev 人工核对及正式双端内容验证，再取得准确发送范围的授权。

海报富媒体放在下一阶段：对应语言和内容版本的图片经人工确认后，再实现 Notification Service Extension、受控 HTTPS 下载、时间限制、附件校验以及下载/解码/超时的原纯文字回退。本次全部为纯文字通知，不把缺图当发送失败，也不把纯文字测试当图片回退已通过。

依据 Apple 一手资料：[申请通知权限](https://developer.apple.com/documentation/usernotifications/asking-permission-to-use-notifications)、[delegate 安装时序与前台/点击处理](https://developer.apple.com/documentation/usernotifications/unusernotificationcenterdelegate)、[登记 APNs](https://developer.apple.com/documentation/usernotifications/registering-your-app-with-apns)、[远端 sender](https://developer.apple.com/documentation/usernotifications/setting-up-a-remote-notification-server)、[通知内容扩展](https://developer.apple.com/documentation/usernotifications/modifying-content-in-newly-delivered-notifications)。权限在使用者有明确上下文后申请，拒绝后不反复弹窗；delegate 在 launch 时安装。
