# 复盘：20261020-grp006-merge-local

数据见同目录 INDEX.md 和 manifest.json。未填写的小节删掉前请写明原因。

## 结论先行

交付类型：**测试**（本地单元与离线只读检查），不是 `four_layer_release`。

最终状态：新增的 `group_worker`（逐组 T/R/P）与 `group_pipeline`（`status`/`run`/`merge`，合并第 1–3 步）单元测试通过；相关 Layer 2 回归 206 项通过（并在合入最新 dev 后重跑 145 项相关测试通过）；合并比较新增后 `tests/test_group_pipeline.py` 8 项、三组文件 29 项通过；本地 CI 分片 0、1、2、3 通过，分片 4–7 未完成（分支在运行中合入 dev，结果不作为证据）。仓库的 Python tests 等工作流当前为 `disabled_manually`，PR 上没有 CI 检查，故本轮以本地分片为验证证据。`15030286` 的 ko 402 组离线 `status` 全为 `missing`（该 run 没有逐组记录），零模型调用、零记录写入。

补充（同一分支后续提交 `066a1624`）：再次 `merge` 会与上一份合并清单逐组比较记录哈希，变化组必须恰好等于 `--affected`，多一组或少一组都拒绝并列出组 ID；`tests/test_group_pipeline.py` 增至 8 项。`15030286` 的离线 merge 复放无法在 dev 上完成：该 run 冻结 policy 的插件实现哈希属于运行分支的四文件闭包，`admit_evidence` 在任何组比较前就拒绝记录的插件收据；因此 `plan`/`status` 仍是该产物上受支持的零调用检查。

再次补充（`6026d183`）：`redo --group-id … --reason …` 已实现。它从当前合并产物读出被拒译文，写只追加的 `sermon-group-directive-v1` 指令，把指令作为 `operatorRevision` 送进 T/R 的 prompt，`revisionSha256` 进入记录键，旧记录变 `stale`、新记录是新修订。每次运行写独立 `attempt-NNNN` 目录；合并输出按 candidate SHA-256 存放并用 `current.json` 指针切换。`tests/test_group_pipeline.py` 9 项、组与 Layer 2 相关回归 117 项通过。

再补充（`3125e1bd`）：`group_tasks.py plan` 的子命令分发已修（原来把选项直接交给 `group_plan` 的解析器会报错），`prepare-l3`（合并第 5–6 步）与失败映射已加入。`15030286` ko 的 `plan` 在当前树上仍是零调用只读：402 组，T/R/S `expected_reusable`，P/Q/A/U `stale`，约 4 秒；本地生产 runbook 已加逐组操作入口。`tests/test_group_pipeline.py` 增至 11 项。

再补充（`8256bec5`）：第 7–9 步的可恢复执行器 `group_tasks.py stages` 已加。它按 `sermon-group-l3-stages-v1` 顺序运行现有 producer 命令，逐 stage 绑定命令 SHA-256、退出码与耗时；非零退出或“成功但缺 `produces`”都停止，已有产物按 resume 跳过，未解析占位符在派发前拒绝。`tests/test_group_l3_stages.py` 7 项通过。真实 Spark 渲染与音频 QC 仍未运行。

证据边界：没有真实付费调用、TTS、ASR、部署或 Firebase 操作。`merge` 只到 candidate 与合并清单；第 4–10 步（校准、豁免、speech job、渲染、排程、整轨、筛查/音频 QC、试听豁免）未接线，合并清单记录为 `pendingSteps`，结果是 `candidate_ready_layer3_pending`，不能当四层完成。

## 总时间

自动汇总（核对后保留）：

- `20261020-grp006-merge-local`（outcome.json）：墙钟约 1h10m；没有 journal，计算和等待未拆分。等待主要是本地 CI 分片运行与上下文整理。

## 各层模型、耗时与速度

| 层／阶段 | 模型或后端 | 推理强度／tier | 调用次数 | 计算耗时 | token 或音频秒数 | 速度 | 费用 | 证据 |
|---|---|---|---|---|---|---|---|---|
| L1 来源 ASR | not_run | | 0 | | | | $0 | |
| L1 词级对齐（MFA） | not_run | | 0 | | | | $0 | |
| L1 英文机器评审 | not_run | | 0 | | | | $0 | |
| L2 初译 | 测试用 fake caller（等同 `gpt-6.1-sol` high 的角色） | | 2 次/组 | 测试内 | 合成 payload | 不适用 | $0 | tests/test_group_worker.py |
| L2 独立审核 | 测试用 fake caller（等同 `gpt-6.1-sol` medium 的角色） | | 2 次/组 | 测试内 | 合成 payload | 不适用 | $0 | tests/test_group_worker.py |
| 文本质检（回译） | not_run | | 0 | | | | $0 | |
| L3 配音（TTS） | not_run | | 0 | | | | $0 | |
| L3 回转写筛查（ASR） | not_run | | 0 | | | | $0 | |
| 音频质检 | not_run | | 0 | | | | $0 | |
| L4 构建与发布 | not_run | | 0 | | | | $0 | |

已复制的收据里没有模型身份；本轮所有模型调用均为测试 fake，没有真实 provider 收据。

## 错误

| 层／阶段 | 现象 | 原因 | 发现时机 | 处理 | 回归测试 | 提交或 PR |
|---|---|---|---|---|---|---|
| L2 逐组 worker | 一组 custom plan 被拒绝（“Group plan must cover source units exactly once”） | `models.group_plan` 只接受覆盖全部 source unit 的计划 | 单元测试 | 新增 `allow_subset`（只接受 Layer 1 组的保序子集），worker 使用 | tests/test_group_worker.py | 本 PR |
| L2 逐组 worker | 第二组 T 记录被判 stale（`englishContextSha256` 不同） | 单组计划让 `surrounding_context` 的位置归零 | 单元测试 | 新增 `context_plan`，上下文仍按完整 Layer 1 计划计算 | tests/test_group_worker.py | 本 PR |

## 可以改进的地方

| 类别 | 改进 | 依据（本报告的数值或错误） | 预期收益 | 负责人 | 跟踪 |
|---|---|---|---|---|---|
| 流程 | `redo --reason` 把修正意见送进 T 的 payload | 命令尚未实现，返修仍靠 `run` 重跑同一输入 | 操作者能只改一组并带上原因 | 待定 | DEV-GRP-007 |
| 流程 | 合并第 4–10 步接线到现有 L3 producer | `merge` 目前停在 candidate | 逐组流水线真正到发布前 | 待定 | DEV-GRP-006 |
| 速度 | 并行 worker 与 provider 路由级停止 | 现在 `run` 串行，unknown 停止整个 run | 多组返修墙钟下降 | 待定 | DEV-GRP-002 |

## 实际覆盖范围

- **执行**：新增单元测试 `tests/test_group_worker.py`（5 项，含锁、unknown、内容失败）、`tests/test_group_pipeline.py`（5 项，含 status、预算拒绝、merge、CLI），相关 Layer 2 回归 206 项；合入最新 dev 后相关子集 145 项重跑通过。
- **复用**：无。测试 fixture 为合成来源、锚点、policy 与插件。
- **未执行**：真实模型、Spark、TTS/ASR、音频质检、L3/L4 构建与发布、`15030286` 的逐组重跑。

## 遗留状态

- `artifacts/local-runs/20261018-grp001-plan-15030286/group-config-ko-20261020.json` 与 `group-status-ko-20261020.json` 是本轮离线只读检查的输入/输出，留在被忽略目录。
- 无 Spark 会话、无 job hold、无未结算付费调用。

## 外部可见的变化

无。Dev 页面、TestFlight、生产目录均 not_run；本报告与代码 PR 是仅有的外部变化。
