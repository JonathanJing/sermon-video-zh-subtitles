# 固定三分钟页面生成与双端发布测试

日期：2026-10-04（美国太平洋时间；发布回执为 2026-10-05 UTC）。

本轮结果：三语言页面、资源与目录已真实发布，HTTP 校验通过；Web 与 Beta 原生读取均失败，因此不能认定为双端播放验收通过。用户授权仅在测试环境使用明确标记的模拟审核收据，收据不代表正式内容批准。

## 基线与范围

- PR #242 已合并；工作从最新 `origin/dev` 的 `5a67c81d7acc88bb540ae9d9f0d2db61567525fb` 开始，分支为 `codex/dev-180s-page-test-20261004`。
- 固定复用 `artifacts/dev-full-rerun-20261001` 的片段：原时间窗口 60–240 秒，裁切文件实测 180.013167 秒，SHA-256 为 `79bada8f2e960adb470a146f183449db433308b53c20d03ea9c7e2e0a66e906b`。源内坐标从 0 开始；未重新确定完整讲道边界。
- 英文 39 个单元；中文、韩文、西班牙文各 13 组。音轨实测分别为 191.6、215.2、194.08 秒；四个媒体文件均经 ffprobe 与完整音频解码检查。
- 新增付费模型 API 调用为 0；复用历史译文、对齐与音轨。大纲与默想使用明确标记的结构测试内容，未执行真实模型生成、翻译审核或新 TTS。原来源 URL 未核验，模拟 source 明确使用 `.invalid` 地址；不将其作为正式来源证据。
- 固定 pageId：`mockup-20261005-dev-180s`。页面及三语言 target 均有 `simulationOnly`、`diagnosticOnly` 标记，默认生产 reader 排除它。
- Beta 原生配置与 Dev 网页使用同一 Firebase Dev origin：`https://ai-for-god-sermon-audio-dev.web.app`。本轮发布的是 Beta/Dev 内容入口；没有上传新 TestFlight 二进制，也没有操作生产 Hosting。

## 实际执行与证据

所有运行产物位于未入 Git 的 `artifacts/dev-180s-page-test-20261004/`。

| 环节 | 结果 | 证据路径（相对产物根） |
|---|---|---|
| 新 CLI media plan、submit、后台执行与媒体解码 | 通过 | `preflight-2/summary.json` |
| 未批准源与 fixture delivery 准入负例 | 按预期拒绝 | `preflight-2/` 下 JSON 回执 |
| 模拟输入、冻结与正常 Layer 4 prepare | 通过；非正式内容 | `simulated-inputs/simulation-scope-report.json`、`prepare-result.json` |
| 资产先行发布 | 真实部署至 `c92386b7e453742c` | `publication/asset-first/deployment-attempt-v2.json` |
| 三语言目录封存与发布 | 真实部署至 `77f78c8a2a27b6d8` | `publication/final/deployment-attempt-v2.json` |
| 完整发布快照 HTTP 校验 | 405 文件通过 | `publication/final/publication-http-v2.json` |
| 网页依赖修复发布 | 真实部署至 `36fbf0ccbb987fb4` | `publication/runtime-repair/deployment-attempt-v2.json` |
| 最终 24 模块与目录 HTTPS 字节校验 | 25 文件通过 | `publication/runtime-repair/runtime-http-verification.json` |
| Web 实际网络 reader | 三语言均拒绝字幕；测试页不进入选择器 | `web-live-readback.json` |
| 当前 Beta 原生 repository 实际 HTTPS 读取 | 资源校验通过，三语言 transcriptLoad 均失败 | `native/dev-live-readback.json` |

每次部署使用正常 guarded publisher、远程 lease、基线与回执。原目录 3 个页面逐项保留，默认页仍为 `resi-20261004-69ba7a66`；Hosting headers、rewrites、redirects 保留。完整快照校验与后续模块补丁校验是两份证据，不能把前一份 deployment digest 当作最终补丁的 digest。

中文静态页面可打开：<https://ai-for-god-sermon-audio-dev.web.app/pages/mockup-20261005-dev-180s/zh-Hans/index.html>。浏览器实际检查了正文、大纲、默想和模拟审核标题/摘要。静态模板仍有“已批准完整阅读稿”等旧文案，和明确的模拟摘要矛盾；此为未修复的测试发现，不属于正式审核通过。

## 本轮修复

1. 正常 builder 将源视频显示时长与源 approvedWindow 比较，独立完整解码译文音轨。以前错误地要求自然语速音轨与源视频等长；新增 10 秒视频/12.5 秒音轨的真实构建回归。
2. 网页 runtime 从固定三个模块改为封存本地 ES module 的递归导入闭包（当前 24 个）。实测旧部署缺少新版 catalog export，导致整个页面一直加载；依赖修复后页面启动恢复。
3. 修复 builder 与 guarded publisher 直接脚本调用时嵌套 `scripts` 导入失败，失败发生在部署前。
4. 新增单独的模拟 metadata schema；仅接受精确 Dev intent、模拟标题与声明。正式 metadata schema 没有放宽，缺失 intent 或生产路由均拒绝。
5. catalog schema 补上客户端已有的模拟 flags 与线上已有的顶层 `defaultTargetLocale` 兼容字段，保留默认页面。Dev reader 的模拟页面标签不再显示为真实人工内容审核。

## 未通过项与后续修复要求

**P1：Web 与原生混用源视频时长和配音时长。** Web `published-weeks.mjs` 的 `validatedCues(captions.cues, content.durationSeconds)`，以及原生 `PublishedTranscript.swift` 的 spoken cue 校验均使用 180.013167 秒源时长。三条自然语速音轨长于源视频，导致 Web 报 `Invalid published transcript cue`，原生报“字幕时间或单元无效”。资源下载和 hash 通过不代表 reader 可用。

应扩展并版本化内容时间轴契约，绑定实测 `audioDurationSeconds`：口播字幕按音频时长校验，完整译文/source anchors 按源时长校验；同时检查实际播放、全文跟随、回到当前句与语言切换。不得把源视频时长改成音轨时长，或截断、缩放既有字幕来掩盖失败。本轮保留现状和失败证据，没有宣布修复此缺陷。

**P2：静态页审核文案。** 模拟 metadata 虽有醒目标题和警告，legacy HTML 模板仍写“已批准”。后续应让模板消费明确的 review mode，并重新 prepare、封存与发布相关 HTML/manifest/catalog hashes，不能只改线上 HTML 而留下旧 hash。

## 验证边界

- 最终相关 Python 回归：23 passed；Web 组件回归：71 passed；原生配置门控：6 passed、1 skipped。计数是各自测试集合，不叠加早期重复运行。
- 组件通过仍未覆盖本轮实际双端字幕拒绝，这是端到端测试带来的主要发现。
- 没有真实设备播放、场地验收、新 TestFlight 构建、冷启动模型吞吐、付费模型质量、人工翻译批准或听审。device/venue 字段保留 `not_run`。
- 新统一 CLI 的 fixture transport 不能准入 `app.delivery`；本轮正常 delivery adapter 消费独立模拟 packages。不能据此声称新 CLI 已从零完整执行 L1–L4。

复盘结论：重复利用缓存消除了新增模型计费，真实发布和远端读回揭露了 producer 与两个 reader 的时钟契约不一致。下一次验收应先修复共享时钟契约和静态审核文案，再使用同一 SHA 的片段复测；无需重跑已验证的译文或音频生成。

## PR #245 后续代码修复与本地复测

用户随后要求根据复盘写代码到 PR #245。该修订修复上述 P1/P2，历史发布结果保持原样，不把本地通过写成线上通过。

- 内容契约升级为 `sermon-full-video-text-content-v2`，增加必需的实测 `audioDurationSeconds` 和 `reviewMode`。producer 对音轨完整解码、验证声明时长；源窗口、全文、caption 字节均保留各自原有坐标。
- Web 与原生分别验证两个时钟。v1 缺字段保留兼容回退，v2 缺字段和非法数值拒绝；全文越过源窗口、caption 越过音轨仍拒绝。Web 的 track 时长与字幕时钟改用音频字段。
- 模拟 metadata 必须使用模拟 v2 content，正式 metadata 不接受模拟 content；v2 reader 要求模拟 page/target 都有 simulationOnly 和 diagnosticOnly，原生还要求显式 Dev context。静态页不再含“已批准完整文稿”等审核声明。
- 同一 SHA 的固定片段重新走正常 prepare，新增模型 API 调用仍为 0；三个音轨与字幕没有重生成。新候选的 Web 读取三语言均通过，原生 repository 通过本地 HTTP 映射逐个验证资源 hash、全文与字幕，三个 transcriptLoad 均通过。该本地测试目录沿用原有三页和默认页的目录对象，但只提供新页的候选资源；没有把它当成完整 Hosting 基线或新发布回执。
- 相关 Python：25 passed；Web 三个相关测试文件：79 passed；Core：82 执行通过、7 明确跳过。新增负例覆盖声明音频时长与绑定媒体不符、缺字段/非法字段、两类字幕越界，以及模拟审核准入。静态页测试验证没有正式批准文案。
- 证据：`pr245-fix-inputs/prepare-result.json`、`pr245-fix-inputs/web-readback.json`、`pr245-fix-inputs/native-readback.json`、`pr245-fix-inputs/web-tests.log`、`native/pr245-core-tests.log`（均相对本报告产物根）。原生回执的 `transport=local_http_test_origin_mapping` 与 `actualHTTPOrigin` 明确区分真实 HTTPS 发布。

本次只更新 PR 代码与复盘；最终 Hosting 版本仍是初次测试的 `36fbf0ccbb987fb4`。修复后线上读回、新 Beta 二进制和设备播放尚未执行，不能称为 Beta 发行或真机验收通过。
