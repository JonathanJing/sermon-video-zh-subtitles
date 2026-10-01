# Firebase 网页 SVG 图标

以原生 iOS 候选的 `apps/tongxing-ios/ICON-INVENTORY.zh.md`（PR #192，四图标优化）作为动作与形状基准。`icons.svg` 是手工重绘、可编辑的 SVG 路径库；符号名称表示参考的原生图标，不是导出的 SF Symbols 文件。iOS 继续使用系统符号。

两套网页实现（每周播放器与 `firebase/dev/public` 多语言阅读器）使用字节一致的 `icons.svg`、`icons.mjs`、`brand-icon.svg`、`brand-icon-light.svg`。共 32 个图形，包括网页补充符号；其中部分预留给对应动作，并非所有页面都有该功能。

| 动作 | SVG 图形名称（对应原生选择） |
| --- | --- |
| 播放 / 暂停 | `play.fill` / `pause.fill` |
| 前后调整 | `gobackward` / `goforward`；保留 1 秒、5 秒、0.25 秒的实际幅度文字 |
| 定位总入口 / 听音 / 取消听音 | `magnifyingglass` / `mic` / `stop.circle` |
| 段落或时间跳转 | `arrow.right.to.line` |
| 回当前句 / 精调 / 撤销跳转 | `text.bubble` / `slider.horizontal.3` / `arrow.uturn.backward` |
| 周次 / 更多 / 证道内容语言 | `calendar` / `ellipsis.circle` / `globe` |
| 完整视频 / 大纲 | `play.rectangle` / `list.bullet.rectangle` |
| 关闭 / 导航 | `xmark` / `chevron.left`、`chevron.right`、`chevron.down` |
| 下载 / 恢复位置 | `arrow.down.circle` / `clock.arrow.circlepath` |
| 选择 / 完成 / 提示 / 隐私 | `checkmark` / `checkmark.circle.fill` / `info.circle` / `hand.raised` |

太阳、月亮、评价手势、反馈旗帜及待完成圆圈为网页补充图形，采用相同 24×24 网格、1.8 单位圆角描边和 `currentColor`。界面语言沿用 iOS 的短文字标记，不再使用原来的 `◎`，也不复用证道内容语言的地球。

品牌 SVG 按原生页头 PNG 参考重绘“同”字与书本，提供深浅两种配色。原生 PNG 源图保持原样；网页 favicon 改为 SVG，`apple-touch-icon` 保留 PNG 以支持 iOS 添加到主屏幕。浏览器原生 select 箭头、audio controls、details 展开标记由浏览器绘制，不在自定义图标替换范围。

## 更新规则

- 图标使用 `<svg aria-hidden="true" focusable="false"><use href="/icons.svg#…"></use></svg>`。路径由同源 sprite 提供，无外部图标库。
- 翻译标记放在独立文字节点；`setButtonLabel` 只更新标签，`setIcon` 只在播放状态改变时更新图形。
- 480px 以下的底栏工具显示纯图标，原有标签仅视觉隐藏，继续提供无障碍名称与至少 44px 点击区；各精调幅度仍可见。
- SVG 变动同步两套资源；Dev CSS 以每周播放器 CSS 为前缀。资产必须列入 weekly build、UI refresh、deploy 和 multilingual assembly 清单。
- 图标替换不修改字幕、音频、目录、语言选择或播放位置规则。源码、Firebase 预览、正式站发布分别记录。

## 本轮验证

2026-10-01：网页 363 项测试、weekly release 32 项测试、multilingual assembly 与 Dev app 17 项测试通过。浏览器验证 SVG 实际几何渲染、390/320px、中英文、深浅主题、精调弹窗、全文跳转及合成静音音频的播放/暂停图标切换。此验证不代表实际证道音频或现场对齐验收。

忽略目录 `artifacts/web-icons/2026-10-01/` 保存截图、测试日志、浏览器证据和基于当前正式站快照的图标预览候选；候选保留所有内容/音频/目录字节。预览发布不更新正式站。

本轮 Firebase 预览：[iOS SVG 图标候选](https://ai-for-god-sermon-audio--ios-svg-icons-vemy99i4.web.app/)，有效至 2026-10-08。线上浏览器验证通过；13 个更新／新增文件的 HTTP 字节与候选一致，SVG 的 Content-Type 为 `image/svg+xml`，正式站入口保持原样。多语言阅读器源码另经中／英／韩／西界面切换与语言弹窗验证；它不是本次预览首页的实现。
