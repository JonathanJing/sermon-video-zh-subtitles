# 复盘：20261017-g1-cascade-pr582

## 结论先行

测试类型；最终草稿 #582 精确 head 为 `be9c558d3883063a99343e1da8e18b3e0c5adcba`。六个 G1 堆叠 PR 的父分支按序无冲突合入，均已推送并通过 `git diff --check`。最终 head 上 Mac mini 的 8 个直接相关模块共 47 项单测通过。另有两次广集主动中断（均 exit 130）和一次因 Mac mini 缺少 `ffprobe` 而出现 13 项环境错误的 60 项测试；这些均不计作通过。四轮分别见各自 `outcome.json` 与 `test.log`。

这只是 draft 代码与本地测试证据。G1 开窗、locale 处置、真实校准、豁免签发、QC 预算批准、发布与设备验收都未执行。

## 总时间

本机 Python 3.12 广集运行 1m27s 后为释放 CPU 中断；Mac mini Python 3.14 广集运行 5m05s 后按上限中断；首轮 mini 窄集 7s，去除 `ffprobe` 依赖后的窄集 9s。均无 journal，计算与等待未拆分；无同范围历史比较。

## 各层模型、耗时与速度

未调用模型；无 token、音频生成或 API 费用。L1–L4 实际生产阶段均为 `not_run`。

## 错误

| 阶段 | 现象 | 原因与处理 | 证据 |
|---|---|---|---|
| 本机广集 | exit 130，未得到套件总数 | 用户要求释放本机 CPU；中断并转到 mini | `g1-cascade-pr582-20261017/` |
| mini 广集 | 5m05s 持续单核计算后 exit 130 | 终止栈在韩语筛查正则生成／编译；设定时间上限后改跑关键模块，未得出该广集的通过或代码回归结论 | `g1-cascade-pr582-mini-broad-20261017/` |
| mini 首轮窄集 | 60 项中 13 项环境错误 | 仅 `test_sermon_unified_audio` 依赖的 `ffprobe` 缺失，随后 synthetic MP4 fallback 报长度错误；未改动主机服务或安装工具，保留失败并排除此模块复核剩余 8 模块 | `g1-cascade-pr582-mini-smoke-20261017/` |
| mini 次轮窄集 | 47 项通过 | 8 模块定向单测，退出码 0 | `g1-cascade-pr582-mini-noffprobe-20261017/` |

## 可以改进的地方

Mac mini 的独立测试环境若要覆盖 `test_sermon_unified_audio`，需先提供 `ffprobe`；本轮没有把环境缺失归为代码回归。广集韩语筛查路径应另做有界性能诊断，不能凭中断栈断言性能退化。

## 实际覆盖范围

通过的 8 模块：`test_sermon_workflow_jobs`、`test_sermon_unified_reviews`、`test_implementation_freeze`、`test_tongxing_audio_ports`、`test_qc_runtime_implementation_closure`、`test_accounting_observability`、`test_verify_sermon_observability_sidecars`、`test_review_leaves`。导入的可编辑 `tongxing_production` 路径已确认位于最终 #582 的独立 worktree。Mac mini 为 macOS Python 3.14；项目 GitHub CI 使用 Linux Python 3.12，不能互相替代。

`identity-receipt.json` 是 #571 基线 `249ae12a34d19baaaaf899e2e1e1ad0106cf1c9c` 至最终草稿 #582 的只读预览：W `acbe525679820292…`→`6eeb52aa5d640df3…`，T `27025236239627f6…`→`d32c3865b5d39157…`，筛查计分 `cb123c807a0306e3…`→`bb055d32a3d1b06f…`，语速 `2e8ad1a69c4c9735…`→`baab89fc2397739b…`。W 成员 22→23；新增 `storage/files.py`，共 15 项新增或字节变化。它不是 G1 关窗代记录。

## 遗留状态

Mini 上两个独立检出及虚拟环境保留用于同 SHA 复核；无生产 job hold、Dev 文件、构建号或待清理媒体由本轮产生。#582 的 `test_sermon_unified_audio` 仍需在具备 `ffprobe` 的环境或 CI 中验证；广集未取得最终通过结果。

## 外部可见的变化

六个 draft PR 的分支 head 已推送，未合入 `dev`；本报告单独成文档 PR。无 Dev 发布、TestFlight、HTTP、设备或场地验收。
