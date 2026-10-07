# 9/27 与 10/4：交付、人审、HTTP 与浏览器对照

只读现存收据与已有审计；时间统一为 America/Los_Angeles（PDT，UTC−7）。没有重跑线上请求、模型、部署或设备。这里只衡量交付结果，不推断缺失的整周开跑时间。

## 实际时序与截止前状态

| 环节 | 9/27 证据 | 10/4 证据 | 判断 |
|---|---|---|---|
| 提前交付文字 | release-plan-draft.createdAt 9/26 周六22:28:35 已记原视频+三语文字 published_http_verified；独立text-only收据支持该状态 | 本周中文先交，其他语言后续；本审计未取得同口径的“周六三语文字已公开”证据 | 上周已经支持拆阶段交付，不是本周首次实现 |
| 三语音频人审决定 | 9/27 周日06:12:18 | 中文08:24:33；韩/西11:00:39 | 本周韩西批准已在10:00之后；不是机器产物时间，也不是完整聆听耗时 |
| 三语网页 HTTP/播放 | 06:25:02 HTTP 98/98；06:26:21 三语播放选择与字幕可见全部true；07:55:02 App v3主目录三语published_http_verified | 中文09:28:45正式HTTP；09:41:46收据记录Prod/Dev中文片段实际播放；KO/ES原始资产HTTP约11:12；11:22:23三语媒体就绪，playbackTest=not_run | 按10:00界线，上周三语Web有直接已交付证据；本周只中文在界线前可证。不能把11:12资产时间当最终catalog上线时间 |
| 最后元数据修正 | 9/27 18:06:51才将目录标题从“耶稣配得”补为“启示录：耶稣带来的安慰与盼望 · 耶稣配得” | 初次日期占位，之后补真实标题/系列/讲员/经文 | 上周也有截止后补修；不能说上周所有质量问题10点前全闭合 |

上周音频批准→三语HTTP约12分45秒，→浏览器收据约14分03秒；这些仅是批准后的两个事件间隔。源取得/真实开跑时间不足，不能据此写“上周总制作耗时15小时”，也不能把本周与上周不同范围时间直接算提速百分比。

## 进步、未改善与退步

### 可以确认的进步

- 本周最终封装与身份核验更细：六份初始全文/口语批准链6/6，五份ready hash span，三份口语原生调用链3/3；最终Prod/Dev各15个记录文件30/30 SHA一致，6/6 Range206，KO/ES四份release→原始HTTP→16个资产身份匹配。上周已有HTTP98/98，不能仅凭本周数量更多/更少判强弱；进步在本周已明确核对的封装绑定和环境覆盖。
- 本周代码新增任意受支持locale子集、精确同步未验收例外、真实原录制sourceWindow与clip时间分离，以及动态页面时长。属于范围/契约能力增加；不等于最终视频同步质量改善或端到端提速。
- 本周明确保留videoSync1x=not_run并绑定用户发布例外，状态表达更精确；这个透明度改进不应被包装成同步已完成。

### 未改善／反复发生

- **元数据仍在交付后修。** 上周三语正式metadata在周六22:26已批准，却到周日18:06才把系列名加入目录标题；本周先发布日期占位再修真实信息。是同类“批准内容未完整进入首版显示”的交付问题反复，不是同一个字串补丁回滚。
- **交付仍依赖多步桥接和补丁。** 上周phase1–10后续逐步完成首页/选择/双稿/英语/对齐/目录/标题；本周七份ignored run-bound桥接及三次交付代码修补。说明下游预检、参数化命令与完整消费者路径尚未一次打通。
- **真实设备与现场仍缺。** 上周phase9和浏览器均device/venue not_run，本周最终收据同样not_run；模拟器/原生reader不是实体设备验收。
- **统一时序仍缺。** 9/29效率报告已指出9/27检查点缺执行span，本周控制收据15/56有时间、HTTP5/27有时间；四份复制旧部署收据、六份旧final-http身份过期。当前不能从文件名或mtime算整条关键路径。
- **Dev可见性是本周具体漏项，但不能确称上周同故障重犯。** 本周visibility-status直写“Beta读Dev而Dev缺Oct4”，随后补Dev并保留359项。上周已有App v3/三语HTTP与原生decode，9/29报告也要求Web/iOS刷新；本次证据未找到上周同一Beta/Dev漏发布及修复时间。因此可说既有跨端发布门禁仍未固化，不说已证实同一Dev bug复发。
- **时间线绑定要分病因。** 上周sourceWindow从0到31:31，本周源片段来自完整录制非零offset。上周正确的0起点不能证明早已解决本周的非零offset序列化；本周复用31:31硬编码则确为跨周模板泛化不足。

### 结果层面的退步／证据变弱

- 10:00前的三语公开交付：上周06:26已有三语Web播放收据，本周KO/ES批准11:00后、资产HTTP11:12，交付更晚。这个结论不依赖猜测开跑时间。
- 视频同步验收：上周三语v2人审均记录videoSync1x=approved、synchronization=approved；本周三语videoSync1x=not_run并走发布例外。能说本周完成的验收范围收窄，不能仅凭收据断言音质更差。
- 最后三语浏览器播放证据：上周有三语选中播放、字幕可见和随后paused=false/time>0；本周最后11:22收据只有readyState4/error null，playbackTest=not_run。中文较早有真实片段播放，不补足最终韩/西播放证据。
- 发布可追溯性局部退步：上周phase10明确liveBaseVersion/newLiveVersion/publishedAt/httpCatalogSha；本周抽样11份deployment receipt都没有部署版本且发生旧收据复制。范围不同，只能称本周这些收据未保住上周已经出现的版本/时间信息，不能推断所有外部日志都缺失。

## 直接证据与 SHA-256

以下路径均为仓库相对路径；SHA来自当前本地字节。上周浏览器收据中的httpVerificationSha256应与同目录HTTP原始文件匹配。

| 路径 | SHA-256 |
|---|---|
| `artifacts/drive-source-20260926-1730/release-plan-draft.json` | `7d1617731fc499b6c28a2f989b95f55f2fc15acd433be6bf276a9b4e10a79087` |
| `artifacts/drive-source-20260926-1730/text-only-publication-receipt.json` | `df2c399fd016fad021993ccee704edd6d69d65fe147e61118568ac665609da8d` |
| `artifacts/drive-source-20260926-1730/formal-page-metadata.approved.json` | `41a7d80211cec5905a7f566c90944c75b8b107195f62f6f2e3dd825dbd8c2eca` |
| `artifacts/drive-source-20260926-1730/three-locale-audio-user-approval-20260927-1312.json` | `f5720b2034ef57840f374d270878ce9de4c799c1ff036f9545132e7a805a752d` |
| `artifacts/drive-source-20260926-1730/full-video-audio-publish-20260927-v3/http-verification.json` | `ca9c1d48857c39be3e05f2ccd972c64492966a474d6395add155997db12d8722` |
| `artifacts/drive-source-20260926-1730/full-video-audio-publish-20260927-v3/browser-verification.json` | `4610b8719586f531ca4bd7312e7588d771c5e2ac20afde75c18f4d9c90cdf1e5` |
| `artifacts/drive-source-20260926-1730/layer4-app-hosting-phase9-ios-alignment-20260927-v1/phase9-http-receipt.json` | `8945f521baa29f5539896d32974639f0bb4e6978c8976cf83ad1e944d7b87d58` |
| `artifacts/drive-source-20260926-1730/layer4-app-hosting-phase9-ios-alignment-20260927-v1/browser-playback.json` | `ccd196e4d95289f9b52ae1d42b82e41dfdc61cd284ad94b2d33e54c801cbe786` |
| `artifacts/drive-source-20260926-1730/layer4-app-hosting-phase10-series-title-20260927-v1/title-correction-receipt.json` | `1ca17decd1f832aa780485e2a0227cf4df472b92b96364c92dcafffb32aa165a` |
| `artifacts/post-live-runs/2026-10-04/resi-69ba7a66/ios-visibility-check-v1/visibility-status-v1.json` | `c94d2f9e3af0d7f84936adcfd55b46eb4a2b1caa110791c848ae036ebc3268a1` |
| `artifacts/post-live-runs/2026-10-04/resi-69ba7a66/metadata-title-fix-v1/prod/metadata-revision-receipt.json` | `25f4d7f1812a058867f28d27ad11d8f0aab24aba28970e48d4475a498a4805d8` |
| `artifacts/post-live-runs/2026-10-04/resi-69ba7a66/full-retrospective-v1/handoffs-release/findings.md` | `3208a2b67c1c357adc6300ff9617345f9c8c403953cff5128517977658af5183` |
| `artifacts/post-live-runs/2026-10-04/resi-69ba7a66/full-retrospective-v1/handoffs-release/metrics.json` | `42fbd476de49eb1fb3d47aa6cf8bcf54addbf37a8028ae06ba19aa52a291615b` |
| `artifacts/post-live-runs/2026-10-04/resi-69ba7a66/runtime-evolution-audit-v1/delivery.md` | `fc73010bddc277a8931cc9e92e75e0da10729c7f10891d04d0046ac93fa9bad0` |
| `docs/reports/20260929-weekly-workflow-efficiency-findings.zh.md` | `8bf4f70867af9b5c50516a6fa7b10cf58d61b34d3f75f420c28203c4ce8c3a27` |
| `docs/reports/20260929-dev-release-backlog-audit.zh.md` | `3aadab0cf50226da057243dafd4f061e6f94eefd75e2acfc99406ae0290eec5d` |
| `artifacts/drive-source-20260926-1730/layer3-analysis/spoken-script-drafts/es/formal-revision/formal-audio-v6/human-reviewed-20260927-1312/audio-human-review-receipt.json` | `0e6985754af8cc97ceaea2a90e35f01afee2a114d6dd478e48eb040313be04f0` |
| `artifacts/drive-source-20260926-1730/layer3-analysis/spoken-script-drafts/ko/formal-audio-20260927-1100/human-reviewed-20260927-1312/audio-human-review-receipt.json` | `c01ff1b5de93a3ea4249b73ea051cae5f7484ce9b7e0af6c6618e4cc04407cb2` |
| `artifacts/drive-source-20260926-1730/layer3-analysis/spoken-script-drafts/zh-Hans/formal-audio-20260927-1100/human-reviewed-20260927-1312/audio-human-review-receipt.json` | `6edba6b38569553306eae3b46b64ef4a354238dff3347f0c9db21df5b1357544` |
