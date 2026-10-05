# Spark 高优先级独占控制验收

2026-10-05，PR #248。控制层已实现，实际制作模型推理、OpenAI API 和 Codex CLI 调用均为 **0**。本轮只验证抢占、保持独占、准入、中断对账、状态保存和恢复；恢复验证会重新加载原常驻模型，没有发起生成请求。

## 实现与边界

[主机控制器](../../scripts/spark_exclusive_session.py)使用持久 owner 锁、代码／boot 身份、fsynced intent/readback 和私有恢复快照。begin 的抢占模式不等待其他任务空闲；保存队列及运行状态，暂停 Spark API／scheduler、collector／llama-server 和冻结 ID 的运行容器。恢复只处理原先运行的项目，核验原模型 ID 和健康状态。

[真实入口准入](../../scripts/production_spark_admission.py)覆盖正常／诊断 L2、来源 API、英文复核、Supervisor、学习产品、旧页面译文及转写、notes／reading edition、Spark MFA、TTS／ASR／demo 模型加载。CLI/API 正常返回结束 job；异常保留 unknown，不自动恢复服务或重发。模型加载需要实际父 job 绑定；只持有 session token 不足以取得 GPU。

Docker 的 `--network none` 保留，通过 host 的私有 Unix socket 实时验证 active job、runner PID/startTicks、会话及 peer UID。容器不能通过该 socket 关闭会话、创建 job 或释放未知占用。整轮 DAG 持有父 job，各分支受原来的业务资源池约束；四分支、23 业务槽、三语言等参数未改变。

范围是当前受管服务及容器；管理员直接 SSH、其他仓库入口不受强制隔离。未知 GPU／模型进程会拒绝新派发。AutoRemove 容器缺少重建合同会在停止前拒绝。原生队列中已执行的任务保留原数据库与备份，恢复前对账；控制器不绕过旧 scheduler 的自动重排风险。未绑定 Mac 调用的 unknown 占用不接受一枚任意 `process_exited` 布尔值释放。重启或控制器代码变化需重新对账，不能自动续跑旧身份。

## 离线验证

- 全部本轮修改的 14 个测试文件：133 passed、17 subtests passed；日志 `/tmp/spark-combined-final.log`。
- 之后三项具体恢复修复及最新 gateway/helper：55 passed、2 subtests passed；日志 `/tmp/spark-final-controls-and-gateway.log`，包含 31 项核心控制测试。
- 正常生产边界、GPU 父 job、renderer、ASR、MFA、旧 API/CLI、notes/reading 定向回归：86 passed、13 subtests passed；日志 `/tmp/spark-gates-final-frozen.log`。
- 额外八模块检查：117 passed、45 subtests passed，另外两项 Study 路径失败已按下述根因修复；修复后的 Study／SourceBudget 定向验证 16 passed，日志 `/tmp/spark-study-receipt-path-regression.log`。
- 四层模拟器迁移：9 passed、4 subtests passed；CI 同入口 evaluator 通过，29 events、12 个合成调用、所有 externalCalls 为 0。

上述分组有重叠，不相加为独立测试总数。覆盖双 owner、身份变更、只恢复原运行状态、AutoRemove 拒绝、部分变更未知、幂等恢复、PID 复用、代码／boot 身份、排队与实际执行区分、缺少 session 时零派发、独占容量与自有作业重叠。

## 顺带修复的现有回归

提交前按 CI 的真实入口核对，确认旧 head 的 root-1 失败来自四层模拟器仍采用 Astra medium → Sol medium，当前 runner 已要求 Sol 6.1 high → medium。仅迁移模拟 policy 与假调用角色识别，保留故障注入事件、模拟标记和正式审批关闭，未修改生产译审合同。

扩大调用边界回归还发现学习产品 reader 的旧路径假设：预算器已按 operation＋request hash 保存响应，study 仍读取 request hash 单独命名的旧文件。执行和只读验收改为消费同一预算路径解析器，保留旧响应路径兼容，不因读回失败重新调用模型。新旧路径、续跑、篡改和 unknown 的回归分别验证；此项不代表旧 Study API 入口已完成 CLI 模型迁移。

## 实机无推理验证

主机 `achillesjing@192.168.1.152`，使用既有 TTS 镜像启动 **不分配 GPU、不联网、不导入模型** 的 CPU 计数容器，计数每 0.2 秒原子保存。它在抢占前实际持续运行，不是一个已结束的任务。首次明确冻结容器 ID，第二次验证自动选取全部运行容器。

| 检查 | 已观测结果 |
|---|---|
| 初始状态 | 四个 unit active；llama-server GPU 进程报告 35,695 MiB；原模型健康；CPU 计数持续增加 |
| 抢占后 | 四个 unit inactive、CPU 容器停止、GPU 进程 0 |
| 内存 | MemAvailable 约 71.1 GiB → 稳定约 117.2 GiB；90 GiB 是本轮控制验证的入口阈值，不是 8×8 推理峰值的验收 |
| 跨多次作业保持 | 两次模拟作业和一次返修结束后仍 exclusive_ready，计数保持不变，没有自动恢复 |
| 持有与未知结果 | held job 阻止 finish；真实绑定 sleep PID 的 unknown 阻止恢复，进程仍活动时拒绝对账，退出后按原 startTicks 对账并显式 resume-begin |
| Linux/Docker 只读准入 | 两轮各两个 CPU 容器通过真实 SO_PEERCRED 验证、得到 active jobId，finish 写请求被拒绝；无模型导入 |
| 两轮恢复 | 均 closed、四个 unit active，原模型 `Qwen3.8-27B-UD-Q4_K_XL-Unsloth` 健康且 ID 相同；第二轮计数 1521 → 1525，证明从保存值继续增长 |

最终第二轮恢复与探针清理收据保存在下述 ignored 目录；已核对 closed、原服务健康、计数恢复，删除自有 CPU 探针后 inspect 仍通过。控制验证只证明上述负载及协议；没有真实中断生产中的原生 LLM/外部 API 任务，也没有证明任意 GPU 进程能原地恢复指令状态。

本地证据：`artifacts/spark-exclusive-control-20261005/`。Spark 私有会话、历史及备份：`/home/achillesjing/.local/state/tongxing-spark-exclusive/`。队列参数、SQLite、运行数据和凭据不进入 Git。Git 仅保存实现、测试及本报告。

## 开始下一轮真实测试

下一轮使用 `artifacts/next-concurrency-605s-20261005-r6-final/` 的 `validated-command-preparation.json`。远端快照目录为 `/home/achillesjing/dgx-spark-benchmark/results/next-concurrency-605s-audio-prep-r6-2ee7c764e9de`，完整 SHA 为 `2ee7c764e9de38f93a11be8e66bdb76094fa656fab9d89e5ce18651f310928a3`。579/579 文件哈希通过，包含 538 项代码／配置／schema／术语、27 项 locale 夹具和 14 项准备材料；r4 三个实际 CPU 容器加载各 136 anchors／46 groups 的夹具成功；r6 保留上述模拟器与 Study reader 修复，控制器另去除一个行尾空格；夹具和实际加载依赖按哈希／仅空白变化证明绑定复用 CPU 证据，未再次启动模型。主比较 DAG 13 节点、新 ASR 探针 1 节点均 ready。旧 r3 或失败的 r4 staging 不再作为新版入口。缺失 schema／术语表曾被 CPU-only 夹具加载发现，失败目录及已知终态收据均保留，未越过真实调用边界。

先建立整轮高优先级会话，再让所有 controller/CLI 子进程继承同一身份：

```sh
.venv/bin/python scripts/spark_exclusive_session.py begin \
  --session-id dev-605s-next --owner codex-pr248 \
  --minimum-available-gib 90 --preempt --allow-interrupted-restart
export SPARK_EXCLUSIVE_SESSION_ID=dev-605s-next
export SPARK_EXCLUSIVE_SESSION_OWNER=codex-pr248
```

之后才运行 dev 环境启动器及冻结的测试 DAG。来源 ASR4 的新转录探针与固定源稿三语言比较保持各自身份，不能将新 anchors 接到旧候选。

测试、返修或等待审核之间不要调用 finish。整轮关闭且所有 job 已终态后显式恢复：

```sh
.venv/bin/python scripts/spark_exclusive_session.py finish \
  --session-id dev-605s-next --owner codex-pr248
```

失败时先 status/reconcile，不清 ledger、不制造新 session 绕过未知占用。正常 native 模型入口需要绑定实际运行进程的父 job；推荐使用已接入的 wrapper，避免手工启动未受管 GPU 进程。代码/test、远端 CI、真实模型测试、正式发布分别报告。
