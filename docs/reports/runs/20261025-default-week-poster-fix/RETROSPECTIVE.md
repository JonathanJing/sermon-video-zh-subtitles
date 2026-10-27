# 复盘：20261025-default-week-poster-fix

数据见同目录 `INDEX.md`、`manifest.json`，以及 `default-week-poster-fix-20261025/` 下的 `summary.json` 和 `deployment-receipt.json`。

## 结论先行

交付类型为 `four_layer_release` 的目录默认周次修复。用户报告正式 iOS App 的“每周海报”仍显示旧周；代码读取 `catalog.defaultPageId`，线上 v5/v4/v3 默认页仍是 10 月 18 日。10 月 25 日页面和三语海报已经存在。只把三份目录默认页改为 `revelation-jesus-wins-20261025`，部署状态 `deployed`；线上回读 328 个公开文件与候选逐字节相同。手机实际显示尚未验收。

## 总时间

部署回执记录 2026-10-25 15:14:54–15:15:21 UTC，约 27 秒。基线获取、候选准备和回读未统一记录起止时间，不汇总整轮墙钟时间；没有模型运行或付费重试。

## 各层模型、耗时与速度

L1、L2、L3 均复用已发布产物，本轮模型调用 `not_run`、新增模型费用 0。L4 只修改目录默认页并通过受控 Hosting 发布；发布和回读结果见 `deployment-receipt.json` 与 `summary.json`。

## 错误

| 阶段 | 现象 | 原因 | 发现时机 | 处理和核验 |
|---|---|---|---|---|
| L4 海报入口 | App 每周海报仍显示 10 月 18 日 | 发布海报及通知时未更新 v5/v4/v3 默认页 | 发布后，用户反馈 | 以实时完整基线生成只修改三份目录的候选；校验投影和三语海报绑定；部署后回读 328 个文件和三个 HTTP 目录 |

## 可以改进的地方

海报发布前应以 App 的实际选择规则核对 `defaultPageId` 与 sidecar 的 `pageID` 组合；此轮修复再次证明单独核对海报文件和通知深链不足以覆盖首页海报。跟踪项待加入下一次周更预检。

## 实际覆盖范围

L1–L3 复用；L4 目录默认页修复、受控部署、完整站点回读、三语图片 SHA 与发布包身份检查通过。没有重新生成音频、海报，也没有重复发送 APNs。

## 遗留状态

本地候选和回读保存在 Git 忽略的 `artifacts/`；没有新的 Dev 文件或 job hold。正式设备显示与点击结果 `not_run`，需用户在联网 App 中刷新后确认。

## 外部可见的变化

生产 Hosting 从 `361c2ecfb4a9f5ea` 更新到 `61e7e79c4fa61b42`；v5、v4、v3 的默认页均为 `revelation-jesus-wins-20261025`，其它 325 个公开文件字节不变。新 App 构建、TestFlight、设备播放及场地验收均 `not_run`。
