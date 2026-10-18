# 复盘：20261017-l4-announcement-sidecar-migration-test

数据见同目录 `INDEX.md`、`manifest.json`，以及摘要所依据的脱敏 `outcome.json` 和 `summary.json`。

## 结论先行

交付类型为本地代码测试。L4 announcement sidecar 的字节保持迁移测试退出码为 0，4 项测试通过；旧、新入口在冻结时钟下生成的 sidecar、PNG 和 binding receipt 字节相同，外部工作目录下的 CLI 与模块别名也通过。该结果不证明生产运行或发布。

## 总时间

本报告没有保存运行起止或阶段计时，无法计算墙钟、计算、等待与返工时间，也没有同配置基线可比。

## 各层模型、耗时与速度

L1–L4 真实模型调用均为 `not_run`，模型调用数和网络请求数均为 0。推理强度、tier、token、音频秒数、费用与速度不适用。

## 错误

初次运行发现动态旧路径 loader 保留的 facade 模块缺少 digest/build 属性；通过 facade 的 `__getattr__` 委托修复。随后 3 个既有合成 binding 测试与新增的旧/新入口比较共 4 项测试通过，原始实现字节与冻结时钟产物比较也通过。

## 可以改进的地方

后续文件迁移应在首轮预检中同时覆盖外部工作目录的 CLI、模块别名和 facade 属性访问；这能更早发现仅导入成功、但运行时属性未透传的问题。

## 实际覆盖范围

覆盖 3 个既有合成 binding 测试、旧/新外部工作目录 CLI 与模块别名、实现文件字节比较，以及冻结时钟下 sidecar、PNG 和 binding receipt 的字节比较。未运行网络请求、真实输入、L1–L4 生产、页面发布、设备或场地验收。

## 遗留状态

本次本地迁移测试已通过；是否满足 PR 合并条件仍须独立查看该提交的云端 required checks。没有生产运行或发布状态可由本报告结算。

## 外部可见的变化

无外部变化。生产运行、页面发布、Dev 发布、TestFlight、设备播放和场地验收均为 `not_run`。
