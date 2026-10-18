# 复盘：20261017-pr607-dual-pdf-timeline-ci

## 结论先行

交付类型为测试。PR #607 精确提交 `4baa3cf8` 的 workflow_dispatch Python CI run `39069811515` 通过：八个 root 分片与汇总成功，Native/shared contracts 跳过。仅证明合成 CI 和本地测试，不证明真实下载或 PDF 发布。

## 总时间

报告无 journal、timings 或起止时间，无法核实墙钟、等待、返工或历史比较。

## 各层模型、耗时与速度

L1–L4 均 `not_run`；无模型调用、token、音频或费用。

## 错误

该次 CI 无失败；跳过的 Native/shared contracts 不作通过声明。

## 可以改进的地方

流程：后续 CI 摘要记录 job 时间；依据是当前无法核实墙钟，收益是区分排队与执行。负责人为 CI 报告维护者；无单独跟踪项。

## 实际覆盖范围

覆盖 timeline move 在 #602 合入后的八分片 Python CI；真实 post-live 媒体、PDF、HTTP、设备和场地未执行。

## 遗留状态

报告未记录 job hold、Dev 文件、构建号或本地产物清理状态。

## 外部可见的变化

仅 CI 与本报告 PR；发布、TestFlight、设备和场地验收均 `not_run`。
