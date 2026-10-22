# 2026-10-22 播客正式页面发布：如果我有更多时间 · 耶稣差遣并使属祂的人复活

交付类型：`four_layer_release` 的 Layer 4 正式页面（配音来自逐句优先实验线，见[播客整期报告](20261022-sentence-first-podcast-full-episode.zh.md)）。正式站 `https://ai-for-god-sermon-audio.web.app`。

## 发布了什么

| 项 | 值 |
|---|---|
| pageId | `if-i-had-more-time-jesus-sends-and-resurrects-his-own` |
| 标题 | 如果我有更多时间 · 耶稣差遣并使属祂的人复活（韩、西语内容用对应的 10-18 证道译名） |
| 类别 | 证道播客（en Sermon Podcast、ko 설교 팟캐스트、es Pódcast del sermón），`mediaType=podcast` |
| 语言 | zh-Hans（页面默认）、ko、es，各 746 句 |
| 状态 | 三语 `contentStatus=human_reviewed`、`audioStatus=human_reviewed`，release v2 `published_http_verified` |
| 审核依据 | 用户 2026-10-22 在对话中确认：三条整轨全部听完，韩、西语译文全部审过，“全部通过”。中文译文为既有人工批准的 Layer 2 候选 |
| 来源 | YouTube `AKY0k5KiKns`，媒体 sha256 `145a2e99…`，批准窗口 5.5–2406 s，英文来源包 `495781ac…` |
| 音轨 | MP3 192 kb/s：zh 3085.78 s、ko 3042.98 s、es 3140.26 s；Steve Bang Lee、John Thomas 两种声音 |
| 同步 | 自然语速配音，比原片长约四分之一，不跟原视频同步；字幕按配音自身时间轴；不提供听音定位 |

## 发布过程

1. 取完整 live baseline：`c2febd95227a047b`（245 文件，243 公开）。
2. 发现 live v4/v3 与 v5 投影不一致：v4 5 页、v3 3 页的 `defaultTargetLocale` 仍按 8b703903 之前的规则（取第一个键 `es`）。经用户同意，新增 `contract.repair_projected_defaults`，只允许页面默认语言不同，其他任何差异都拒绝；live baseline 用显式开关接受这一种偏差，候选仍严格校验。
3. 第一次部署：12 个新资产（三语 page、content、captions、MP3）+ 修正后的 v4/v3，版本 `b222ecbe3c3b1e69`。
4. HTTP 核验 12 项：GET 与 SHA 全部一致，三条 MP3 均返回 206 与正确 Content-Range。
5. 第二次部署：三语 release v2（绑定核验证据）+ v5/v4/v3 追加本页，版本 `f69a0a5f1e1af73a`。发布器回读 v3/v4/v5 一致；独立回读三份目录与三份 release 字节一致。默认页面不变（`resi-20261018-15030286`）。

## 发布后修复：iOS 读不到文稿

用户在 iPhone 上看到音频可播，但“文稿暂时无法读取”。原因：content 的 `durationSeconds` 写成批准窗口长度 2400.5 s，而全文 cue 用媒体时间，最后几句结束于 2406.0 s；iOS `validateCues` 要求每句结束不超过 `durationSeconds`，整份文稿被拒。浏览器 HTTP 核验和 schema 校验都发现不了这一点。

修复：三语 content 改为 `durationSeconds=2406.0`，写到新路径 `content/<pageId>/<locale>-r2.json`（已发布的旧文件不覆盖、不再被引用）；发布前用与 iOS 相同的规则逐句检查。先部署新 content（`7da71006cba9b577`），12 项 HTTP 核验通过，再部署改绑后的三语 release 和三份目录（`1719a01b0c552a79`），回读一致；按 App 的读取路径从目录到 release 到 content 与字幕，三语逐句检查通过。

## 第二次修复：正式版 App 找不到播客；10-11、10-18 没有小标题

用户在正式版 App 的证道列表里找不到本页，10-11、10-18 两页也没有小标题。上一节“需新版 App”的判断是错的。

- **原因一（本页消失）：** 上一次修复把文稿放到 `content/<pageId>/<locale>-r2.json`。正式版 App 的 `TargetLanguageReleasePackage.validate` 只接受 `/content/<pageId>/<locale>.json`（页面、字幕同理），三种语言的 release 都被拒（“双稿发布资产路径与语言不符”），整页不显示。开发版跳过这项检查，所以开发版里看得到。仓库的 `validate_v2_release_target` 原本没有这条规则，发布工具没拦住。
- **原因二（小标题）：** App 只从目录页面的 `displayCategory` 读小标题（09-27、10-04 两页写死为“正式播放版”）。线上 10-11、10-18 两页没有这个字段。
- **修复：** 把修正后的文稿字节（与 `-r2` 文件相同，哈希不变）写回固定路径并部署（`ebaeb979a9e0e7fb`），12 项 HTTP 核验通过；再部署改绑到固定路径的三语 release，以及 v5/v4/v3 目录（`a06790750abdd291`）。同一次部署经用户同意，给 `resi-20261011-54475d42`、`resi-20261018-15030286` 加类别“正式播放版 / Archive edition”，投影带到 v4/v3 的 `resi-20261018-broadcast`；其他页面任何字段都不变（暂存时逐页比对）。回读一致。
- **验证：** 用 iOS Core 的 Swift 代码解码线上 v5/v4/v3 目录和全部 18 个 release，全部通过，类别显示为预期值；按 App 读取路径逐句检查三语文稿与字幕通过。
- **防止再犯：**
  - 发布合同新增 `validate_v2_asset_paths`，与 iOS 同一条规则：v2 release 的页面、文稿、字幕必须在固定路径。`validate_v2_release_target` 调用它（带测试）。
  - 快照校验 `validate_catalog_snapshot` 对所有 v2 release 跑这条规则，受保护发布器在部署前就会拒绝；用当天的快照实测：出问题的 `-r2` 快照被拒，现在的线上快照通过。
  - 发布驱动的 `fix-content` 改为在原路径写入修正后的字节，只改 release 里的哈希；去掉了写新路径的旧步骤。
  - runbook 写明：修已发布文件就在原路径写入；开发版看得到不代表正式版看得到。

正式版 App 实机刷新后能否看到本页与小标题，待用户确认。

## 外部可见的变化

- 第二次修复后：10-11、10-18（含 v3/v4 中的 10-18 broadcast 版次页）显示小标题“正式播放版”；本页三语文稿回到固定路径，已不再引用的 `-r2` 文件仍留在站上。

- 新页面一项，三语可选。
- 旧客户端读取的 v4/v3 中，以下页面的默认语言改为与 v5 一致：resi-20261004、jesus-is-worthy、09-27 周次、resi-20261011（es → zh-Hans），resi-20261018-15030286 的 v4 版次页（es → ko）。内容、音轨和其他字段不变。

## 没有验证的部分

- 浏览器里实际选页和播放、iOS 刷新与播放、离线下载：`not_run`。
- 英文对照（english-reference）与大纲、默想没有发布；页面没有摘要。
- 另一个代理的正式播客生产若要发布同一期，需用新的 pageId 或替换本页。
- `tests/test_run_dev_simulated_delivery.py::test_chain_resumes_http_failure_without_repeating_asset_publication` 在干净的 dev 上同样失败，与本次修改无关。
