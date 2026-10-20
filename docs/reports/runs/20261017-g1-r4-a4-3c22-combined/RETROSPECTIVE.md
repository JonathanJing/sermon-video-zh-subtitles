# 复盘：20261017-g1-r4-a4-3c22-combined

## 结论先行

测试交付。#582 以普通 merge 同步 #588 `3c22a7a3`，再保留 R4 的 legacy 同对象门面并恢复 `scripts/tongxing_host.py` 到与 A4 相同的字节。最终 head `c0e2a9c5` 已推送并远端读回。四模块 17 tests、五模块 30 tests、run-start 两次 27/28 tests、最终 closure-path 单测 1 test 均通过。另有一次测试选择器写错类名，退出码 1，修正选择器后通过；该错误不是产品代码回归。

## 总时间

五次成功测试的程序耗时分别为 0.246、0.384、2.654、2.529、0.009 秒；完整开发/等待墙钟未记录。选择器错误的程序耗时不足 0.001 秒。

## 各层模型、耗时与速度

L1–L4 生产阶段均为 not_run。本轮只运行本地合成测试和 mock SSH，未产生付费模型、Spark 作业或费用收据。

## 错误

测试命令首次写成不存在的 `CheckTests`，unittest 发现失败（退出码 1）；改成实际的 `StartCheckTests` 后目标单测通过。手写 off-CWD 断言曾把 `QcRuntime` 惰性加载器本身与模块对象比较；改为调用加载器后两种导入顺序均通过。

## 可以改进的地方

保留 host 的 legacy 同对象门面可保持 G1 身份；新增 closure-path 测试对 28 个键逐一核对 package 解析，并模拟远端 `sha256sum` 正确与错误摘要。预期在发送 Spark 运行前发现路径或字节偏差。负责人为 R4 集成工作，跟踪 #582。

## 实际覆盖范围

覆盖统一复核、实现冻结、run-start drain、音频/review 端口及 run-start 工具；额外验证 off-CWD 导入顺序、惰性 host 绑定、28 个 closure 文件的远端命令和本地四身份相等。W/T/scoring/rate 在 A4 与 R4 本地均为 `38cf46dd`/`d32c3865`/`c7d8c5ab`/`71064724`。未执行真实 L1–L4、校准、发布或设备验收。

## 遗留状态

#582 仍待 exact-head CI、代码/安全审查；合并须等待 G1 最终代记录。没有生产 job hold 或构建号。

## 外部可见的变化

#582 工作分支已推送；此报告为 docs-only 草稿 PR。未合并 dev、未发布或现场验收。
