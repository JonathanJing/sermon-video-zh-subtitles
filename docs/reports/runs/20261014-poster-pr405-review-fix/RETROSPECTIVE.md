# 复盘：20261014-poster-pr405-review-fix

数据见同目录 INDEX.md 和 manifest.json。未填写的小节删掉前请写明原因。

## 实际覆盖范围

本轮是 PR #405 海报渲染修复的本地验证，不是四层讲道生产：L1–L3 均 `not_run`；L4 只执行本地海报渲染与检查，没有发布。`summary.json` 记录 13 个布局用例、26 张 PNG、26 张双二维码解码验证、10 个机器内容披露用例、3 个长元数据用例及 17 个通过的单元测试。PNG 本身按报告策略未复制，结论仅以脱敏的 `summary.json` 和 `outcome.json` 为证。

## 结果和结束信号

`outcome.json` 的结束信号是 `status=passed`、`stage=local_renderer_review`。`summary.json` 的状态是 `passed_local_renderer_review`，并明确 `published=false`、`humanApproval=false`。因此本报告只证明本地渲染、代表性预览检查和二维码解码检查通过，不证明发布、人工批准、设备显示或现场验收。

## 耗时

报告未复制 `timings.tsv`，`outcome.json` 也没有起止时间；无法从现有证据计算墙钟、计算、等待或返工时间，也无法与上一轮作数值比较。

## 错误

本报告没有记录失败或错误。回归覆盖为 17 个单元测试、13 个布局用例，以及 26 张 PNG 的双二维码解码；具体修复提交不在本报告证据内。

## 占用资源之后才暴露的错误

`not_applicable`：现有报告没有记录占用远端资源或占用资源后才发现的错误；全部证据来自本地渲染检查。

## 遗留状态

报告未记录 Dev 文件、job hold 或构建号。源运行生成的 26 张 PNG 未纳入公开报告；其本地保留或清理状态不在本报告证据内。

## 外部可见的变化

Dev 发布 `not_run`；TestFlight `not_run`；设备显示 `not_run`；现场验收 `not_run`。`summary.json` 明确 `published=false`，本报告也没有受保护分支推送证据。

## 后续

没有从本报告产生新的修复项。若需要性能比较，应在下一次同类本地渲染验证中补采 `timings.tsv` 或带起止时间的 `outcome.json`；本报告未指定负责人或跟踪条目。
