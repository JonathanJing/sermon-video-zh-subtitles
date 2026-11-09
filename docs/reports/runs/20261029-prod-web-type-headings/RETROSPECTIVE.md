# 复盘：20261029-prod-web-type-headings

数据见同目录 INDEX.md 和 manifest.json。

## 结论先行

交付类型：仅 Web UI 的 Production Hosting 更新，不是 `four_layer_release`。目录、内容、媒体、审核收据和 Hosting 配置都没有改动。

最终状态：`deployed`，用 guarded publish 部署。
- 基线版本：`sites/ai-for-god-sermon-audio/versions/642d25fc58fe5c4e`。
- 新版本：`4f25c78256b2d5c2`，`ownedVersionObserved=true`。
- 发布依据：用户在 chat 中授权（decisions.ndjson）。

内容来自 JonathanJing/sermon-video-zh-subtitles#1494，即文字最小 12px 和标题层级修正。源提交是 dev 的 2eb18808。

证据边界：
- HTTP 检查：四个改动文件的字节与源一致。
- 浏览器检查：只看了一个页面，结果如下。
- 未验证：iOS、其他页面和语言、真机。

## 总时间

部署前后约 10 分钟，不含等待。没有写 journal。

- 拉取基线：约 1 分钟。
- 准备候选：小于 1 分钟。
- guarded publish：28 秒，18:47:41–18:48:09 UTC。

## 各层模型、耗时与速度

不涉及模型调用（modelCalls=0）。

| 层／阶段 | 模型或后端 | 推理强度／tier | 调用次数 | 计算耗时 | token 或音频秒数 | 速度 | 费用 | 证据 |
|---|---|---|---|---|---|---|---|---|
| L1–L3 | not_run | | 0 | | | | 0 | 仅 UI 更新 |
| L4 构建与发布 | Firebase Hosting guarded publish | — | 1 | 28 s | — | — | 0 | candidate/hosting-publish.log |

## 错误

没有发生错误。

`prepare_dev_web_ui_update.py` 的 UI 文件清单里没有 `speaker-clip-demos.mjs` 和 `voice-demo.css`，但 #1494 改了这两个文件。这次的处理：
- 用一个包装脚本，把这两个文件追加到 `PRODUCTION_UI_DEPENDENCIES` 后再调用 `prepare()`。
- 绑定源提交、保留文件不变、无文件删除和封存这几项检查照常执行。
- 实际改动的路径正好是这四个：`/index.html`、`/style.css`、`/speaker-clip-demos.mjs`、`/voice-demo.css`。

## 可以改进的地方

| 类别 | 改进 | 依据（本报告的数值或错误） | 预期收益 | 负责人 | 跟踪 |
|---|---|---|---|---|---|
| 流程 | 让 `prepare_dev_web_ui_update.py` 接受与基线有差异的共享语音演示文件，或改为按源闭包和基线的差异来决定替换哪些文件 | 这次需要额外的包装脚本才能发布 #1494 的四个文件 | 以后的 UI 修复不用包装脚本 | 未指派 | 未建 |

## 实际覆盖范围

- L1–L3：未执行。
- L4：只覆盖 Web reader 的外壳文件。354 个公开文件里有 350 个保持不变。

部署后的 HTTP 检查：带 no-cache 抓取了 6 个文件，与源提交逐字节一致。其中 4 个是本次改动的文件，另外 `app.mjs` 和 `published-weeks.mjs` 本来就与源一致。

浏览器检查只看了一个页面：`revelation-jesus-wins-20261025`，zh-Hans。
- 样式正常加载。
- 可见文字最小 12px，小于 12px 的为 0。
- 标题层级 H1→H2→H3，没有跳级。

已知的 404 在部署前的基线里就存在，不是这次部署造成的：
- `/alignment/if-i-had-more-time-*.json`，4 个 podcast 页面。
- `/voice-demos/speaker-clips-v2/catalog.json`，production 上没有语音演示目录。

## 遗留状态

本地产物在 `artifacts/web-type-headings-production-20261029/`，已被 Git 忽略。不需要清理远端资源。

## 外部可见的变化

- Production Web：已更新，版本 `4f25c78256b2d5c2`。
- iOS、TestFlight：not_run，没有改动。
- Dev Hosting：not_run，这次没有发布。
