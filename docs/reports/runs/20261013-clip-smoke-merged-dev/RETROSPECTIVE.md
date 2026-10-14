# 复盘：20261013-clip-smoke-merged-dev

数据见同目录 INDEX.md 和 manifest.json。未填写的小节删掉前请写明原因。

## 结论先行

本轮只证明合并后代码能够完成诊断级 Dev 发布冒烟：最终信号为 `diagnostic_dev_http_verified`，模型/API 请求、token 和费用均为 0。它不包含正式内容审批、Beta 构建、设备播放或场地验收，不能作为正式四层发布已获准的证据。

## 实际覆盖范围

L1–L3 仅使用冒烟输入与模拟内容，不形成正式内容包；L4 在 Dev 上执行诊断级页面发布与 HTTP 回读。`productionEligible=false`，正式内容审批未执行。

## 结果和结束信号

`build-inputs`、`baseline`、`delivery-preflight` 和 `delivery-execute` 均通过；执行最终信号为 `diagnostic_dev_http_verified`。基线记录 `complete_verified_not_deployed`（636 个 live 文件，其中 634 个 public、2 个 managed），预检为 `validated_not_deployed`。

## 耗时

导出耗时为：构建输入 9 秒、基线 20 秒、预检 3 秒、执行 171 秒；执行日志内的工作流 wall time 为 168.501662 秒。报告没有导出可把等待与计算进一步拆开的数据，也没有同口径上一轮基线。

## 错误

未导出失败阶段或重试；模型/API 请求数、token 与费用均为 0。该结论只覆盖本报告所列日志，不代表正式内容路径无错误。

## 占用资源之后才暴露的错误

无此类错误：预检通过后执行也完成诊断回读。由于本轮没有进入付费模型或 Spark 路径，不能据此评价这些资源路径的预检覆盖率。

## 遗留状态

报告未导出 Spark round、job hold 或本地清理回执，因此这些状态不能由本报告确认；本轮没有 Beta 构建号。Dev 资产是否仍被引用应以当前托管清单另行核对。

## 外部可见的变化

Dev 执行了 asset-first 与 final-overlay 两次托管发布，日志记录版本 `48c4be794623a7c1` 与 `71948af0d2b436f5`，随后完成诊断 HTTP 回读。正式内容审批为 `false`；Beta 构建、设备播放、TestFlight 与场地验收均为 `not_run`。

## 后续

- 报告维护者：把本报告作为合并后诊断冒烟证据，不提升为正式发布证据；跟踪项 `DEV-RUNREPORT-001`。
- 发布负责人：如需正式发布，另起绑定真实 L1–L3 包和人工审批的 L4 运行，并保留发布与设备验收回执。
