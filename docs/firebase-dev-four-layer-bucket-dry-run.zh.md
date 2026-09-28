# Firebase Dev：四层 bucket 视频演练

## 用途与边界

输入是从 2026-09-27 已批准的完整视频截出的 **03:33.44–04:03.56**（30.12 秒）测试片。后端从一个模拟 HTTP 链接读取这段 MP4，并以独立 `dryrun-...` 身份依次产生 Layer 1 英文单元、Layer 2 三语文字、Layer 3 三语截取音轨／字幕、Layer 4 测试页面和发布清单。每个私有包标记 `simulation_only`、绑定上游 SHA；计时日志记录各层开始、完成、耗时，以及逐英文单元、逐语言文字单元和逐字幕 cue。

此快速演练**复用已审整篇的对应区间**，不重跑 ASR、翻译模型、TTS、人工全文／整轨审核，也不把整篇的人审收据迁移到截片身份。Dev 公开的 Release 和目录使用专门的 `sermon-dev-simulated-*` schema；正式 `/multilingual-v3.json` 与 App 文件保持原字节。测试页是 Dev 的独立演练入口，尚未验证 App 选页、现场声音定位、字幕随视频滚动或 iOS。不能将此收据升格为正式 `four_layer_release`。

## 新 bucket 合同在 Dev 的测试形状

每次演练固定产生三语各 6 个资源（页面、全文、字幕、MP3、模拟 Release、定位索引），再加英文对照及对齐索引，共 **20 个新 Hosting 资源**；另有 **1 个 Dev 演练目录**，以及 **1 个独立 Dev bucket 视频对象**。阶段清单的 20 文件／`videoDelivery` 形状按 `sermon-multilingual-v3-stage-manifest-v3` 校验，但保存的清单标明 `simulation_only`。视频对象路径为 `gs://ai-for-god-sermon-media-dev/weekly/<dryrun-pageId>/<clip-SHA>.mp4`；Hosting 原同源路径精确 302 到对象。正式 Production 每周仍使用[正式合同](tongxing-weekly-release.zh.md#正式三语周更文件数合同)和正式审核门禁。

## 2026-09-28 实跑

| 步骤 | 已验证结果 |
| --- | --- |
| 来源 | 正式视频 SHA-256 `01cdde6f014192dff4b2243372c0a0b1ad61f018dfaa98b5256715916bfe56cd`；准确重编码后片段 30.1301 秒、2,170,958 字节、SHA-256 `4736fdffb44f9006bb60104636e9249135da031e282f1ed47c502615b055720e`。模拟链接为本机 HTTP 服务。 |
| Layer 1–3 | 6 个英文单元 `0-u047`–`0-u052`，三语各 6 个文字单元及 6 个音频字幕 cue；三语截取 MP3 各 30.12 秒／241,580 字节。第二轮把母版按固定参数重切，截片 SHA 完全一致；英文源包的人审状态、切点、anchor SHA、正式页面素材链均通过检查。计时日志共 55 条事件，均有 `startedAt`、`finishedAt`、`elapsedMs`。 |
| Dev 基线 | 发布第二轮前，把当前线上 Dev 的 **244 个完整文件**逐项 GET／SHA 与本地完整快照比较，合计 1,812,222,583 字节，全部一致。[基线收据](/Users/jonathan_jing/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/artifacts/firebase-dev-four-layer-bucket-dry-run/2026-09-28-clip-01/baseline-preflight-v4.json) |
| Layer 4 | 最新 `pageId=dryrun-20260927-clip-02`；本轮仍为 20 个周资源 + 1 个 Dev 演练目录 + 1 个 bucket 对象，Dev 完整快照 244 → 265 个 Hosting 文件。原正式 catalog 和 App JS 线上 SHA 未变化。第一轮 `clip-01` 演练页保留作迭代对照。 |
| bucket／HTTP | 公开完整 GET 与片段 SHA 一致；同源路径 302；首尾 Range 为 206，CORS 为 Dev origin；21 个新增 Hosting 文件逐项线上 GET／SHA，三语 MP3 Range 与媒体类型通过；原有 244 个文件部署后 ETag 与预检一致。[第二轮 HTTP 收据](/Users/jonathan_jing/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/artifacts/firebase-dev-four-layer-bucket-dry-run/2026-09-28-clip-02/http-receipt-v2.json) |
| 浏览器 | [中文测试页](https://ai-for-god-sermon-audio-dev.web.app/pages/dryrun-20260927-clip-02/zh-Hans/index.html)显示 6 组中英对照；bucket 视频开始实际播放，时长 30.1301 秒、无媒体错误；中文 MP3 时间推进至 4.58 秒、时长 30.12 秒。[韩语](https://ai-for-god-sermon-audio-dev.web.app/pages/dryrun-20260927-clip-02/ko/index.html)和[西语](https://ai-for-god-sermon-audio-dev.web.app/pages/dryrun-20260927-clip-02/es/index.html)页面切换、文字及音轨路径已检查。三语音轨的完整人耳听审未做。 |

本地忽略目录 `artifacts/firebase-dev-four-layer-bucket-dry-run/2026-09-28-clip-01/` 与 `2026-09-28-clip-02/` 保留测试片、逐层模拟包、阶段清单、计时日志、完整 Dev 候选和 HTTP 收据。它们不进入 Git。

## 重跑要点

1. 从已核对的 9/27 播放视频按以下参数准确重编码 720p H.264/AAC 测试片，记录片段 SHA 和 `ffprobe` 时长。将片段放在本机 HTTP 服务下；一次只使用不含凭据的链接，脚本限制输入为 50 MiB。
2. 用 [`preflight_firebase_dev_snapshot.py`](../scripts/preflight_firebase_dev_snapshot.py) 将当前 Dev **全部线上文件**与完整本地快照逐项比对，保存一小时内的收据。在该快照上运行 [`firebase_dev_four_layer_bucket_dry_run.py`](../scripts/firebase_dev_four_layer_bucket_dry_run.py)；传入模拟 URL、片段与母版 SHA、已审 English Source Package 和 anchor manifest、正式公开素材快照、Dev 快照、基线收据及新 `dryrun-...` ID。脚本重切母版证明截片来源，再生成不覆盖现有目录的候选。
3. 把候选视频上传到 Dev bucket，验证完整 GET／SHA、CORS 和首尾 Range；然后以候选 `hosting/firebase.json` 发布完整 Dev 快照。不要从旧快照删除其他 Dev 功能。
4. 运行 [`verify_firebase_dev_four_layer_bucket_dry_run.py`](../scripts/verify_firebase_dev_four_layer_bucket_dry_run.py)，传入候选和基线预检收据，核对 21 个新 Hosting 文件、原有文件的 ETag、bucket 视频和三语音轨；浏览器实际打开三语测试页并试播。正式发布器、App 内选页与 iOS 验收分别运行，不由本模拟结果代替。

本次脚本只实现确定性的阶段模拟及候选构建；`gcloud storage cp`、Firebase Dev deploy 和浏览器播放仍是明确的后续步骤。下一轮可把这些步骤接入带租约、可续跑的 Dev 编排器，并让失败事件也保留计时日志。完整快照预检会读取约 1.8 GB Dev 公开文件；若以后改用 Firebase Hosting 发布清单 API，应保持同等的全文件身份校验。

```bash
ffmpeg -hide_banner -loglevel error -ss 213.44 -i <已核对的完整播放视频.mp4> \
  -t 30.12 -vf scale=1280:-2 -c:v libx264 -preset veryfast -crf 27 \
  -c:a aac -b:a 96k -movflags +faststart <Dev测试片.mp4>
```
