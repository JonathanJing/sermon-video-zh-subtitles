# 2026-11-15 第 10 周《耶稣胜过这世界》运行报告

- 页面：`revelation-jesus-is-better-20261115`（production，zh-Hans / ko / es）
- 来源：Drive `1kzxU2KOnJdOjSvSJc-KYFVVWav3K9QnK`，sha256 `821cf83587854c95e4c39d005755a88d7a7a83f9e352d042733aff6566edb5bd`
- 英文：OpenAI whisper-1 + gpt-4o-transcribe，human-approved 435 句
- 译文：Claude Code CLI Opus 2.1.325，独立 Opus 审计；中文用户修正 20 句
- 配音：Spark Qwen3-TTS 12Hz 1.7B Base，Eric checkpoint，batch 8；人工整轨听审
- 最终标题：`耶稣胜过这世界`（主标题不再带系列前缀；titleCheck approved_exception）
- 线上页面：https://ai-for-god-sermon-audio.web.app/pages/revelation-jesus-is-better-20261115/zh-Hans/index.html
- 英文对照：https://ai-for-god-sermon-audio.web.app/english-reference/revelation-jesus-is-better-20261115.json

## 发布意图与部署

| 意图 | 内容 | 部署版本 |
|---|---|---|
| `20261115-week10-01` | 首次发布：assets、release/catalog/英文对照、rich 手册+对齐 | `df92efe3…` → `91a58963…` → `2eaa3092…` |
| `20261115-week10-02` | 标题改为「耶稣胜过这世界」（带系列前缀） | `690b6e78…` → `6f60f850…` → `2e815f77…` |
| `20261115-week10-03` | 主标题去掉系列前缀，只留证道标题 | `40e7bd03…` → `d984203a…` → `c24a92bf…` |

三次发布意图各自 ≤3 次托管部署；最终 gate `--require-guide --require-alignment` pass，smoke 三语 pass（含 `/api/session` 200）。

## 七件套

1. 页面/三语 assets：`publish-gate3`、`smoke3`、HTTP 200
2. release v2：`9ad31b98…` / `0c5b6b4e…` / `9bc26252…`
3. 目录 v5/v4/v3：默认页为本页，标题「耶稣胜过这世界」
4. `/english-reference/…json`：三语 435 blocks
5. 现场对齐：`/alignment/…json` + 三个 217,498-landmark 索引 200
6. 手册：`/weekly-guides/manifest-v1.json` week 10 entry，richRevision `72f22984…`，release 重绑 `9ad31b98…`
7. 统计目录：`sermon-feedback-api-00025-veh`，三语 + 上周三语 `/api/session` 200

## 复盘要点

- 首次 stage1 用 Node 26 的 firebase CLI 被 SIGKILL；核对线上未产生 release 后释放租约，改 Node 22 重发（35 s）。
- `stage2 --with-english` 在封存后写英文对照，补封后发布。
- 字幕 9 处 0.04 s 句界重叠，修 sentences.jsonl 后重出资产。
- 标题两次变更均走 `published_page_replace` A/B/C；`finish` 补了从 content 回写目录 title 的最小修改。
- rich 手册用用户 PDF 页渲染 + 参考目录 licensed 插图 + 重建 Pleiades 地图证据；rich 修订 `72f22984…`，地图证据 `e50ba62c…`；证据类型为页对齐 PDF 渲染，不是原始浏览器截图，已在 `publish-intent` 记录。
- 主标题 approved_exception 由用户指定，reason/approvedBy 与三语 publishedTitles 写入页面配置；ko/es 页面标题仍保留各自系列前缀。
- 海报：交接包 `artifacts/sentence-first-agent/20261115-jesus-is-better-poster/handoff.json`，主视觉/双二维码由海报 agent 按 `docs/tongxing-weekly-poster-format.zh.md` 生成；本次未上传/发送海报。

## 代码变更

- `packages/production/src/tongxing_production/delivery/weekly_guide_staging.py`：week10 标题白名单
- `packages/production/src/tongxing_production/delivery/weekly_guide_rich.py`：rich 修订/地图证据哈希
- `packages/production/src/tongxing_production/delivery/published_page_replace.py`：finish 回写目录 title
- `experiments/sentence-first-agent/pages/revelation-jesus-is-better-20261115.json`：页面配置与 approved_exception
- `docs/series-sermon-titles.zh.md`：week 10 中文标题

工具改动均不在 `sfa-prod-20261115` 锁定清单内；生产页面字节、release、catalog、英文对照、对齐、手册、统计目录均按上述发布意图留证。
