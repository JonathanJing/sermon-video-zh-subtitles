# Durable job 的目录持久化边界

本批延续 E4 crash-window 与 #131 的 decision-budget 修复，复用 `sermon_workflow_jobs.py`，没有新建队列、自动重试或改变 side-effect 权限。

## 修正的窗口

旧 `start_job` 在 worker 启动前同步 request/state 和 job root／直接父目录，但 `mkdir(parents=True)` 可创建更深的目录。祖先目录的新增入口尚未持久化时，主机／文件系统崩溃可能使已执行工作的整段证据路径丢失。仅记录“调用前哪些目录不存在”也不充分：另一个 admission 可能刚创建这些目录，存在不代表持久化完成。

现在在外部工作前依次同步 lock inode、`.locks` 目录，以及 job root 到同一文件系统根部的完整目录链，再持久化 request／queued receipt 后启动 worker。跨文件系统的挂载点视作预先存在的环境基础设施，不尝试持久化另一个文件系统的父目录。任何同步失败都传播错误，worker 不启动；已建立的不完整 job 目录继续按 `uncertain` 处理，不自动清空或重新执行。

Decision budget 使用同一目录链同步函数，保留 reservation-before-responder、未知结果阻断与每 production run 两次总预算。原 `peek_job` 的只读检查路径不调用写入或同步函数。

## 证据与限制

回归覆盖新建多层目录、预先存在但可能尚未持久化的祖先、lock／目录链各处同步失败、queued request 在 spawn 前存在，以及重启后的不重复执行。既有真实短进程、跨进程去重、owner 丢失、timeout、controller crash-window 与 decision logging-failure 测试继续运行。

这是调用顺序与故障注入证据，没有实际断电或模拟整个文件系统；依赖操作系统／文件系统遵守成功返回的 fsync 持久化语义。不声称生产模型、真实媒体、设备或现场验收。本批将既有 durable job suite 纳入 Stage 0 组件清单，Stage 0 人工 sign-off 与 canonical runner 尚未完成。
