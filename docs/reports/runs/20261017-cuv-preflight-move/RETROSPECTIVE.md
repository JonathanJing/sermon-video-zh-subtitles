# 复盘：20261017-cuv-preflight-move

## 结论先行

交付类型为本地代码测试。`outcome.json` 记录通过；66 项定向测试执行，65 项通过、1 项跳过。只验证 CUV 预检、缓存复用、旧路径别名与主脚本的模拟执行；未运行真实生产或模型调用。

## 总时间

三组成功测试分别用时 1.841、22.927 和 0.012 秒，合计约 24.8 秒。未记录整轮起点、等待或返工时长，不能据此推算完整墙钟时间。

## 各层模型、耗时与速度

L1–L4 的真实生产阶段均未执行。CUV 测试用替身响应验证调用与缓存行为；付费模型调用 0，费用 0。无真实模型速度数据。

## 错误

首次用系统 Python 运行时，因缺少 `jsonschema` 而在测试收集阶段失败；改用仓库虚拟环境和本 worktree 的 `PYTHONPATH` 后，三组定向测试均通过。该失败没有执行模型或生产阶段。

## 可以改进的地方

后续复测直接使用仓库虚拟环境并明确设置 worktree 包路径，避免把主 checkout 的 editable package 误认为当前实现。

## 实际覆盖范围

`tests.test_cuv_preflight` 与 `tests.test_cuv_incremental_reuse`：12 项通过；`tests.test_sermon_cuv_translation`：48 项通过；`tests.test_infrastructure_path_aliases`：6 项执行，5 项通过、1 项跳过。旧/新实现文件 SHA-256 一致；`scripts.cuv_preflight` 与包导入指向同一模块。真实 CUV 审稿、发布、设备验证均未执行。

## 遗留状态

本地代码分支待上游评审。旧冻结运行必须在其原 checkout 续跑；新的 L2 code identity 会因包文件与门面变更而变化。

## 外部可见的变化

未 push、开 PR、部署或发布。
