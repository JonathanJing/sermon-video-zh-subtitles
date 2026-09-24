# Firebase 四层制作公开 Tracker

这是可部署到独立 Firebase Hosting 站点的**公开只读、脱敏**状态页。它按周显示共享 Layer 1，以及简体中文、韩语、西语等每种语言的 Layer 2–4 检查点、进度和有条件 ETA；从源页面是否出现／更换视频，跟踪到每语言页面、正式语音、声纹索引和设备／现场验收。浏览器从专用 Firestore 命名数据库 `sermon-tracker` 实时读取，规则禁止客户端写入。所有人都能读取已发布状态，管理员在本地用服务端发布器更新。Firebase [Security Rules](https://firebase.google.com/docs/firestore/security/rules-conditions)约束客户端请求；服务端 SDK 写入由 IAM 控制。

公开快照仅有状态、数量、时间、步骤实测耗时与尝试次数、经允许的源页面链接和同周播放页链接。视频 ID／原视频 URL、审核原因、证据路径、内部哈希、声纹音轨 SHA 和凭据不会进入公开文档。发布器还会对生成器输出做一次明确的字段投影，额外字段自动丢弃。页面的百分比只表示检查点；ETA 是连续串行估算，缺工时或待人工审核时显示未知。页面不会替代正式包的 validator、内容听审、HTTP 核验或设备验收。

## 配置与部署

1. 在目标 Firebase 项目中新建**专用** Firestore 命名数据库 `sermon-tracker` 和独立 Hosting 站点。不要把本目录的规则部署到现有反馈数据库；规则部署会覆盖目标数据库现有规则。参见 Firebase 的[多站点 Hosting](https://firebase.google.com/docs/hosting/multisites)和[规则部署说明](https://firebase.google.com/docs/rules/manage-deploy)。
2. 复制 `public/tracker-config.example.json` 为被忽略的 `public/tracker-config.json`，填写 Firebase Web App 的**公开**配置与数据库 ID。不要放管理员令牌、服务账号密钥或其他凭据。
3. 安装依赖、运行测试并构建。为新站点绑定 Hosting target `sermonTrackerAdmin`，再把规则及静态页部署到**指定**的数据库和站点。先检查目标项目／target 绑定。

```bash
cd experiments/sermon-dubbing-poc/tracker-admin
npm install
cp public/tracker-config.example.json public/tracker-config.json
# 填好公开 Firebase Web App 配置后：
npm test
npm run build
firebase target:apply hosting sermonTrackerAdmin YOUR_TRACKER_SITE --project YOUR_PROJECT
firebase deploy --only firestore:sermon-tracker --project YOUR_PROJECT
firebase deploy --only hosting:sermonTrackerAdmin --project YOUR_PROJECT
```

已在项目 `ai-for-god-sermon-audio-dev` 建立独立站点 `ai-for-god-sermon-tracker-dev`、专用数据库 `sermon-tracker`（`us-west1`、Standard、删除保护、首库免费配额）和公开 Web App；规则与页面于 2026-09-23 部署。[线上 Tracker](https://ai-for-god-sermon-tracker-dev.web.app/) 可直接查看。其他项目复用时仍按上述步骤建立自己的独立资源。`?demo=1` 显示明确标记的合成样例，不读取真实数据。

本地 UI 审核可先 `npm run build`，将 `dist/` 复制到忽略 Git 的 `artifacts/tracker-ui-review/`，用快照生成器把当前账本写成该目录的 `local-preview.json`，再从仓库根目录运行 `python -m http.server 4178 --bind 127.0.0.1 --directory artifacts/tracker-ui-review`。打开 `http://127.0.0.1:4178/?local=1` 即可查看**非实时**脱敏快照；此模式不连接 Firestore，也不执行发布。

## 更新每周状态

本地工作账本由[四层 tracker](../../../scripts/four_layer_progress.py)维护；[快照生成器](../../../scripts/build_four_layer_tracker_snapshot.py)汇总账本、源监控、同语言 Release Package、可选旧中文目录、HTTP 收据和声纹证据。正式 producer 尚未全部自动写入账本，所以未有收据的阶段需操作者按真实证据更新。`source-video-state.private.json` 保存在快照旁边的忽略 Git 工作目录，用于比较同一周视频 ID；此文件**不得放进 Hosting public/dist 或 Firestore**。

本轮之后的片段 POC 用[四层 Tracker 文档](../../../docs/four-layer-production-tracker.zh.md)中的 `init-poc` 建立准确 `pageId`、原视频及候选窗口绑定的新账本；它不授予人工范围批准。耗时审计使用[四层计时入口](../../../scripts/four_layer_measure.py)：首批正式 producer 加 `--progress-ledger` 即自动写执行 span；未接入的命令仍用 `run --step` 包装。`audit` 只读地将私有 `accounting/events.jsonl` 关联到检查点，并列出缺少计时的已完成步骤。公开 Firebase 页面显示步骤的实测耗时、重试／失败次数、审核等待和缺实测计时的完成步骤数，不上传模型请求细节或私有日志。人工审核等待需在发出和收到审核时及时更新 Tracker 状态；旧产物的文件时间不能补作实测耗时。

```bash
python scripts/four_layer_progress.py artifacts/my-run/four-layer-progress.json init \
  --page-id my-page --target dev --locales zh-Hans ko es
python scripts/build_four_layer_tracker_snapshot.py \
  --ledger artifacts/my-run/four-layer-progress.json \
  --out artifacts/my-run/public-tracker-snapshot.json \
  --source-monitor artifacts/live-source-monitor/report.json \
  --source-page-url https://www.marinerschurch.org/irvine/ \
  --service-date 2026-09-20
cd experiments/sermon-dubbing-poc/tracker-admin
node publish.mjs --project YOUR_PROJECT --database sermon-tracker \
  --snapshot ../../../artifacts/my-run/public-tracker-snapshot.json
# 默认只验证；确认目标项目后，加 --execute 才写 Firestore。
```

把 `watch-config.example.json` 复制为被忽略的 `watch-config.json`，配置本周账本与证据路径后，可运行：

```bash
node publish.mjs --project YOUR_PROJECT --database sermon-tracker \
  --watch-config watch-config.json --watch --execute
```

`--watch` 默认每 15 秒重建，只在内容状态变化时写入；网页收到 Firestore 更新后实时刷新。它不会启动模型、下载视频或部署网页。发布器的 ADC 身份需要相应数据库的写入 IAM 权限，凭据不能放进网页或公开快照。发布器默认 dry run，并要求明确 `--execute`。

每语言声纹可附加 `--fingerprint-evidence`，格式见 `fingerprint-evidence.example.json`。生成器核对同语言 Release Package 的音轨 SHA、本地索引字节和可选线上 HTTP 收据；仅在同语言证据成立时显示“本地已生成”或“线上已核验”。旧中文 `weekly.json` 路径单独标记 legacy，不会推断韩语／西语已经发布。

## 当前边界

- 2026-09-23 的 Dev POC 捕捉使用 `pageId=2026-09-20-lion-of-judah-poc`。忽略 Git 的证据目录为 `artifacts/tracker-runs/2026-09-20-dev-poc/`，保存工作账本、线上 `weekly.json`、逐音轨 HTTP／SHA／Range 收据、公开快照和 `tracker-deployment-verification.json`。未登录 Web SDK 已成功读取文档并列出该周记录；其他集合的读取被拒绝。线上 HTML、配置和 CSP 均返回 200，浏览器显示四语状态及筛选结果；原 POC 目录在 Tracker 部署后字节未变。
- 当前 POC 的忽略 Git `watch-config.json` 已填好本地路径。运行前先刷新其中的线上目录／HTTP 收据；`--watch` 只观察这些本地文件和账本，不替代定时源监控或自动下载新视频。
- 另一个已发布的状态记录 `2026-09-20-blocks9-14-178s-dev-progress` 对应正在制作的三语 178 秒片段：Layer 1 为 4/4，三语 Layer 2 各 4/4，Layer 3 各 1/6，Layer 4 各 0/4，总计 19/46。该记录是审核收据的事后捕捉；计时预检显示 19 个已完成步骤没有实测执行 span，不能据此比较阶段速度。后续步骤可用新计时入口留证，本轮结束再审计。
- 该 POC 的中文、韩语、西语、越南语各有机器文字候选与可访问的短音轨；四条音轨的 SHA 和 Range 通过。越南语机器音频筛查标记需复核。四语的正式文字审核、音色听审、完整 Layer 3 音轨、声纹、设备和现场验收均未由此 POC 获得批准；正式检查点为 0/60。来源页面／视频更新尚无本周 source monitor 收据，保持“未检查”；ETA 仍未知。
- 正式四层 producer 到工作账本的自动同步仍在[Tracker Backlog](../../../docs/four-layer-production-tracker.zh.md) 的 TRK-002。人工更新必须引用真实包与收据。
- “视频已更新”仅指同周源监控发现的视频 ID 相对上次本地状态变化，不证明下载、解码或人工范围批准。
