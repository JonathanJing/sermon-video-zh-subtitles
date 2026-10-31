# 复盘：20261024-feedback-catalog-sync

数据见同目录 INDEX.md 和 manifest.json。

## 结论先行

`four_layer_release` 的 Layer 4 后续同步：把匿名统计 API `sermon-feedback-api` 的来源目录补齐到当前线上页面。结束信号是 revision `sermon-feedback-api-00018-nux` ACTIVE，部署源码中的 `catalog.json` SHA-256 `948f93d2…` 与本地构建一致，且此前被拒的新音轨 `/api/session` 返回 200。

起因：2026-10-24 查询 30 天统计时发现，10-18 部署的目录（26 个来源，`31725ca9…`）缺少线上 21 条音轨中的 8 条，这些音轨的网页／iOS 收听上报会以 `unknown_source` 被静默丢弃。用户在对话中授权重新部署。

证据边界：只证明 API 目录与运行状态；没有在网页或 iOS 上实际播放这 8 条音轨来回读一条收听记录。10-18 至 10-24 期间丢失的收听数据无法补回。

## 总时间

约 11 分钟墙钟（18:30–18:41Z）：目录构建与校验约 3 分钟，Cloud Functions 构建部署约 6 分钟，回读与 smoke 约 2 分钟。无等待、无返工。

## 各层模型、耗时与速度

| 层／阶段 | 模型或后端 | 推理强度／tier | 调用次数 | 计算耗时 | token 或音频秒数 | 速度 | 费用 | 证据 |
|---|---|---|---|---|---|---|---|---|
| L1–L3 | reused | not_run | 0 | 0 | reused | n/a | US$0 | 线上已发布产物 |
| L4 统计目录同步 | `build_language_listening_catalog.py` + gcloud functions deploy | n/a | 1 次部署 | 约 9 分钟 | n/a | n/a | Cloud Build 免费额度内 | `deploy-receipt.json`、`deploy.log` |

## 错误

| 层／阶段 | 现象 | 原因 | 发现时机 | 处理 | 回归测试 | 提交或 PR |
|---|---|---|---|---|---|---|
| L4 统计 | 8 条线上音轨不在 API 目录 | 10-18 之后的发布（10-18 broadcast ko/es、两期 if-i-had-more-time）没有同步重新部署统计目录 | 发布后（统计查询时） | 从当天与线上 v5 字节一致的完整快照重建目录并部署；运行代码保持 00017 原字节 | 新目录用线上 `core.mjs` 的 `createService` 加载通过；新音轨 mint 200 | 本报告 |

## 可以改进的地方

| 类别 | 改进 | 依据 | 预期收益 | 负责人 | 跟踪 |
|---|---|---|---|---|---|
| 流程 | 每次 Layer 4 发布清单加入“统计目录覆盖全部线上音轨”检查，缺失时同步部署 | 本次 8/21 缺失持续 6 天 | 不再静默丢失新页面的收听统计 | repo owner | `DEV-USAGE-001` |
| 预检 | 提供只读脚本：下载线上函数源码目录并与 v5 目录逐条对比 | 本次手工完成该对比 | 每周可一键检查 | repo owner | `DEV-USAGE-001` |

## 实际覆盖范围

- L1–L3：未执行，全部复用线上产物。
- L4：只更新统计 API 来源目录；Hosting、目录、客户端均未改动。
- 新增 8 个来源：`resi-20261018-15030286` ko/es，`if-i-had-more-time-jesus-sends-and-resurrects-his-own` zh-Hans/ko/es，`if-i-had-more-time-jesus-promises` zh-Hans/ko/es。原 26 个来源逐字段不变。

## 遗留状态

- dev 分支 `services/feedback/core.mjs` 与线上不同（含尚未部署的 alignment 统计代码）；本次刻意未部署，保持线上运行代码不变。
- smoke 产生 1 条无收听记录的会话（`appVersion=smoke-20261024`），30 天 TTL 自动删除，不进入收听报表。

## 外部可见的变化

- Cloud Functions：`sermon-feedback-api-00017-mev` → `sermon-feedback-api-00018-nux`，34 个来源。
- Hosting、TestFlight、App Store、受保护分支：not_run。
