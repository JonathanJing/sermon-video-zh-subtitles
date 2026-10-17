# 复盘：20261017-g1-cascade-v2-r4

## 结论先行

测试交付。#582 接入 #588 最新 head，无合并冲突；两组定向测试共 120 项，119 通过、1 跳过，diff check 通过。严格 L2 未知结果重试探针与 G1 的 audio、review、jobs、path alias、QC 闭包入口已覆盖。未运行真实作业或付费模型。

## 总时间

两组有效定向测试 20.121 + 6.990 秒；完整开发与等待墙钟未记录。

## 各层模型、耗时与速度

L1–L4 未执行；模型调用 0、费用 0，无模型速度数据。

## 错误

测试中的预期错误路径打印五条 `SERMON_LOGGING_WRITE_FAILED`。单独运行重试探针时首次误写类名 `StrictLayer2Tests`，加载错误退出 1；改用实际 `StrictAdapterTests` 后通过。没有代码修复。

## 可以改进的地方

单测选择器先核对类名；下一步在最终集成提交上跑更广的 CI。

## 实际覆盖范围

覆盖 accounting contract、observability、strict Layer 2 retry、Review、G1 audio/jobs/path aliases/QC closure；未做真实任务派发、跨机恢复、校准或发布验收。

## 遗留状态

#582 仍为草稿；G1 merge gate 未开放。

## 外部可见的变化

只推送 #582 工作分支和本 docs-only 报告 PR；未合并 dev 或发布产品。
