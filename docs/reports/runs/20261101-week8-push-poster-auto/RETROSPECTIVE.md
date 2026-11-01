# 复盘：20261101-week8-push-poster-auto

数据见同目录 INDEX.md 和 manifest.json。未填写的小节删掉前请写明原因。

## 结论先行

交付类型为**测试**（`deliveryType: test`），最终状态 `pass`。本报告覆盖两件事：一是 2026-11-01 主日推送的**只读内容预检**（`ios-push-20261101-preflight`，`preflight_pass`，未向 APNs 发送）；二是 iOS「本周海报」在服务日 08:00 本地时间后自动显示的门禁与界面验证（`ios-poster-auto-20261101`，`pass`，最终提交 `eaac2a5b`，已 rebase 到 `origin/dev`）。证据边界：iOS 行为只在模拟器与合成公告 fixture 上验证；正式目录、release 与海报字节的绑定由预检在公网重新核验；**真机安装、生产内容构建、推送设备显示与点击海报均未验证**。推送实际发送安排在 2026-11-01T16:00Z（08:00 America/Los_Angeles，DST 已结束），其 APNs 回执属于另一次运行，不在本报告内。

## 总时间

本轮从 2026-10-31T23:34 PDT（06:34Z）开始排查到报告生成约 2026-11-01T00:20 PDT（07:20Z），约 46 分钟墙钟时间。可拆出的阶段：

- 只读预检（`ios-push-20261101-preflight`）：06:41:38Z → 06:43:14Z，约 96 秒，含 npm 依赖安装、生产目录/海报核验、订阅快照、APNs 凭据本地校验和 7 项服务测试。
- iOS 构建：06:44:35Z → 06:45:30Z，约 55 秒。
- Core 测试：两轮（首轮 06:40Z 前后，约 4 分钟含编译；复审修复后定向重跑约 1 分钟），每轮 119 项通过。
- Hosted 测试：三轮（首轮 5 项、复审修复后 5 项、新增信号测试后 6 项），每轮 30–60 秒，均通过。
- UI 测试四轮：首轮 126 秒（2 项失败，见「错误」）；修复后 85 秒通过；补截图后 102 秒通过；复审修复后 75 秒通过。
- 独立只读审核：约 10 分钟（审核者另起进程，读取精确提交并独立跑 Core 定向测试）。
- 其余为代码编写、复审修复、证据整理和报告生成；没有可对照的上一轮同类运行。

## 各层模型、耗时与速度

| 层／阶段 | 模型或后端 | 推理强度／tier | 调用次数 | 计算耗时 | token 或音频秒数 | 速度 | 费用 | 证据 |
|---|---|---|---|---|---|---|---|---|
| L1 来源 ASR | not_run（复用既有已发布来源） | — | 0 | — | — | — | 0 | 生产 v5 目录与 release 包读回 |
| L1 词级对齐（MFA） | not_run | — | 0 | — | — | — | 0 | — |
| L1 英文机器评审 | not_run | — | 0 | — | — | — | 0 | — |
| L2 初译 | not_run | — | 0 | — | — | — | 0 | release 包 `published_http_verified` |
| L2 独立审核 | not_run | — | 0 | — | — | — | 0 | contentStatus `human_reviewed` |
| 文本质检（回译） | not_run | — | 0 | — | — | — | 0 | — |
| L3 配音（TTS） | not_run | — | 0 | — | — | — | 0 | audioStatus `human_reviewed` |
| L3 回转写筛查（ASR） | not_run | — | 0 | — | — | — | 0 | — |
| 音频质检 | not_run | — | 0 | — | — | — | 0 | — |
| L4 构建与发布 | 无新内容发布；仅 iOS 本地构建与只读推送预检 | — | 0 模型调用 | 构建约 55 秒 | — | — | 0 | `ios-poster-auto-20261101`、`ios-push-20261101-preflight` |

本轮没有模型请求或付费推理；文案来自 `send-core.mjs` 的固定 `BODIES` 表与已发布公告标题。

## 错误

| 层／阶段 | 现象 | 原因 | 发现时机 | 处理 | 回归测试 | 提交或 PR |
|---|---|---|---|---|---|---|
| iOS UI 测试 | `testPosterPromptPersistsDismissalAndCanReopen` 与 `testPosterStaysManualBeforeItsServiceDate` 首轮失败，找不到 `weekly-update-open` 卡片 | 新的 `--ui-testing-weekly-update-pending` 启动参数没有同时带 `--ui-testing-weekly-update`，URLProtocol fixture 未注入 | 占用模拟器资源后 | 两个测试改为同时传两个参数；重跑 4 项全部通过 | `TongxingUITests/WeeklyUpdateUITests` 4/4 通过 | 已并入 `eaac2a5b` |
| 推送预检 | 任务简报把 08:00 America/Los_Angeles 写成 15:00Z，实际因 DST 结束应为 16:00Z | 简报未按夏令时切换计算 UTC | 预检（发送前） | 预检按 16:00Z 记录发送时间并显式标记偏差；调度提醒按 08:00 本地时间创建 | 预检 `summary.json` 的 `sendTime` 字段；Core 测试新增精确 DST 时刻断言 | 无代码改动 |

## 可以改进的地方

| 类别 | 改进 | 依据（本报告的数值或错误） | 预期收益 | 负责人 | 跟踪 |
|---|---|---|---|---|---|
| 预检 | 新增 UI 测试 fixture 参数时，同时检查 `UITestContent.nativeResponses` 的启用条件是否满足 | 首轮 2 项失败、多花约 2 分钟 | 少一轮返工 | iOS 实现者 | 本报告「错误」表 |
| 流程 | 跨夏令时的推送/提醒时间用 IANA 时区的日历计算，不手写 UTC | 15:00Z 与 16:00Z 偏差一小时 | 避免提前或延后发送 | 推送操作者 | 预检 `sendTime` 字段 |
| 质量 | 独立审核发现的「前台返回先于公告刷新」缺口已用刷新完成信号修复；新增 hosted 信号测试 | 审核 0 阻塞／3 项非阻塞，修复后重验 | 首次 08:00 打开即可显示，不必二次返回 | iOS 实现者 | `eaac2a5b` |
| 证据 | 自动显示需要在真机安装包含该提交的构建；应在下一分发候选里补真机锁屏/前台截图与推送点击海报截图 | 当前只有模拟器合成 fixture 证据 | 闭合真机与推送验收 | iOS 实现者 + 用户 | 待分发候选 |

## 实际覆盖范围

- **已执行**：生产 v5 目录中 `revelation-jesus-marks-his-own-20261101` 的页面、三语 release 包公网字节 SHA、`published_http_verified`、三语公告与海报 PNG 字节 SHA 校验；活跃订阅只读快照（1 位，无重复 token）；APNs 生产凭据本地格式/权限/P-256/ES256 校验（无网络）；`services/push` 7 项测试。
- **已执行（iOS）**：Core 119 项测试（含 5 项 08:00/时区/精确 DST 边界）、6 项 hosted 测试、4 项 UI 测试；模拟器截图覆盖「到点前只有卡片」「到点后自动弹出海报」「已读后冷启动不再弹出」「海报缺失不自动弹空 Sheet」。
- **已执行（独立审核）**：另一只读审核者以 `e7d348b8` 为精确 revision 复核并要求无阻塞修改，结论 APPROVE；其非阻塞项中的前台刷新时序、语言重载竞态与截图流程健壮性已修复并重验。审核 diff 与最终提交为同一 patch 语义，最终提交 rebase 到 `origin/dev`（`eaac2a5b`）。
- **未执行**：L1–L3 内容生成与审核（本轮复用既有发布），APNs 发送，真机安装/显示/点击，实体海报二维码扫描，`TONGXING_LIVE_POSTER_SMOKE` 实时冒烟与 App Store 截图流程（Release 构建、需环境变量），生产内容构建的设备验收。

## 遗留状态

- 推送预检计划 `artifacts/ios-push-20261101-preflight/plan.json` 已于 06:57:04Z 过期，不能复用；08:00 本地时间的发送必须重新生成计划。
- 预检记录中的 `codeCommit` 为预检当时的仓库 revision `ce293ecd`（当时工作分支）；iOS 提交最终 rebase 到 `origin/dev` 后为 `eaac2a5b`，两者内容只差本报告的 iOS 修复与 dev 历史。
- iOS 改动提交 `eaac2a5b` 在分支 `feat/week8-push-poster-auto`；仓库内尚无包含该提交的分发构建，现有商店/Beta App 不会自动弹出海报。
- 所有原始产物在忽略目录 `artifacts/`；本报告只含脱敏副本。

## 外部可见的变化

本轮没有对外发布：没有推送 APNs、没有 Firebase/Hosting 发布、没有 TestFlight 上传。外部可见变化仅为分支提交与草稿 PR（报告 PR 另开，只含 `docs/reports/runs/`）。推送发送与设备验收按各自运行单独记录。
