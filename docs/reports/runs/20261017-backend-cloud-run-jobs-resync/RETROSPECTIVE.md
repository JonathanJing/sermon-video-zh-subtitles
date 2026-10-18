# 复盘：Cloud Run job dispatcher 包化合并后本地复测

## 结论先行

从已合并的 #846 完整 head 同步至 `dev` 后，迁移分支保留原两个代码提交并新增无冲突合并提交。44 个定向测试通过；`uv` 构建 service wheel 与 sdist，仓库外安装 wheel 后，新旧导入指向同一模块对象。所有请求使用假 session，未派发 Cloud Run Job。Docker 镜像检查未在本机运行。

## 总时间

没有保存统一起止时间，不能推算本轮总墙钟或等待拆分。定向测试约 0.2 秒，wheel 构建约 1.1 秒。

## 各层模型、耗时与速度

L1–L4 均 `not_run`；实际模型调用和 Cloud Run 请求均为 0。没有 token、音频或费用指标。

## 错误

本轮同步及定向检查没有错误。Docker/Podman 可执行文件均不可用，镜像构建留给 CI。

## 可以改进的地方

等待本分支 exact-head 的 backend image workflow：它应构建包含 `services/api` 的镜像，并校验新旧模块及 `backend.app` 的调度绑定。

## 实际覆盖范围

覆盖假 session 的资源边界与 POST payload、API handler 调度 patch、新旧模块同一性、wheel 安装后的仓库外导入。未覆盖真实 Google 凭据、Cloud Run API、镜像启动或已部署服务。

## 遗留状态

没有远端任务或生产产物；本地构建产物在临时目录。CI 终态待观察。

## 外部可见的变化

这份报告记录本地复测。代码和报告 PR 在后续步骤创建；没有部署或设备验收。
