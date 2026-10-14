# 复盘：20261011-feedback-api-deploy-r14-verified

数据见同目录 `INDEX.md`、`manifest.json` 与 `evidence/outcome.json`。

## 结论先行

- **高置信结论：** feedback API revision `sermon-feedback-api-00014-bej` 部署后为 ACTIVE 并承接 100% 流量；GET `/api/session` 返回预期的 405，7 个本地 source case 通过且 unknown source 被拒绝。
- **证据边界：** 浏览器三语 session smoke 为 `not_run`；HTTP 405 只验证 method guard，不证明真实 POST session、三语 UI 或端到端反馈流程。
- **处置建议：** `MERGE_AFTER_SYNC_AND_GREEN`。本复盘已补齐；合并报告不等于浏览器验收完成。

## 实际覆盖范围

- 在 dev project 的 `us-west1` 部署 feedback API revision r14，并检查 function ACTIVE、ready revision 与流量切换。
- 对 GET `/api/session` 做 method-guard smoke，期望并得到 HTTP 405 `method_not_allowed`。
- 本地 catalog validation 覆盖 7 个 source case，并确认 unknown source 拒绝。
- 未执行讲道 L1–L4、内容发布、iOS 构建、浏览器三语 session、设备或场地验收。

## 结果和结束信号

- `evidence/outcome.json`：`status=passed`，revision `sermon-feedback-api-00014-bej`，`trafficPercent=100`，HTTP status 405。
- detail 记录 deploy exit 0、function ACTIVE、ready revision 接收 100% 流量。
- browser smoke 明确为 `not_run`；outcome 没有独立 startedAt/endedAt 或 runner exitCode 字段，不能补写。

## 耗时

- 报告没有 `timings.tsv` 或部署起止时间，不能给出部署、流量切换、HTTP 检查的精确耗时，也不能与上一 revision 比较性能。

## 错误

- 已导出证据没有部署错误；GET 405 是预期结果，不是失败。
- 由于未运行真实 POST/session 与浏览器三语 smoke，不能判断这些路径是否存在错误；状态为 `not_run`，不是 pass。
- 本地 7 个 source case 通过与 unknown source 拒绝来自 outcome detail；报告未导出逐 case receipt，不能扩大为所有 catalog 输入通过。

## 占用资源之后才暴露的错误

- 没有已知部署后错误。浏览器 smoke 未执行，因此不存在可评价的浏览器后置错误证据。
- 部署已切换 100% 流量；若真实 POST 路径有问题，本报告的 GET 405 smoke 无法在切流前证明它，后续应将真实只读/可回滚 smoke 前移到流量切换验证。

## 遗留状态

- 前一 revision 为 `sermon-feedback-api-00013-xom`；rollback source 已保存到本地 artifacts，但 rollback 未执行。
- r14 当前承接 100% 流量。报告没有未结束 job、锁或其他远端资源收据。
- 浏览器三语 session smoke、设备与 UI 验收仍待执行。

## 外部可见的变化

- dev feedback API 的 active revision 与流量已从 r13 切换到 r14；这是实际外部部署变化。
- 没有 Firebase 内容页发布、TestFlight、讲道设备播放或场地验收；均为 `not_run` 或未涉及。

## 后续

1. 维护者应在单独、绑定 r14 revision 的收据中运行三语浏览器 session smoke，并覆盖真实允许的方法；本报告的 405 不能替代该验收。
2. 若 smoke 失败，应使用已保存的 r13 rollback source 按部署 runbook 评估回滚；本报告不授权或记录已回滚。
3. 报告流程继续由 `DEV-RUNREPORT-001` 跟踪；本 PR 合并前同步 `dev` 并保持 docs-only CI 绿色。
