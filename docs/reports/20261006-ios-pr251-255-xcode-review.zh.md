# PR251–255：Xcode 与设计验证

2026-10-06。目标为分析、构建与原生截图，未合并原 PR、未发布新 Beta。五个原始 head 均实际构建；只有 PR253 原样构建成功。当前 PR252 与 PR254 有播放栏冲突，253→254→255 为堆叠链，251 独立。

## 原始构建

| PR | 精确 head | 原始结果 | 阻断 |
|---|---|---|---|
| 251 | 046dc373c2911aa731c365d84c1052e8686bd48b | BetaDebug，exit65 | matchFn 缺 @escaping |
| 252 | 4ce5bee2fa94f647dd8e2856c88b06a78f60e857 | Debug，exit65 | Shape 泛型没有 strokeBorder |
| 253 | 1c4aa74078be44c985f1dc787796b48dd1ba120d | Debug，exit0 | 构建通过，折痕逻辑仍有反例 |
| 254 | 936cd1d8080d69a3469d7652c54a0d1be5698c29 | Debug，exit65 | 两个 PlaybackMoreControls 缺 isPreparing |
| 255 | 96130cc88928a7170a822f0c45e5fe94d206aad4 | BetaDebug，exit65 | Optional AppModel 不满足 ObservedObject |

工具链为 /Applications/Xcode.app 的 Xcode27.1，iOS Simulator27.1 SDK；原始 build 使用 generic iOS Simulator，不等于真机运行。分别保存实际 status.json、日志和 xcresult。

原始证据：

- PR251 独立 worktree `pr251-earlystop-validation`，`artifacts/tongxing-ios/pr251-validation/cli/20261006T072034-build-08a29e63/`；原 test 编译失败 `20261006T072106-test-2d7b4307`。
- PR252 独立 worktree `pr252-exact-build`，`artifacts/tongxing-ios/2026-10-06/cli/20261006T072345-build-00affdd6/`。
- PR253 独立 worktree `pr253-exact-build`，`artifacts/tongxing-ios/2026-10-06/cli/20261006T072404-build-7fa7d0e0/`。
- PR254 独立 worktree `pr254-exact-build`，`artifacts/tongxing-ios/2026-10-06/cli/20261006T072346-build-c76f2d29/`。
- PR255 本验证 worktree，`artifacts/tongxing-ios/2026-10-06/cli/20261006T072001-build-3850f8d5/`。

## 行为问题

1. **P1，251 超时未释放等待**：`AudioAlignmentController.swift:223–236` TaskGroup 在取消其余 child 后仍等待 child 完成。加唯一 @escaping 验证修补后，四项新 checkpoint 测试实际 3 通过、1 失败；慢匹配测试仍只有一次 match、没有 seek，3秒最终等待超时，未进入下一 checkpoint。证据 `pr251-validation/cli/20261006T072126-test-82e2dd64/test.xcresult`。不可把 cancelAll 当作硬超时。[Apple TaskGroup 说明](https://developer.apple.com/documentation/swift/taskgroup/isempty)
2. **P1，251 启动异常清理缺失（源码审查）**：`MicrophoneCapture.swift:138–152` 配置录音 category 后、activeStream 赋值前，启动失败／取消分支没有对新 session teardown、移除 observer 或恢复播放 category。须补可注入启动失败／启动后取消验证。当前没有真机触发证据。
3. **P2，251 15秒预算只限制累计 PCM**：没有独立 wall-clock watchdog。无 buffer／frame gap 下实际占麦可能延长至控制器20秒期限；fake checkpoint 不验证真实 PCM 与墙钟，需要专项测试。
4. **P1，255 后台下载到期（源码与平台合同）**：`AppModel.swift:675–676` 无 expiration handler，只在下载返回后 end；到期时慢下载不能保证结束任务和进入重试。Apple 明确必须在期限结束前结束，否则可能终止 App。[Apple 后台任务文档](https://developer.apple.com/documentation/uikit/uiapplication/beginbackgroundtask(expirationhandler:))
5. **P2，253 避让可被 clamp 抵消（几何反例）**：原 ContentView，254迁至 PlaybackDock 的 avoidingReservedRegions。1000×600 host、区域(490,0,20,600)、面板(440,52,320,176)，当前算法选纵轴移动后 clamp 到 y12，仍跨区域。右侧本有空间；最终矩形没有检查交集。该项为源码推导，未声称半折真机复现。
6. **P2，252 紧凑模式丢失 VoiceOver 时间**：紧凑布局隐藏 timeAndStatus，playButton accessibilityValue 只有 statusLabel，未包含进度／总长。注释所说通过播放按钮保留时间尚未实现。
7. **254 精调共享浮层缺入口（本地候选实测）**：暂停就绪且无撤销位置时，PrecisionSheet 的 PlaybackDock 没有 alignmentModel／precision／current，hasMoreControls 为 false，故看不到更多按钮。验证测试 line30 isHittable 失败，截图确实没有定位图标。OutlineSheet 同类调用也需检查。此项是声明的共享面板目标未可达，未武断标为相对基线的新回归。

## 截图候选与差异

截图在 `codex/pr251-255-xcode-validation`，基于255 head并合并252，合并 revision `553a933b0006a8b8fd4174c849966aba5b2f75b2`。只为继续界面验证做最小编译修补：Shape→InsettableShape、两个 isPreparing:false、移除 Optional 上的 @ObservedObject；保留后者为普通可选参数。因此**不证明255对齐徽标观察已修复**。251在另一独立目录验证，不包含在截图候选内。

新增测试仅采集状态及44pt命中区、精调入口。不改字号／产品时间规则。精确可重放差异见 [validation-only.patch](20261006-pr252-255-validation-only.patch)，对上述 merge revision应用。原PR未改；这些修补不是生产候选。

实际验证：

- iPhone18Pro / iOS27.0：UI3项，2通过（AX3收起／展开、普通手机横屏操作），1失败（精调面板没有更多）。`cli/20261006T072314-test-93d14633/test.xcresult`。
- Duo外屏466×678 / iOS27.1：外屏布局与更多邻近按钮1通过；内屏横向1跳过，观察到的仍为外屏尺寸，不能替代内屏实测。`cli/20261006T072557-test-0fc02b16/test.xcresult`。
- SwiftUI真实视图预览：ContentView和PlaybackDock各light／dark／dark-large共6张，render test通过，成功Manifest含源码SHA和dirty状态。`preview/20261006T072559-e616e89a/manifest.json`。这是合成静音音轨视图预览，不是线上媒体或锁屏截图。

视觉结论：常规字号浅／深色与圆形收起态可读，主要按钮可达；AX3预览出现时间与微调图标拥挤、播放栏与当前字幕区域重叠，不能据渲染成功宣称大字号阅读通过，需补安全区与滚动可读性检查。普通横屏PNG出现捕获裁切／黑区，保留原图但不用于视觉验收；仅相应UI位置断言通过。Duo外屏截图的合成夹具处于音频未准备失败状态，不证明播放或声学识别。

本地截图入口 `artifacts/tongxing-ios/pr251-255/screenshots.md`：4张竖屏运行截图、2张Duo外屏运行截图、6张视图预览，共12张已读取有效截图。另保留横屏问题PNG和原始XCTest附件、manifest。

## 建议顺序

先修251、252、254、255编译阻断；随后处理251超时／资源清理和255到期收尾。再修折痕最终交集、精调／大纲入口、紧凑栏VoiceOver时间与AX3阅读布局。按253→254→255保持依赖，252与254整合保留圆玻璃、ViewThatFits及可见收起按钮。真机声学、耗电、VoiceOver焦点、后台真实期限、Duo内屏／半折均未验收。

本轮网页处理 not_applicable（原生PR构建和设计审核）；不触发内容生产、PR合并或TestFlight分发。
