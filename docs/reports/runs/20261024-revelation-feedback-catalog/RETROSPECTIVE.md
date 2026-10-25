# 复盘：20261024-revelation-feedback-catalog

证据见同目录 `INDEX.md`、`manifest.json` 和六份脱敏收据。本轮是既有四层页面的 Layer 4 反馈统计来源目录同步。

## 结论先行

正式站 Hosting 保持 `833eda14595b165d`。从该版本的完整核验快照重建目录，以 revision `00018-nux` 的 34 条来源为基准，新增 `revelation-jesus-wins-20261025` 的 zh-Hans、ko、es 三条；原 34 条逐字段不变。反馈函数部署为 ACTIVE `sermon-feedback-api-00020-nag`，100% 流量。部署源码包逐文件回读：相对 `00018` 只变动 `catalog.json`，新文件 SHA-256 为 `09c067c052948308b7a4f859dafdedda9e23153569985e965e6f7baf0f90c0cf`。

三条音轨各一次独立 `POST /api/session` 均返回 200；目标页的三语浏览器冒烟均通过，页面自己的会话请求全部为 200。这个结果只覆盖 API 会话与浏览器页面，不代表真机播放或现场验收。

## 总时间

`outcome.json` 从快照完成到冒烟结束记录约 2 分 55 秒。没有 journal，无法准确拆分构建、等待和返工；未作同类耗时比较。

## 各层模型、耗时与速度

| 阶段 | 状态 | 证据 |
|---|---|---|
| L1–L3 | reused，未运行模型 | `summary.json` |
| L4 反馈目录 | 从线上 v5 快照构建 37 条来源；只更新函数源码包中的 catalog | `catalog-receipt.json`、`deploy-receipt.json` |
| API 与浏览器 | 三条独立会话 POST 200；三语页面冒烟 pass | `api-session-receipt.json`、`browser-smoke-receipt.json` |

## 错误

首次部署命令的构建服务账号参数缺少 `projects/.../serviceAccounts/...` 前缀，在参数校验阶段返回 400；函数仍为 ACTIVE `00019-yik`，未创建新 revision。核对状态后用同一候选包和完整资源名部署成功。没有重建目录或重复发送会话 POST。

## 可以改进的地方

部署命令的预检应直接核对 `buildConfig.serviceAccount` 的完整资源名，避免一次参数校验失败。每次页面资产变更后应核对反馈来源的音频哈希；本轮发现 `00019-yik` 虽已有该页面的三条旧来源，但哈希与当前 v5 不同，导致当前音轨的会话请求返回 400。

## 实际覆盖范围

从当前线上版本读取完整快照并验证逐文件字节；`build_language_listening_catalog.py` 核验发布包、正文、字幕和音频哈希。候选相对 `00018` 的九个源码文件只有 `catalog.json` 改动；当前 `00019` 的八个运行文件也与 `00018` 同哈希。部署源码包和 ACTIVE revision 均已回读。没有改 Hosting、Web 代码、页面资产或 iOS。

## 遗留状态

浏览器警告仍列出其他旧页面的可选 alignment 与 voice demo 资源 404；本页必需资源和会话检查通过。真机播放和现场验收未运行。三次直接会话 POST 与浏览器加载创建的是没有收听记录的短期会话，不构成收听统计回读。

## 外部可见的变化

Cloud Functions revision `00019-yik` → `00020-nag`，来源目录保有原 34 条并将该页面的三条旧哈希替换为当前三条。Hosting 版本不变；TestFlight、App Store、设备和现场均未改动或验收。
