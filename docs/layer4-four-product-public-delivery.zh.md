# Layer 4 四产物公开交付 v3

本适配器消费已经批准的译文、音频、大纲与默想；不生成文本，不调用模型，不替代人工审核。

## 输入与公开输出

`sermon_unified_delivery` 输入仍使用 `sermon-unified-delivery-v1` 配置。每种语言的 outline、meditation 必须是 `sermon-study-artifact-v1`，各自有绑定该 artifact/source/text/page/locale 的 `sermon-study-review-v1` 批准。source unit IDs 必须属于当前全文候选。

启用 `require_study` 的 builder 输出新的 [release v3 schema](../schemas/sermon-target-language-release-package-v3.schema.json)。继续使用 `/releases-v2/{pageId}/{locale}.json` URL 和 catalog-v3；目录名是兼容路由，不是 schema 版本。每个 v3 release 恰好包含七种公开资源：

| role | URL |
|---|---|
| page | `/pages/{pageId}/{locale}/index.html` |
| content | `/content/{pageId}/{locale}.json` |
| audio | `/media/{pageId}/{locale}.mp3` |
| captions | `/captions/{pageId}/{locale}.json` |
| outline | `/study/{pageId}/{locale}/outline.json` |
| meditation | `/study/{pageId}/{locale}/meditation.json` |
| product_manifest | `/study/{pageId}/{locale}/products.json` |

outline/meditation 是完整原学习产物的 JSON。products 使用 [公开产物 manifest schema](../schemas/sermon-public-app-products-v1.schema.json)：`schemaVersion=sermon-public-app-products-v1`、`pageId`、`locale`、`sourceIdentity`、`fourProducts`。公开资源不包含私有审核人、审核说明或本地路径；公开 review hash 仍绑定私有批准收据。

`sourceIdentity` 包含原 sourceId、完整 URL SHA-256、media SHA-256、媒体时长及批准窗口起止秒数和原窗口 receipt bytes SHA-256。`inspect()` 同时返回 `pageId`、`sourceIdentity`、`sourcePackageSha256`、`sourceUrlHash` 与原 `approvedWindow`，供 owner 与当前 manifest 比较，不允许凭相同视频 ID 代替当前窗口或页面身份。

`fourProducts` 包含 sourcePackageSha256、textCandidateSha256、audioPackageSha256、outlineArtifactSha256、meditationArtifactSha256、outlineReviewSha256、meditationReviewSha256、metadataApprovalSha256、contentSha256、candidateSha256。artifact/review/package hash 是 UTF-8、sorted-key、compact、非 ASCII 转义的 canonical JSON SHA-256；content hash 和 assets hash 是原文件 bytes SHA-256。

候选 hash 沿用现有 App join：先计算

```text
join = sha({source: sourcePackageSha256, products: {
  text: textCandidateSha256, audio: audioPackageSha256,
  outline: {status: "human_reviewed", artifactSha256: outlineArtifactSha256, reviewSha256: outlineReviewSha256},
  meditation: {status: "human_reviewed", artifactSha256: meditationArtifactSha256, reviewSha256: meditationReviewSha256}
}})
candidateSha256 = sha({products: join, metadataApproval: metadataApprovalSha256, contentSha256})
```

PDF 不进入该身份。静态 HTML 包含 `study-outline` 和 `study-meditation` 两个 section，每条标题和完整正文进行 HTML 转义。Web App 从独立资源校验 hash 与身份后加载全文学习内容，独立大纲替换旧 metadata outline。正文保留换行，使用 textContent 渲染；切换 UI 语言不会改写已批准学习文本。

## 机器质检发布（release v4 / catalog v4）

完整文稿、口播稿或音轨中有任何一项用[机器质检豁免](machine-quality-waiver.zh.md)代替人工收据时，builder 输出 [release v4](../schemas/sermon-target-language-release-package-v4.schema.json)，URL 改为 `/releases-v4/{pageId}/{locale}.json`。v4 与 v3 的七种资源、`sourceIdentity`、`fourProducts` 相同，另加：

- `contentStatus`、`audioStatus`：各为 `human_reviewed` 或 `machine_checked`，至少一项为 `machine_checked`。完整文稿用豁免时 `contentStatus=machine_checked`；口播稿和音轨都是人工收据时 `audioStatus` 才是 `human_reviewed`。
- `reviewBasis`：`fullText`、`spokenText`、`audio` 各记 `kind`（`human_review` 或 `machine_quality_waiver`）和收据的 canonical SHA-256。
- `disclosure`：`{locale, text, english}`，`locale` 必须等于 `targetLocale`。

`contentStatus=machine_checked` 时正文必须是 [content v3](../schemas/sermon-full-video-text-content-v3.schema.json)：`status=machine_checked`、`reviewMode=formal`，`disclosure` 与 release 相同；人工文稿不得带 `disclosure`。content v3 只能随 release v4 发布：三项都是人工审核时（写 release v3）必须用 content v2，因为网页和 iOS 只通过 release v4 读取 content v3。大纲与默想在这一步仍要求人工批准。

封存总是写出 [catalog v4](../schemas/sermon-multilingual-catalog-v4.schema.json)（`/multilingual-v4.json`）和 `/multilingual-v3.json`，报告记录两者的 SHA（`catalogV4Sha256`）。v4 的机器质检 target 必须指向 `/releases-v4/`，并具备 text、captions、audio；人工 target 与 v3 相同。v3 由 `project_human_catalog` 从 v4 去掉机器质检 target 得到：没有剩余 target 的页面被删除，被删的默认语言或默认页改为剩余项。基线只有 v3 时按 v4 升级后合并；只有机器质检页面而没有人工页面时拒绝封存。

读取方先请求 v4；404 时按原来方式读 v3，v4 读取或校验失败时也退回 v3 并记录错误。机器质检语言显示“机器质检”标签和 `disclosure.text`，不显示人工批准文案。`machine_reviewed` 仍只供 Dev 预览。

### 跨来源单页（catalog v5）

同一篇讲道若因语言制作历史不同而必须使用不同的已冻结视频来源，不能把其中一个来源写成整页的共同身份。[catalog v5](../schemas/sermon-multilingual-catalog-v5.schema.json) 用 `sourceMode=per_target` 把页面限定为共享的 family／周次／标题入口，并要求每个 locale target 独立声明 `editionId`、`sourceIdentitySha256`、`sourceMediaSha256` 与 `videoDelivery`。Release、content、指纹、对齐、英文对照和缓存都按该 target 的 edition/source 校验；family `page.id` 用于选页、历史记录和 announcement 路由。海报二维码编码 target `editionId` 作为兼容深链：v5 reader 把 edition 映射回 family，v4 fallback／旧客户端则直接打开真实 edition。切换到不同 edition 时播放器不得继承旧视频位置。

v5 同时投影出诚实的 v4/v3 兼容目录：v4 按 edition 拆成独立页面，v3 仍是 v4 的 human-only 投影。旧客户端因此可能看到两个来源版本；支持 v5 的 Web/iOS 只显示一个 family 页面。single-source 页面可无损升级为 v5 `single_source`，但只有发布计划一次性覆盖原页面全部 targets、每个旧 locale 的来源字段不变且被吸收的独立 edition target 逐字段一致时，才允许晋升为 `per_target`。发布前后 CAS 和 readback 必须同时核对 v5、v4、v3；不得只写 v5 或改写任一旧 release/content 哈希。

附加资源工具在站点带 v4 时读 v4，否则照旧只读 v3，人工周次的输出逐字节不变。读 v4 前都先核对 v3 正是 v4 的人工投影，不一致就拒绝。[英文对照](../packages/production/src/tongxing_production/delivery/published_english_reference.py)和定位补充资产（`experiments/sermon-dubbing-poc/bind_published_fingerprints.mjs`）也覆盖机器质检语言；英文对照的 `reviewState=human_approved` 只表示英文来源经人工批准，各语言译文仍以自己的 release 和正文状态为准。[对齐绑定](../packages/production/src/tongxing_production/delivery/published_alignment_catalog.py)把绑定写进 v4，再把 v3 重写为新 v4 的人工投影，先写 v3、后写 v4，每份都原子替换；中断后重跑仍可接受。目录状态只从 release 原样核对，从不提升。配音不在原视频时钟上（`audioDurationSeconds` 与 `durationSeconds` 相差 0.1 秒及以上，例如精简口播）的语言不能做声纹定位，绑定会拒绝。绑定会改变两份目录的 SHA，之后发布要以绑定后的候选为准。[听审统计来源目录](../tools/ops/build_language_listening_catalog.py)已按 #260 读取 v4。[旧版 v3 周更组装](../packages/production/src/tongxing_production/adapters/legacy/assemble_multilingual_v3_update.py)只会写 v3，基线带 v4 时仍会拒绝。

## 封存、发布与端点

准备验证会同时检查私有批准、公开 bytes、候选 hash 与静态 HTML 完整显示。除逐语言七种资源外，准备 manifest 的 `runtimeAssets` 冻结并公开发布 reader 的**完整外壳闭包**（`runtime_web_files()`：`index.html`、它引用的样式、主题脚本、图标与品牌图、离线 service worker、声纹 worker／worklet，以及从 app.mjs、published-weeks.mjs、content-locales.mjs 出发的全部 ES 模块；`/weekly.json` 这类数据文件不算外壳），避免与旧 Web baseline 合并时留下旧的 `index.html` 或不支持 v3 的 reader（2026-10-11 线上故障的原因）。这些文件进入 input snapshot、HTTP 清单和 sealed snapshot；`verify`／`seal` 还会逐个核对它们与当前代码库 `apps/listening-web` 同哈希，web 改动之后必须重新 prepare。HTTP 准备 receipt 必须恰好覆盖全部逐语言资源与共享 runtime。封存清单与 live HTTP 验证包含学习资源及产品 manifest。原有多语言 overlay、baseline 和未知发布 lease 规则不变。

发布入口的另外三道门（2026-10-11 复盘 `DEV-R242-029`）：

1. **线上基线必须当场取。** prepare 之前用 `tools/ops/prepare_dev_simulated_publication.py baseline --environment production --out <新目录>`（可带 `--cache-public`／`--cache-receipt` 复用上周已核验的字节）从 Hosting API 取当前 live 版本的文件清单并逐文件按 gzip 哈希核对，写出 `baseline-receipt.json` 与 `seal-report.json`。本地留存的旧基线不能当 live 基线：2026-10-11 本地快照比线上少 13 个文件，发布后外壳不完整。
2. **发布后浏览器冒烟。** 发 Dev 和发生产之后各跑一次 `tools/ops/smoke_published_page.py --origin <站点> --page-id <pageId> --out <报告>`（需要本机 Chrome 和 Node）：`scripts/smoke_browser_cdp.mjs` 通过 Chrome 调试协议打开三语 `/?week=<pageId>&contentLang=<locale>`，只观察、不自己发请求。每个语言都要与该语言的发布包对上：URL 保留请求的周和语言，内容语言选择器显示该语言，`<audio>` 地址是该发布包的音频，标题以该语言正文标题开头，当前字幕和全文来自该语言的 cue；不能有 `console.error`、未捕获异常，也不能有外壳文件或本发布包资产加载失败；页面自己发出的 `/api/session` 请求全部返回 200，且每个请求带的周、音轨 ID 和音频哈希只能是该发布包的音轨或阅读器的使用统计锚点（默认页默认语言的音轨），并至少有一个是该发布包的音轨，免得反馈和收听统计记到别的音轨上；超过截止时间即失败。其他可选资源（例如别的页面的定位索引）加载失败只记为警告并列出。页面打开时本来就会建匿名会话，冒烟不额外建；报告只是浏览器渲染证据，不是设备或现场验收。
3. **反馈目录随周发布同步。** 新页面的音轨必须进入反馈 API 的来源目录，否则该页的赞踩、逐句反馈和收听统计全部返回 400 `unknown_source`（2026-10-02 至 10-11 三周 9 条音轨曾如此）。来源目录用现有的 `tools/ops/build_language_listening_catalog.py --public <与线上一致的站点快照> --previous-catalog <线上函数当前的 catalog.json> --legacy-locale zh-Hans --out <新 catalog.json>` 生成：它保留全部旧来源（已有来源的任何变化都会报错），逐个核验已发布的音频、字幕、正文和 release 哈希，为每个带音轨的语言加上 `pageId`／`audioLocale`，时长取客户端上报的配音时钟。运行时代码和 `server-config.json` 取自线上函数当前的源码包（位置见 `gcloud functions describe sermon-feedback-api`），只替换 `catalog.json`，再按线上相同的参数 `gcloud functions deploy`；这是对外动作，需授权。回退就是用原源码包按同样参数重新部署。部署后用浏览器冒烟确认三语 `/api/session` 返回 200。

封存站点带 v4 时（四层封存总会写出 v4），即使本次全是人工审核的语言，端点回读也必须包含 `/multilingual-v4.json`，因为当前网页和 iOS 先读 v4；只回读 v3 不能证明当前客户端的路径；托管发布部署前比较线上 v4 与基线，部署后回读 v4 与封存 SHA。新版本经 CDN 传播需要片刻：部署后的版本、v3／v4 回读、对账时的目录回读，以及刷新基线时逐文件的 GET，都在 `guarded_hosting_publish.PROPAGATION_TIMEOUT_SECONDS`（默认 120 秒，每 5 秒一次）内重复只读检查，到期仍不一致才判为不一致或结果未知；不重复部署。每个 read 传入当前剩余 timeout，完成时再核对统一 deadline，过期成功不接纳；HTTP 断流（含 IncompleteRead）只重读。发布从本次 `firebase deploy --json` 的 `status=success/result.hosting` 单站点版本回执固定 `newVersion`，保存为 `hosting-deploy-result.json`，在任何线上回读前写入 attempt；缺失、无效或多站点回执保持 unknown，不能用首次观测到的非基线版本代替本次部署身份。注入的 subprocess runner 也须向提供的 stdout 写同形 JSON。目录读取前后及后续重试必须仍为回执版本；其他发布者换版本时保留 unknown 收据与 lease，不把无关版本记为本 attempt 成功。新 attempt 同时保存版本化 `versionPropagation`，绑定 attempt、基线、CLI 回执哈希和 ownedVersion；仅明确 `ownedVersionObserved=false` 时，发布或对账可在同一传播 deadline 内等待 live 从基线切换。首次观测本次版本后先持久化 true，再读目录；崩溃后对账仍拒绝退回基线或第三方版本。缺该状态的旧 attempt 继续严格确认，不推测尚未观测，也不改写旧收据升级等待权限。到期不一致保留 unknown 和 lease，不重部署。对账也须匹配该已记录版本；旧 unknown attempt 没有版本回执时仍需显式确认版本，不能自动认领。四产物端点使用 [client readback v2](../schemas/sermon-client-readback-v2.schema.json)，必须包含当前 catalog、release 及所有七种资源的 URL/bytes hash。Web 的 dev / production_web 端点还必须回读上述三份 reader runtime（role=reader_runtime）。每个 locale 的播放 telemetry 另需：

```json
{"studyArtifacts":{"outline":"<canonical artifact SHA-256>","meditation":"<canonical artifact SHA-256>"},"studyDisplayed":true}
```

逐语言人工验收行的 `checks` 另含 `outline: pass` 和 `meditation: pass`。缺任一资源、任何语言的当前学习展示或原有播放/字幕证据，不能把该端点提升为通过。HTTP、设备和现场验收仍分别记录；测试用 synthetic receipt 不证明真实设备/生产验收。

## 旧版本迁移

- 旧版（legacy）工具保留其文档化范围，不能替代本路径；纯文字语言经 `audio_unavailable` 发布，仅当发布计划、producer 与客户端都支持。
- 没有 require_study 的旧 builder 路径继续产生 release v2；旧 snapshot、catalog-v3、Web v2 页面继续可读。
- v2 没有独立学习资源，不授予四产物资格，不能将旧 content.outline 当成 v3 的独立 outline。
- 将旧页面升级到 v3，必须提供同一 source/text 身份下的新独立学习产物和两份人审 receipt，重新 prepare、HTTP 验证、seal，并取得绑定新候选的发布授权。不能原地改旧 release schemaVersion。
- 仅新增 v3 资源时，旧客户端可能拒绝未知 release schema；必须更新客户端解析与显示能力后再实施相应发布。代码测试不等于该更新已部署。
