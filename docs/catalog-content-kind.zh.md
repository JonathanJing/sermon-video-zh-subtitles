# 目录内容类型：`contentKind` 与 `mediaType` 的分工

日期：2026-11-16。起草原因：iOS 1.26.34 的「证道与播客」分栏把 2026-10-25 起的周日证道放进了播客栏。本文定义统一规则，记录本次数据修复和工具，不改变内容审核、发布包或音频身份。相关：[页面类别](ios-page-display-categories.zh.md)、[iOS 选篇面板设计](../apps/tongxing-ios/PICKER-CONTENT-TABS.zh.md)。

## 事故与根因

- 页面发布器（`experiments/sentence-first-agent`）的 page-config schema 只允许 `mediaType` 取 `podcast` 或 `clip`。这是驱动路线的技术标记，不是内容类别；周日证道的页面因此也写成 `mediaType: podcast`。
- 目录 `multilingual-v3.json` 原样继承该字段。iOS 选篇面板按 `mediaType == "podcast"` 分栏，于是 4 篇周日证道（10-25、11-01、11-08、11-15）出现在播客栏。
- `displayCategory` 一直是对的（周日证道／证道播客），但它只有本地化标签：标签是展示文案，不能当机器分类键，也不该让客户端解析中文。

## 规范（2026-11-16 起）

| 字段 | 语义 | 规则 |
| --- | --- | --- |
| `contentKind` | 内容类别，locale 无关 | `sermon` / `podcast` / `clip`；**客户端分组只看它** |
| `mediaType` | 技术来源标记（由发布器 schema 决定） | 只在真正的播客页保留 `podcast`；非播客页不写；`video` 只在页面确实发布视频时使用 |
| `displayCategory.labels` | 展示文案 | 仅用于显示，永不参与分组 |
| 兜底 | 2026-11-16 之前写入的目录没有 `contentKind` | 退回旧规则 `mediaType == "podcast"` |

作者侧类别到 kind 的映射（发布器与离线工具共用）：

| 类别（en / zh-Hans） | `contentKind` |
| --- | --- |
| Sunday sermon / 周日证道 | `sermon` |
| Archive edition / 正式播放版 | `sermon` |
| Sermon clip / 证道片段 | `clip` |
| Sermon Podcast / 证道播客 | `podcast` |
| Podcast / 播客 | `podcast` |
| Experiment clip / 实验片段 | `clip` |

没有 `displayCategory` 的页面沿用历史规则，但结果要显式写进 `contentKind`：`mediaType == "podcast"` → `podcast`，否则 `sermon`。未知类别**拒绝**发布或规范化，不允许猜。

## 发布器

`experiments/sentence-first-agent/sfa_publish.py` 的 `_page_entry` 现在写 `contentKind`，并且只在 `contentKind == "podcast"` 时写 `mediaType`。发布门的双时钟放宽（`sfa_publish_gate.py` 的 `content_clock`）仍只对带 `mediaType: podcast` 且无对齐能力的播客页生效；周日证道页有 `alignment` 能力，本来就按严格 ±1 秒规则检查，去掉 `mediaType` 不改变其结论。

## 客户端

- iOS Core：`MultilingualPage.isPodcastContent` 优先 `contentKind`，缺失时退回 `mediaType == "podcast"`；`displayEdition` 的兜底标签用同一判断，避免分组和行内标签用两套规则。
- 选篇面板与打开时的默认分类用 `isPodcastContent`（`WeekSheet`、`AppModel.selectedContentIsPodcast`）。
- 网页 `displayCategoryLabel` 仍是标签优先；`contentKind` 暂不影响网页展示，留待网页按同一分类重排时使用。

## 工具

- `tools/ops/normalize_catalog_content_kind.py`：离线规范化一个目录——补 `contentKind`、去掉非播客页的 `mediaType`、按目录 schema 校验；`--check` 只报告并以 1/0 表示是否需要规范化；永不部署。
- `tools/ops/publish_hosting_files.py`：克隆线上版本、只上传指定文件、finalize + release 并做 HTTPS 读回；整站 `firebase deploy` 在 2.9 GB 快照上已被 jetsam 杀过两次，单文件展示修正不需要它。默认只出计划，`--execute` 才发布。
- `experiments/sentence-first-agent/page-config.schema.json` 未改：`mediaType` 仍是技术枚举，`contentKind` 由类别派生，避免要求每个页面配置重复声明。

## 默认页：最新一期周日证道

`defaultPageId` 决定客户端在“没有已保存选择”时打开哪一页。生产目录曾把它指向 11-15 的播客单集（`if-i-had-more-time-jesus-is-better-than-this-world`），所以新装 App 打开就是播客，选篇面板默认也停在「播客」。

2026-11-16 起统一为：

- **默认页 = 最新一期周日证道**：在 `contentKind == "sermon"`、非 `diagnosticOnly`／`simulationOnly` 的页面里取日期最大的一页；播客与片段永远不会成为默认。
- 工具：`tools/ops/set_catalog_default_page.py --policy latest-sermon`（`--check` 只报告；输出按目录 schema 校验；不部署）。
- 每份投影（v3／v4／v5）都要改：客户端优先读 v5，网页与旧客户端读 v3。
- 发布驱动 `sfa_publish.py stage2` 按同一规则设默认页（不再无条件设成本页），`tools/ops/sfa_publish_gate.py` 也按这条规则检查，所以播客页晚于证道发布不会再抢默认页。

改完后的默认页：

| 站点 | 改前默认 | 改后默认 |
| --- | --- | --- |
| 生产 | `if-i-had-more-time-jesus-is-better-than-this-world`（播客，11-15） | `revelation-jesus-is-better-20261115`（周日证道，11-15） |
| Dev | `resi-20261018-broadcast`（证道，10-18） | `revelation-jesus-wins-20261025`（周日证道，10-25） |

发布：生产 `d948e5c3691157e6` → `a27987cfbc3a7a23`（release `1794890764072000`）；Dev `24a69950d7d4e328` → `6045c142ca7299c1`（release `1794890771277000`），两份都做了 HTTPS 读回。

验证：读回三份投影的 `defaultPageId` 均为最新证道；iPhone 18 Pro Max 模拟器上干净安装 Release 构建后，首页即该证道，选篇面板默认停在「周日证道」并勾选它。已保存过选择的用户仍会恢复自己的上次内容——本规则只决定“没有选择时”的默认。

## 本次数据修复（2026-11-16）

App 读 `multilingual-v5.json`（其次 v4、v3）；网页与旧客户端读 v3。三份投影必须一起修，否则 App 仍按旧字段分栏。两个站点都用同一方式：发布前快照 → 规范化 → 克隆发布 → HTTPS 读回。

| 站点 | 文件 | 修复前基线版本 | 修复后版本 | Release | 页面 |
| --- | --- | --- | --- | --- | --- |
| `ai-for-god-sermon-audio`（正式） | v3 | `6e795dbcdd1580d0` | `763fe8c46c773951` | `…/releases/1794846098015000` | 14 页：7 `sermon` + 7 `podcast` |
| `ai-for-god-sermon-audio`（正式） | v4、v5 | `763fe8c46c773951` | `d948e5c3691157e6` | `…/releases/1794847740202000` | 15 页全部规范化 |
| `ai-for-god-sermon-audio-dev` | v3 | `afccd110ce4c179a` | `a65f405aaa50a157` | `…/releases/1794846089521000` | 17 页：13 `sermon` + 2 `podcast` + 2 `clip` |
| `ai-for-god-sermon-audio-dev` | v4、v5 | `a65f405aaa50a157` | `24a69950d7d4e328` | `…/releases/1794847749037000` | v4 29 页、v5 28 页 |

修复只改展示分类字段：逐页比对修复前后的目录，除 `contentKind`／`mediaType` 外完全一致；42（正式）与 48（dev）个 release 包哈希未变，审核状态、音频、字幕都没有动。发布前快照与回执在忽略目录 `artifacts/catalog-audit/`（`<site>-v*.json`、`publish/<site>/normalize-v*-receipt.json`、`publish*.json`）。

## 验证与边界

- 修复后 HTTPS 读回的 v3／v4／v5：没有页面仍同时具备 `contentKind != podcast` 与 `mediaType: podcast`；v5 的 15 页里 4 篇周日证道（10-25、11-01、11-08、11-15）全部为 `contentKind: sermon`。
- 客户端实测（iPhone 17 / iOS 27.2 模拟器，BetaRelease 1.26.34 (79)，Dev 内容源）：调用 App 的刷新路径后打开选择面板——10-25 的「耶稣得胜」出现在「Sunday sermon」列，播客列只剩播客。截图在忽略目录 `artifacts/catalog-audit/app-evidence/`（`picker-podcast.png` 修复前、`picker-sermons-fixed.png`／`picker-podcast-fixed.png` 修复后）。
- 已经提交审核的 1.26.34 按旧规则（`mediaType`）分组，因此数据修复后它的分栏立即变正确；客户端里 `contentKind` 优先的判断要等下一个包含该改动的版本才生效，用来防止再次出现同类错标。
- iOS Core 120 项测试通过，含新增 `contentKindDecidesGroupingBeforeTheTechnicalMediaType`（回归用例直接取这次的错标组合）；ops 工具 18 项单元测试通过；`ContentPickerUITests` 在模拟器通过。
- 未做：真机（与本机模拟器不同）显示、网页分栏、以及缓存已热的旧客户端；旧客户端需要一次刷新或重启才会读到新目录。

## 回滚

- 目录：用 `artifacts/catalog-audit/<site>-v*.json`（修复前快照）重复同一条克隆发布命令即可回到修复前内容；三份投影要一起回滚。
- 客户端：`isPodcastContent` 的 `mediaType` 兜底保证旧目录仍能分组；若下一个版本要撤销 `contentKind` 优先，只需改回该属性一处。
