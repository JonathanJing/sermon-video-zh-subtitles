# 本地三分钟预加载与 batch 实验协议

目标是同一三分钟样本下比较模型加载、first generation、warm reuse 和 batch 1/2/4 的完整耗时，再依据证据调整运行参数。本轮不训练权重，不重跑整条视频，不调用付费外部 API。

统一日志使用[已有 accounting 合同](workflow-accounting-log-contract.zh.md)及[本地测量扩展](../experiments/local_experiment_log/README.zh.md)。L1–L4 是业务层；这轮复用冻结的源/文本，只执行 L3。MacBook、Mac mini、Spark 是执行位置，缺少 MacBook 客户端时只能报告 Mini/Spark 验证，不冒充完整客户端往返验收。

## 启动条件

每次实验冻结 source window、媒体/中文 spoken units、授权来源、checkpoint、代码与 runtime hashes；保持顺序、分段、speaker、精度、attention、生成参数一致。源码支持 batch 不等于已部署入口支持 batch，目录存在不等于权重/CUDA 已验证。计划模板在 experiments/local_experiment_log/experiment-plan.template.json，必须填入实际身份与准入引用。

模型运行必须通过保护既有常驻生产工作负载的、获准且有期限的隔离/资源准入机制。需要排队、资源窗口、timeout、worker lifetime、失败和退出回执；只限制容器 CPU/memory 不能证明 GPU 隔离。不能扩大现有 cpu_smoke gate，不能直接复用绕过全局调度的 legacy SSH/SCP GPU launch。没有任务注册或字节 API 时，不创造生产 endpoint。回收使用审查过的路径并验证 job/attempt/trial、byte count、SHA256。

## 固定样本与矩阵

默认使用同一授权的 180 秒源音频及对应冻结中文 units，比较全部完成耗时。源音频三分钟不保证输出音频三分钟。若选择每组 180 秒 wall_budget，应另设 duration_mode/budget_scope，准备足够冻结负载，仅计预算内完成并通过校验的 units，不与固定样本结果混合。

| 策略 | batch | 重复与生命周期 |
|---|---|---|
| cold：每 trial 新进程加载一次 | 1、2、4 | 各 3 次，不是每 unit 加载 |
| warm：获准 resident worker 复用 | 1、2、4 | 3 个 session，每 session 加载一次并各运行一次 batch |

共 18 trials，逐个执行；session 内顺序轮换 1/2/4、2/4/1、4/1/2，让首轮推理覆盖不同 batch。初轮不扫描 8/16，不隐含 dummy warmup，不复用已生成音频，不自动重试。worker/PID 不变、load_count=1 及实际生成字节共同支持 preload 复用。OOM、timeout、缺字节、输出质量问题或资源窗口变化即停，保留失败并写 backlog。

## 测量与验收

记录完整请求/返回、准入/queue、model load、首批与后续 batch、写盘/回收耗时，以及实际 batch/返回 wave 数、有效 units/s、characters/s、音频秒数、RTF、worker RSS、CUDA allocated/reserved/peak、UMA 系统可用内存与其他 compute processes。CUDA 区间在开始/结束同步，记录计时策略和开销。不可跨机器相减单调时钟。

session 从创建到退出计完整成本，preload load 只计一次；请求延迟与 session 成本并列。1 次、3 次等摊销明确标为计算，不冒充额外实测。first generation 与 subsequent generation 分开，不把输出缓存算作 warm reuse。

固定样本只有全部 units 与产物字节完整、24 kHz/finite signal/时长检查通过且无截断漏读时才进入速度比较；人工听审独立记录。较短音频可能来自内容缺失，不能单凭 RTF 判为加速。既有 renderer seed=42+batch 起点的策略在改变 batch 时不保证波形一致；实际 producer 的 seed policy 必须冻结进配置。

后续一次只改变一个已有参数，记录完整 config hash、失败与质量影响。降低 max_new_tokens 造成截断不能计为优化成功。模型换型或权重训练另立实验。
