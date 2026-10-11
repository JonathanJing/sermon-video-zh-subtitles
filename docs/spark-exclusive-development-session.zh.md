# Spark 整轮开发独占会话设计

状态：已实现，控制层通过离线与实机无推理验证；证据见[验收报告](reports/20261005-spark-exclusive-control-verification.zh.md)。用于页面实际制作及真实模型测试，独占窗口跨越多次测试和返修，整轮开发结束时才恢复原服务。纯离线单元测试不需要占用 Spark。

2026-10-05 用户修正：页面制作拥有高优先级，不等待其他任务自然空闲。先保存其他任务状态，再暂停入口并中断竞争工作负载；不支持检查点的任务允许保存参数和产物后中断，结束后从已有产物重跑。未知 API 调用先对账，不自动重发。此处“恢复”包括服务重启和从已有产物重新执行，不能宣称任意 GPU 进程都能恢复到同一条指令。

## 当前发现

核验主机 `achillesjing@192.168.1.152`：Docker 所有容器均已停止，但 GPU 上仍有 `llama-server.service` 的 llama-server 进程，报告 35,695 MiB（约 34.9 GiB）。主机 MemAvailable 为 76,301,090,816 bytes（约 71.1 GiB）。这些是调查时刻的读数，不是未来开跑保证。

`llama-server.service` 与 `llama-performance-collector.service` 的 Restart 为 always；`spark-agent.service` 和 `spark-api.service` 为 on-failure。只处理 Docker 不能释放这部分内存；应经服务管理入口停止模型，并阻止调度器重新派发。

Spark Agent 工作目录为 `/home/achillesjing/spark-agent-current`，存在 `resource_control` 的 admission、lease、ownership 和 cleanup 代码；`scheduler_entry.py` 标注 offline deployment。当前检查未证明 guardian 和 hooks 已生效，后续核对实际入口再决定复用。本仓库音频 wrapper 的锁仅保护指定 broker 下的音频 job，不能阻止其他仓库、常驻服务或直接启动的进程。

## 最小实现

在 Spark 上设主机级固定路径的账本和 owner 锁，例如 `/home/achillesjing/.local/state/tongxing-spark-exclusive`。同一 developmentSessionId 绑定多次 runId，不按 run 各建独占目录。begin 在事务锁内持久化 active session；后续命令逐次核验 sessionId、owner 和 revision，不依赖 SSH 连接持续打开。运行级 GPU 锁仍保留。

已实现 [scripts/spark_exclusive_session.py](../scripts/spark_exclusive_session.py) 的 inspect、begin、status、require、job-start／bind／end、finish、reconcile 和 resume-begin。主机状态固定存储，SSH 传输按代码 hash 部署 stdlib 模块，无推理或运行时安装。控制目标为当前四个受管 unit，以及抢占开始时冻结的全部运行容器；不可恢复的 AutoRemove 容器会在停止前拒绝。

| 阶段 | 行为及验收 |
|---|---|
| 暂停准入 | 优先接入已实际部署的 guardian；否则暂停 Spark API 和 scheduler 的受管入口，通过 SSH 保留状态检查。维护状态未证明生效不能报告 ready。直接 SSH、其他调度器逐项标明是否受管，首版不宣称能防止管理员绕过 |
| 保存恢复快照 | 记录原先运行的目标服务／容器、完整 container ID、image ID、autoRemove、restart policy、unit 身份、任务计数和内存读数。只保存必要字段与配置 hash，不保存环境变量、凭据或完整 docker inspect。每项修改前写 intent，之后写 readback |
| 保存与抢占 | 不等待既有任务完成：固定入口后保存队列、任务参数、执行身份和已有产物位置，再按恢复计划中断受管工作负载。数据库备份和任务参数为私有恢复材料，不进入 Git 或公开 log。运行中的未知 API 结果独立登记，恢复前必须对账 |
| 释放常驻模型 | 当前候选是先停 collector，再通过 systemd 停 llama-server。运行容器按冻结 ID 优雅停止，保留镜像、权重、卷和缓存。autoRemove／一次性容器需有可核验的重建入口，不能保存不完整参数后声称能恢复。身份不明的进程先识别管理入口，不能用任意 PID kill 冒充可恢复抢占 |
| 启动器子进程 | 调度器（`spark-agent.service`）的直接子进程默认不允许存在。唯一例外是 Python multiprocessing 的 `resource_tracker` 辅助进程：父进程为启动器主进程、命令行精确匹配 `from multiprocessing.resource_tracker import main;main(N)`、自身没有子进程、且不占用 GPU。只有这一种子进程被豁免，准入检查和停止单元时都适用；其他任何子进程仍会以 `launcher_workers_active` 拒绝。 |
| 核验容量 | 目标 unit／容器已停，竞争 GPU PID 已退出，MemAvailable 连续稳定并达到本轮 minimumAvailableGiB。默认最低可用内存为 110 GiB（`DEFAULT_MINIMUM_AVAILABLE_GIB`，CLI `--minimum-available-gib` 的默认值），即整轮任务独占 Spark 直到结束；可显式传入其他值。该默认值来自 2026-10-05 实机验证中停服务后约 117 GiB 可用内存的余量，不代表 128 GB 整机内存全部可用。GPU 内存总量为 N/A 时不能当成零占用 |
| 保持整轮独占 | fresh source/MFA、TTS、回转写和后续 renderer 均核验 session token，worker 带归属。返修、locale 切换、阶段结束、等待人审或单个 CLI 退出都不恢复常驻服务。发现外部模型重新启动，停止新派发并报告竞争，不擅自杀进程 |
| 计划中会话关闭 | `planning` 状态且所有操作都是 `not_started`（没有任何停止或启动生效）时，owner 可直接关闭账本，前提是每个快照单元的身份和 active 状态、以及每个容器的身份和运行状态都未变化；不发出任何启停命令。任一变化都拒绝关闭。 |
| 开发结束恢复 | owner 明确关闭整轮会话；确认所有本会话 job 终态且进程退出，再恢复原先运行的模型、collector 和容器，最后解除其他任务准入。原先停止的项目不启动。核验原模型 ID 和服务健康，部分失败保留 restoring_failed，幂等重试只处理未完成项 |

独占期间新的测试模型仍正常占用内存。验收目标是释放竞争模型并获得明确容量，不能把整机内存降到零作为条件；保留系统内存和可回收文件缓存。不调用 drop_caches、docker prune、删除权重或 GPU reset。

`--preempt --allow-interrupted-restart` 对应用户的高优先级决定，不要求队列先空闲。私有备份保存 SQLite、旧队列和原生模型 slot 信息；原生模型请求被中断时由调用方重新提交保存的输入。原先仅 durable 排队／待输入的任务不阻碍服务恢复；实际执行中的原生派发或旧内存队列需先对账，因为旧 scheduler 重启会自动重排 running 任务。控制器不会为解除屏障而改写外国任务数据库。AutoRemove 重建、未绑定的 Mac CLI 未知占用的终态收据适配仍未接入，不能据此宣称所有外部进程均能自动续跑。

## 生命周期及异常恢复

```mermaid
stateDiagram-v2
    [*] --> planning
    planning --> draining: 冻结快照、暂停其他准入
    draining --> exclusive_ready: 工作负载退出、容量通过
    exclusive_ready --> running: 本会话派发
    running --> exclusive_ready: 终态及退出证据通过
    running --> reconcile_required: 远端结果未知
    reconcile_required --> exclusive_ready: 对账通过
    exclusive_ready --> restoring: 整轮开发关闭
    restoring --> closed: 原服务健康、准入恢复
    restoring --> restoring_failed: 部分失败
    restoring_failed --> restoring: 续做未完成项
```

begin 部分失败按逐项 intent 对账；能确认未启动本轮作业且变更结果均已知时，可恢复已停止的原服务。不能在普通 finally 中无条件恢复。SSH 断线、Mac 睡眠、CLI 超时或 owner 心跳失联进入待对账，不自动恢复抢内存、不释放未知 job reservation。超时仅发出提醒。重启导致 bootId 变化后重新对账；若尚未实现开机维护门禁，重启后常驻模型自动启动是明确未覆盖边界，禁止自动续跑测试。

## 接入与验收

当前[下一轮准备报告](reports/20261005-next-concurrency-test-preparation.zh.md)的 ready 是夹具及依赖预检；采用本设计后还需 exclusive_ready。在任何付费 API／CLI 调用前建立会话，避免译审完成才发现 Spark 被占用。代码接入改变冻结实现身份时，新建准备目录及远端快照，保留旧 mock 和收据。

开发顺序：只读 inventory／恢复计划 → 持久会话及 unit/container adapters → 高优先级抢占／admission adapter → 各真实入口 session 核验 → 单次真实 stop/restore 验收。只加本仓库 token 而不封闭 Spark Agent 派发，不满足独占条件。

离线故障测试覆盖双 owner、快照过滤、原先停止的不恢复、身份变化、autoRemove 拒绝、stop/start 未知结果、部分 begin/restore 失败、幂等恢复、终态 job 仍有进程、外部新启动、owner 失联和 bootId 变化。真实验收单独执行：停常驻模型测内存 → 同一会话跑两个测试及一次返修，确认中途未恢复 → 结束核验原模型健康及调度准入恢复。只读调查不代替这些操作证据。

统一 log 记录 sessionId、runIds、host/bootId、状态与耗时、MemAvailable 前后及稳定采样、GPU PID 归属、stop/restore intent/readback、unknown 和最终恢复状态；不记录凭据。独占准备和常驻模型恢复耗时与制作墙钟、模型推理吞吐分别统计。

关联：[计算策略](local-production-compute-policy.zh.md)、[并发设计](production-concurrency-expansion-design.zh.md)。
