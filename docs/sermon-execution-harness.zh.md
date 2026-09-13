# 周六执行保护与恢复

本轮在已有 Supervisor、来源审批、缓存校验和账本上增加执行保护，保留原生产架构。入口见[周六统一入口](saturday-harness.zh.md)；质量比较与执行观察分别见[离线质量回归](saturday-quality-harness.zh.md)和[Trace 导出](sermon-trace-export.zh.md)。这些工具不授予人工审批，也不自动发布中文音频。

## Supervisor 租约

`backend/leases.py` 为每次持有租约分配独立 token。本地租约用稳定的 flock 文件保护状态变更，保留递增 generation；GCS 用对象 generation 条件读写防止旧持有者续租或释放新租约。

Supervisor 在执行期间自动续租，间隔至多 30 秒；确认超时或失去所有权即停止本地子进程组。每个证据写入和最终提交标记前重新核对当前租约。后台续租请求也有独立确认期限，不能因为初始租约很长而让失联执行持续数小时。

实际命令通过独立监护进程启动；Supervisor 持有的管道一旦关闭，监护进程终止整个命令进程组。即使 Supervisor 遭遇不可捕获的 `SIGKILL`，也不会让原本地生成进程继续等待租约到期后与新运行重叠。

新协议需要重启原有执行进程后才生效。已提交的远端 API 请求和已经发生的外部写入不能撤回；租约核对与其他资源的写入不是跨资源原子事务，不能称为 exactly-once。

## 配音工作目录与命令期限

`run_weekly_dubbing.py` 和桥接器按解析后的真实工作目录竞争同一把本地 OS 锁，路径别名不能绕开。锁文件不删除；直接子进程继承锁描述符，因此父进程被强制终止时，仍在工作的直接子进程会继续阻挡本机重复执行。

每次尝试在 `WORK/accounting/harness/attempts/` 保存独立状态，`latest.json` 是最新指针。记录阶段、缓存命中、开始/结束和异常类型，保留上次未正常结束的尝试。完成状态只是 `candidate_ready_for_review`，不改变已有的音频、时间同步或人工审核收据。

| 参数 | 默认 | 作用 |
|---|---:|---|
| `--command-timeout` | 3600 秒 | 单个模型/本地命令上限 |
| `--transfer-timeout` | 600 秒 | SSH 检查和 SCP 传输上限 |
| `--execution-timeout` | 21600 秒 | 验证冻结 job 后的执行期限，各阶段不重置 |

期限由剩余总预算与单命令上限中较小者决定。超时或可捕获的中断会清理命令进程组，保留原始异常类型；清理也有有限等待。脱离进程组的守护进程和远端任务不在本地清理保证内。

Temporal adapter 显式启用 `SERMON_HARNESS_GUARDED_CHILDREN=1` 后，每层 `bounded_process` 通过 `sermon_guarded_command.py` 建立独立的父存活管道。即使多层取消时中间父进程先被强杀，管道 EOF 也会级联终止内层独立进程组；守护进程捕获 TERM 保持观察，直到子进程结束、父管道关闭或整个组被 KILL。工作锁描述符继续传递，标准输入与输出保持原命令语义。其他入口默认不启用这一模式，任意自行脱离且未经过此包装的后台进程仍不在保证内。

## SSH 中断与隔离导入

每个冻结 job 使用固定 Docker 容器名。开始前检查同名容器是否仍存在；存在时停止，不启动第二个生成。发出远端模型命令前，先持久记录 `outcome_unknown`。SSH 超时或退出 255 不表示远端已停止，运行状态转为 `waiting_remote_reconciliation`，不会直接启动音频修复。

再次运行时，先确认容器退出，再下载到 `WORK/accounting/remote-recovery/` 的新隔离目录。正常生成结束后的下载也走同一路径：

1. 核对 job、renderer、checkpoint、逐段 WAV/JSON、汇总报告和修复诊断哈希。
2. 在复制前检查全部本地碰撞；已有文件必须字节一致，任何不一致都保留双方并停止。
3. 只补入缺失文件，保留隔离原件；修复收据引用的诊断音频一同保留。
4. 重新运行既有缓存验证。若已得到完整 render，则复用结果，跳过生成。

补入前持久保存 `accounting/harness/pending-import.json`，绑定已验证隔离目录和每个文件的哈希。若在 WAV 与收据两次复制之间中断，下一次先重验该清单及原件，再补齐缺失文件，不再次下载或生成。没有清单的残缺文件仍须人工检查，不能自动认领。

没有收据的远端 WAV、身份不匹配、无法确认的容器状态都需要检查保留证据。不会删除远端容器或音频，也不会猜测“失败等于尚未执行”。自动单段修复还要求当前 renderer identity 完整相等，且失败收据晚于本次远端尝试标记；旧 `failure.json` 不能触发新的模型调用。

## 验证边界

本轮使用本地真实进程故障注入、临时文件和 mock SSH/GCS 验证。覆盖目录别名竞争、父进程中断、续租失败、进程组清理、远端未知结果、缓存碰撞、下载中断和候选审批隔离。没有运行付费模型、Spark 生成、GCS 生产写入或现场播放；软件测试通过不能代替下一次真实生产验证。

2026-09-06 第一阶段本地验证：根目录 Python 测试 934 项、配音 Python 测试 197 项全部通过；质量 fixture 正例退出 0、负例退出 1。当时仅导出 18 个 OTLP spans。该阶段日志、代码哈希和报告保存在忽略目录 `artifacts/saturday-harness-validation-2026-09-06/`；后续 P1/P2 集成证据按下面的专题文档单独保留。

```bash
.venv/bin/python -m unittest tests.test_lease_fencing tests.test_sermon_execution_harness tests.test_saturday_harness
.venv/bin/python -m unittest discover -s experiments/sermon-dubbing-poc -p 'test_execution_recovery.py'
```

P1 已接入本机隔离安装的 Promptfoo 和持久化 Jaeger/OTLP 接收器：真实质量基线、旧版本数字回归和完整音频结构检查见[质量验收](saturday-quality-harness.zh.md)，真实 trace 重启保留、重送去重及自动观察见[追踪集成](sermon-trace-export.zh.md)。P2 的 Temporal 持久工作流、审批等待、未知结果恢复和本地服务操作见 [Temporal 操作说明](sermon-temporal.zh.md)。Temporal 只编排既有执行入口，信号不构成人工批准；LangGraph 不属于本次实现。

P1/P2 最终验证记录为 `artifacts/saturday-p1-p2-validation-2026-09-06/verification.json`。最终根目录 950 项、配音模块 200 项测试通过；另实际执行 Promptfoo 的 4 项安装集成检查通过。真实 Temporal SDK 四组场景通过，报告的源码及依赖 SHA 与交付代码一致；独立审查复验了旧恢复信号和三层进程取消修复。Jaeger、账本观察器、Temporal server 和正式只读 worker 在最终检查时运行正常，现有周六任务历史只有一次 inspect、零次 execute。此记录不授予原候选音频的人耳审核、PDF 或发布完成状态。
