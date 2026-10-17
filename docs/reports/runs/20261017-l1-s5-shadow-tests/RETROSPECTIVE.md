# 复盘：20261017-l1-s5-shadow-tests

## 结论先行

交付类型：本地离线测试。首轮 44 项测试有 1 项失败；隔离解释器绑定本 worktree 后，44 项全部通过，退出码 0。固定输入的旧/新 shadow 比较通过。未运行真实 ASR、MFA、模型、音频、发布或设备验收；此结果只支持 S5 代码行为评审。

## 总时间

首轮测试 4.353 秒，复核测试 4.803 秒（unittest 输出）。身份比较各次小于 1 秒。没有完整 journal，因此不拆分计算与等待时间，也不推断正式生产速度。

## 各层模型、耗时与速度

L1 shadow 仅使用固定的本地英文分段 fixture；模型调用数 0，费用 0。L1 真实 ASR/MFA/英文机器评审及 L2–L4 均为 `not_run`。

## 错误

| 阶段 | 现象 | 原因与处理 | 回归 |
|---|---|---|---|
| 首轮包外 CWD 门面测试 | 43 项通过、1 项失败；外部子进程读到另一棵 checkout 的生产包 | 测试复用了原仓库 editable Python 环境，子进程删除 `PYTHONPATH`。改用临时解释器，使其子进程也从 S5 worktree 加载包；未修改用户原环境。 | 44 项通过，包外 CWD 门面导入和 CLI `--help` 通过。 |

## 实际覆盖范围

- 旧/新 runner 哈希及输出目录不同，旧收据文件保留；anchor JSON 和文件字节相同。
- 新 Source Package 的 `anchors.artifact.path` 随新目录改变，包文件哈希改变；`packageId` 与 `downstreamInvalidationKey` 相同。这个固定 fixture 不证明所有历史产物可复用。
- 定向测试包括 shadow、fragment POC、post-live 工作流及生产包导入边界；没有运行完整四层作业。

## 遗留状态与外部变化

没有模型任务、job hold、发布或远端写入。代码 PR 与本报告 PR 分开评审；尚需在实际来源收据上确认历史校验与下游绑定，不把本地 fixture 当成现场验收。
