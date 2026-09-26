# 同行 iOS 设计约定

日期：2026-09-05。用户已选择 **iOS 27 设计语言**，继续使用“同行”、副标题“证道中文听译”和同行绿。设计目标是让听众容易读到当前字幕、找到播放控制并完成现场微调。

Apple 已发布 iOS 27 设计资源，并继续完善 Liquid Glass，包括让用户在系统设置中调整透明程度。因此，优先采用系统组件及其自适应行为。[设计更新](https://developer.apple.com/design/whats-new/) · [iOS 27 公告](https://www.apple.com/newsroom/2026/06/apple-unveils-next-generation-of-apple-intelligence-siri-ai-and-more/)

## 视觉与交互

| 区域 | 实施方向 |
| --- | --- |
| 导航 | 使用系统导航与工具栏。同行绿用于品牌和主操作，文字、次级信息使用适应外观的语义颜色。 |
| 当前字幕 | 使用稳定实底，基准字号 26 pt，随 Dynamic Type 增长。允许自然换行和滚动，避免用固定高度、截断或缩字掩盖空间不足。 |
| 字幕全文与大纲 | 保持清晰的内容层，使用普通背景、间距和文字层级；正文不应用 Liquid Glass。 |
| 悬浮播放器 | 采用单层 `.regular` Liquid Glass，内部使用普通按钮。播放、暂停与前后微调保持稳定位置，主播放操作用同行绿突出；不叠加第二层玻璃按钮或额外模糊背景。 |
| 内容与播放器交界 | iOS 26 及以上用 `safeAreaBar`，为自定义控制栏接入系统滚动边缘效果，并让正文避开操作区域。 |
| Sheet | 保留系统默认背景、圆角与紧凑尺寸自适应。大纲使用 large；精调面板使用 medium/large，无障碍大字时仅使用 large，避免播放器占满半屏。 |

Liquid Glass 属于导航与操作层；大量文字的控制优先使用 `.regular`。自定义背景、重叠玻璃和过多颜色会干扰内容层级及可读性。[Materials](https://developer.apple.com/design/human-interface-guidelines/materials) · [采用 Liquid Glass](https://developer.apple.com/documentation/technologyoverviews/adopting-liquid-glass)

## 无障碍与尺寸适配

- 深色模式采用对应背景与语义字色；增强对比时，检查同行绿、状态文字和控制边界是否仍清楚。
- 系统控件随减少透明度与减少动态效果等设置调整；自定义播放器也要响应这些设置，必要时采用实底并减少形变或过渡动画。
- Dynamic Type 增大后，字幕继续增长；时间与状态、按钮标签可调整为上下排列，避免拥挤或遮挡。
- 小屏、横屏和窗口缩放时，保留播放与微调操作，正文继续可滚动。紧凑高度使用压缩标题与横向控制栏，为当前字幕留出首屏空间；sheet 的内容与底部控制仍需在真机复核。

### iPhone Duo 的可用区域

[Duo 几何资料](https://safearea.info/iphone-duo)列出：外屏竖向为 466×678 pt，右侧安全区 84 pt、底部 34 pt，安全区内约 382×644 pt；内屏横向为 951×669 pt，右侧同样留 84 pt，安全区内约 867×635 pt；内屏竖向为 669×951 pt，顶部留 82 pt、底部 34 pt。页面还列出相机遮挡和半折时的折痕保留区域。尺寸用于回归检查，不在 App 中按机型名称或这些固定数值排版。

主界面和系统工具栏留在 SwiftUI 安全区内。底栏从运行时 `GeometryReader` 获取可用区域；iOS 27.1 起读取**已激活**的 `.division` 保留区域，把整组播放按钮放在折痕的一侧。短而窄的可用区域默认显示进度、播放、±1 秒和“更多”；展开可使用现场对齐、当前句、撤销与精调。收放仅改变呈现，不改变播放状态或定位。其他系统继续使用安全区内的布局。

Apple 的 [Duo 适配说明](https://developer.apple.com/videos/play/tech-talks/111461/)和 [保留区域 API 示例](https://developer.apple.com/videos/play/tech-talks/111463/)要求以实际 size class、安全区和保留区域响应展开与半折。本轮 iOS 27.1 Duo 外屏模拟器已验证按钮位于右侧安全区内、“更多”展开与大字收放；截图位于忽略目录 `artifacts/tongxing-ios/2026-09-26/duo-safearea/`。内屏开合、半折与真机仍需视觉和操作验收；构建与 Core 几何测试不能代替这些检查。

上述方向依据 Apple 对文字缩放、布局适应与系统外观设置的要求；具体排版仍需按实际设备尺寸检查。[Typography](https://developer.apple.com/design/human-interface-guidelines/typography) · [Layout](https://developer.apple.com/design/human-interface-guidelines/layout) · [Sheets](https://developer.apple.com/design/human-interface-guidelines/sheets)

## 接口与兼容范围

以下签名和最低版本已从本机 Xcode 26.6 所含 iOS 26.5 SDK 的 SwiftUI / SwiftUICore `swiftinterface` 核对。最低部署版本保留 iOS 17；新接口使用 availability 分支。

| 接口 | 最低 iOS / macOS 版本 |
| --- | --- |
| `glassEffect(_ glass: Glass = .regular, in shape: some Shape = DefaultGlassEffectShape())` | 26.0 / 26.0 |
| `Glass.regular`、`.clear`、`.identity`；`tint(_ color: Color?)`；`interactive(_ isEnabled: Bool = true)` | 26.0 / 26.0 |
| `.buttonStyle(.glass)`、`.buttonStyle(.glassProminent)` | 26.0 / 26.0 |
| `GlassButtonStyle.init(_ glass: Glass)` | 26.1 / 26.1 |
| `GlassEffectContainer(spacing: CGFloat? = nil, content: () -> Content)` | 26.0 / 26.0 |
| `safeAreaBar(edge: VerticalEdge, alignment: HorizontalAlignment = .center, spacing: CGFloat? = nil, content: () -> some View)` | 26.0 / 26.0 |
| `presentationDetents(_ detents: Set<PresentationDetent>)`；带 `selection: Binding<PresentationDetent>` 的重载；`presentationDragIndicator(_ visibility: Visibility)` | 16.0 / 13.0 |
| `presentationBackground<S: ShapeStyle>(_ style: S)`；`presentationCornerRadius(_ cornerRadius: CGFloat?)`；`presentationCompactAdaptation(_ adaptation: PresentationAdaptation)` | 16.4 / 13.3 |
| `presentationSizing(_ sizing: some PresentationSizing)` | 18.0 / 15.0 |

`glassEffect`、`safeAreaBar` 等使用 `if #available(iOS 26, macOS 26, *)`。iOS 17–18 使用单层标准 Material 与 `safeAreaInset`，保留相同的操作与内容层级；减少透明度时仍需响应系统设置。Sheet 默认外观无需通过 `presentationBackground` 或固定圆角重新绘制。[自定义 Liquid Glass](https://developer.apple.com/documentation/swiftui/applying-liquid-glass-to-custom-views)

## 验证边界

iOS 26.5 SDK 可以用于验证这些接口的源码兼容性；采用 iOS 26 起提供的接口，也不等于已经验证 iOS 27 的实际外观或系统偏好行为。iOS 27 模拟器与真机检查尚待兼容的 Xcode 环境。

需复核：小屏与横屏、窗口缩放、较大无障碍字号、深色模式、增强对比、减少透明度、减少动态效果，以及各 sheet 内播放器是否遮挡内容。本文件不声明任何测试通过；本轮实际验证见 [README](README.zh.md)。
