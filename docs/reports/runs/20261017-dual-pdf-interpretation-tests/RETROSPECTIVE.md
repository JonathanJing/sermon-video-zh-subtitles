# 复盘：20261017-dual-pdf-interpretation-tests

数据见同目录 `INDEX.md`、`manifest.json` 和 `dual-pdf-interpretation-tests-20261017/summary.json`。本报告只记录本机软件测试。

## 结论先行

交付类型：测试。基于 #594 head `78e96150`，纯移动提交 `bf770e59` 保留原实现字节；接线提交 `a4d42f81` 移除实现中的仓库根推断和旧脚本导入，保留旧 CLI 与导入门面。81 个定向 unittest 通过，`outcome.json` 记录 `status=passed`、`exitCode=0`。旧 CLI 帮助、`git diff --check` 和包实现路径断言退出 0。没有真实模型、远端服务、生产发布或设备验收。

## 总时间

定向 unittest 墙钟 4.040 秒，见 `timings.tsv`。其他短检查未统一计时；没有记录可拆分的等待或返工时间，也没有可比的同范围上轮测试。

## 各层模型、耗时与速度

| 层／阶段 | 状态 | 模型、用量与费用 | 证据 |
|---|---|---|---|
| L1 来源 ASR、MFA、英文机器评审 | `not_run` | 无调用、无费用 | `summary.json` |
| L2 初译、独立审核、文本质检 | `not_run` | 无调用、无费用 | `summary.json` |
| L3 配音、回转写、音频质检 | `not_run` | 无调用、无费用 | `summary.json` |
| dual-PDF 本地渲染与合同测试 | 81 个本机 unittest | 固定 JSON、reportlab 和 mock；无模型调用、token、音频时长或费用 | `summary.json`、`timings.tsv` |
| L4 发布 | `not_run` | 无发布、无费用 | `summary.json` |

## 错误

本轮最终命令无失败。没有占用付费资源或发生发布后错误。

## 可以改进的地方

| 类别 | 改进 | 依据 | 预期收益 | 负责人 | 跟踪 |
|---|---|---|---|---|---|
| 预检 | 隔离工作树测试先核对生产包实际文件路径 | `summary.json` 的实现路径断言；共享虚拟环境默认指向主检出 | 防止错检出 | 该批维护者 | 代码 PR 验证说明 |
| 身份 | 新运行按包内实现新哈希冻结解释 PDF；旧哈希收据保持原记录 | 原实现 SHA-256 `95ab692f…`，接线后 `2cbad471…` | 防止把旧收据误认为新实现的批准 | 该批维护者 | 本批代码审查 |

## 实际覆盖范围

覆盖旧 `scripts` 导入同一模块、仓库外 CWD 用固定 JSON 调用旧 CLI 生成 PDF 和 QA、`generate_notes_with_openai` 的延迟渲染消费者、post-live 独立 PDF 分支的旧脚本命令、路径别名和加载代码身份，以及冻结 notes 缓存的本机测试。`run_frozen_interpretation_notes` 的收据只绑定 notes 生成器、提示词和术语，PDF 渲染另行执行；这次没有改其缓存身份。没有运行 L1–L4 真实生产流程或复用生产收据。

## 遗留状态

没有远端 job hold、Dev 文件或构建号。代码提交 `a4d42f81` 已推送至独立分支，代码 PR #598 为草案；本报告通过单独文档 PR 交付。旧实现哈希与新实现哈希不同，需在下一次真实运行中使用新身份；不改写旧收据。

## 外部可见的变化

无 Dev 发布、TestFlight 或受保护分支推送。HTTP、浏览器、设备播放和场地验收均为 `not_run`。
