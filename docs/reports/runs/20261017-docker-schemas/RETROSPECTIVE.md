# 复盘：20261017-docker-schemas

## 结论先行

交付类型：测试。Dockerfile 增加 `schemas/` 复制；定向现有后端测试通过，宿主环境的 `sermon-unified-production-event-v1` schema validator 加载通过，`git diff --check` 通过。当前环境没有 `docker` 命令，实际镜像构建与容器内读取未验证。

## 总时间

这组短检查没有可靠的统一起止时间，不能分解计算、等待与返工，也不与历史运行比较。

## 各层模型、耗时与速度

L1 至 L4 生产阶段均为 `not_run`。没有模型调用、token、音频处理或费用。

## 错误

最初的定向测试未显式设置工作树的 package 路径，解析到主检出；修正 `PYTHONPATH` 后定向测试通过。`docker` 不存在（退出码 127），因此镜像构建和容器内 smoke 未执行。

## 可以改进的地方

在具备 Docker 的 CI 或构建主机上，对新镜像做干净构建，并从容器内以无凭据只读方式加载一个实际 schema validator。该检查是本批仍欠缺的镜像交付证据。

## 实际覆盖范围

本地检查只覆盖 Dockerfile 差异、现有后端 Docker 命令合同及宿主 schema 加载。代码修复仅将根 `schemas/` 复制到 `/app/schemas/`；没有改变 Python 实现、schema 内容、运行身份或生产流程。容器实际资源存在性仍待验证。

## 遗留状态

无远端 job、发布产物或待清理资源。代码在独立分支，报告通过单独文档 PR 交付。

## 外部可见的变化

无镜像推送、Dev 发布、TestFlight、HTTP、设备或场地验收；均为 `not_run`。
