# 同行 iOS 组件规范

准备日期：2026-09-30。本文把 [设计约定](DESIGN.zh.md) 转成组件接口、状态和预览要求；[验收矩阵](UI-ACCEPTANCE.zh.md) 单独记录如何验证。组件清单来自当前 SwiftUI 源码，规范要求不等于已经完成视觉或无障碍验收。

## 开发基线

- 在 Xcode 打开当前工作分支的 `apps/tongxing-ios/Tongxing.xcodeproj`，选择 `Tongxing` scheme。开始改动前用 `git branch --show-current`、`git rev-parse HEAD`、`git status --short` 记录基线；同名工程可能属于不同 Git worktree，不按名称判定重复或删除。
- 最低部署版本由 [project.yml](project.yml) 保持为 iOS 17.0。新系统设计效果与最低支持版本分别验证。Duo 专属 API 同时需要 SDK 编译条件和运行时 availability；具体回退见下表。
- 组件直接观察既有 `AppModel` / `PlaybackController`。`PlaybackController` 是播放位置、播放意图、等待状态及撤销位置的唯一来源。组件自己的展开、弹层、焦点状态可以留在 View；不得为预览或组件化另建生产播放器状态模型。
- 界面语言、证道内容语言、音频语言是三个独立维度。切换界面语言只改变按钮和提示；可选内容与音轨来自实际发布能力，不能根据翻译后的标签推断音频存在。英文原文保留来源/对照含义。
- Apple [设计资源](https://developer.apple.com/design/resources/) 可作为系统控件和图标参考。SwiftUI 实现与此组件清单是当前交付依据；以后引入 Figma 时，记录所用资源版本并映射到同一组件，不建立第二套不一致的规范。

## 组件清单与接口

“原生组合”表示保留系统控件的导航、焦点与呈现行为；“自定义组合”表示业务排版，内部仍优先使用原生 `Button`、`Text` 等。

| 组件 / 源码 | 类型与职责 | 输入与必须覆盖的状态 | 交互和语义约束 |
| --- | --- | --- | --- |
| `ContentView` 的 `NavigationStack`、工具栏与语言菜单；[ContentView.swift](App/ContentView.swift) | 原生组合；页面、更多选项、界面语言入口 | `AppModel`、布局环境；加载中、空目录、失败、已有缓存、已选页面 | 导航名称清楚；错误提供可执行恢复动作；窄屏与系统侧栏中仍能找到页面和语言入口 |
| `ContentUnavailableView` / `ProgressView`；同上 | 原生；空内容、未就绪与加载反馈 | 目录、页面、音频分别加载或失败 | 清楚说明正在准备哪项资源；文字可换行，不用无限 spinner 替代失败原因 |
| 内容语言选择与当前页面信息；同上 | 原生 Sheet/List + 自定义标题组合 | 页面标识、发布 locale、文字/音频能力、选中状态 | 内容语言与音频语言分别标识；仅显示实际可用能力；切换后保留来源与审核声明 |
| 当前字幕、全文行、英文对照；同上 | 自定义组合；阅读与时间定位 | 当前 cue、完整文本、音轨时间、原文是否存在；长文、无字幕、无原文、纯文字内容 | 字幕随 Dynamic Type 增长；全文文字不是隐含跳转按钮，仅明确时间按钮定位；对照文字保留语言属性；阅读层不使用玻璃 |
| `PlaybackDock`；[PlaybackDock.swift](App/PlaybackDock.swift) | 自定义组合；稳定的主播放、±1 秒、进度与“更多” | 同一个 `PlaybackController`、`isPreparing`、`.bottom` / `.trailing`、`inSystemBar`、可选回调；未就绪、准备中、就绪、播放、等待、暂停、收起 | 不可播放时提供真实不可用语义与状态说明；等待时仍表达当前可执行操作；收起/展开不改变播放意图；系统栏内不再叠加玻璃 |
| `PlaybackMoreControls` 与邻近浮层；上述两个文件 | 自定义组合；现场对齐、当前句、撤销、精调 | 播放器、可选 `AppModel`、动作回调、可用宽度；无撤销/有撤销、不可精调、长标签、大字 | 浮层在触发按钮邻近并留在可用区域；打开不移动主播放键；关闭/escape 可达；焦点进入浮层并在关闭后回到合理位置；精调在浮层关闭后打开 |
| `AlignmentControls`；[ContentView.swift](App/ContentView.swift) | 原生按钮 + 自定义状态说明 | `AppModel` 的对齐可用性、进度、结果与原因 | 只在明确操作后启动短时采集；资料缺失时解释并保留手动定位；匹配结果经既有控制器提交，不自行推算位置 |
| `PrecisionSheet`、`OutlineSheet`、页面选择与更多选项；同上 | 原生 Sheet、Form、List、Slider | 当前位置/时长、微调、目录、大纲；不可定位、可定位、大字与紧凑高度 | 使用系统呈现与关闭入口；精调大字采用 large；拖动和时间按钮经播放器提交；切换 sheet 不产生第二播放器 |
| 下载与恢复位置卡片；同上 | 原生按钮/进度 + 自定义信息组合 | 未下载、下载中、取消、验证失败、已验证离线、旧书签 | 完整哈希验证前不能称为离线可用；恢复位置是用户操作；下载完成不能夺取正在播放的音源 |
| 品牌颜色与播放栏表面；[DesignSystem.swift](App/DesignSystem.swift) | 自定义共享样式 | 外观、增强对比、减少透明度、系统版本 | 使用语义背景/字色；仅主操作与品牌使用 accent；控制层单层材质；可访问性设置优先于装饰效果 |

## 共享视觉值

以下是项目选择，不把所有数值称为 Apple 强制标准。`DesignSystem.swift` 的 `ListeningMetrics` 集中管理命中区 44 pt、主播放直径 56 pt、阅读字号基准 26 pt 和控制层圆角 30 pt；只有一个组件使用的排版值留在该组件，不为抽象而建立第二套主题系统。

| 语义 | 当前基线 / 准备要求 |
| --- | --- |
| 主文字 / 次级文字 | 使用 `.primary` / `.secondary`，不固定黑白正文颜色 |
| 页面 / 阅读块 / 不透明控制层 | `Brand.background` / `Brand.surface` / `Brand.controlSurface`，对应系统语义背景 |
| 品牌与主操作 | `Brand.accent` 随浅深外观切换；主播放文字由 `Brand.prominentLabel` 配对。对比度仍需在实际背景与状态下测量 |
| 当前字幕 | 基准 26 pt，使用 `@ScaledMetric(relativeTo: .title2)`；不是最大字号或固定高度 |
| 标题、正文、辅助信息 | 优先 `.headline`、`.body`、`.footnote` 等系统文字样式；时间使用等宽数字，状态在阅读区有完整文字 |
| 主要交互命中区 | 项目基线至少 44×44 pt；命中区与视觉图标大小分开。现有微调 44×52、更多 48×52、主播放 56×56，系统栏主播放 44×44 |
| 字号与长标签 | 不为保持单行缩小可读字号；允许换行、滚动或调整横竖布局。完整状态不能只靠图标或颜色表达 |
| 图标 | 使用 SF Symbols；图标按钮有操作名称，装饰图标不重复朗读文字。符号粗细和缩放与相邻文字一致 |
| 间距与圆角 | 由内容层级和实际可用空间决定；系统导航/Sheet 不覆盖系统圆角。自定义播放栏圆角及内边距集中在该样式或组件 |
| 动画 | 收起与展开响应 Reduce Motion；预览观察不能替代系统设置下的实际操作 |

参考 Apple [按钮](https://developer.apple.com/design/human-interface-guidelines/buttons)、[文字](https://developer.apple.com/design/human-interface-guidelines/typography)、[SF Symbols](https://developer.apple.com/design/human-interface-guidelines/sf-symbols)、[品牌](https://developer.apple.com/design/human-interface-guidelines/branding)。

## 系统版本和布局回退

| 能力 | 新系统实现 | 回退 / 验证要求 |
| --- | --- | --- |
| 底部安全区 | iOS 26+ `safeAreaBar` | iOS 17–18 使用 `safeAreaInset`；阅读内容不能被控制栏挡住 |
| 控制栏材质 | 可用 SDK 与 iOS 26+ 的 `.glassEffect(.regular)` | 旧系统单层 `.regularMaterial`；减少透明度时用语义实底；增强对比时检查边界 |
| Duo 系统侧栏与 division 保留区 | `canImport(SwiftUI, _version: 8.0.85)` 并通过 iOS 27.1 运行时检查 | 旧 SDK 编译安全区/底栏/自定义侧栏分支；不能只凭 Swift 编译器版本判断 API 存在 |
| 小屏、横屏、展开与半折 | 读取实际几何、安全区、size class、已激活保留区域 | 不按机型名称硬编码布局；测试目标尺寸可固定，生产排版不固定 |
| Sheet | 系统默认呈现；按内容选择 detent | 精调大字保持 large；实际检查横屏关闭入口、滚动末尾和键盘避让 |

参考 Apple [布局](https://developer.apple.com/design/human-interface-guidelines/layout)、[采用 Liquid Glass](https://developer.apple.com/documentation/technologyoverviews/adopting-liquid-glass)、[自定义玻璃](https://developer.apple.com/documentation/swiftui/applying-liquid-glass-to-custom-views)、[Sheet](https://developer.apple.com/design/human-interface-guidelines/sheets)。

## Canvas 与夹具约定

在 Xcode 打开 [UIComponentPreviews.swift](App/UIComponentPreviews.swift)，使用 **Editor → Canvas** 并启动预览。运行完整 App 与 Canvas 分别用于流程和组件检查；macOS 的 `TongxingPreview` 仍是共享界面的辅助入口，不能作为 iPhone 预览证据。

| Canvas 场景 | 准备内容 |
| --- | --- |
| `01 · Listening / light`、`02 · Listening / dark` | 同一收听页面的浅色/深色外观；可从页面进入全文与弹层 |
| `03 · Largest text` | `.accessibility5` 最大无障碍字号 |
| `04 · Published reader / Korean` | 发布页面的韩语内容夹具；不代表界面语言也切为韩语 |
| `05 · Loading`、`06 · No connection` | 持续加载、连接失败状态 |
| `07 · Dock / ready`、`08 · Dock / preparing`、`09 · Dock / trailing` | 独立的就绪/准备中/侧栏播放器 |
| `10 · More / largest text` | 最大字号下独立“更多”组件 |

独立组件场景中的导航/关闭回调用于外观展示；需要验证完整跳转和关闭时从页面场景进入。界面语言复用 `AppLocalization.shared`，在页面菜单中切换；不通过多个预览同时写不同的全局语言来伪造独立语言环境。增强对比、减少透明度与减少动态效果是只读系统环境，通过 Xcode Environment Overrides、Inspector 或运行设备的设置验证；不添加假环境键绕过真实设置。

预览复用 `UITestContent` 的本地合成文案与静音，使用独立 `URLSession`、`URLProtocol` 和临时目录，不依赖实时目录、生产下载或真实麦克风；缓存、书签和语言偏好与正常 App 隔离。就绪页面夹具经既有 `OfflineLibrary` 校验后提供本地音频，UI 仍观察同一个真实播放器。视图预览不伪造生产内容的已审核、已发布或离线完整性结论。

最低预览覆盖：收听页面、全文长文、底部播放器、侧栏播放器、播放器未就绪/准备中、“更多”有无撤销、浅深外观、无障碍字号。预览中未覆盖的状态在 [验收矩阵](UI-ACCEPTANCE.zh.md) 中保留待验证，不因组件能渲染就记为通过。

Apple [为界面添加预览](https://developer.apple.com/documentation/xcode/adding-previews-to-your-interface-files) 说明了命名、变体与预览上下文。新增组件时同步补充本表、相关状态预览和必要的行为测试；不以截图数量代替交互证据。
