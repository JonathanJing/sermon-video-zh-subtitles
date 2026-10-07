# 同行每周内容发行

本流程接收既有生产脚本生成的单周候选包，保存完整历史目录，再核验发布后的公共资源。它不调用模型、不重新生成音频、不授予内容审核或现场同步批准，也不创建或替换现有定时任务。生产和配音仍按 [本地生产 runbook](codex-local-production-runbook.zh.md) 执行。

当前 registry／`weekly.json` 流程是 Layer 4 的 legacy adapter。今后的 Production 多语言周更必须输入同一 `targetLocale` 已批准的 `Target-Language Candidate` 和 `Target-Language Audio Package`，生成逐语言 [Release Package v2](../schemas/sermon-target-language-release-package-v2.schema.json)，并以 [Catalog v3](../schemas/sermon-multilingual-catalog-v3.schema.json) 让 Firebase 与已安装 iOS App 刷新发现页面。纯文字发行也必须由同语言 Layer 3 显式记录 `audio_unavailable`，且先确认 Web/iOS 都支持该能力。旧 v1/v2 CLI 不能作为正式 v3 周更证据。`published_http_verified` 不反向提升翻译、音频或现场审核状态。

## 每周路径

来源完整可用 → 现有流程生成候选 → 内容审阅与对应音轨收据 → 自动生成并绑定听音定位指纹 → 在正式站完整快照上追加 v2 Release／v3 Catalog 候选 → 检查历史文件与目录差异 → 资产先发、v3 目录最后发 → HTTP 文件核验 → Firebase App 和同版本 iOS App 刷新选页／播放验收 → 本周海报交付（分别验收）。每周只更新内容；客户端出现不支持的新 schema、语言或能力时才安排 App 版本更新。

对听众而言，每周目标是从 App 的“选择证道”进入本周内容，在原有界面中观看视频、切换已发布语言、收听配音和阅读文稿；单独的 `/pages/<pageId>/index.html` 只是资产地址与浏览器兼容入口。HTTP 核验可先记录 `published_http_verified`，但本周 App 交付须另外核对 Web App 根路径及原生 iOS 的目录展示、页内播放，并在实际安装版本上验收。未分发的新二进制不能视作用户手机已经拥有本周页面。

周次、source route 和 source ID 共同决定内容项。同一周的直播归档与独立 YouTube 视频分别保留。已存在的源身份不能借同一个 page ID 改写。音频与审核声明沿用各页原始数据，不因进入发行清单而升级。

正式多语言目录的页面名称采用默认内容语言已批准的「系列名 · 本篇标题」，例如「启示录：耶稣带来的安慰与盼望 · 耶稣配得」。`multilingual-v3.json` 的 `pages[].title` 供 iOS 选页列表和本周页头直接读取；只改目录元数据即可让已安装的 App 在刷新目录后显示新名称。每周发布前用同语言 `content/<pageId>/<locale>.json` 的 `series`、`title` 校验该字段，不能只写简称或从未审核文字另造系列名。

### 机器质检周次：v4 目录与 v3 投影

按 [机器质检豁免](machine-quality-waiver.zh.md) 自动发布的语言走四层封存（`build_full_video_app_release.py seal` 与托管发布），不走下面的 v3 组装器。封存写出 `/releases-v4/<pageId>/<locale>.json`、`/multilingual-v4.json`，并把 `/multilingual-v3.json` 写成 v4 去掉机器质检语言后的投影：旧版 iOS 看到的目录与上周相同，新版网页和 iOS 先读 v4，显示“机器质检”标签和披露文案。两份目录一起比较交换、一起回读；只会改 v3 的旧组装器遇到带 v4 的基线会拒绝。字段见 [四产物公开交付](layer4-four-product-public-delivery.zh.md#机器质检发布release-v4--catalog-v4)。

### v3 周更发布清单与验收

这一清单优先于下文仅适用于 `weekly.json` 的 legacy 命令。当前仓库的 `assemble_multilingual_hosting.py`、`deploy_multilingual_hosting.py`、`verify_multilingual_hosting.py` 仍只处理 v2 Catalog／v1 Release；在 v3 入口实现并通过定向测试前，不得用这些命令部署新周后宣称两端已经刷新可用。

[9/27 专用 L4 adapter](sep27-full-video-app-layer4.zh.md#命令与输出) 的 `seal` 只生成单页 catalog，不能直接覆盖完整旧目录。它的 `published_http_verified` 包只绑定 12 项资产 GET／SHA 收据；最终包和合并后 catalog 的第二次部署核验、音频 Range 与 App 验收仍须分别完成。该专用输出不能替代下列完整周更 stage 合同。

### 正式三语周更文件数合同

已发行的 Hosting 视频周次沿用 `three_locale_full_video_v1`：**21 个新周 Hosting 资源 + 1 个更新的 `/multilingual-v3.json` = 22 个 Hosting 文件**。新的 bucket 视频周次使用 `three_locale_bucket_video_v2`：**20 个新周 Hosting 资源 + 1 个更新的 catalog = 21 个 Hosting 文件，另有 1 个不可变 Cloud Storage 视频对象**；合计处理 22 个 Firebase 资源，但不可把它写成 22 个 Hosting 文件。两个配置都只约束单周增量，既有完整站点、客户端代码、海报和 Dev dry run 分别计数。

从模拟链接到 Layer 1–4 的快速测试使用独立的 [Firebase Dev 四层演练](firebase-dev-four-layer-bucket-dry-run.zh.md)。它按正式周资源的 20+1+1 形状验证资产，再额外更新 1 个 Dev App 演练周次指针；**App 内选页、三语切换与播放是演练通过条件**，独立 HTML 仅供调试。模拟包不取得正式人审资格，也不写入 Production catalog。

| 资源 | 数量 | 固定路径 |
| --- | ---: | --- |
| 完整视频，旧配置 | 1 Hosting | `/pages/<pageId>/full-video-browser.mp4` |
| 完整视频，新配置 | 1 bucket 对象、0 Hosting 文件 | `https://storage.googleapis.com/<专用媒体bucket>/weekly/<pageId>/<播放文件SHA>.mp4`；原同源路径用精确 302 指向该对象 |
| 中文、韩语、西语的页面、全文、字幕、音轨、v2 Release、听音定位指纹 | 18（每语 6） | `/pages/<pageId>/<locale>/index.html`、`/content/<pageId>/<locale>.json`、`/captions/<pageId>/<locale>.json`、`/media/<pageId>/<locale>.mp3`、`/releases-v2/<pageId>/<locale>.json`、`/fingerprints/<sha前16位>-landmarks.json` |
| 英文对照与对齐索引 | 2 | `/english-reference/<pageId>.json`、`/alignment/<pageId>.json` |
| v3 目录 | 1（更新） | `/multilingual-v3.json` |

旧配置的 `stage-public`、manifest v2 和 21 文件校验保持可读。新配置的 `stage-public` **不包含 MP4**，manifest v3 使用 `profile=three_locale_bucket_video_v2`，列出恰好 20 个新 Hosting 文件及 `videoDelivery`（同源固定路径、bucket HTTPS URL、播放文件 SHA-256、字节数）。同一 `videoDelivery` 必须写入 v3 catalog 的本周 page；三语 content 的 `sourceVideoUrl` 仍是同源路径，`browserVideoSha256` 均等于视频对象 SHA。`--video-file` 指向暂存区外的已审完整 MP4，组装时实测字节数与 SHA；来源母版的 `sourceMediaSha256` 保持原身份，不能混用。组装器拒绝缺失／多余文件、对象不匹配及不安全 URL。新报告分别记录 `addedFileCount=20`、`catalogUpdateFileCount=1`、`weeklyFileCount=21`、`bucketObjectCount=1`、`weeklyFirebaseObjectCount=22`。

发布顺序是：在与正式站分离的 Dev 项目用模拟视频和真实 bucket 完成端到端测试；正式发布时先上传并验证不可变对象的大小、哈希、`Content-Type: video/mp4`、公开 GET、首尾 206／`Content-Range`，再准备 Hosting 完整快照及精确 302、限定 `media-src` 的 CSP，最后更新 catalog。发布后的同源视频 URL 必须返回预期重定向并可在 Web 播放和拖动；未点视频时不应下载完整视频。当前独立页面使用 `preload="metadata"`，仍可能下载少量视频数据；若要零预取，须在新周页面生成时改为 `preload="none"` 并重算页面及 Release 哈希。回退保留上一版 catalog、Hosting 配置及旧视频文件，不能先删除旧资源。iOS 当前已安装版本只提供文稿／音频，没有原生原视频播放器；本合同不把 bucket 视频 HTTP 验证宣称为 iOS 视频验收。要让 iOS App 内看原视频须另行开发并发布一次客户端更新。

旧 `sermon-multilingual-v3-stage-manifest-v1` 候选只需保留原始文件与审核证据，按实际选择的配置重新生成清单；组装器不自动迁移或替旧清单补齐文件。输出状态固定为 `validated_not_deployed`，不能直接作为上线收据。bucket 配置还须传 `--video-file`；入口如下：

```bash
.venv/bin/python scripts/assemble_multilingual_v3_update.py \
  --base-public artifacts/<已核对的完整正式站快照>/public \
  --stage-public artifacts/<本周已审公开资产>/public \
  --stage-manifest artifacts/<本周已审公开资产>/stage-manifest.json \
  --base-firebase-json artifacts/<已核对的完整正式站快照>/firebase.json \
  --video-file artifacts/<本周已审完整播放视频>.mp4 \
  --out artifacts/<本周-v3-候选>
```

上例用于 bucket 配置；旧 Hosting 视频配置不传 `--video-file` 和 `--base-firebase-json`。bucket 配置的候选同时输出带精确 302 与视频 CSP 的 `firebase.json`，但组装器不上传对象、不部署站点。发布后以如下命令单独取得视频的线上收据；它会完整读回一次 MP4 核对 SHA，并检查旧同源 URL 的 302、首尾 206／Range 和 CORS，因此会产生一次视频大小的下载流量：

```bash
.venv/bin/python scripts/verify_v3_bucket_video.py \
  --origin https://ai-for-god-sermon-audio.web.app \
  --catalog artifacts/<本周已发布候选>/public/multilingual-v3.json \
  --page-id <本周pageId> \
  --out artifacts/<本周视频HTTP收据>.json
```

组装后的本地候选可再独立运行只读检查，先固定当前干净代码 commit 和 `build-report.json` 的文件 SHA-256：

```bash
.venv/bin/python scripts/inspect_multilingual_v3_release.py \
  --candidate artifacts/<本周-v3-候选> \
  --baseline artifacts/<原始完整正式站快照>/public \
  --expected-commit <40位代码commit> \
  --expected-report-sha256 <build-report.json的64位文件SHA256> \
  --project ai-for-god-caption-dev \
  --site ai-for-god-sermon-audio \
  --video-file artifacts/<本周已审完整播放视频>.mp4
```

旧 Hosting 视频配置不传 `--video-file`。检查器重新读取所有候选和基线文件，核对 manifest、rollback catalog、旧页面/资产保留、新三语 package/sidecar 绑定、精确文件数量，以及 bucket 视频本地字节和候选 Hosting 目标；结束前再检查文件和代码身份。输出到 stdout，输入目录不变、无网络或部署动作。成功只标记 `local_snapshot_consistent_release_gates_pending` 且 `deploymentAllowed=false`，同时保留新增/替换/保留文件集合及上游 package hashes。

这个本地结果不能证明基线仍与线上一致，不独立验证上游人审收据，也不验证 Firebase alias 的当前映射或取得发布授权。当前没有部署器消费该结果来自动放行；线上基线 CAS、独立人审、精确发布批准、受保护代码晋升、site 串行锁、部署后 HTTP/Range、设备与现场门槛仍需分别完成。不要将旧 v2 部署 CLI 用于该 v3 候选。

| 阶段 | 必须保存的结果 |
| --- | --- |
| 构建 | 从冻结的 Layer 1–3 包与批准的系列／标题生成本周各语言 v2 Release、页面、全文、英文对照、字幕、完整播放视频、音频和定位 sidecar；按所选配置把视频放在 Hosting 或独立 bucket。每个公开资源有固定路径及 SHA；不公开含绝对路径的私有包。 |
| 合并 | 读取正式站完整基线与旧 v3 hash，追加本周 `pageId` 和 target，设置本周 `defaultPageId`；旧周、旧语言、legacy 功能及被引用资产逐一保留，覆盖／丢失即失败。 |
| 发布 | 先上传不可变资产与 Release，最后更新 `/multilingual-v3.json`；目录明确 `no-store`，记录新旧目录 hash 和可回退的旧版本。 |
| HTTP | 对 catalog、Release、页面、全文、英文对照、字幕、定位文件和音频逐项 GET／SHA；音频验证 206／Range。bucket 配置另验对象身份、视频首尾 Range 及同源 URL 的重定向和播放；确认三语和功能声明与真实资产相符。 |
| App | Firebase App 重新加载后，在 App 选页中打开本周每个已发布语言并试播；同一已安装 iOS 版本点击“刷新证道目录”后完成相同检查。记录构建版本、时间、所选 pageId／locale、结果；不得以独立 HTML 页、HTTP 收据或模拟器代替真机结论。 |

当用户正听旧周时，刷新只增加本周选项，不强制中断播放；本周仍须在选页入口容易找到。设备、现场和海报分别记录，不阻塞已通过的 HTTP 状态。

[可选 Agents API 全流程](agents-end-to-end-workflow.zh.md)可通过 `--release-workflow-config` 连接配音、同步、页面、发行准备、授权部署、HTTP 核验与登记；默认入口和现有定时任务未自动切换。海报继续由 Codex 按下述默认交付环节完成，端到端入口尚未自动调用 ImageGen。

## 新页面固定包含自动听音定位

`build_weekly_app.py --weekly-job <job目录> --out <新目录>` 在构建同步正式页面时，自动调用 `build_fingerprint_index.mjs`，无需另外手工生成索引或修改 `weekly.json`。同步试播仍使用 `--review-preview --sync-preview`，生成指纹不改变其待审状态。

1. 校验 job 中原始完整录制的路径与 SHA-256，以及操作员已确认的起止范围；不能用中文配音或裁剪后却未换算时间的原声替代。
2. Node.js 调用 FFmpeg 提取该范围，在本机计算频谱地标指纹；不调用语言模型、ASR 或 TTS。公开包只保存特征索引，不复制原声或麦克风录音。
3. 将索引绑定到来源 SHA、绝对证道窗口、页面 ID 和同步中文音轨 SHA，按索引内容哈希命名，写入 `weekly.json` 与构建文件清单。来源、范围或音轨变化须重新构建。
4. 发行校验检查新页面的定位要求、索引内容和哈希、同源 URL、浏览器运行文件、音轨时长与来源绑定；缺失或损坏时停止构建／发行。历史页保留原能力，不凭新规则宣称已经拥有指纹。
5. 用户在 HTTPS 页面主动启动听音并授权麦克风，设备采集约 10 秒，用本地 Worker 匹配同一录制。可靠且未过期的结果补偿等待时间，自动定位并播放中文音轨；浏览器阻止播放时保留手动按钮。无可靠匹配时不跳转，可重新采集或手动定位。

构建通过 `weekly_audio_fingerprint.py` 连接底层索引脚本。新页记录版本化 `automaticAudioAlignment`（`sermon-automatic-audio-alignment-v1`），构建报告保留 `automaticAudioAlignmentPages`，发行合并时继续保留这些要求；`ready` 仅表示可用索引已生成且绑定校验通过。

尚未生成同步音轨的 `--review-preview` 是自然语速试听候选，会明确记录定位不可用；它不能作为已经具备自动听音定位的新页面完成交付。完整同步页面缺少原声、依赖（Node.js / FFmpeg）或有效指纹时，构建直接失败，不静默跳过。构建和发布检查不等于真实手机麦克风或礼拜现场验收；用户许可、不同录制、变速和噪声等使用边界见[现场声音定位](sermon-app-field-alignment.zh.md)。

## 一次性建立发行清单

从当前线上对应的本地完整发行包开始。`build-report.json`、`public/` 文件和反馈目录均须通过现有契约与哈希检查。先验证线上内容，再登记已发布基线：

```bash
python3 experiments/sermon-dubbing-poc/verify_weekly_release.py \
  --release /absolute/path/to/current-release \
  --origin https://ai-for-god-sermon-audio.web.app \
  --out artifacts/weekly-release/current-http-verification.json

python3 experiments/sermon-dubbing-poc/weekly_release.py bootstrap \
  --registry artifacts/weekly-release/registry \
  --release /absolute/path/to/current-release \
  --origin https://ai-for-god-sermon-audio.web.app \
  --verification artifacts/weekly-release/current-http-verification.json
```

不传 verification 时，只登记为 `baseline_registered_local`，不能称为线上验证通过。重复 bootstrap 拒绝覆盖。清单及媒体保存在 ignored artifacts 中。

## 准备新一周

用已有 `build_weekly_app.py` 生成本周候选包，再合入登记过的内容：

```bash
python3 experiments/sermon-dubbing-poc/weekly_release.py prepare \
  --registry artifacts/weekly-release/registry \
  --candidate /absolute/path/to/new-week-candidate \
  --out artifacts/weekly-release/new-release
```

查看新包的 `release-plan.json`。它列出 added、updated、unchanged、removed，不允许删除历史页。已有页面内容发生变化时，必须在 prepare 命令中用 `--replace-page <page-id>` 明确选择，多个页面可重复传入；同源重建也遵守这一规则，防止候选包的历史占位页覆盖旧音频。替换后保留候选页的审核状态，不自动升级批准。

该命令复用登记版本的 UI、声音库、反馈开关与其他设置，保留旧哈希媒体地址，并为合并后的全部页重建反馈目录。候选包中附带的页面代码更新需走单独 UI 发布流程；候选声音库与登记版本不一致时拒绝合并，声音库变更须单独审阅发布。

**Production 站点已有 `multilingual-v2.json` 时，不直接部署这个 legacy-only 包。** 旧发行器不会把多语言目录和正式资源纳入它的严格清单；`deploy_firebase.py --execute` 会先读取 Production v2 catalog 并默认拒绝覆盖。将这份已准备的 legacy release 与当前已通过 Production HTTP 核验的完整多语言候选合成一个新候选：

```bash
.venv/bin/python scripts/refresh_multilingual_hosting_with_legacy.py \
  --base-candidate /absolute/path/to/current-production-multilingual-candidate \
  --legacy-release /absolute/path/to/prepared-legacy-release \
  --prior-http-verification /absolute/path/to/previous-production-http-verification.json \
  --out /absolute/path/to/next-production-hosting-candidate
```

组装器核对旧三语文件与 Firebase 配置哈希、新 legacy 包及其发行计划、旧周次全集、反馈配置和旧 UI；只更新 `weekly.json`，并加入新的哈希媒体与下载。新候选再按[分支与 Firebase 环境流程](development-branch-and-firebase-environments.zh.md#每周内容与代码发布顺序)执行 Production 预检、部署和 HTTP 核验，并向 `run_multilingual_cd.py` 传入同一个 `--legacy-release`。反馈开启时，统一入口先按既有 `deploy_feedback.py` 准备／部署新 API 目录，再部署 Hosting；其收据状态仍为 `deployed_verification_pending`，须独立核验 API，Hosting 的 HTTP 成功不能代替。明确回退到完整 legacy 快照时，原部署器才可使用 `--allow-multilingual-rollback`；该选项是有意移除三语目录，不用于普通周更。

输出目录必须是新目录，不能位于 registry 或 candidate 内。准备过程不推进 registry head。`build-report.json` 与发行计划绑定候选输入、上一版本及上一代 generation，避免并发候选覆盖较新的发行记录。

## 发布与核验

使用既有发布程序及对应站点的已有授权。若启用反馈功能，须按既有反馈部署流程同步新包中的 `feedback-catalog.json`。本模块不自动修改反馈服务、发布 Hosting 或授权消息推送。

发布后立即执行：

```bash
python3 experiments/sermon-dubbing-poc/verify_weekly_release.py \
  --release artifacts/weekly-release/new-release \
  --origin https://ai-for-god-sermon-audio.web.app \
  --out artifacts/weekly-release/new-http-verification.json

python3 experiments/sermon-dubbing-poc/weekly_release.py record-published \
  --registry artifacts/weekly-release/registry \
  --release artifacts/weekly-release/new-release \
  --verification artifacts/weekly-release/new-http-verification.json
```

核验覆盖全部公开文件的实际 GET、大小与 SHA-256，并对每个 MP3 检查 HTTP 206、Content-Range 和首段字节。完整读取可能产生站点流量费用。失败会写报告并返回非零状态，不得继续登记成功。核验器限制总下载字节、总时长和单次请求时长，并拒绝跨来源或降级跳转。

登记命令要求完整文件与 Range 检查均通过，且绑定本次 build-report、站点和当前 registry head。成功状态为 `published_http_verified`，不等于真机或现场验收。重复登记同一已验证版本保持幂等。

随后验证 App 刷新能列出新内容、来源与审核提示正确、下载及离线读取可用。新内容的现场同步另行验收；HTTP 报告始终明确标注客户端未测试，不能代替此步骤。

## 每周海报交付

新增海报采用用户已确认的 [格式规范 v1](tongxing-weekly-poster-format.zh.md)：2:3 竖版、App 系统字体、两个独立二维码和 App 原文免责声明。下面既有 CLI 示例保留历史单网页二维码流程；它们尚未实现新格式，不应把旧渲染器的单码校验当作新双码验收。

海报是每周内容发行后的默认交付环节，无需用户每周重复要求。先完成本周内容的发布与 HTTP 核验，再以对应本地发行包、明确的页面 ID 和站点 origin 制作；海报交付不自动向聊天群、邮件或其他渠道发送，也不自动上传到站点。

1. 从发行包 `public/weekly.json` 中精确选取 `page-id`，使用该页的中文主题、日期、经文与讲员。不得依据“最新一周”、文件夹名称或图像模型的自由生成文字猜测这些信息。保留该发行包及目录哈希、页面 ID、origin、主视觉文件和最终产物的绑定证据。
2. 由 Codex 使用内置 ImageGen 制作与主题相符的主视觉，预留文字和二维码区域；二维码使用真实编码器生成，不要求图像模型绘制。合成脚本只使用已有主视觉，不自动调用付费 API。生成失败或工具不可用时记录待完成，不伪称图像已生成。
3. 用本地脚本合成可分享海报；网页版二维码必须编码选定站点的精确 `?week=<page-id>` 地址；新格式另外加入固定正式 App Store 下载二维码。海报上的主题、日期、经文与讲员使用 catalog 数据，不能靠宣传措辞把候选页升级为正式发布、人工听审通过或现场同步已验收，也不得暗示教会官方背书。

不传 `--art` 时，只生成供 Codex 使用的 brief 和 prompt；据此使用内置 ImageGen 生成主视觉，不会由脚本自动调用图像 API。最终渲染必须绑定已通过的 HTTP 核验文件：用 `--verification` 显式指定，或使用发行包内默认的 `http-verification.json`。

```bash
# 准备 brief / prompt
python3 scripts/build_sermon_poster.py \
  --release artifacts/weekly-release/new-release \
  --page-id '<本周目录中的完整页面 ID>' \
  --verification /path/to/http-verification.json \
  --out artifacts/sermon-poster/YYYY-MM-DD/delivery \
  --origin https://ai-for-god-sermon-audio.web.app

# ImageGen 完成后，用实际主视觉及其生成提示词渲染
python3 scripts/build_sermon_poster.py \
  --release artifacts/weekly-release/new-release \
  --page-id '<本周目录中的完整页面 ID>' \
  --verification /path/to/http-verification.json \
  --art artifacts/sermon-poster/YYYY-MM-DD/main-art.png \
  --art-prompt /path/to/actual-imagegen-prompt.txt \
  --out artifacts/sermon-poster/YYYY-MM-DD/delivery \
  --origin https://ai-for-god-sermon-audio.web.app
```

本地合成需要 macOS 的 Swift 命令行工具（AppKit、CoreImage、Vision）；准备 brief 不调用图片模型。

产物为 `poster.png`、`poster-preview.png` 与 `poster-receipt.json`。`--art-prompt` 绑定实际用于生成该主视觉的提示词文件。

4. 独立解码最终 PNG 与分享缩略图中的二维码，二者必须与目标完整 URL 逐字一致；检查目标页仍可访问且显示正确周次。还须目视检查两种尺寸的中文、日期、经文、讲员、留白、裁切和二维码清晰度。只验证二维码源文件或仅看合成前主视觉不能代替最终产物验收。
5. Codex 完成两张图片的目视检查后，用完全相同的渲染参数追加 `--visual-reviewed`，把此次图片目视验收记入收据，保持 `humanApproval: false`；不能预先传该参数代替实际看图，也不修改音频人工听审状态。在任务中交付 `poster.png`、`poster-preview.png` 及 `poster-receipt.json`，保存本次输入绑定、二维码解码与目视 QA 结果。机器目视检查保持机器标记，不能记为人工批准；页面发布、音频听审、现场同步、海报 QA 和外部发送分别记录。用户未要求发送时，交付到当前任务即止。

### 多语言已发布页面海报

对于 v3 或 v4 目录中的多语言正式页面，使用 `scripts/build_multilingual_sermon_posters.py`，从同一发布目录中按 page ID 读取每个 locale 的已发布包和完整文稿，沿用发布包里的标题、系列、日期、讲员与经文。发布目录有 `multilingual-v4.json` 时读 v4；机器质检的语言把审核标签换成对应说明（例如“译文与配音经机器质检 · 未经人工审核”），并要求发布包带同语言的披露文案。中文、韩语和西班牙语各交付完整 PNG、分享预览及收据，复用同一 ImageGen 主视觉。该适配器不改变旧中文周次的海报路径。

网页版二维码固定指向原 App 根路径：`?week=<pageId>&contentLang=<zh-Hans|ko|es>&lang=<zh|ko|es>`。`contentLang` 选择文稿及音轨，`lang` 明确选择界面语言；两者独立。客户端允许有效 `lang` 参数优先于浏览器记住的语言，无有效参数时保持原有偏好。最终 PNG 与预览仍须独立解码，且浏览器核验正确周次、内容语言、界面语言和音轨。

既有 Supervisor 和发行 CLI 不会因这项流程约定自动调用 ImageGen 或发送海报。续跑时复用已验证主视觉和发行包；若页面或链接变化，重新绑定并核验最终图，保留旧版证据。

## 历史与恢复

`registry/releases/<release-id>/` 保留每版完整内容和媒体，`registry.json` 保留版本顺序。上一版本由 release-plan 的 `rollbackReleaseId` 指明。回退前应明确选择该快照，经已有发布入口重新部署并重新核验；本版没有自动回退或删除历史的命令。

准备失败只清理本次临时目录，不修改当前 head。并发期间 head 变化会使旧候选的登记失败；使用新 head 重新 prepare。核验旧收据不能代替实际发布后的新检查。

音频指纹索引现通过 `sermon-audio-fingerprint-binding-v1` 接入：只接收同源、哈希命名的 `/fingerprints/<sha16>-landmarks.json`，并核对源视频 SHA、页面、证道窗口、同步中文音轨 SHA 和数值特征结构；不发布原声或采集音频。历史页及指纹文件随发行快照保留，未绑定或损坏的索引会阻止发布。浏览器匹配使用同源 Worker；使用限制见 [现场声音定位](sermon-app-field-alignment.zh.md)。旧的 `track.alignment` 外部索引接口仍不支持。

## 验证命令

```bash
python3 -m unittest discover -s experiments/sermon-dubbing-poc -p 'test_weekly_release.py'
python3 -m unittest discover -s experiments/sermon-dubbing-poc -p 'test_verify_weekly_release.py'
python3 -m unittest discover -s experiments/sermon-dubbing-poc -p 'test_build_weekly_app.py'
```

前两组测试使用合成文件与可控 HTTP 响应，覆盖历史保留、来源冲突、哈希/路径、验证失败、并发登记与恢复。真实网络验证、App 验收及生产发布分别记录。

## Agents API 与费用边界

发行清单与 HTTP 核验仍是普通程序，本身不增加模型调用。2026-09-11 上游生产 Supervisor 已实现 Agents API 默认后端；当前调度默认模型为 Sol Medium，以最小状态白名单选择现有确定性生产工具，保持人工审批、租约及发布校验。具体切换状态见 [生产 runbook](codex-local-production-runbook.zh.md) 与 [Supervisor 设计](sermon-production-supervisor-agent.zh.md)。配音候选审核及本章的 Firebase 发行流程仍需各自的有效收据，不能用 Agent 会话完成代替。

此前在 Codex 对话中完成的上层处理，使用的是所选 Codex 登录/计费方式。脚本内部单独调用的转写、翻译等 API 仍有自己的费用。切换到 Agents API 后，上层 Agent 模型调用也按 API 计费，不能视为已经包含在 ChatGPT 订阅里。

费用口径为全部模型调用的输入、缓存、输出（含 reasoning）之和，再加实际使用的工具、沙箱与第三方服务。多轮工具结果、子 Agent 和重试都会贡献用量；任务不是按“每篇页面”固定收费。使用 `environment: none` 和本机函数可避免托管沙箱这一项，但模型 token 与底层生产成本仍存在。

以下是 2026-09-10 查得的 Astra 内容模型历史算例，不适用于当前 Sol Supervisor 计价：每百万 tokens 普通输入 $10、缓存读取 $1、缓存写入 $12.50、输出 $50。超过 272K 输入的单次请求有长上下文加价，其他运行模式也可能有不同价格。简单算例：累计 100K 普通输入与 10K 输出，在没有缓存写入、工具、沙箱和其他加价的条件下约 $1.50。这不是本项目每周实测费用或账单承诺。

Agents API turn usage 为 best-effort，可为 null，且不单列 cache-write count；费用报告必须保留 unknown 并与 Platform 账单核对，不能把未知记为零。实测会话既出现已知 token 计数，也出现 null；最终费用须对账。

来源：[Agents API 计费](https://developers.openai.com/api/docs/guides/agents-api/overview)、[用量口径与限制](https://developers.openai.com/api/docs/guides/agents-api/observability)、[Astra 价格](https://developers.openai.com/api/docs/models/gpt-6-astra)、[Codex 计费](https://learn.chatgpt.com/docs/pricing)。

### 单中文周次（v4 stage manifest）

用户明确只发布中文时，可使用 `sermon-multilingual-v3-stage-manifest-v4`：`single_zh_bucket_video_v1` 包含 8 个新增 Hosting 资产、1 个 catalog 更新及 1 个不可变视频对象；`single_zh_full_video_v1` 包含 9 个新增 Hosting 资产及 1 个 catalog 更新。同语言候选和正式音频包仍须人审，全文、字幕、音轨、Release、听音定位指纹、英文对照与对齐索引均须精确绑定。完整正式站基线合并保留旧周和旧语言，不将单中文 manifest 用于三语周次。旧 manifest 不原地迁移；从已有已审包重新生成 v4 清单。

`build_full_video_app_release.py prepare --locales zh-Hans` 支持单中文准备；`--source-date-label` 可使用中性的日期标题，不替尚未核实的篇名和讲员生成批准。`verify` 与 `seal` 按准备包的实际语言数量验证，设备和现场验收继续保持独立字段。`assemble_multilingual_v3_update.py` 消费 v4 清单并核验所有新增资产及历史字节保留；后续仍需实际部署与 HTTP/Range 回读。

单周播放片段与母版原声指纹使用不同的时间原点时，全文可附加版本化 `sourceWindow`（`schemaVersion=sermon-original-recording-window-v1`、母版 `mediaSha256`、批准的 `startSeconds/endSeconds`）。构建器将它与源包窗口逐项比较；Web App 将它保存为 `sourceFingerprintWindow`，仅用于指纹来源绑定，播放与字幕仍从片段零点开始。历史内容未带此块时保持原有零点校验。页面元数据暂未确认时，日期标签使用明确的待补充说明，以兼容已有客户端必填字段，不猜测讲员或篇名。
