# Firebase Dev：四层 bucket 视频演练

## 用途与边界

输入是从 2026-09-27 已批准的完整视频截出的 **03:33.44–04:03.56**（30.12 秒）测试片。后端从一个模拟 HTTP 链接读取这段 MP4，并以独立 `dryrun-...` 身份依次产生 Layer 1 英文单元、Layer 2 三语文字、Layer 3 三语截取音轨／字幕、Layer 4 发布资产和 **Dev App 内可选择的新周次**。每个私有包标记 `simulation_only`、绑定上游 SHA；计时日志记录各层开始、完成、耗时，以及逐英文单元、逐语言文字单元和逐字幕 cue。

此快速演练**复用已审整篇的对应区间**，不重跑 ASR、翻译模型、TTS、人工全文／整轨审核，也不把整篇的人审收据迁移到截片身份。Dev 公开的 Release 和目录使用专门的 `sermon-dev-simulated-*` schema；正式 `/multilingual-v3.json` 及其默认周次保持不变。Dev 专用 App adapter 从 `/dry-run/latest.json` 加载模拟周次，明确显示「DEV 演练」「未单独人审」。三种独立 HTML 页面只是调试资产；**验收入口是 App 首页周次选择器**。本测试不证明 iOS、现场声音定位或正式 `four_layer_release`。

## 新 bucket 合同在 Dev 的测试形状

每次演练固定产生三语各 6 个资源（兼容 HTML 页面、全文、字幕、MP3、模拟 Release、定位索引），再加英文对照及对齐索引，共 **20 个新 Hosting 资源**；另有 **1 个 Dev 演练目录**、**1 个可变 Dev App 周次指针** `/dry-run/latest.json`，以及 **1 个独立 Dev bucket 视频对象**。因此单轮 Dev 演练改变 22 个 Hosting 文件加 1 个 bucket 对象；正式 Production 每周仍按[正式合同](tongxing-weekly-release.zh.md#正式三语周更文件数合同)使用 20 个新周资源、1 个 v3 catalog 更新和 1 个 bucket 对象。阶段清单的 20 文件／`videoDelivery` 形状按 `sermon-multilingual-v3-stage-manifest-v3` 校验，但保存的清单标明 `simulation_only`。视频对象路径为 `gs://ai-for-god-sermon-media-dev/weekly/<dryrun-pageId>/<clip-SHA>.mp4`；Hosting 原同源路径精确 302 到对象。

## 2026-09-28 实跑

| 步骤 | 已验证结果 |
| --- | --- |
| 来源 | 正式视频 SHA-256 `01cdde6f014192dff4b2243372c0a0b1ad61f018dfaa98b5256715916bfe56cd`；准确重编码后片段 30.1301 秒、2,170,958 字节、SHA-256 `4736fdffb44f9006bb60104636e9249135da031e282f1ed47c502615b055720e`。模拟链接为本机 HTTP 服务。 |
| Layer 1–3 | 6 个英文单元 `0-u047`–`0-u052`，三语各 6 个文字单元及 6 个音频字幕 cue；三语截取 MP3 各 30.12 秒／241,580 字节。第二轮把母版按固定参数重切，截片 SHA 完全一致；英文源包的人审状态、切点、anchor SHA、正式页面素材链均通过检查。计时日志共 55 条事件，均有 `startedAt`、`finishedAt`、`elapsedMs`。 |
| Dev 基线 | 发布第二轮前，把当前线上 Dev 的 **244 个完整文件**逐项 GET／SHA 与本地完整快照比较，合计 1,812,222,583 字节，全部一致。[基线收据](/Users/jonathan_jing/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/artifacts/firebase-dev-four-layer-bucket-dry-run/2026-09-28-clip-01/baseline-preflight-v4.json) |
| Layer 4／App | 第一轮仅有三种独立 HTML 展示，未进入 App。第三轮 `pageId=dryrun-20260927-clip-03`，从已安装的 Dev adapter 自动更新 `/dry-run/latest.json`；完整 Dev 快照 268 → 289 个 Hosting 文件。正式 v3 catalog 与默认正式周次不变。 |
| bucket／HTTP | 第三轮完整 GET 与片段 SHA 一致；同源路径 302；首尾 Range 为 206，CORS 为 Dev origin；22 个变更 Hosting 文件逐项 GET／SHA，三语 MP3 Range 与媒体类型通过；原有 267 个非指针文件部署后 ETag 与预检一致。[第三轮 HTTP 收据](/Users/jonathan_jing/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/artifacts/firebase-dev-four-layer-bucket-dry-run/2026-09-28-clip-03/http-receipt.json) |
| App 实际操作 | [Dev App 演练周次](https://ai-for-god-sermon-audio-dev.web.app/?week=dryrun-20260927-clip-03&contentLang=zh-Hans)可从首页周次选择器进入。中、韩、西内容可切换，各语言 30.12 秒音轨在 App 内开始实际播放；韩语全文里的英文对照已显示。回到 App 首页时正式 9/27 整篇仍是默认周次。首页旧「每周演练页」外链已移除，独立 HTML 只作调试，不计作最终交付。 |

本地忽略目录 `artifacts/firebase-dev-four-layer-bucket-dry-run/2026-09-28-clip-01/`、`2026-09-28-clip-02/` 与 `2026-09-28-clip-03/` 保留测试片、逐层模拟包、阶段清单、计时日志、完整 Dev 候选和 HTTP 收据。它们不进入 Git。

## 重跑要点

1. 从已核对的 9/27 播放视频按以下参数准确重编码 720p H.264/AAC 测试片，记录片段 SHA 和 `ffprobe` 时长。将片段放在本机 HTTP 服务下；一次只使用不含凭据的链接，脚本限制输入为 50 MiB。
2. 首次用 [`install_firebase_dev_dry_run_app.py`](../scripts/install_firebase_dev_dry_run_app.py) 在完整 Dev 快照上安装模拟周次 adapter；以后复用它。用 [`preflight_firebase_dev_snapshot.py`](../scripts/preflight_firebase_dev_snapshot.py) 将当前 Dev 全部线上文件与本地快照比对；相邻两次有收据时，可对未变文件核对 ETag，只下载变更文件。在该快照上运行 [`firebase_dev_four_layer_bucket_dry_run.py`](../scripts/firebase_dev_four_layer_bucket_dry_run.py)；传入模拟 URL、片段与母版 SHA、已审 English Source Package 和 anchor manifest、正式公开素材快照、Dev 快照、基线收据及新 `dryrun-...` ID。脚本重切母版证明截片来源，再生成不覆盖现有周目录的候选，并更新唯一 Dev App 指针。
3. 把候选视频上传到 Dev bucket，验证完整 GET／SHA、CORS 和首尾 Range；然后以候选 `hosting/firebase.json` 发布完整 Dev 快照。不要从旧快照删除其他 Dev 功能。
4. 运行 [`verify_firebase_dev_four_layer_bucket_dry_run.py`](../scripts/verify_firebase_dev_four_layer_bucket_dry_run.py)，传入候选和基线预检收据，核对 22 个变更 Hosting 文件、原有文件的 ETag、bucket 视频和三语音轨。**从 Dev App 首页选择新周次**，切换三语并在 App 内试播，同时检查英文对照与模拟标识。正式发布器和 iOS 验收分别运行，不由本模拟结果代替。

本次脚本只实现确定性的阶段模拟及候选构建；`gcloud storage cp`、Firebase Dev deploy 和 App 实际播放仍是明确的后续步骤。下一轮可把这些步骤接入带租约、可续跑的 Dev 编排器，并让失败事件也保留计时日志。首次完整快照预检读取约 1.8 GB Dev 公开文件；相邻迭代可复用收据核对未变文件 ETag，只下载新增或修改的文件。

```bash
ffmpeg -hide_banner -loglevel error -ss 213.44 -i <已核对的完整播放视频.mp4> \
  -t 30.12 -vf scale=1280:-2 -c:v libx264 -preset veryfast -crf 27 \
  -c:a aac -b:a 96k -movflags +faststart <Dev测试片.mp4>
```
