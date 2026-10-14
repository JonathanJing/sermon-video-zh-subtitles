# 复盘：20261013-clip-real-e2e-r2-layer4

数据见同目录 INDEX.md 和 manifest.json。未填写的小节删掉前请写明原因。

## 结论先行

本轮只证明复用既有机器检查包后，诊断级 Dev L4 能完成发布与 HTTP 回读，最终信号为 `diagnostic_dev_http_verified`。`formalContentApproval=false`，模型/API 调用为 0，Beta 构建和设备播放未执行，因此不是正式发布或设备验收证据。

## 实际覆盖范围

L1–L3 未在本轮重跑，复用前序机器检查包；本轮仅执行 L4 Dev 诊断发布。没有人工内容审批，也没有把机器豁免提升为人工批准。

## 结果和结束信号

执行最终信号为 `diagnostic_dev_http_verified`，页面为 `mockup-dev-clip-real-20261013b`。工作流 wall time 为 160.881493 秒；模型/API 请求、token 与费用均为 0。

## 耗时

报告没有导出 `timings.tsv`；只可引用执行日志中的 160.881493 秒 wall time，不能进一步拆分等待/计算，也不能与上一轮作同口径比较。

## 错误

未导出失败阶段或重试。此结论只覆盖 L4 诊断发布路径，不覆盖前序 L1–L3 的内容或音频问题。

## 占用资源之后才暴露的错误

无此类错误；本轮没有进入 Spark 或付费模型路径，不能用它评价这些资源路径的预检覆盖率。

## 遗留状态

报告未导出本地清理清单；本轮没有 Spark round、job hold 或 Beta 构建号。Dev 资产当前引用关系需以托管清单另行核对。

## 外部可见的变化

Dev 执行 asset-first 与 final-overlay 两次托管发布，日志记录版本 `b5cb66079b392c33` 与 `f7db1f0d7a93c6a9`，并完成诊断 HTTP 回读。正式内容审批为 `false`；TestFlight、Beta 构建、设备播放和场地验收均为 `not_run`。

## 后续

- 报告维护者：仅把本报告作为诊断 L4 证据；跟踪项 `DEV-RUNREPORT-001`。
- 发布负责人：正式发布须绑定有效 L1–L3 身份与人工批准，并另存设备/发布回执。
