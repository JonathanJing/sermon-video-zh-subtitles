# 复盘：20261017-source-failure-move

原始证据的脱敏副本、来源哈希和边界见本目录 `INDEX.md` 与 `manifest.json`。

## 结论先行

交付类型：测试。`outcome.json` 记录 `focused_pass_broad_incomplete`。两个本地代码提交分别完成字节不变搬移和兼容接线；六项定向测试通过，验证固定原因码、未知调用协调、旧导入等同于新模块、执行身份指向实现文件、隔离预加载以及合成 Prefect 预检阻断。整组 106 项测试没有有效通过结论；没有真实 Source、模型或发布运行。

## 总时间

本报告的 `startedAt` 与 `endedAt` 只在整理证据时记录同一时刻，不能代表测试耗时。没有 journal，也未拆分计算、等待、返工；无同类可比基线。

## 各层模型、耗时与速度

L1–L4 真实生产均为 `not_run`。无模型、ASR、MFA、TTS、审核 API、token、音频或费用。本轮运行的是本地合成测试与代码身份检查。

## 错误

1. 首轮 106 项测试在复用主 checkout editable package 的 Python 环境下出现 4 个失败和 1 个错误；隔离子进程导入了不同 checkout 的 package，结果不能作为本 worktree 回归结论。另有临时 job 清理时序错误，未判定与本次搬移有关。修正方式是在本 worktree 的忽略 `.venv` 中绑定本地 package。
2. 修正环境后，宽范围合成套件仍在执行身份检查中耗时较长，主动以退出码 130 中止。`targeted.log` 是此中止的脱敏片段。没有宣称该套件通过。
3. 缩小验证后，6 项定向测试全部通过，且隔离导入不加载 checkout host。对应代码提交 `eac80caeba5f2cfaf786a262723d2ebdd8c5ff2d`、`0fd5a0d330bfbf64cd178e9e8abeda995be1367d`。

## 可以改进的地方

- 预检：工作树测试前先检查 editable package 的实际 `__file__`，避免跨 checkout 假失败。此项已在后续验证中执行。
- 速度：将真实需要的失败收据与身份用例单独运行，避免为 24 行搬移触发整个合成 DAG 套件；完整套件交由 CI 或专门的合成流程执行。

## 实际覆盖范围

定向覆盖 L1 的失败分类、严格收据和身份映射，以及合成诊断阻断；未执行任何真实层生产。旧 `scripts.sermon_source_failure` 与新 `tongxing_production.source.failure` 是同一模块对象；记录路径为 package 实现文件。旧收据继续按原逻辑读取，但新执行的代码身份必然变化，不能把旧执行身份视为本次实现。

## 遗留状态

本地 worktree 清洁；仅有被忽略的测试输入、脱敏报告和独立 `.venv`。没有 Dev 上传、远端 job hold、发布构建号或待清理生产文件。宽范围合成套件未完成。

## 外部可见的变化

无。没有 push、PR、部署、HTTP 读回、设备或场地验收。
