# 固定 Layer 2 的运行心跳与无进展超时

固定 L2 worker 现在在既有 durable job request 中绑定 `sermon-job-liveness-v1` policy。`sermon_workflow_jobs` 仍是唯一进程所有者，继续使用既有 guarded process group 和锁来终止任务及子进程；没有第二套调度器或自动重试系统。默认 shadow 不创建心跳、锁或其他文件。

| 约束 | 当前固定 L2 policy | 依据/含义 |
|---|---|---|
| command startup | 60 秒 | 受控命令启动后，必须完成固定入口准入并写入第一条 liveness receipt |
| heartbeat interval | 30 秒 | 活跃 reporter 独立发送存活信号；不等于完成工作 |
| heartbeat timeout | 90 秒 | 观察不到递增 heartbeat sequence 即停止本地命令 |
| no-progress timeout | 900 秒 | 没有实际 producer checkpoint 即停止，即使心跳仍活跃 |
| execution deadline | 21,600 秒 | 保留原总上限，另由上述较短的专项限制约束 |
| provider attempt | 1 | 沿用既有 `chat_json(..., retries=1)`，其 HTTP timeout 仍为 300 秒 |
| automatic retry | 0 | 同一身份不 respawn；有完整返回缓存或候选时只能显式恢复/对账 |

这些是本地保护边界，不是已经实测的生产 SLA、速度收益或真实媒体阈值。初始 queued owner 尚未启动就死亡仍走原 owner/lock reconciliation，不宣称该表实现了另一个持久后台 queue watchdog。未实现全局 API/TTS 资源预算或 Layer 1/3/4 专属心跳策略。

## 证据、进展与失败

`liveness.json` 是 job 目录中的私有可变运行证据，绑定 exact job/request hash。writer 在受控命令第一步前持久化，周期 heartbeat 只增加 sequence；Source 准入、模型请求开始、响应缓存已保存、完整模型证据与候选验证等实际工作才增加 progressSequence。模型返回值先由已有 producer 持久保存 raw/parsed cache，再写进展检查点；心跳写失败不能丢掉已经返回的付费结果。

monitor 用本机 monotonic 计时，只接受有序、有限、绑定正确且大小受限的普通文件。mtime 或 wall clock 不能延长截止时间，symlink/损坏/重放/回退/冲突 sequence 都 fail closed。退出零码还必须有 finished receipt；它也不替代候选 validator、人工审批或页面状态。

心跳、启动、无进展、缺完成收据等失败保留为 uncertain 并继续阻塞重复执行。取消通过现有 process-group/guardian 链清理；即使本地子进程已停止，也不能推断远端模型取消或未收费。原始请求、缓存与失败事实保留，candidate 完成但 job 未确认的窗口沿用显式 artifact reconciliation。

政策改变属于执行身份改变：旧 request 不被默默升级。原代码/request 的在途任务、跨版本迁移、未知付费调用仍需独立工程对账；不通过新 tick 或替换配置扩大预算。

## 本地证据与边界

回归覆盖 monotonic 时钟、heartbeat 与进展分离、无/坏/过大/符号链接收据、非法 policy、持久化失败、真实短子进程与后代取消、无完成收据的零退出、同一身份不重复启动、固定 L2 producer 的实际检查点，以及响应缓存先于失败检查点保存。响应均为固定合成夹具，空 key CLI 没有真实 API 调用。

本子项不是完整 E4 或 Stage0 完成标签。真实片段、10分钟、整篇、第二周以及工程/内容/兼容性/设备/现场验收门槛保持不变。

审查补充：每次 poll 在读取前及读取后、接纳更新 sequence 前检查原截止时间。已经超过 startup/heartbeat/no-progress 的任务锁定失败；迟到的首条、progress 或 finished receipt 不能续命，`completed()` 同样受此约束。fake-clock 回归在旧代码复现了 4 个失败断言，并覆盖读取本身跨越期限的窗口。
