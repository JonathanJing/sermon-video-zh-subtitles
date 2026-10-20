# 复盘：20261017-backend-image-resources-smoke

## 结论先行

交付类型：测试。#600 头部 `8de4dda5` 的 GitHub Actions 完整构建了 backend Docker 镜像，并在容器内通过生产 schema loader 与术语表 reader 读取资源，`resource-smoke` 成功。镜像没有推送或部署。#596 的较窄重复镜像作业在合并检查成功后被取消，不能视为 #596 该提交的单独成功收据。

## 总时间

合并检查 job 从 15:20:04 UTC 到 15:20:57 UTC，约 53 秒；不包含排队时间。#596 的取消作业未保留可比计算时间。

## 各层模型、耗时与速度

L1–L4 均为 `not_run`。没有模型、远程生产运行、token 或费用。

## 错误

合并检查没有失败。#596 的 schema-only 作业在运行中被取消，原因是其子分支 #600 的实际镜像检查已成功覆盖相同 schema 路径及新增术语表路径；取消不是代码测试失败。

## 可以改进的地方

在父子分支均改 Docker 资源时，先确定一个最终镜像头部，再派发一次合并检查，避免重复构建。

## 实际覆盖范围

GitHub run `39044515997`：Dockerfile 从本仓库上下文构建，容器内执行 `tongxing_production.contracts.schemas.validator("sermon-app-delivery-v1")` 和 `scripts.series_terminology.context()` 并确认非空。它验证容器资源和依赖加载，不能证明 HTTP 服务启动、线上部署或运行时凭据。重复父分支 run `39044491505` 为取消状态。

## 遗留状态

#596 和 #600 均为草稿，待按依赖顺序合并。尚无部署后的 HTTP 读取或生产验收。

## 外部可见的变化

仅 CI 测试结果；镜像未发布，用户或设备不可见。
