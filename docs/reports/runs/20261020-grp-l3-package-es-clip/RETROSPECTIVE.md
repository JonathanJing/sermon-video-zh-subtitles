# 复盘：20261020-grp-l3-package-es-clip

数据见同目录 INDEX.md 和 manifest.json。

## 结论先行

交付类型：**测试性真实 L3 运行**（只跑 `audio.package`，不合成、不筛查、不做音频 QC）。

最终状态：`group_tasks.py stages` 用真实 `tools/ops/run.py audio.package` 从 2026-10-19 es clip 的已筛查渲染重建音频包；退出 0，5.93 秒，重建包与运行原始包在 canonical JSON 下**完全一致**（`7bac907b…`），零模型调用、零付费调用、零 Spark 运行。

证据边界：这不是一次新的 TTS/ASR/QC 运行；它证明阶段执行器能驱动真实 producer，并证明该 clip 的文本豁免在当前 dev 代码下仍可消费。

## 总时间

- package stage：5.93 s（含进程启动与包校验）
- 无等待付费服务；无 Spark 会话。

## 各层模型、耗时与速度

| 层／阶段 | 模型或后端 | 调用次数 | 计算耗时 | 费用 | 证据 |
|---|---|---|---|---|---|
| L3 package | 无模型（确定性） | 0 | 5.93 s | $0 | `out/stage-report.json` |
| L3 渲染/筛查/音频 QC | not_run | 0 | | $0 | |

## 错误

| 现象 | 原因 | 处理 |
|---|---|---|
| 首次 package 运行 `FileNotFoundError: .venv/bin/python` | `stages` 以配置目录为 cwd | 增加 `variables.repoRoot` 作为工作目录 |
| 15030286 zh-Hans package 被拒 | 文本豁免的 QC 实现哈希与当前代码不同 | 记录为冻结身份不兼容；改用 2026-10-19 es clip 豁免 |

## 可以改进的地方

| 类别 | 改进 | 跟踪 |
|---|---|---|
| 流程 | 跑一次完整 clip 音频（渲染→压缩→筛查→QC） | 需要 Spark 会话与新的 QC 预算授权 |

## 实际覆盖范围

- 执行：真实 `audio.package` producer。
- 未执行：TTS、ASR 筛查、音频 QC、发布。

## 遗留状态

- 无 Spark 会话、无付费调用、无未结算预算。

## 外部可见的变化

无；仅本报告与代码 PR。
