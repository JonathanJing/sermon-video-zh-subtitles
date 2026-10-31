# 复盘：20261024-web-podcast-optional-summary

数据见同目录 INDEX.md 和 manifest.json。

## 结论先行

交付类型：Production Web 前端单文件更新（UI-only overlay，不是 `four_layer_release`），状态 **pass**。

- 现象：Production Web「本期与往期」只列出 v5 目录 7 页中的 5 页。缺的是两期已发布、`human_reviewed` 的播客：`if-i-had-more-time-jesus-sends-and-resurrects-his-own`（2026-10-18）和 `if-i-had-more-time-jesus-promises`（2026-09-19）。
- 原因：这两期的 `/content/<pageId>/<locale>.json` 没有 `summary`／`outline`。`published-weeks.mjs` 要求这两个字段都存在，所以三种语言全部报 `Invalid published content metadata`，整页被丢弃。iOS 把这两个字段当作可选，Production 列表只由 release 包决定，所以 iOS 上能列出。
- 修复：PR #1345 让已发布播客可以省略这两个字段，缺省为 `''`／`[]`；字段存在时仍然校验，视频和 Dev 候选仍要求必填。#1344 把它晋升到 `main`（`e821690e`）；overlay 只改 `/published-weeks.mjs`。操作者用 `guarded_hosting_publish.py --execute` 部署：版本 `25986755c1843f5b` → `5b203d534c8b558d`。
- 证据边界：代码测试、HTTP 字节一致、线上加载器回放、浏览器渲染都已通过。设备与现场验收 `not_run`。iOS 没有改动，本轮也没有复测。

## 总时间

约 6.5 小时墙钟（2026-10-24 17:20Z 至 23:56Z）。其中计算约 1.5 小时，主要是本地根 unittest 全量约 61 分钟，再加两次 15 项复跑。其余是等待：等操作者执行 `--execute`，以及等另一会话合并 #1344／#1347。返工：一次 `run_unittest_ci.py --shard-index` 用了从 1 开始的索引（应从 0 开始），重跑一次。

## 各层模型、耗时与速度

| 层／阶段 | 模型或后端 | 推理强度／tier | 调用次数 | 计算耗时 | token 或音频秒数 | 速度 | 费用 | 证据 |
|---|---|---|---|---|---|---|---|---|
| L1–L3 | not_run（内容未变） | | 0 | | | | 0 | catalog sha 未变 |
| L4 构建与发布 | `prepare_dev_web_ui_update.py --environment production` + `guarded_hosting_publish.py` | — | 1 次部署 | 部署约 25 s | — | — | 0 模型费用 | deployment-attempt.json |

## 错误

| 层／阶段 | 现象 | 原因 | 发现时机 | 处理 | 回归测试 | 提交或 PR |
|---|---|---|---|---|---|---|
| L4 Web reader | 两期已发布播客在 Production Web 不显示 | Web 校验要求 content 带 `summary`／`outline`，iOS 不要求；两期播客的 content 缺这两个字段 | 发布后（用户发现） | 放宽 Web 校验，与 iOS 一致 | `published-weeks.test.mjs` 新增用例（旧实现下失败） | #1345，#1344 |
| L4 发布检查 | 发布时没有发现 Web 会拒绝该页 | 发布与快照检查没有用 Web 加载器回放 | 发布后 | 本轮用 `loadPublishedWeeks` 对线上回放 | — | 见改进 |
| 本地 CI 替代 | 根 unittest 13 failures + 2 errors | 与改动无关：旧 `main` `b8c2556e` 上同样失败（backend 导入、identity／cache 检查） | 晋升前 | 记录；未修 | — | 待跟踪 |

## 可以改进的地方

| 类别 | 改进 | 依据（本报告的数值或错误） | 预期收益 | 负责人 | 跟踪 |
|---|---|---|---|---|---|
| 预检 | 发布与快照检查用 Web 的 `loadPublishedWeeks` 回放每个新页面；Web 与 iOS 任一端会丢弃该页时就失败 | 两期播客在 Web 上不可见，直到用户发现 | 发布即可确认两端都能列出 | 待定 | 待开 backlog |
| 质量 | Web 与 iOS 的 content 字段可选性用共享 fixture 对齐 | Web 与 iOS 规则不一致 | 防止两端再次分叉 | 待定 | 待开 backlog |
| 流程 | 查明 15 个本地 unittest 失败（CI 停用期间无人发现） | 旧 `main` 上同样失败 | 恢复本地替代 CI 的可信度 | 待定 | 待开 backlog |

## 实际覆盖范围

L1–L3 未执行，内容与目录不变（v5 catalog sha `4fbd50a2…`，v3 catalog sha `8427a4c6…`）。L4 只替换 Web 运行时的一个文件；其余 293 个公开文件按字节保留。

## 遗留状态

- `resi-20261018-15030286` 的 ko／es 对齐绑定无效（声纹对齐不可用，页面正常显示），未处理。
- 本地产物在 `artifacts/web-podcast-optional-summary-20261024/`（baseline、两个候选），已被 Git 忽略，可删除。
