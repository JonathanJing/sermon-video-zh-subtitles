# 复盘：20261017-docker-schemas-python-ci

## 结论先行

交付类型：测试。Docker schema COPY 的提交 `76ca0947` 在 GitHub Python tests 工作流中 8 个 root shard 和汇总作业均成功。随后新增了真实镜像 smoke 工作流，本报告不能代表其结果。

## 总时间

运行平台未在此摘要保留完整起止时间；不推算耗时或与历史比较。

## 各层模型、耗时与速度

L1–L4 均为 `not_run`；无模型、付费请求、token 与生产速度数据。

## 错误

该 CI 运行没有失败 job。没有执行 Docker 镜像构建，因此还不能断言 schema 在容器里可读取。

## 可以改进的地方

已在下一提交加入镜像构建和生产 schema loader smoke，等待新工作流结果。

## 实际覆盖范围

GitHub Actions Python tests run `39042346824`，8 个 root shard、`unittest` 汇总成功，native client 检查跳过。当前 PR 头为后续 `34ffd1ca`，须以新头 CI 和镜像作业作为最终代码验证。

## 遗留状态

镜像 smoke run `39044491505` 待完成；无部署和容器发布。

## 外部可见的变化

无生产发布、设备或现场交付。
