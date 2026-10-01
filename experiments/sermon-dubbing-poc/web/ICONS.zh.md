# Firebase 网页 SVG 图标

以原生 iOS 候选的 [图标清单](https://github.com/JonathanJing/sermon-video-zh-subtitles/blob/062cbab91270190f5ceaa42ab96b31b547f99686/apps/tongxing-ios/ICON-INVENTORY.zh.md)（PR #192 的固定参考版本，四图标优化）作为动作与形状基准。`icons.svg` 是手工重绘、可编辑的 SVG 路径库；符号名称表示参考的原生图标，不是导出的 SF Symbols 文件。iOS 继续使用系统符号。

两套网页实现（每周播放器与 `firebase/dev/public` 多语言阅读器）使用字节一致的 `icons.svg`、`icons.mjs`、`brand-icon.svg`、`brand-icon-light.svg`。共 43 个图形（37 个原生对应符号与 6 个网页补充符号）；其中部分预留给对应动作，并非所有页面都有该功能。

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

太阳、月亮、评价手势、反馈旗帜及待完成圆圈为网页补充图形，采用相同 24×24 网格、2.15 单位圆角描边和 `currentColor`。界面语言沿用 iOS 的短文字标记，不再使用原来的 `◎`，也不复用证道内容语言的地球。

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

## 进一步对齐（2026-10-01）

补齐原生的全部 37 个符号，包括文本搜索、试听、波形、网络状态、等待及耳机；仅资产补齐不新增网页功能。已有周次、内容语言、隐私、第二个撤销入口和动态资料下载补对应图标，字幕标题改为 `waveform`。多语言阅读器的大纲入口、读取失败与内容语言选中项分别使用大纲、网络提示和勾选，界面语言仍为短文字。

真实 AppKit SF Symbols 对照用于修正旋转箭头、恢复位置、日历、信息、举手、徽章、耳机、沙漏、文本搜索及网络提示的轮廓与方向。SVG 为原创重绘，保留系统符号与 SVG 的实现差异，不宣称逐像素一致。

维护检查：

```sh
python3 scripts/check_tongxing_icon_alignment.py
```

该命令从 `App`、`Shared`、`ListeningActivityExtension` 提取字面量和条件表达式中的符号名称，核对 SVG 覆盖、运行时注册表、两端资源字节、HTML 引用和共享 CSS 前缀。动态计算的符号名称须在新增时人工核对。

进一步验证：网页 363 项、multilingual assembly/Dev app 17 项通过；37 组真实符号参考与 SVG 均渲染。浏览器验证已有入口、浅深、中英、390/320px、弹窗与合成静音播放状态；多语言阅读器通过归档音频的实际获取/哈希检查，验证内容选中勾选在中/英/韩/西界面切换后保留。这不是实际听感或现场对齐验收。证据在 `artifacts/web-icons/2026-10-01/alignment/`。

## 独立 Firebase App 交付（2026-10-01）

`codex/firebase-app-update` 从最新 `dev` 基线 `63c0a18` 单独提取网页实现与构建资产清单；不包含 PR #192 的原生源码、英文全文搜索或语言切轨功能。Firebase 网页可独立审核、合并及晋升。上面的 37 个原生对应符号数量描述固定参考候选；当前 `dev` 有 33 个原生符号，维护检查对其中三个旧名称使用明确的动作映射：

| 当前 dev 的旧符号 | 网页新图标 | 动作 |
| --- | --- | --- |
| `ellipsis` | `magnifyingglass` | 定位入口 |
| `text.line.first.and.arrowtriangle.forward` | `text.bubble` | 回当前句 |
| `waveform.badge.mic` | `mic` | 听音对齐 |

这些映射使维护检查无需依赖原生候选先合并；不是旧、新图形完全相同的声明。新增其他原生符号缺少对应 SVG 仍会失败。参考清单链接固定到候选 SHA，不要求该文件存在于本分支。

本次独立预览使用 `ai-for-god-sermon-audio-dev` project 的短期 Hosting channel 和合成文稿／静音 MP3，反馈关闭；不使用生产项目或真实证道发布目录。正式 Dev 入口与 Production 均不在本次更新范围。独立验证证据存于忽略目录 `artifacts/firebase-app-update/2026-10-01/`。

独立分支本轮重新执行：363 项网页测试、52 项 weekly release/build/deploy guard 测试、17 项 multilingual assembly/Dev app 测试通过。合成预览的本地浏览器验证 SVG 几何、390/320px、中英、浅深、精调弹窗、播放／暂停及全文入口。

[独立 Firebase App 预览](https://ai-for-god-sermon-audio-dev--firebase-app-update-9gf6afl1.web.app/)，有效至 2026-10-08；页面使用每周播放器，顶部明确标识合成内容与静音音频，多语言阅读器源码另在同一 PR 更新。它是短期 Dev channel，不是正式 Dev 或 Production 的发布。
