# 复盘：20261017-dual-pdf-mobile-pdf-tests

数据见同目录 `INDEX.md`、`manifest.json` 和 `dual-pdf-mobile-pdf-tests-20261017/summary.json`。本报告只记录本机软件测试。

## 结论先行

交付类型：测试。基于 `1e9c6140`，移动提交 `9216c998` 保持实现字节相同，接线提交 `78e96150` 保留旧 CLI 和导入门面。定向 unittest 共 59 个通过；`outcome.json` 为 `status=passed`、`exitCode=0`。旧 CLI 帮助、`git diff --check`、工作树实现路径断言均退出 0。未执行真实模型、远端服务、生产发布或设备验收。

## 总时间

定向 unittest 墙钟 3.462 秒，见 `timings.tsv`。其他短检查未统一计时，不能由此推算整轮墙钟；等待和返工未分段记录。无可比的上一轮同范围测试。

## 各层模型、耗时与速度

| 层／阶段 | 状态 | 模型、用量与费用 | 证据 |
|---|---|---|---|
| L1 来源 ASR、MFA、英文机器评审 | `not_run` | 无调用、无费用 | `summary.json` |
| L2 初译、独立审核、文本质检 | `not_run` | 无调用、无费用 | `summary.json` |
| L3 配音、回转写、音频质检 | `not_run` | 无调用、无费用 | `summary.json` |
| dual-PDF 本地渲染与合同测试 | 59 个本机 unittest | reportlab 和固定文本；无模型调用、token、音频时长或费用 | `summary.json`、`timings.tsv` |
| L4 发布 | `not_run` | 无发布、无费用 | `summary.json` |

## 错误

本轮最终命令无失败。未发生占用付费资源或发布后错误。

## 可以改进的地方

| 类别 | 改进 | 依据 | 预期收益 | 负责人 | 跟踪 |
|---|---|---|---|---|---|
| 预检 | 每次隔离工作树测试先核对 `tongxing_production` 的实际文件路径 | 本轮另做实现路径断言；共享虚拟环境的默认可编辑包指向主检出 | 防止测试错检出 | 该批维护者 | 代码 PR 验证说明 |

## 实际覆盖范围

覆盖旧 `scripts` 导入同一模块、跨模块字体和页面常量、仓库外 CWD 的旧 CLI 生成 PDF 与 QA、路径别名与加载代码身份，以及 post-live 命令构造。本机测试使用固定文本；没有运行 L1–L4 真实生产流程，也没有复用生产收据。

## 遗留状态

没有远端 job hold、Dev 文件或构建号。代码提交 `78e96150` 已推送至独立分支，代码 PR #594 为草案；本报告通过单独文档 PR 交付。

## 外部可见的变化

无 Dev 发布、TestFlight 或受保护分支推送。HTTP、浏览器、设备播放和场地验收均为 `not_run`。
