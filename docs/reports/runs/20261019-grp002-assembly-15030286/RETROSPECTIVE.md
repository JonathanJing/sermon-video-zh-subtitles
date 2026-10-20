# 复盘：20261019-grp002-assembly-15030286

数据见同目录 INDEX.md 和 manifest.json。

## 结论先行

交付类型：**测试**（`DEV-GRP-002` 逐组组装 candidate 的离线等价检查），不属于 `dual_pdf`、`live_session` 或 `four_layer_release`。最终状态 `completed_byte_identical`，exit 0，全程零模型调用。

方法：取 15030286 三个语言最终一轮（ko、es 为 g2，zh-Hans 为 g1）的整篇 evidence 与插件收据，拆成逐组的 T、R、P 记录。T 的草稿与 T、R 的输入取自该次运行的轮次缓存（`group_legacy.layer2_records`），R 的产出是 evidence 行本身，P 的产出是插件对该组的结果。然后用 `group_assembly.assemble` 组装，与原文件逐字节比较。

| 语言 | 组数 | 跳过 | candidate 字节 | 插件收据字节 | evidence 字节 | candidate SHA-256 |
|---|---|---|---|---|---|---|
| ko | 402 | 0 | 相同 | 相同 | 相同 | `d544e0c5…` |
| es | 402 | 0 | 相同 | 相同 | 相同 | `e787142f…` |
| zh-Hans | 402 | 0 | 相同 | 相同 | 相同 | `06388d4c…` |

ko 的 SHA 与该语言 group-revision 收据里的 `candidateJsonSha256` 一致。

证据边界：
- 这些记录是为等价检查从整篇产物拆出的（`derivation=whole_path_equivalence_check`），组装器只在 `equivalence_check=True` 时接受，生产合并不会用它们。
- 插件按冻结运行的 checkout 执行：`wt-l2rev`（es、zh-Hans）与 `wt-l2rev2`（ko）。共享插件模块也从那里加载，因为 dev 上的 `auto_qc_text_common.py` 不同（选项 B）。所以在 dev checkout 上，这三份 candidate 不能按冻结 policy 重新准入；这符合"已有运行保留冻结身份"的规则。
- `humanApproval=false`，`releaseEligible=false`。

## 总时间

约 3 分钟墙钟；三个语言各自的组装加比较为 3.9 s（ko）、5.6 s（es）、5.0 s（zh-Hans）。没有等待或返工计入；调试插件闭包花了几次重跑，见"错误"。

## 各层模型、耗时与速度

没有模型调用（`not_run`），费用为 0。L2 只做确定性重放：插件与 `admit_evidence`。

## 错误

| 层／阶段 | 现象 | 原因 | 发现时机 | 处理 | 回归测试 | 提交或 PR |
|---|---|---|---|---|---|---|
| 检查脚本 | `rule preflight: plugin implementation differs from frozen policy` | 插件闭包只在插件位于本 checkout 的插件目录时才包含共享规则文件；指向另一个 checkout 时只哈希插件本身 | 预检（本地，未占用资源） | 检查时把宿主的 `plugins.root` 指向冻结 checkout 的插件目录 | 无（检查脚本） | — |
| 检查脚本 | `plugin_record_differs_from_fresh_run` | 插件按模块名导入共享规则，拿到的是 dev 版 `auto_qc_text_common.py` | 预检 | 检查时从冻结 checkout 按原模块名加载三个共享插件模块 | 无（检查脚本） | — |

## 可以改进的地方

| 类别 | 改进 | 依据（本报告的数值或错误） | 预期收益 | 负责人 | 跟踪 |
|---|---|---|---|---|---|
| 流程 | 逐组 worker（`DEV-GRP-002` 剩余部分）写 R、P 记录时直接调用 `reviewed_outputs`／`plugin_outputs`，让生产记录与本次检查同形 | 本次 1,206 组全部组装成功 | 生产组装不需要再拆整篇产物 | DEV-GRP-002 | backlog `DEV-GRP-002` |
| 预检 | 重放冻结运行时由宿主按冻结 checkout 解析插件与共享规则，不靠检查脚本替换 | 上面两条错误 | 冻结运行的重放可以复现 | DEV-GRP-006 | backlog `DEV-GRP-006` |

## 实际覆盖范围

- **L1：** 只读。
- **L2：** 三个语言的组装与准入重放；没有翻译、复核或文字 QC 调用。
- **L3、L4：** 未涉及。

## 遗留状态

本机 `artifacts/local-runs/20261019-grp002-assembly-15030286/` 留有记录库（含译文的 payload）与三份组装清单，被 Git 忽略，未导出。

## 外部可见的变化

无。设备播放、场地验收：`not_run`。
