# 复盘：20261017-docker-schema-final-image-smoke

## 结论先行

交付类型：测试。PR #596 当前头部 `34ffd1ca` 的镜像资源工作流 39044491505 在重新运行后成功：构建后端 Docker 镜像，并在容器内通过生产 schema loader 读取 `sermon-app-delivery-v1` validator。未发布镜像或部署服务。

## 总时间

这次重新运行含 runner 排队和镜像构建；没有独立的纯计算、等待与成本分解，不推算速度。

## 各层模型、耗时与速度

L1–L4 均为 `not_run`；无模型、token、音频或费用。

## 错误

同一工作流的首次尝试在镜像构建中途被取消，不能算通过；重新运行的 `resource-smoke` job 完整成功。此前 Python CI 和取消状态另由 #620、#621 记录。

## 可以改进的地方

保持镜像构建与容器内资源读取同时验证，防止只在宿主源码树找到 schema。

## 实际覆盖范围

GitHub Actions 的 Docker build，以及容器内 `schemas.validator("sermon-app-delivery-v1")`。没有验证真实 Cloud Run 部署、运行中 API、其他 schema、Terminology 资源或外部设备。

## 遗留状态

#596 仍为草稿；Python tests 当前头部的全量运行尚在队列。镜像未推送。

## 外部可见的变化

无部署、HTTP 读回、设备或场地验收。
