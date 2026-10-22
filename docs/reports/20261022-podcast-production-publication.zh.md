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

## 外部可见的变化

- 新页面一项，三语可选。
- 旧客户端读取的 v4/v3 中，以下页面的默认语言改为与 v5 一致：resi-20261004、jesus-is-worthy、09-27 周次、resi-20261011（es → zh-Hans），resi-20261018-15030286 的 v4 版次页（es → ko）。内容、音轨和其他字段不变。

## 没有验证的部分

- 浏览器里实际选页和播放、iOS 刷新与播放、离线下载：`not_run`。
- 英文对照（english-reference）与大纲、默想没有发布；页面没有摘要。
- 另一个代理的正式播客生产若要发布同一期，需用新的 pageId 或替换本页。
- `tests/test_run_dev_simulated_delivery.py::test_chain_resumes_http_failure_without_repeating_asset_publication` 在干净的 dev 上同样失败，与本次修改无关。
