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

## Firebase App 内播放

首页读取旧 `/weekly.json`，再由 `published-weeks.mjs` 读取已发布的 v3 目录及 v2 包，将本周三语音轨接入现有播放器。无周次参数时默认本周；旧周次链接仍可使用，并可在“本期与往期”中同页切换本周。“内容语言”选择中文、韩语或西语时，同时切换对应音轨和短口播字幕；完整文稿在“字幕全文”内独立展开，保留原视频时间，不混用配音字幕时间。

之前的首页跳转和下拉选项跳转方案已撤销。`firebase/production-overlay/current-week-router.js` 保留为空操作兼容文件，避免缓存旧 HTML 的用户再次跳转。新首页不再加载该脚本，也不展示另页入口。

本次 UI 候选位于忽略目录 `artifacts/drive-source-20260926-1730/layer4-app-hosting-phase5-in-app-20260927-v1/`；只更新播放器界面及加载模块，已批准的视频、文稿、字幕、音轨和发布包保持原字节。发布与实际浏览器验证收据存放在该目录。此发布范围是 Firebase Web App，原生 iOS 二进制分发、真机和现场验收仍独立记录。

2026-09-27 本次部署完成：11 项变更 UI 资产均 HTTP 200 且 SHA-256 与候选一致；线上浏览器在根路径分别启动三语音轨，播放时间推进至中文 9.02 秒、韩语 4.87 秒、西语 8.41 秒，三者时长均 1891.677333 秒且无媒体错误。往期切换回中文并禁用不存在的韩／西内容，返回本周恢复三语选择。另留有 390×844 手机宽度截图。定向验证为 69 项 JavaScript 测试、32 项周发布 Python 测试通过；这不代表手机真机或现场验收。

## 本周现场声音定位

`bind_published_fingerprints.mjs --public <新Hosting候选/public> --page-id <pageId> --source <冻结原视频>` 为已发布三语生成定位补充资产。先核验 v3 目录、正式包、文稿、原视频及三条配音哈希，使用原视频完整 0–1891.677333 秒提取一次声纹，然后分别绑定三条音轨；既有正式包和已批准媒体不改动。

补充接口 `/alignment/<pageId>.json` 使用 `sermon-published-alignment-v1`：顶层为 `pageId`、`sourceIdentitySha256`、`targets`；各 locale 包含 `releasePackageJsonSha256` 与现有 `sermon-audio-fingerprint-binding-v1` 的 `audioFingerprint`。这是独立、可选的新接口，无旧数据迁移；未提供或不匹配时仅关闭定位，保留配音播放。客户端核对来源、页面、音轨、窗口、发布包和索引哈希路径；Worker 在听音时再校验整个索引 SHA 和身份。切换语言使用对应音轨绑定并取消旧定位结果。

本周索引及补充接口在 `layer4-app-hosting-phase6-alignment-20260927-v1/` 候选内。沿用原定位算法、10 秒采集和可靠性阈值；声音在当前设备处理。页面入口与原声回放测试、实际手机麦克风和现场验收分别记录。

原声回放检查：7 个分布于 01:00–30:00 的 10 秒片段 × 3 语言索引，21/21 命中，测得偏差均为 0 秒；静音和另一篇 Sep20 英文原声 × 3 索引，6/6 拒绝。详见该候选内 `fingerprint-replay-validation.json`。这项结果仅证明离线原声匹配，不代表真实手机麦克风或现场噪声下的成功率。

Firebase 部署后，2 个 UI 文件、1 份绑定接口和 3 份索引均 HTTP 200、完整 SHA 一致；线上浏览器逐一切换中、韩、西内容并成功打开定位面板，始终停留根路径。手机宽度截图为 `alignment-mobile.png`；未启动真实麦克风或现场验收。
