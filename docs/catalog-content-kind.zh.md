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

## 本次数据修复（2026-11-16）

两个站点都用同一方式修复：发布前快照 → 规范化 → 单文件克隆发布 → HTTPS 读回。

| 站点 | 修复前基线版本 | 新版本 | Release | 页面 |
| --- | --- | --- | --- | --- |
| `ai-for-god-sermon-audio`（正式） | `sites/ai-for-god-sermon-audio/versions/6e795dbcdd1580d0` | `…/versions/763fe8c46c773951` | `sites/ai-for-god-sermon-audio/releases/1794846098015000` | 14 页：7 `sermon` + 7 `podcast` |
| `ai-for-god-sermon-audio-dev` | `sites/ai-for-god-sermon-audio-dev/versions/afccd110ce4c179a` | `…/versions/a65f405aaa50a157` | `sites/ai-for-god-sermon-audio-dev/releases/1794846089521000` | 17 页：13 `sermon` + 2 `podcast` + 2 `clip` |

修复只改展示分类字段：发布包 URL、SHA-256、审核状态、音频与字幕都没有变。发布前的目录快照与规范化回执在忽略目录 `artifacts/catalog-audit/`（`<site>-v3.json`、`publish/<site>/normalize-receipt.json`、`publish.json`）。

## 验证与边界

- 修复后 HTTPS 读回的目录：正式 7 sermon + 7 podcast，dev 13 sermon + 2 podcast + 2 clip；没有页面仍同时具备 `contentKind != podcast` 与 `mediaType: podcast`。
- iOS Core 120 项测试通过，含新增 `contentKindDecidesGroupingBeforeTheTechnicalMediaType`（回归用例直接取这次的错标组合）；两个 ops 工具的 18 项单元测试通过。
- 已经提交审核的 1.26.34 按旧规则（`mediaType`）分组，因此数据修复后它的分栏立即变正确；`contentKind` 要等下一个包含该客户端判断的版本才生效，用于防止再次出现同类错标。
- 本页不声称真机、Beta 或网页展示已验收；那需要人工在实际设备上确认。

## 回滚

- 目录：用 `artifacts/catalog-audit/<site>-v3.json`（修复前快照）重复同一条单文件发布命令即可回到修复前内容。
- 客户端：`isPodcastContent` 的 `mediaType` 兜底保证旧目录仍能分组；若下一个版本要撤销 `contentKind` 优先，只需改回该属性一处。
