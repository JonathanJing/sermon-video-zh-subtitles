# 复盘：20261009-l3-l4-auto-handoff

## 实际覆盖范围

- 运行 `tests.test_backend_four_layer_dry_run`：9 项通过，其中新增两项验证每种语言 L3 成功后自动进入 L4、L4 复制文件 SHA 与 L3 产物一致；以及 L3 失败时不创建 L4 预览。
- 运行 `scripts/evaluate_backend_four_layer_dry_run.py`：成功路径及 L1、L2、L3、L4 失败注入均符合预期，未触达的故障点被拒绝。
- 本流程使用固定夹具和合成测试音，外部调用均为 0；不代表正式包、真实模型、人工听审或发布验收。

## 结果和结束信号

- `run-01/outcome.json`：succeeded，exit 0。
- unittest 与官方 evaluator 均通过。首次直接调用系统 Python 因缺少 `jsonschema` 在导入阶段失败，未进入测试；使用仓库要求范围内已存在的临时依赖目录重跑成功，未修改系统 Python。

## 耗时

- unittest：0.738 秒。
- 官方 evaluator：0.470 秒。

## 错误

- L3 正常完成后，L4 自动开始；逐 locale 的 L3 `endedAt` 不晚于 L4 `startedAt`，复制到预览目录的媒体 SHA 与该 locale 的 L3 receipt 相同。
- 注入 `layer3:ko` 失败后未生成 L4 层，也没有预览 HTML；Dev 导入器拒绝该失败运行。
- 增补回归位于 `tests/test_backend_four_layer_dry_run.py`。正式生产的 callback adapters 与 durable release 仍未接入该 dry-run 编排。

## 占用资源之后才暴露的错误

- 无。本轮仅本地模拟，无 Spark/GPU、网络或 provider 调用。

## 遗留状态

- 本地报告与评估收据保留在忽略目录 `artifacts/`。

## 外部可见的变化

- 未部署 Dev/Firebase、未发布正式 release、未做设备或现场验收。

## 后续

- 按仓库运行报告流程公开本脱敏报告；测试改动提交并推送到当前工作分支。
