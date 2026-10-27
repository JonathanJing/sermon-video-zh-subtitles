# 复盘：20261025-feedback-catalog-sync

数据见同目录 INDEX.md 和 manifest.json。

## 结论先行

`four_layer_release` 的 Layer 4 后续同步：把 2026-10-25T02:32Z 发布的新页 `revelation-jesus-wins-20261025`（zh-Hans／ko／es 三条音轨）补进匿名统计 API `sermon-feedback-api` 的来源目录。结束信号是 revision `sermon-feedback-api-00019-yik` ACTIVE 并承接 100% 流量，部署源码包（generation `1792897689233697`）里的 `catalog.json` SHA-256 `8da82964…` 与本地构建一致，其余 8 个文件与上一 revision 逐字节相同，且本页三语 `POST /api/session` 从部署前的 400 `unknown_source` 变为 200；浏览器冒烟（`smoke_published_page.py`，v3）三语 pass。

起因：海报收尾的浏览器冒烟发现本页三语 `/api/session` 返回 400（`artifacts/sermon-poster/2026-10-25/summary.json` 的 `browserSessionFailure`）。目录在 10-24 同步（00018，34 个来源）时尚未包含这一页。用户在对话中授权并亲自执行部署。

证据边界：只证明 API 目录、运行状态和一个无头浏览器中页面自己的会话请求；没有在网页或 iOS 上实际播放并回读一条收听记录，也没有设备或场地验收。02:32Z 发布到 03:08Z 部署之间约 36 分钟的收听上报已丢失，无法补回。

## 总时间

约 9 分钟墙钟（03:01–03:11Z）处于本会话；另加约 50 分钟等待：部署命令交给用户执行，用户首次点击后未真正运行（无 deploy.log、无新 Cloud Build），第二次在终端运行成功（03:08:54Z 完成）。计算部分：目录构建与校验约 2 分钟，Cloud Functions 构建部署约 5 分钟，回读与冒烟约 2 分钟。无返工。上一轮同类运行（10-24）约 11 分钟、无等待。

## 各层模型、耗时与速度

| 层／阶段 | 模型或后端 | 推理强度／tier | 调用次数 | 计算耗时 | token 或音频秒数 | 速度 | 费用 | 证据 |
|---|---|---|---|---|---|---|---|---|
| L1–L3 | reused | not_run | 0 | 0 | reused | n/a | US$0 | 线上已发布产物（逐句优先代理线 2026-10-25 发布） |
| L4 统计目录同步 | `build_language_listening_catalog.py` + `gcloud functions deploy` | n/a | 1 次部署 | 约 7 分钟 | n/a | n/a | Cloud Build 免费额度内 | `deploy-receipt.json`、`deploy.log`、`summary.json` |

## 错误

| 层／阶段 | 现象 | 原因 | 发现时机 | 处理 | 回归测试 | 提交或 PR |
|---|---|---|---|---|---|---|
| L4 统计 | 新页三语 `/api/session` 400 `unknown_source` | 10-25 发布后没有同步重新部署统计目录；发布清单的目录覆盖检查（10-24 复盘提出，`DEV-USAGE-001`）尚未落地 | 发布后（海报冒烟） | 从与线上字节一致的快照重建目录并部署；运行代码保持 00018 原字节 | 新目录经线上 `core.mjs` 的 `prepareCatalog`／`createService` 本地加载并为三条音轨 mint 成功；部署后三语 200；浏览器冒烟 pass | 本报告 |
| 流程 | 第一次“已运行部署”后无 deploy.log、revision 未变、无新 Cloud Build | 部署脚本未真正在带 gcloud 的终端执行 | 回读时 | 以 describe／builds／bucket 三项证据判定未部署，请用户在终端重跑 | 第二次运行后 00019 ACTIVE | 本报告 |

## 可以改进的地方

| 类别 | 改进 | 依据 | 预期收益 | 负责人 | 跟踪 |
|---|---|---|---|---|---|
| 流程 | 逐句优先代理线的发布 runbook 在 Hosting 发布步骤之后加入“统计目录重建并部署”步骤，与四层周更清单一致 | 本次新页发布后 36 分钟内三语 400 | 新页上线即可统计 | repo owner | `DEV-USAGE-001` |
| 预检 | 把本次的“下载线上函数源码包 → 只替换 catalog.json → 哈希对比”固化为只读脚本，输出 deploy 命令 | 本次手工完成，与 10-24 相同 | 每周一键准备，减少手工差错 | repo owner | `DEV-USAGE-001` |
| 流程 | 部署回读先核对 revision／Cloud Build／源码 generation 三项，再判定“已部署” | 本次第一次报告“已运行”实际未部署 | 避免基于口头完成信号读取旧 revision | repo owner | 本报告 |

## 实际覆盖范围

- L1–L3：未执行，全部复用线上产物。
- L4：只更新统计 API 来源目录；Hosting、目录、客户端均未改动。
- 快照：`artifacts/sermon-poster/2026-10-25/upload-v2-readback/public`，其 `multilingual-v5.json`（`cc4891e4…`）与 `weekly.json`（`6b7bbd01…`）与线上字节一致；本页 release／content／captions 哈希与线上一致。
- 新增 3 个来源：`revelation-jesus-wins-20261025` zh-Hans（1860.24 秒）、ko（1860.0 秒）、es（1861.07 秒），各 418 条字幕，week `2026-10-25`。原 34 个来源逐字段不变，`voiceIds` 不变，`weekIds` 增加 `2026-10-25`。

## 遗留状态

- dev 分支 `services/feedback/core.mjs`（`3e36fc59…`）仍与线上（`a4cfad3d…`）不同，含尚未部署的 alignment 统计代码；本次刻意未部署。
- 回退包：上一 revision 的源码 zip 保存在本地 `artifacts/feedback-catalog-sync-20261025/rollback-00018/`（不入 Git）。
- 冒烟产生 3 条无收听记录的会话（`appVersion=smoke-20261025`）加浏览器冒烟自身的会话，24 小时凭据到期、30 天 TTL 自动删除，不进入收听报表。
- 浏览器冒烟的 5 条 warning 为可选资源 404（其他页面的 `/alignment/*.json`、`/voice-demos/speaker-clips-v2/catalog.json`），与 10-25 海报冒烟相同，不属于本次范围。

## 外部可见的变化

- Cloud Functions：`sermon-feedback-api-00018-nux` → `sermon-feedback-api-00019-yik`，37 个来源，运行时参数不变。
- Hosting、TestFlight、App Store、受保护分支：not_run。
