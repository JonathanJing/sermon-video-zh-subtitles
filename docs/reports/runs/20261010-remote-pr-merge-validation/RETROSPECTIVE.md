# PR 合并验证复盘

## 实际覆盖范围

仅验证并合并仓库代码与设计文档，不是 L1–L4 内容生产或发布。原始 29 个未合并 PR 中，13 个非运行报告 PR 纳入本次任务，16 个运行报告 PR 排除。#215、#280 先行合并，其余提交保留原历史整合到 #332。#314/#323 重复内容消解，#259 旧基线正常合并后保留当前 dev，未改写历史。

## 结果和结束信号

首个整合提交 46e2a256a2ca810dc387626f20b554b1f5719592 的 17 个模块联合 316 项测试通过。随后 CI 暴露测试 mock 隔离问题；最终整合提交为 56514935daae72b1f8b8ac7e4bd209cc4df52f6e，38 项预算适配器测试通过，最终 review 另修复视频 route/CSP/HTTP 验证、实验未完成退出状态、缓存账本恢复守卫，联合 29 项测试通过（1.205 秒）；后续将 Claude transport 配置校验前移预算预留，25 项定向回归通过（1.861 秒）。实验审查修复未绑定预算的 live 入口（关闭）、5xx 未知结果预算留存和停止、choice 概率评分以及人工评测计时/身份，联合 173 项离线测试通过（7.812 秒）。主动复核补齐 weekly preflight blocked 的失败终态和缓存恢复，28 项定向测试通过（1.749 秒），未知预留不释放不重发。最终审查修复生产策略冻结身份、fresh checkout scratch parent、弃权评分及已完成 reviewer 工件与 preview/transport 指纹绑定；联合 175 项测试通过（6.909 秒）。一次测试模块名误写已更正且保留。df0b582d 全部 CI 通过后，额外审查修复无效引用评分、空阶段终态、完整 paired timing、调用标记 fsync 与截图 manifest 绑定；联合 182 项离线测试通过（7.278 秒）。最终提交 56514935 的全部 CI 通过，审查线程全部处理，#332 于 2026-10-11T03:49:21Z 合并。远端 dev 与 fetched origin/dev 均回读为 704d257235d59df5d6da21262361a912bccc7481；13 个原 PR 均 MERGED，16 个原报告 PR 仍 OPEN，剩余非报告 PR 为零。包含全部 13 个非报告 PR 的当前 head；16 个报告 head 未新进入祖先，docs/reports/runs 无净变化。最终 CI、dev commit 与 PR 状态见 summary.json。

## 耗时

最终 316 项联合测试耗时 19.804 秒。此前各阶段重跑仅验证局部修复，不合计为吞吐指标。等待 GitHub 排队和检查不是模型计算时间；本轮没有模型速度或生产耗时结论。

## 错误与修复

- MFA 容差限定最后 phone、切块结束边界，并处理 20 ms 浮点误差。
- Meaning-notes 使用完整 JSON 工件 canonical hash，元数据变化不能复用旧修复批准。
- Claude 独立实验绑定输出 cap、单次尝试、固定模型与环境、preview/cache 身份和未知用量；新 canonical 派发继续 Sol。历史 Claude cache-only helper 的离线兼容不代表真实历史缓存已端到端恢复。
- Dev 视频消费 canonical verifier 收据并复制 staging；UI plan 仅复制 changedPaths 的计划内容，保留未计划 baseline 模块，校验输入与输出字节；外部操作前独占创建结果文件。
- 海报检查 target 的诊断标记以及 page/locale/source/candidate 绑定，移除没有 anchor 支持的硬编码时间，在所有写入前检查全部语言输出。
- Shadow 保留脚手架，独立执行/request 版本与 terms-only allowlist；候选 schema、pending-term plugin admission 和人工术语 receipt producer 尚未完成，故 transport 前 fail closed。
- 速度索引按逐次收据扣除 reasoning 重算可见生成 TPS，恢复实际 reviewer 模型身份，并补全本地完整基准与入口链接。
- 并发/云端设计区分默认串行和 v3 collector，明确停止收据版本、job-root 容量范围与 L1 immutable revision/fenced pointer。

首轮整合 CI 的 root-4 分组有 660 个测试，其中预算锁等待测试失败：sleep mock 观测989014次，而被测 mark_request 仍严格限定100次；与共享全局 mock 被其他调用污染的推断一致，未取证具体线程。只修复测试 mock 的模块引用隔离并检查全局 sleep 未改变，38 项定向测试通过；失败 run/job 与断言数保留 failure-receipt.json，最终 CI 使用新 head。

初始测试的缺依赖、缺 scratch 目录及测试期间源身份变化均保留在 summary.json，随后用正确环境、稳定代码重跑通过。#285 两个脱敏 warning 日志 fixture 原始空格保留，其他源码/文档 whitespace 检查通过。

## 资源占用后的错误

没有占用 Spark、发出付费模型请求或部署。本地测试暴露的问题均在离线准备阶段修复。为避免旧 PR 检查占用最终验证容量，最终整合阶段主动取消了 19 个本轮创建且已被 integration 祖先覆盖的旧分支 CI；另取消被后续 review 修复取代的 2 个 integration 旧 head 工作流；未取消报告分支、dev 或最终 integration 的检查。

## 遗留状态

未创建模型 job hold、媒体或 App 构建；没有在原 checkout 修改用户文件；原 checkout 的当前分支由并行工作管理，本轮仅使用独立整合 worktree。运行报告按仓库流程另开草稿 PR，不合并。Shadow 能力仍关闭，不能宣称实际可运行。

## 外部可见变化

仅 GitHub 分支、PR 元数据、审查线程与合并记录发生变化。最终合并保留分支保护，以 #332 的 CI 为准，不绕过 required checks。没有 Firebase 部署、TestFlight 上传、设备播放或场地验收。

## 后续

Shadow candidate/人工术语收据链的完整实现需要单独任务和真实验证。本报告已由本地协作 agent 复核；独立云端报告会话尚未执行，记为 not_run。本次结果不作为任何内容生产/听审/发布批准。
