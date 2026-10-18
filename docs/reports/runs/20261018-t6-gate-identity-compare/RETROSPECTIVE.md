# 复盘：20261018-t6-gate-identity-compare

## 结论先行

交付类型：本地身份验证。两个隔离 worktree 分别固定于 `origin/dev@7eabdf6a` 与 PR #1036 代码头 `c0224028`，各自 `.venv -I` 已确认导入本 checkout 的包；调用仓库的 `text.controller.code_identity()` 与 `review.waiver.implementation_sha256()`。Layer 2 身份由 `a8029704…c660` 变为 `6931172b…2cc`，G1 W 两边均为 `df299eca…41b10`。没有重签旧收据或生产运行。

## 总时间

两次身份计算各约一秒内；隔离 worktree 准备和人工核对未完整计时，不给出总墙钟或性能结论。

## 各层模型、耗时与速度

L1–L4 真实生产均 `not_run`。无模型、token、音频、Spark 或费用。

## 错误

无计算失败。旧/新扫描条目分别为 822/823；仅旧脚本路径哈希改变、包实现路径新增。中央 `path_aliases.py` 未改变，因而 W 保持 G1 实施代。

## 可以改进的地方

每次路径迁移先列出身份扫描差异，避免把“实现主体近似不变”误说成旧收据可复用；新的 Layer 2 计划须绑定新哈希。

## 实际覆盖范围

仅比较当前 `dev` 与候选分支的代码身份和 W；未复验旧实验计划、正式 Layer 2 候选内容或机器质检。完整精确值见同目录 `summary.json`。

## 遗留状态

PR #1036 仍为草稿，正式三语 Layer 2 尚在运行。用户已选择保留历史实验快照只读，未来重启另建计划，见 #1050。

## 外部可见的变化

`not_run`：无 Dev 发布、TestFlight、HTTP 读回、设备或场地验收。
