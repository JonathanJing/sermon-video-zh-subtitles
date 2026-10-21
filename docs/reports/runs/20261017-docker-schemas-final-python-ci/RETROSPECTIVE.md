# 复盘：20261017-docker-schemas-final-python-ci

## 结论先行

交付类型：测试。Docker schema 资源 PR #596 的头部 `34ffd1ca` 在 Python tests 工作流 39044491446 中成功：8 个 root 分片、`unittest` 汇总和 native-client 检查通过。容器构建及内置 schema loader 另由 #628 记录。没有部署服务。

## 总时间

并行 CI 包含 runner 排队；未拆分纯计算与等待，也没有可比的生产耗时或成本。

## 各层模型、耗时与速度

L1–L4 生产均为 `not_run`；无模型、token 或费用。

## 错误

本轮无失败 job。镜像资源工作流的首轮取消与重新运行详见 #628；不能把取消计作通过。

## 可以改进的地方

Dockerfile 资源变化继续由镜像构建和容器内 loader 验证，Python CI 补充回归，而非只检查宿主源码树。

## 实际覆盖范围

GitHub Actions run 39044491446 的 8 个 Python root 分片、汇总和 native-client 成功。容器内只验证一个生产 schema loader，未覆盖全部资源或真实 Cloud Run 部署。

## 遗留状态

#596 待合并，#600 术语资源 PR 依赖它。无发布镜像或服务。

## 外部可见的变化

无部署、HTTP、设备或场地验收。
