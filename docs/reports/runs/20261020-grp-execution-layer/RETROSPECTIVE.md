# 复盘：20261020-grp-execution-layer

数据见同目录 INDEX.md 和 manifest.json。

## 结论先行

交付类型：**测试**（本地单元 + 15030286 零调用只读检查），不是 `four_layer_release`。

最终状态：逐组执行层（`run`/`redo`/`merge`/`prepare-l3`/`stages`）的 102 项测试通过；`15030286` ko 的 `plan` 与 `status` 仍是零模型调用的只读检查（402 组）。没有付费调用、Spark、部署或 Firebase 操作。

证据边界：`stages` 只是执行者；第 7–9 步没有真实 Spark 运行。`prepare-l3` 只复用现有 speech job producer，文本放行与声音授权由操作者提供。第 4 步校准仍属外部 QC 路径。

## 总时间

- 单元：9.5 s（102 项）
- 离线 `plan`：3.24 s；离线 `status`：0.41 s
- 无等待付费服务；墙钟主要花在实现与上下文整理。

## 各层模型、耗时与速度

| 层／阶段 | 模型或后端 | 调用次数 | 计算耗时 | 费用 | 证据 |
|---|---|---|---|---|---|
| L1–L2 | not_run | 0 | | $0 | 复用已有 15030286 产物 |
| L3 渲染/筛查/音频 QC | not_run（只有 stage 执行器测试） | 0 | | $0 | tests/test_group_l3_stages.py |
| L4 | not_run | 0 | | $0 | |

## 错误

| 层／阶段 | 现象 | 原因 | 处理 | 回归测试 |
|---|---|---|---|---|
| 编排 | `group_tasks.py plan` 报 invalid choice | 子命令选项未带 `plan` 词转发 | 转发完整 argv | tests/test_group_pipeline.py |
| 编排 | 重跑同组撞 `Frozen model input changed` | 复用同一轮目录 | 每次运行独立 `attempt-NNNN` | tests/test_group_pipeline.py |
| 编排 | redo 后合并撞 `merge_output_changed` | 合并产物路径固定 | 按 candidate SHA-256 内容寻址 + `current.json` | tests/test_group_pipeline.py |
| L3 stage | 命令里的 JSON 字面量被当成占位符 | 用“任意 `{`”判断 | 只匹配 `{name}` | tests/test_group_l3_stages.py |

## 可以改进的地方

| 类别 | 改进 | 依据 | 跟踪 |
|---|---|---|---|
| 流程 | 第 4 步校准接入 merge | 目前由外部 QC 路径产出文本放行收据 | DEV-GRP-004 |
| 流程 | 真实 Spark stage 配置与一次运行 | `stages` 未跑真实命令 | DEV-GRP-006 |
| 质量 | 15030286 的离线 merge 复放 | 插件闭包漂移 | 需运行分支闭包或重放模式 |

## 实际覆盖范围

- 执行：102 项单元测试；15030286 的 `plan`/`status` 只读检查。
- 未执行：真实模型、TTS/ASR、Spark、L3/L4 产物、发布。

## 遗留状态

- 无付费调用、无 Spark 会话、无部署。
- 轮目录、指令与合并产物都在被忽略的 `artifacts/` 下。

## 外部可见的变化

无。仅代码 PR #1207 与本报告。
