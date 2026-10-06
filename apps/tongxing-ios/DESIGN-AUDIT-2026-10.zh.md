# 同行 iOS 设计审核（iOS 27 规范）

日期：2026-10-06。依据 Apple iOS 27 设计规范（Liquid Glass 世代，WWDC26 定稿）与本目录 [DESIGN.zh.md](DESIGN.zh.md)，对当前实现的审核记录。

## 结论

实现与 DESIGN.zh.md 的吻合度高；对照 iOS 27 规范，代码层面无硬伤，主要风险是**尚未在 iOS 27 真机/模拟器实测**（DESIGN.zh.md 已声明）。

## 通过项

- 玻璃只用于操作层：悬浮播放器单层 `.regular`，内部普通按钮；字幕正文用实底 `Brand.surface`。
- Reduce Transparency 回退实底+阴影；增强对比加描边（`ListeningGlassSurface`）。
- 系统 `glassEffect(.regular)` 自动跟随 iOS 27 玻璃强度滑块。
- NavigationStack + toolbar；Duo 用 `toolbarVerticalEdge` + `.axisBehavior(.verticalPreferred)` 进系统竖栏。
- 触控目标全 ≥44pt；字幕 26pt + `@ScaledMetric`；VoiceOver label/value/hint 覆盖；reduceMotion 动画置 nil。
- Sheet 系统默认外观，大字号只用 large detent。

## 本轮改动（对应 PR）

1. **收起态玻璃改圆形**：收起后 56pt 圆形播放键外套圆角矩形玻璃，改为 `Circle`（Liquid Glass 形状跟随内容）。`ListeningGlassSurface` 参数化为泛型 Shape，新增 `listeningCircularGlassSurface()`；原有调用签名不变。
2. **窄屏紧凑布局**：`PlaybackDock.horizontalControls` 加 `ViewThatFits`，宽度不足时（分屏/紧凑窗口）去掉时间标签、保留播放与微调；时间信息仍经播放键的 accessibilityValue 提供给 VoiceOver。
3. **大字号压缩字幕卡片**：`currentSubtitle` 在 accessibility size 下 padding 20→12、spacing 20→12，避免大字字幕占满首屏。

## 仍需真机验证（未在本 PR 改动）

- iOS 27 玻璃强度滑块全范围（ultra clear → fully tinted）下悬浮播放器的可读性。
- 同行绿 `Brand.accent` 在深色/浅色/增强对比下的实际对比度（建议 Accessibility Inspector 实测）。
- Duo 内屏横向、半折、大字 VoiceOver 顺序（DESIGN.zh.md 已列）。
