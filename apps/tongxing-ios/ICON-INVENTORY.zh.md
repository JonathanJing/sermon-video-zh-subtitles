# 同行 iOS 图标清单

盘点日期：2026-10-01。本轮四图标优化基于 `5d31793d20bcb95febd65cc91bf0afd649b89706`，清单已同步优化后的候选源码（PR #192）。此清单不代表已发布版本。

范围：`App/`、`ListeningActivityExtension/`、`Shared/` 的实际界面代码与品牌资产。共 **37 个不同的 SF Symbols**、**50 次符号字面量引用**（包含动态状态分支），另有 **2 类品牌资源**。同一符号跨页面复用只计一种；测试示例、生成工具和系统自动绘制的图形不计入符号数。

初次盘点的图标总览采用本机 AppKit 的真实 SF Symbols，统一 medium / 32 pt 便于形状比较；不是 iOS 页面截图，也不反映各控件原有字重、字号、颜色、动态字体或禁用效果。品牌主屏幕项展示 Icon Composer 图层源图，不是系统最终合成效果。初次总览保留为优化前快照；本轮四图标的外观以 `make preview` 和实际 iOS 页面操作为准。

## 本轮已优化的组

- **05 定位入口：** `waveform` → `magnifyingglass`，纯放大镜表示找位置，无可见文字；不再与字幕／音频占位的波形状态复用。
- **06 听音对齐：** `waveform.badge.mic` → `mic`，麦克风直接表达听现场，忙时仍用 `stop.circle`。
- **09 段落跳转：** `scope` → `arrow.right.to.line`，在具体段落旁表达跳转，保留“定位到这段”。
- **10 回当前句：** `text.line.first.and.arrowtriangle.forward` → `text.bubble`，简化为文字气泡，保留“当前句”与无障碍“回到当前句”。

四项保留点击区域、状态条件、标签、无障碍标识及回调。底栏放大镜为 48×52 pt，内部操作至少 44 pt 高。编号沿用初次清单；仍在使用的波形另列为 39，避免改变其他项目编号。网页适用性：`not_applicable`，本轮仅替换原生 SF Symbols，不改变共享语义或内容。

## 后续讨论点
- **03、04：前后微调。** 当前图标不显示“1 秒”；保留无文字外观时，需要评估新用户是否明白调整幅度。
- **14、15：更多和语言。** 页头更多仍是省略号圆圈；地球仅代表证道内容语言。界面语言现在用短文字标记，应保持三类语言的区分。
- **01、02、16、24：播放相关。** 正式播放、暂停、完整视频和音色试听各有场景；优化时保留状态切换和媒介差异。

后续组尚未改动；品牌资源本轮保持现状。

## 播放栏

| 编号 | 当前符号／资源 | 用途与状态 | 源码位置 |
| --- | --- | --- | --- |
| 01 · 播放 | `play.fill` | 底栏主播放按钮，暂停状态时显示；主按钮用品牌绿圆形背景。 | [PlaybackDock.swift:150](App/PlaybackDock.swift#L150) |
| 02 · 暂停 | `pause.fill` | 底栏播放中或等待时显示；灵动岛暂停状态也用此符号。 | [PlaybackDock.swift:150](App/PlaybackDock.swift#L150)、[ListeningActivityWidget.swift:98](ListeningActivityExtension/ListeningActivityWidget.swift#L98) |
| 03 · 后退 1 秒 | `gobackward` | 底栏手动后退 1 秒。图标本身不含秒数，需评估首次使用的可理解性。 | [PlaybackDock.swift:135](App/PlaybackDock.swift#L135) |
| 04 · 前进 1 秒 | `goforward` | 底栏手动前进 1 秒，与后退按钮成对。 | [PlaybackDock.swift:135](App/PlaybackDock.swift#L135) |
| 05 · 定位入口 | `magnifyingglass` | 底栏纯图标找位置入口；打开定位浮层，包含听音、英文搜索、当前句及精调等已有操作。 | [PlaybackDock.swift:89](App/PlaybackDock.swift#L89) |

## 定位与精调

| 编号 | 当前符号／资源 | 用途与状态 | 源码位置 |
| --- | --- | --- | --- |
| 06 · 听音对齐 | `mic` | 定位浮层：听现场并对齐；不忙时显示麦克风。 | [ContentView.swift:849](App/ContentView.swift#L849) |
| 07 · 取消对齐 | `stop.circle` | 听音对齐进行中替换麦克风波形，点击取消。 | [ContentView.swift:849](App/ContentView.swift#L849) |
| 08 · 英文找位置 | `text.magnifyingglass` | 首页“没跟上现场”入口与定位浮层的英文全文搜索入口。 | [ContentView.swift:680](App/ContentView.swift#L680)、[PlaybackDock.swift:232](App/PlaybackDock.swift#L232) |
| 09 · 定位到段落 | `arrow.right.to.line` | 英文全文每段的跳转按钮；只用于具体段落定位，不用于播放器传输控制。 | [EnglishLocateSheet.swift:152](App/EnglishLocateSheet.swift#L152) |
| 10 · 回到当前句 | `text.bubble` | 定位浮层：回到当前字幕位置，使用简洁文字气泡。 | [PlaybackDock.swift:281](App/PlaybackDock.swift#L281) |
| 11 · 定位与精调 | `slider.horizontal.3` | 定位浮层：打开精调面板。 | [PlaybackDock.swift:293](App/PlaybackDock.swift#L293) |
| 12 · 撤销跳转 | `arrow.uturn.backward` | 定位浮层：返回跳转前确认的位置；仅有可撤销历史时出现。 | [PlaybackDock.swift:305](App/PlaybackDock.swift#L305) |

## 导航与页面

| 编号 | 当前符号／资源 | 用途与状态 | 源码位置 |
| --- | --- | --- | --- |
| 13 · 选择周次 | `calendar` | 页头与 Duo 系统侧栏选择证道周次。 | [ContentView.swift:268](App/ContentView.swift#L268)、[ContentView.swift:401](App/ContentView.swift#L401) |
| 14 · 更多选项 | `ellipsis.circle` | 页头与 Duo 系统侧栏打开更多选项；不同于播放栏的定位入口。 | [ContentView.swift:270](App/ContentView.swift#L270)、[ContentView.swift:409](App/ContentView.swift#L409) |
| 15 · 证道语言 | `globe` | 选择已发布的证道内容语言；紧凑布局为纯图标，普通布局带语言和能力文字。 | [ContentView.swift:513](App/ContentView.swift#L513)、[ContentView.swift:524](App/ContentView.swift#L524) |
| 16 · 完整视频 | `play.rectangle` | 首页观看完整视频入口。 | [ContentView.swift:537](App/ContentView.swift#L537) |
| 17 · 证道大纲 | `list.bullet.rectangle` | 旧周次标题区打开证道大纲。 | [ContentView.swift:450](App/ContentView.swift#L450)、[ContentView.swift:482](App/ContentView.swift#L482) |
| 18 · 返回语言列表 | `chevron.left` | 已验证内容页返回证道语言列表。 | [ContentView.swift:924](App/ContentView.swift#L924) |
| 19 · 进入英文全文 | `chevron.right` | 首页英文定位入口右侧的导航箭头。 | [ContentView.swift:683](App/ContentView.swift#L683) |
| 20 · 展开播放栏 | `chevron.up` | 主播放键长按菜单：展开已收起的播放栏。 | [PlaybackDock.swift:168](App/PlaybackDock.swift#L168) |
| 21 · 收起播放栏 | `chevron.down` | 主播放键长按菜单：收起已展开的播放栏。 | [PlaybackDock.swift:168](App/PlaybackDock.swift#L168) |
| 22 · 关闭定位面板 | `xmark` | 定位浮层右上角关闭按钮。 | [PlaybackDock.swift:219](App/PlaybackDock.swift#L219) |
| 23 · 隐私与支持 | `hand.raised` | 更多选项列表进入隐私与支持。 | [ContentView.swift:1281](App/ContentView.swift#L1281) |
| 24 · 音色试听 | `play.circle` | 多语种音色试听 Demo 的播放按钮；与正式播放、完整视频入口是不同场景。 | [ContentView.swift:1677](App/ContentView.swift#L1677) |

## 下载、选择与提示

| 编号 | 当前符号／资源 | 用途与状态 | 源码位置 |
| --- | --- | --- | --- |
| 25 · 尚未下载 | `arrow.down.circle` | 旧周次离线音频提示，下载操作另有文字按钮。 | [ContentView.swift:583](App/ContentView.swift#L583) |
| 26 · 离线音频就绪 | `checkmark.circle.fill` | 旧周次已下载或正在使用离线音频的状态。 | [ContentView.swift:574](App/ContentView.swift#L574) |
| 27 · 当前选中项 | `checkmark` | 已选证道、周次、制作语言、音轨的选中标记。 | [ContentView.swift:970](App/ContentView.swift#L970)、[ContentView.swift:1119](App/ContentView.swift#L1119)、[ContentView.swift:1140](App/ContentView.swift#L1140)、[ContentView.swift:1298](App/ContentView.swift#L1298) |
| 28 · 恢复收听位置 | `clock.arrow.circlepath` | 旧周次恢复历史收听进度提示。 | [ContentView.swift:602](App/ContentView.swift#L602) |
| 29 · 错误提示 | `exclamationmark.circle` | 目录、已发布音频、下载和语言选择的错误提示复用。 | [ContentView.swift:104](App/ContentView.swift#L104)、[ContentView.swift:164](App/ContentView.swift#L164)、[ContentView.swift:589](App/ContentView.swift#L589)、[ContentView.swift:988](App/ContentView.swift#L988) |
| 30 · 离线目录提示 | `wifi.slash` | 目录缓存或网络相关提示。 | [ContentView.swift:99](App/ContentView.swift#L99) |
| 31 · 读取证道失败 | `wifi.exclamationmark` | 页面暂时无法读取证道的错误提示。 | [ContentView.swift:193](App/ContentView.swift#L193) |
| 32 · 暂不可定位 | `info.circle` | 英文全文音频未就绪时的阅读和搜索提示。 | [EnglishLocateSheet.swift:83](App/EnglishLocateSheet.swift#L83) |
| 33 · 暂无语言版本 | `globe.badge.chevron.backward` | 证道语言列表为空时的占位符号。 | [ContentView.swift:943](App/ContentView.swift#L943) |
| 39 · 字幕／音频状态 | `waveform` | 当前字幕状态与无音频占位；本轮不再用作底栏定位按钮。 | [ContentView.swift:126](App/ContentView.swift#L126)、[ContentView.swift:723](App/ContentView.swift#L723) |

## 灵动岛与锁屏

| 编号 | 当前符号／资源 | 用途与状态 | 源码位置 |
| --- | --- | --- | --- |
| 34 · 正在收听 | `headphones` | Live Activity 正在播放时显示；紧凑、最小、展开和锁屏共用同一组件。 | [ListeningActivityWidget.swift:98](ListeningActivityExtension/ListeningActivityWidget.swift#L98) |
| 35 · 等待音频 | `hourglass` | Live Activity 正在等待时显示。 | [ListeningActivityWidget.swift:98](ListeningActivityExtension/ListeningActivityWidget.swift#L98) |
| 36 · 状态已过期 | `arrow.clockwise` | Live Activity 状态过期时优先显示，不是 App 内的刷新按钮。 | [ListeningActivityWidget.swift:98](ListeningActivityExtension/ListeningActivityWidget.swift#L98) |

## 品牌资源

| 编号 | 当前符号／资源 | 用途与状态 | 源码位置 |
| --- | --- | --- | --- |
| 37 · 页头品牌标识 | 浅色／深色图片 | App 内页头 BrandMark，浅色与深色分别使用资源变体；不属于 SF Symbols。 | [BrandMark.png](App/Assets.xcassets/BrandMark.imageset/BrandMark.png)、[BrandMark-dark.png](App/Assets.xcassets/BrandMark.imageset/BrandMark-dark.png) |
| 38 · 主屏幕 App 图标 | 浅色／深色图片 | Icon Composer 的浅色与深色源图；这里展示平面源图，不包含系统玻璃、蒙版与着色合成效果。保留 PNG appiconset 作为对照与回退。 | [Logo-light-source.png](App/AppIcon.icon/Assets/Logo-light-source.png)、[Logo-source.png](App/AppIcon.icon/Assets/Logo-source.png) |

App 图标的图层与外观配置见 [icon.json](App/AppIcon.icon/icon.json)；保留的平面资源见 [AppIcon.png](App/Assets.xcassets/AppIcon.appiconset/AppIcon.png)／[AppIcon-dark.png](App/Assets.xcassets/AppIcon.appiconset/AppIcon-dark.png)。资源选择与主屏幕外观边界见 [品牌说明](Branding/README.md)。

## 系统绘制与非图标入口

- `ProgressView`：下载、准备音频、加载文稿、语言验证及 Live Activity 进度。系统绘制的转圈和进度条没有 App 指定的 `systemName`。
- `NavigationStack`、`NavigationLink`、`DisclosureGroup`、`Menu`、`Picker`、`List`、Sheet、文本选择及 `VideoPlayer` 系统播放界面可能自动带返回箭头、展开箭头、选择标记等。清单中的显式箭头和勾选已计入；系统附加符号随系统与布局变化，未枚举成自定义资产。
- 界面语言短标记（例如“中”）与全文／现场模式 `Picker` 是文字入口，不是图片图标。
- [“英文原视频 ↗”](App/ContentView.swift#L807) 的外链箭头是文字中的 Unicode 符号，不是 SF Symbol；后续可以与导航符号一起评估。
- 锁屏播放控制由系统根据播放器状态绘制；自定义 Live Activity 的符号另列于上表。

## 后续优化的验证项

逐组确定动作、状态及图标选择；保持原有无障碍名称和有效点击区域。实现后比较同条件 iOS 浅色／深色／大字号页面，并定向验证点击、状态切换和禁用状态。品牌标识与功能符号分别评审。网页适配在具体替换方案确定后判断。

## Firebase 网页对应

2026-10-01 网页补充实现以本清单为参考，手工重绘共享 SVG 图形，保留 iOS 原生 SF Symbols。见 [网页图标说明](../../experiments/sermon-dubbing-poc/web/ICONS.zh.md)。网页与原生共享操作语义，网页发布状态单独记录。
