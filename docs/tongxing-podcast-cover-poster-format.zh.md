# 播客封面海报规范 v1（1080×1080）

状态：2026-11-15 起，双人播客的单语海报按本页制作。它是[每周海报格式 v2](tongxing-weekly-poster-format.zh.md) 之外的单独格式：周更证道海报仍用 2:3 竖版和生成的 ImageGen 主视觉，播客海报用**该期 YouTube 封面整张**做主视觉、1:1 方形。两份规范互不替代，各自只适用于自己的页面类型。

本页只写播客海报与周更海报的差别和固定参数；免责声明、二维码绑定规则、官方徽章来源、不自动上传不外发这些要求沿用周更规范，不在此重复数值。

## 与周更海报的差别

| 项目 | 周更证道海报 | 播客封面海报 |
|---|---|---|
| 画布 | 1200×1800（2:3）+ 600×900 | **1080×1080（1:1）+ 810×810** |
| 主视觉 | ImageGen 生成的无文字画面 | **该期 YouTube 封面整张**，不生成、不另配图 |
| 背景中是否有文字 | 禁止 | 保留封面原有英文标题与节目字标 |
| 中文标题位置 | 顶部单行，压在画面上 | 封面下方的米色信息带 |
| 标题写法 | 系列名 · 本篇标题（整条发布标题） | **只写本篇标题**，系列名进信息行 |

封面本身带英文大字，这一点与周更规范「主视觉不放文字」相反；播客海报的写法是让封面的英文标题保持原样，中文标题、系列、日期、讲员、经文、二维码与免责声明全部放在封面下方的信息带里，两者不重叠、不改写封面。

## 画布与版式

| 区域 | 规范 |
|---|---|
| 画布 | 1080×1080 PNG；预览 810×810 PNG，同一构图等比缩小 |
| 封面区 | y=0–608：封面按 1080 宽等比放入，**整张完整显示**，不裁切、不拉伸、不压暗；封面原尺寸 1280×720 |
| 信息带 | y=608–1080（472 px），暖白底 `#F3F0E5` |
| 信息带左列 | x=64 起，宽 540：`同行 —— 本周播客`（17 pt，浅色）→ 本篇标题（STSongti-SC-Bold，最大 52 pt，单行，放不下就缩小字号，缩到下限仍放不下则渲染失败）→ `系列 · 日期 · 讲员`（20 pt）→ `经文 · 审核说明`（16 pt，浅色）→ 免责声明（13 pt，浅色，两行完整） |
| 信息带右列 | 两个 164 px 二维码，各自上方有用途说明（`下载同行 App`／`打开本周网页版`）；左码下方官方 App Store 徽章 164×54；右码下方 `扫码阅读 · 收听` |
| 收尾 | 一条通栏细线（x=64–1016）下接 `一起听懂，一路同行。`（13 pt，浅色） |
| 禁止 | 不裁切标题、不改写封面文字、不叠加未经核对的内容摘录、不加语言列表或设计说明 |

左列文字与右列二维码底边都不越过收尾细线；渲染器对每一段文字做「放不下就缩小、缩到下限就报错」的处理，不允许静默裁切。

## 文案来源

标题、系列、日期、讲员、经文、审核说明一律从精确 `pageId` 的已发布 catalog 与 content 读取，不按「最新一期」或目录名猜。标题取 content 的 `title` 去掉系列前缀后的本篇标题；系列名用 [共享术语表](series-terminology.zh.md) 里该系列的正式中文名。审核说明按发布包的 `contentStatus`／`audioStatus`：两者都 `human_reviewed` 时写「译文与配音已审核」，机器质检语言按周更规范显示对应的机器质检披露。

免责声明与 App「关于同行」原文一致，允许换行，不删改：

> 独立个人项目，与 Mariners Church 无隶属或背书关系。
> AI 合成中文音频与整理文字仅供个人跟读参考。

## 两个二维码与官方徽章

| 位置 | 目标 |
|---|---|
| 左（下载同行 App） | `https://apps.apple.com/app/id6809255441`，下方放 Apple 官方下载徽章 |
| 右（打开本周网页版） | `https://ai-for-god-sermon-audio.web.app/?week=<pageId>&contentLang=<locale>&lang=<interfaceLocale>` |

中文为 `contentLang=zh-Hans&lang=zh`。不得使用 Beta／Dev origin，不得省掉周次或语言绑定。二维码由 CoreImage 真实编码生成，不交给图像模型绘制；官方徽章从 Apple 营销素材接口取一次后缓存，保持原比例与留白。

## 渲染

渲染器：`packages/production/src/tongxing_production/delivery/posters/render_podcast_cover_square.swift`（与 `artifacts/sermon-poster/<date>-podcast-<locale>/render_cover_square.swift` 同源，改动时两处同步并记哈希）。

```bash
# brief.json 见下节字段；封面用该期 YouTube maxresdefault，徽章用缓存文件
swift packages/production/src/tongxing_production/delivery/posters/render_podcast_cover_square.swift \
  brief.json cover.jpg badge.svg <fresh-output-dir>
```

`brief.json` 字段：`pageId`、`locale`、`title`（完整发布标题）、`titleLines`（单行，本篇标题）、`series`、`date`、`speaker`、`scripture`、`qrURL`、`storeURL`、`reviewLabel`、`labels{header, disclaimer, tagline, storeHeading, webHeading, caption}`。输出目录必须是新的；渲染器发现同名文件会拒绝覆盖。

## 验收

- 渲染器对 `poster.png` 与 `poster-preview.png` 各自独立做一次二维码识别，必须恰好解出两个码且 URL 与目标逐字一致；数量或内容不对就退出非零。
- 目视检查两张图：封面完整（英文标题与节目字标一个字不切）、中文标题单行不裁切、系列／日期／讲员／经文正确、免责声明两行完整、徽章比例、二维码静区、细线与页脚留白。
- 网页二维码落点要在浏览器核对标题、周次、内容语言与界面语言；下载码核对重定向后的 App 身份。
- 真机扫码、纸张印刷、上传站点和对外发送分别记录，不能用「图看着对」代替。

## 收据

每张海报一份 `cover-draft-receipt.json`（`tongxing-podcast-cover-poster-draft-v1`），至少记：`pageId`／`locale`、`format`（1080×1080 + 810×810）、`coverPlacement`、封面视频 ID 与缩略图 SHA-256、内容字段、二维码 URL、渲染器与徽章的 SHA-256、三个输出文件的 SHA-256、`qrValidation`（两张图的解码结果）、`status`。图片与收据留在被忽略的 `artifacts/`，不提交 Git。

海报是页面发布后的独立交付：`humanApproval` 保持 `false`，`status=draft_shown_not_uploaded` 表示已出图并交给用户看，不代表人工内容审核、上传或发送。没有用户指示不上传、不替换线上图、不对外发送。

## 历史

- **2026-11-08**：第一版播客封面海报，16:9（1920×1080 + 1440×810），封面满屏、中文信息带压在画面上。产物在 `artifacts/sermon-poster/2026-11-08-podcast-cover/`（在 MBP16 上），收据 `tongxing-podcast-cover-poster-draft-v1`，状态 `draft_shown_not_uploaded`。
- **2026-11-15**：用户改定 1:1：封面整张在上、中文信息带在下，避免满屏版把封面英文标题从中间切掉。本期产物在 `artifacts/sermon-poster/2026-11-15-podcast-zh/`，只保留最终图、收据、封面、徽章与渲染器。16:9 版不再作为新交付模板，只作历史证据。

## 已知缺口

- 目前没有稳定的 CLI 入口（周更用的是 `tools/ops/run.py delivery.posters.build`）；播客海报直接调 Swift 渲染器，brief 由操作者按上节字段手写。
- 多语言版（ko／es）复用同一张封面，只换文案与二维码 `contentLang`／`lang`，尚无批量化入口。
- 真机扫码、印刷和线上图片替换都没有自动验证。
