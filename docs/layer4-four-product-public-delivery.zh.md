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

## 封存、发布与端点

准备验证会同时检查私有批准、公开 bytes、候选 hash 与静态 HTML 完整显示。除逐语言七种资源外，准备 manifest 的 `runtimeAssets` 冻结并公开发布 app.mjs、published-weeks.mjs、content-locales.mjs，避免与旧 Web baseline 合并时留下不支持 v3 的 reader。这三份模块进入 input snapshot、HTTP 清单和 sealed snapshot。HTTP 准备 receipt 必须恰好覆盖全部逐语言资源与共享 runtime。封存清单与 live HTTP 验证包含学习资源及产品 manifest。原有多语言 overlay、baseline 和未知发布 lease 规则不变。

四产物端点使用 [client readback v2](../schemas/sermon-client-readback-v2.schema.json)，必须包含当前 catalog、release 及所有七种资源的 URL/bytes hash。Web 的 dev / production_web 端点还必须回读上述三份 reader runtime（role=reader_runtime）。每个 locale 的播放 telemetry 另需：

```json
{"studyArtifacts":{"outline":"<canonical artifact SHA-256>","meditation":"<canonical artifact SHA-256>"},"studyDisplayed":true}
```

逐语言人工验收行的 `checks` 另含 `outline: pass` 和 `meditation: pass`。缺任一资源、任何语言的当前学习展示或原有播放/字幕证据，不能把该端点提升为通过。HTTP、设备和现场验收仍分别记录；测试用 synthetic receipt 不证明真实设备/生产验收。

## 旧版本迁移

- 没有 require_study 的旧 builder 路径继续产生 release v2；旧 snapshot、catalog-v3、Web v2 页面继续可读。
- v2 没有独立学习资源，不授予四产物资格，不能将旧 content.outline 当成 v3 的独立 outline。
- 将旧页面升级到 v3，必须提供同一 source/text 身份下的新独立学习产物和两份人审 receipt，重新 prepare、HTTP 验证、seal，并取得绑定新候选的发布授权。不能原地改旧 release schemaVersion。
- 仅新增 v3 资源时，旧客户端可能拒绝未知 release schema；必须更新客户端解析与显示能力后再实施相应发布。代码测试不等于该更新已部署。
