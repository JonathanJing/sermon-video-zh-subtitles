# 复盘：20261020-pr-integrate-tools-local

数据见同目录 INDEX.md 和 manifest.json。

## 结论先行

- 类型：本地测试（非生产、非发布、非 Spark）。
- 范围：把 5 个较早的 PR 带到当前 `dev`（810349e2）和新目录结构上：#565、#1080、#1092、#1095、#1137。每个 PR 分支都合并了 dev 并已推送，Codex 线程全部回复并 resolve。
- 结果：5 个 PR 头在本地合成一个分支，跑 96 个受影响测试文件以及 package、ops-run、layout guard 测试，分 8 个并行 chunk：**1,537 passed，0 failed**，退出码 0。`git diff --check` 干净。
- 证据边界：没有跑全量；没有 Node/JS、iOS、Spark、付费模型调用或部署。

## 总时间

- 合成分支上的测试 2026-10-20 21:33:22Z–21:41:31Z，约 8 分钟（机器负载约 280–430）。
- 各 PR 分支上另跑过：#565 PDF 与 package 测试 72 项；#1080 交付测试 620 项（最慢 chunk 9.5 分钟）；#1092 摘要测试 36 项；#1095 模拟器 41 项。

## 各层模型、耗时与速度

不适用：没有调用模型，也没有 Spark 或 TTS。#1095 的模拟器跑 2000 次约 1 分钟，600 次/点的参数扫描约 5 分钟。

## 错误

| 层／阶段 | 现象 | 原因 | 发现时机 | 处理 | 回归测试 | 提交或 PR |
|---|---|---|---|---|---|---|
| 运行报告 | 新规则拦下 dev 上 `20261018-weekly-15030286` 的 `summary.json` | #1084 已带着私有 Drive 文件夹链接合入 dev | 预检（`--verify`） | 替换副本中的链接，manifest 记一次脱敏；链接仍在 Git 历史里 | `test_private_drive_links_are_replaced_and_verify_catches_them` | #1092 |
| 运行报告 | `20261011-weekly-fixtures` 的 `--verify` 失败 | `tooling/` 下的脚本含 home 路径和 secret_field，dev 上本来就失败 | 预检 | 未处理（与本批无关） | — | — |
| 测试脚本 | 第一次分块把整个列表当成一个参数 | zsh 不对 `$T` 做分词 | 占用资源前 | 改用 `${=T}` | — | — |

## 可以改进的地方

| 类别 | 改进 | 依据（本报告的数值或错误） | 预期收益 | 负责人 | 跟踪 |
|---|---|---|---|---|---|
| 流程 | 在 Drive 端收回 #1084 泄露的文件夹分享权限；需要时再决定是否改写历史 | 链接仍在 Git 历史 | 消除泄露 | 用户 | #1092 |
| 质量 | 修 `20261011-weekly-fixtures` 的 `--verify` 失败，或把它的 `tooling/` 移出报告目录 | 629 份报告里唯一在 dev 上失败的一份 | 全部报告都能跑 verify | 待定 | 新 backlog |
| 流程 | `.log` 被 gitignore，手工整理报告时要 `git add -f` | #1137 重新导出时漏加日志摘录 | 少漏文件 | — | 已记在 side-session 笔记 |

## 实际覆盖范围

- L4 交付：#1080 的对齐目录绑定（交付测试），#565 的阅读 PDF（真实发布页 `resi-20261018-broadcast` 导出 35 页 PDF，QA pass，只在本地）。
- 运行记录工具：#1092 的脱敏规则，用它对 `docs/reports/runs/` 下全部 629 份报告跑 verify。
- 规划：#1095 的模拟器（反事实模型，不是真实运行）。
- L1–L3 生产路径：没有执行。

## 遗留状态

- 本地分支 `local/pr-integrate-all` 只在这个 worktree，没有推送。
- `artifacts/sim1095/`、`artifacts/pytest-*.log` 被 Git 忽略。

## 外部可见的变化

- 推送了 5 个 PR 分支，并回复、resolve 了它们的 Codex 线程；这些 PR 还没有合并。
- 没有部署、发布、TestFlight 或受保护分支推送（not_run）。
