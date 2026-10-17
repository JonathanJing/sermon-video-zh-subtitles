# 复盘：20261017-wheel-resources-final-ci

## 结论先行

交付类型：测试。PR #592 头部 `f8f1b521` 的 Python tests 工作流 39043634027 成功：8 个 root 分片、`unittest` 汇总及 native-client 检查均通过。此结果只证明代码和 CI，未执行生产发布或设备验收。

## 总时间

各分片并行运行，包含 runner 排队；本报告没有可核算的纯计算时长或成本，不推断速度改善。

## 各层模型、耗时与速度

L1–L4 生产均为 `not_run`；无模型、音频处理、token 或费用。

## 错误

最终 CI 无失败。前一次 CI 的 wheel 隔离测试受 editable `.pth` 路径影响，修复过程由报告 #609 记录。

## 可以改进的地方

继续让 wheel 测试从仓库外安装目录导入，并同时排除 `PYTHONPATH` 和解释器已有的 editable 源路径。

## 实际覆盖范围

GitHub Actions run 39043634027：8 个 Python root 分片、汇总和 native-client 成功。新测试验证非 editable wheel 中两个 Swift 模板资源的字节及两个旧 CLI 的 `--help`。未检查真实容器部署、App 播放或生产运行。

## 遗留状态

PR #592 仍待合并；只有代码与测试产物，没有发布产物。

## 外部可见的变化

无 Dev 发布、HTTP、TestFlight、设备或场地验收；均为 `not_run`。
