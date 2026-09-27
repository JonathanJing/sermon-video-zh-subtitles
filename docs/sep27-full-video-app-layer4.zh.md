# 2026-09-27 完整视频的 App Layer 4 发布

本周网页保留完整 31:31 视频及已批准的完整三语文稿。配音使用另行批准的短口播稿；两份文字同属一个已批准英文来源，但三语音轨分别绑定短口播候选。因此本次 App 发布使用 `sermon-target-language-release-package-v2`：`targetLanguageCandidateJsonSha256` 指完整阅读稿，`spokenTargetLanguageCandidateJsonSha256` 指短口播稿，`targetLanguageAudioPackageJsonSha256` 指已经整轨听审的音频包。Layer 4 只核对和聚合，不修改任何上游文字或音频。

旧版 App 保持读取 `/multilingual-v2.json` 与 `/releases/` 的 v1 包；新版 App 读取独立的 `/multilingual-v3.json` 与 `/releases-v2/` 的 v2 包。不得把 v2 发布包写入旧目录。新版目录的页面标题来自已批准中文完整页面资料。

## 命令与输出

`scripts/build_full_video_app_release.py` 有三个子命令，均使用仓库 Python 环境：

1. `prepare` 输入同一 `ready_for_translation` 英文包，以及每语言的完整候选与人审收据、短口播候选与人审收据、音频包与整轨人审／ASR 收据、已批准完整文稿 JSON。每种 `--full-candidate`、`--full-review-receipt`、`--spoken-candidate`、`--spoken-review-receipt`、`--audio-package`、`--audio-review-receipt`、`--audio-screening-receipt`、`--full-content` 都传入三次 `LOCALE=PATH`（`zh-Hans`、`ko`、`es`），另传 `--source`、`--metadata-approval`、`--metadata-proposal`、`--page-id`、`--date`、`--out`。页面显示字段须与原提案和批准记录完全一致。输出目录必须不存在。实际参数见 `prepare --help`。
2. `prepare --out PREPARED` 生成 `PREPARED/public/` 的 15 个新文件：每语言一个静态完整阅读页、原样复制的完整文稿 JSON、规范路径 MP3、短口播字幕 JSON，以及一份 `candidate` Release Package。`PREPARED/preparation-manifest.json` 记录 12 项用户资产的 SHA。静态阅读页不依赖脚本，音轨不覆盖网页原有 hashed 路径。此时所有 HTTP、设备、现场状态都是 `not_run`。
3. 将上述 15 个文件叠加到经当前站点基线核对的 Hosting 候选后发布。运行 `verify --prepared PREPARED --origin https://ai-for-god-sermon-audio.web.app --out HTTP.json`，逐一 GET 并计算 12 项新资产的完整 SHA；任何状态或 hash 不符即失败。随后运行 `seal --prepared PREPARED --http-verification HTTP.json --out SEALED`。它只用 12 项资产的 HTTP 收据作发布证据，避免 Release Package 自引用哈希；输出 `SEALED/public/` 的 16 个文件，即 12 项资产、三份 `published_http_verified` Release Package 和 `/multilingual-v3.json`。第二次叠加只更新三份 Release Package 并添加新目录，发布后再次核对三个最终包与目录 SHA。`SEALED/seal-report.json` 列出全部文件、SHA 和字节数。

发布目录：

| 资产 | 路径 |
|---|---|
| 完整阅读页 | `/pages/<pageId>/<locale>/index.html` |
| 完整文稿 JSON | `/content/<pageId>/<locale>.json` |
| 已审配音 | `/media/<pageId>/<locale>.mp3` |
| 短口播字幕 | `/captions/<pageId>/<locale>.json` |
| v2 正式包 | `/releases-v2/<pageId>/<locale>.json` |
| 新 App 目录 | `/multilingual-v3.json` |

本周 `pageId` 是 `2026-09-27-weekend-sermon-drive-530`。原始候选保存在忽略目录 `artifacts/drive-source-20260926-1730/layer4-app-prepared-20260927-v3/`。2026-09-27 已将封装后的三语包与 v3 目录发布到正式 Hosting；最终候选的 111 个文件逐一下载并通过 SHA-256 核对，三条 MP3 的 Range 请求均返回 206。收据位于同一忽略目录下的 `layer4-app-publish-20260927-v1/`。新版 iOS Release 模拟器构建读取正式目录并打开本周页，线上客户端存储测试加载三语阅读页并校验中文音轨。App Store Connect 二进制分发、真机和现场验收另行留证，不从这些结果推断。

## Firebase App 首页

正式 Hosting 首页 `/` 和 `/index.html` 在没有 `week` 参数时，由 `firebase/production-overlay/current-week-router.js` 打开本周完整视频页。带 `?week=<旧周次 ID>` 的直接链接仍进入原有按周阅读器。首页旧入口的“配音待补充”提示已更新为三语配音已发布。本次从前一版 111 文件候选复制，只新增路由脚本并修改首页 HTML；视频、文稿、音轨和发布包均未改动。发布候选和差异、HTTP 核对收据保存在忽略目录 `artifacts/drive-source-20260926-1730/layer4-app-hosting-phase3-home-20260927-v1/`。浏览器实测首页进入 31:31 视频页，韩语和西语均显示对应全文及可选配音；旧周次直接链接仍打开旧页。此网页发布不代表原生 iOS 二进制已在 App Store 分发。

用户从旧周次书签进入时，首页跳转不会发生；因此后来将同一本周页面加入旧阅读器的“本期与往期”选择器，选择 2026.09.27 即打开完整视频页。此修复只更新上述路由脚本，Hosting 候选与差异收据在忽略目录 `artifacts/drive-source-20260926-1730/layer4-app-hosting-phase4-picker-20260927-v1/`。已从线上 2026.09.20 页面实测列表出现本周选项，选择后到达本周 31:31 页面。
