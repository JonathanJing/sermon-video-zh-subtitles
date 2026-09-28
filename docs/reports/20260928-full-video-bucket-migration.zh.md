# 2026-09-28 本周完整视频 bucket 迁移

## 目标与合同

9 月 27 日的 31:31 完整播放视频从 Firebase Hosting 当前发行版移到独立 Cloud Storage bucket。页面、三语全文、字幕、配音、v2 Release、定位索引和 v3 catalog 仍在 Hosting。客户端继续读取 `/pages/2026-09-27-weekend-sermon-drive-530/full-video-browser.mp4`；Hosting 的精确 302 将它转到按 SHA 命名的 bucket 对象。已发行内容的来源身份、三语文字、音轨及逐语言 Release 字节不变。未来周次使用 [`three_locale_bucket_video_v2`](../tongxing-weekly-release.zh.md#正式三语周更文件数合同)：21 个 Hosting 文件和 1 个 bucket 对象。

## 本次操作与证据

| 阶段 | 结果 |
| --- | --- |
| Dev bucket | `gs://ai-for-god-sermon-media-dev`，独立 Dev 项目，公开只读对象、限制 Dev origin 的 CORS。8 秒／739,342 字节模拟 MP4 的公开 GET、CORS、206 Range 均通过。 |
| Dev Hosting | 从当前完整 Dev 快照追加测试页与精确重定向，发布到 `ai-for-god-sermon-audio-dev`；release `1790608571226000`。浏览器实际播放模拟视频至 8.008 秒结尾。[测试页](https://ai-for-god-sermon-audio-dev.web.app/dry-run/video-bucket-20260928/index.html) |
| Production 对象 | `gs://ai-for-god-sermon-media-prod/weekly/2026-09-27-weekend-sermon-drive-530/01cdde6f014192dff4b2243372c0a0b1ad61f018dfaa98b5256715916bfe56cd.mp4`，972,090,864 字节，`video/mp4`，完整公开回读 SHA-256 为 `01cdde6f014192dff4b2243372c0a0b1ad61f018dfaa98b5256715916bfe56cd`，与原 Hosting 视频及三语 content 绑定一致。 |
| Production Hosting | 基线 catalog 与线上均为 `24d38cd8aa0b35798154352b053749697472dc2ba7c0292cf1c5281c155006fe`；新 catalog 线上与候选均为 `bf6bba4cd11441ddb7628a8f7adb719189b0d6b593f51197a501ddbbdf24ea17`。当前发行文件数 108 → 107，仅移除 Hosting MP4；release `1790608820708000`。旧快照保留可回退。 |
| HTTP 和浏览器 | [原视频路径](https://ai-for-god-sermon-audio.web.app/pages/2026-09-27-weekend-sermon-drive-530/full-video-browser.mp4) 返回精确 302；跟随后的首尾 Range 均 206，内容类型 `video/mp4`、总长一致、CORS 限定正式 origin；自动核验完整 GET／SHA 通过。正式[完整视频页面](https://ai-for-god-sermon-audio.web.app/pages/2026-09-27-weekend-sermon-drive-530/index.html)浏览器显示 31:31，点击后时间从 0 推进到 4.18 秒。 |

本地不可入库的回退快照、迁移报告和 HTTP 收据分别在 `artifacts/drive-source-20260926-1730/layer4-app-hosting-sep27-cleanup-20260928-v1/`、`artifacts/video-bucket-migration/2026-09-28-production-candidate/`。Web 的整段播放、iOS 原生视频播放和现场验收未运行；当前 iOS 版本没有原生完整视频入口，文稿与配音继续按原方式使用。现有独立视频页仍是 `preload="metadata"`；后续改为零预取需同步处理页面哈希和逐语言 Release 的引用，不能静默改写已发布不可变资产。
