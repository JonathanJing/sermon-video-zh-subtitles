# 选择证道与播客：两 Tab 内容选择方案（候选）

日期：2026-11-15。状态：**方案 A 切片 1 已实现并定向验证**（入口文案 + 固定分段控件），其余各条仍是候选。基线 `origin/dev` @ `72746e43`，开发分支 `picker-content-tabs`。依据 [UI 迭代流程](UI-ITERATION-WORKFLOW.zh.md) 对“较大导航重组先补有范围的交互方案”的要求先出交互方案，确认后按截图 → 原生实现 → 构建与实际操作 → 独立审核 → 人审落地；本轮不改数据层、不重跑上游生产。

## 1. 问题

现状 `WeekSheet`（[ContentView.swift:1563](App/ContentView.swift#L1563)）把两类内容放进同一张 `List`：

- `model.independentPages`（已发布页面，见 [AppModel.swift:349](App/AppModel.swift#L349)）同时包含周日证道（`mediaType` 为 `"video"` 或空）与证道播客（`mediaType == "podcast"`），按日期倒序混排；
- 类型只由 `SermonHeadingView` 的 `edition` 小字表示（12.5 pt、次级色，见 [SERMON-HEADING.zh.md](SERMON-HEADING.zh.md)）；
- 同日两行结构完全相同（标题／系列／日期·讲员／类型灰字），如「耶稣胜过这世界」与「如果我有更多时间 · 耶稣胜过这世界」，行高、命中区、点击方式一致；
- 入口文案自相矛盾：工具栏「选择证道周次」（`calendar` 图标）→ 标题「选择证道」→ 列表里却是证道与播客混排。

用户提供的 2026-11-15 截图复现了误点：想选证道却点进播客。这属于信息结构问题，不是行间距或文案微调能解决的。

数据侧已有稳定两分类，不需要新 schema：`MultilingualPage.mediaType` 与 `displayCategory`（[MultilingualCatalog.swift:106](Core/Sources/TongxingCore/MultilingualCatalog.swift#L106-L110)）；legacy `weekly.json` 周次始终是证道。

## 2. 方案比较

| 方案 | 结构 | 优点 | 代价 | 结论 |
| --- | --- | --- | --- | --- |
| **A 顶部固定分段控件**（周日证道｜播客） | 同一 sheet 内两条独立列表 | 结构上消除混排；系统控件，无需自绘；与「完成」关系清楚；不新增导航层级 | 顶部多占约 40 pt | **推荐** |
| B 底部悬浮 Tab | sheet 内两套内容库 | 切换落在拇指区；“两个内容库”心智强 | 多占约 90 pt；列表要避开玻璃条；sheet 内再套一层主导航；与右上「完成」形成两套退出语义 | 备选 |
| C 二级进入（两行 → push） | List → List | 零混排，层级最清楚 | 每次都要两次点击；返回多一层 | 不推荐 |
| D 过滤胶囊 + 单列表 | 顶部 chips，默认「全部」 | 改动最小 | 停在「全部」时仍混排，等于没解决 | 不推荐 |

方案 B 的完整外观见设计稿（`05-b-bottomtabs`）。B 不差，只是把一个两列表的切换做成了 sheet 内的主导航，收益（拇指距离）在只有 2 段、每段至多十余行时并不成立。

## 3. 方案 A 规格

### 3.1 入口与主页面

```text
工具栏   [列表图标] 选择证道与播客     （原：日历图标「选择证道周次」）
主页面   标题上方原「已发布页面」灰字 →  内容类型徽标
         [波形] 播客          或        [播放框] 周日证道
         耶稣是公义的，必终结罪恶
         启示录：耶稣带给我们的安慰与盼望
         2026-11-08 · Eric Geiger
```

- 徽标 = 内容类型，用小号药色底 + 同行绿文字，取代「已发布页面」这一在生产环境恒真的状态词；`allowsDevCandidates` 时在其右侧追加「Dev 内容」，保留开发上下文。
- 日期行下方不再重复「周日证道／证道播客」小字，避免同一信息两处出现。
- 类型词只有三处且措辞一致：工具栏入口、页面徽标、Tab。用户不必从最小号灰字推断分类。

### 3.2 Sheet 结构

```text
┌──────────────────────────────────┐
│ ─────                            │  拖拽条
│            证道与播客     [完成]  │  导航栏：标题固定，「完成」不变
│ ┌──────────┬──────────┐          │  固定分段控件（不随列表滚动）
│ │ 周日证道 │   播客    │          │  默认 = 当前内容所在 Tab
│ └──────────┴──────────┘          │
│ ┌──────────────────────────────┐ │  每个 Tab 只有一张列表，无分组标题
│ │ 耶稣胜过这世界           ✓   │ │  当前行：同行绿勾 + 药色底
│ │ 启示录：耶稣带给我们的安慰与盼望│ │
│ │ 2026-11-15 · Eric Geiger      │ │
│ ├──────────────────────────────┤ │
│ │ 耶稣是公义的，必终结罪恶      │ │
│ │ …                            │ │
│ ├──────────────────────────────┤ │
│ │ 耶稣配得                      │ │  legacy weekly.json 周次并入同一张
│ │ 2026-09-27 · Eric Geiger      │ │  列表，按日期排序
│ │ 正式播放版                     │ │  仅版本 ≠ Tab 类型时显示
│ └──────────────────────────────┘ │
│ Dev 内容（仅 Dev／Beta 构建）      │  列表 footer，不是分组标题
└──────────────────────────────────┘
```

- 标题「证道与播客」；右上「完成」不变。
- 分段控件固定在导航栏下方，列表在其下滚动。
- 「证道」Tab：一张列表，已发布证道与 legacy `weekly.json` 周次合并后按日期倒序；不再有「已发布页面／其他周次」两个分组。
- 「播客」Tab：一张列表；无内容时 `ContentUnavailableView` 空态，分段控件仍显示两项。
- Dev／Beta 构建在列表底部加一行 footer「包含 Dev 内容」，不用分组标题表达开发上下文。
- 行沿用 `SermonHeadingView`，只把最后一行小字改为条件显示：与 Tab 标签相同的类别词省略，其余照旧（如「正式播放版」「YouTube 版」，以及将来目录里出现的其他类别）。当前目录的「周日证道／证道播客」正好对应两个 Tab，所以不再逐行重复；分类只依赖 `mediaType`，不解析中文标签。
- detent：两类都在时打开到 `.large`（列表一次看全），可下拖 `.medium` 看到底层页面；只有一类内容时保持 `[.medium, .large]` 与今天的单列表，不显示分段控件。

### 3.3 交互（状态 → 操作 → 预期结果）

| # | 状态 | 操作 | 预期结果 |
| --- | --- | --- | --- |
| 1 | 正在听播客 | 点工具栏「选择证道与播客」 | sheet 打开即落在「播客」Tab，当前单集带勾，不会先看到证道列表 |
| 2 | 正在听证道 | 同上 | 落在「周日证道」Tab，当前证道带勾 |
| 3 | 任一 Tab | 点另一段 | 切换列表，两 Tab 各自保留滚动位置；不改变播放、不关闭 sheet |
| 4 | 任一 Tab | 点一行 | 切到该内容并关闭 sheet；播放位置、音轨与下载状态按现有规则处理，不变 |
| 5 | 播客 Tab 为空 | 打开并切到「播客」 | 空态说明；分段控件两项仍可见可点，不闪变 |
| 6 | 只有一类内容 | 打开 | 无分段控件，标题与列表直接是该类型（等同今天的单列表） |
| 7 | 任意 | 点「完成」或下拉关闭 | 不改变内容；下次打开回到当前内容所在 Tab |
| 8 | VoiceOver | 聚焦分段控件 / 行 | 读「周日证道」/「播客」及选中状态；选中行读「已选中」；行内按标题、系列、日期讲员顺序 |

### 3.4 文案

| 键 | 简体中文 | English |
| --- | --- | --- |
| 标题 | 证道与播客 | Sermons & Podcasts |
| Tab 1 | 周日证道 | Sunday sermon |
| Tab 2 | 播客 | Podcast |
| Dev footer | 包含 Dev 内容 | Includes dev content |
| 空态 | 暂无播客 | No podcasts yet |
| 空态说明 | 播客单集发布后会出现在这里。 | Podcast episodes appear here once published. |
| 入口 | 选择证道与播客 | Choose sermon or podcast |

「周日证道」采用目录 `displayCategory` 的既有中文措辞（[MultilingualCatalog.swift:109](Core/Sources/TongxingCore/MultilingualCatalog.swift#L109)），英文沿用 `reader.sermonCategory` 语义。

### 3.5 实现落点（不改数据层）

- `WeekSheet` 拆为 `ContentPickerSheet` + `ContentTab`；分类走 `MultilingualPage.isPodcastContent`（`contentKind` 优先，旧目录退回 `mediaType == "podcast"`）；legacy `model.weeks` 只进证道 Tab。
- 复用 `SermonHeadingView`，新增「隐藏与 Tab 相同的版本小字」开关，不复制标题层级。
- 保留既有 `accessibilityIdentifier`（`picker-<id>`、`published-page-<id>`、`legacy-week-<id>`），新增 `picker-tab-sermons`、`picker-tab-podcasts`、`picker-section-published`、`picker-section-other-weeks`。
- 大字：系统分段控件标签不随 Dynamic Type 放大，因此无障碍字号下换成两个整宽按钮（≥44 pt 命中区），sheet 只用 `.large`；行不截断、自然换行。
- 不新增播放器、播放状态源、网络字段；不重跑 ASR／翻译／TTS。

### 3.6 落地后的定向验证（切片 1 已执行，见 §6）

- 构建；受影响 `TongxingUITests`（默认 Tab、切换、勾选、行选择、空态）。
- 同配置截图：浅色／深色、`.large`／`.medium`、无障碍大字号、播客空态、只有一类内容的回退态。
- 独立只读审核精确 revision；人审确认；网页处理决定。

## 4. 网页

`deferred`。网页 `content-browser` 已按 `mediaType` 得到类别（`apps/listening-web/app.mjs:201` 一带），iOS 确认后按同一两分类调整信息层级即可，不要求像素一致，不阻塞本轮设计。

## 5. 待确认

1. 两类都在时默认打开 `.large`（列表完整），代价是比现在的半屏多一点空间？（推荐接受，未实现。）
2. 下一片是否按顺序做：主页面内容类型徽标 → 行内与 Tab 重复的类别小字 → 播客空态？
3. 已定：结构用方案 A、标题用「证道与播客」；每个 Tab 只有一张列表，「已发布页面／其他周次」的分组概念已移除（2026-11-16）。

## 6. 已实现：切片 1

分支 `picker-content-tabs`（基于 `origin/dev` @ `72746e43`）。只做方案 A 的第一片：入口文案与固定分段控件。主页面类型徽标、行内小字去重、默认 `.large`、播客空态都还没有。

| 位置 | 改动 |
| --- | --- |
| 工具栏入口 | 「选择证道周次」+ `calendar` → 「选择证道与播客」+ `list.bullet`；identifier `choose-sermon` 不变 |
| Sheet 标题 | 两类都在时「证道与播客」，只有一类时「选择证道」／「选择播客」；标题改为 inline，把高度让给列表 |
| 固定分段控件 | 系统分段控件固定在标题下、列表上；每个 Tab 只有一张列表；已发布证道与 legacy `weekly.json` 周次合并排序，播客列只放播客；Dev 构建用列表 footer 标注 |
| 默认 Tab | 当前正在收听内容所在的类型；目录只有一类时不显示控件，退回原单列表 |
| 无障碍大字 | 系统分段控件标签不随字号放大，改成上下两个整宽按钮（≥44 pt 命中区） |
| 分类依据 | 优先 `contentKind`（`sermon`／`podcast`／`clip`），旧目录退回 `mediaType == "podcast"`；不解析中文类别标签。规则见 [目录内容类型](../../docs/catalog-content-kind.zh.md) |

文件：`App/ContentView.swift`（`WeekSheet`）、`App/AppModel.swift`（`selectedContentIsPodcast`）、`App/Resources/Localizable.xcstrings`（新增 4 键、删除不再使用的「选择证道周次」）、`UITests/ContentPickerUITests.swift`（新增）、`UITests/ListeningFlowUITests.swift`（分类测试按 Tab 取行）、`UITests/AppStoreScreenshotUITests.swift`（sheet 标题候选列表）、`ICON-INVENTORY.zh.md`。

### 证据

- 改前／改后截图，同夹具 `--ui-testing-source-categories`、同设备 iPhone 17 / iOS 27.2、同一展开手势：`artifacts/tongxing-ios/2026-11-15/picker-tabs/before/`、`final/`（含 `picker-content-tabs-sermons`、`-podcasts`、`-large-type`）。
- 定向测试（2026-11-15，模拟器，合成夹具）5 项全通过：`ContentPickerUITests.testPickerSeparatesSermonsFromPodcasts`、`ContentPickerUITests.testPickerLargeTypeUsesLabeledButtons`、`ListeningFlowUITests.testPickerSourceCategoriesBelowDate`、`ListeningFlowUITests.testRemoteCategoriesUseInterfaceLanguageForNewPageTypes`、`ListeningFlowUITests.testRemoteCategoryRefreshWithoutRebuildPreservesPausedPlayback`。
- 边界：模拟器 + 合成内容 + 静音音轨；不是真机、真实听感、现场或发布验收。深色与 `.medium` detent 未单独截图。

## 设计稿位置

`artifacts/tongxing-ios/2026-11-15/picker-tabs-design/`（本地忽略目录，未提交）：`00-before` 现状、`02-a-sermons`／`03-a-podcasts` 方案 A 两个 Tab、`04-a-medium` 半屏、`05-b-bottomtabs` 方案 B、`06-dark` 深色、`07-a11y` 无障碍大字号。**生成效果图不是执行证据**，不替代构建、实际操作或真机验收。
