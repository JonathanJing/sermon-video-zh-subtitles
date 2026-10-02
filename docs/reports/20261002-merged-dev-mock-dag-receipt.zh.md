# 第 1 条实验：合并后 dev `58b46767` 的本机复测回执

本记录补入已经跑完的本机结果，没有重跑 DAG。测量对象是 PR #224 合入 `dev` 的提交 `58b46767aea3cfad04fd89c75a27f490369d2045`，tree `77df394cc0f43a994fd231db3fb34e43d9534b09`。该 tree 与 PR 分支头相同。更早的失败 SHA `8c64502`、修复候选 `ab98774` / `8ff42bc` 和快照优化候选 `988102d` 仍分别保留，不能互相替代。

## 环境与身份

2026-10-02 17:51:57–18:02:24 UTC。统一入口保存的每次 `workflow_started` 都绑定上述完整 SHA，且 `trackedWorkingTreeDirty=false`，共 13 条。范围是两个目标语单元、真实本机 mock 子进程和真实 Prefect。合成 Source/text fixture 调用按场景记录；真实模型、付费 API、GPU 和新 MFA 调用为 0。`productionEligible` 与发布资格不因本次通过而改变。

合并提交上的 Python CI `37043481915` 中，`changes`、`test-group (root-0)`、`test-group (root-1)` 和 `unittest` 为 success；`Native and shared client contracts` 为 skipped。PR 头上的 Local Prefect pilot 三场景在合并前已成功，且与本 tree 相同。本页是该合并 SHA 的本机账本回执。

## 结果

三场景均退出 0。下表 wall time 含 SDK 进程和测试验证，不是关键路径或三分钟真实音频速度。invocation 时长来自保存的进度事件。

| 场景 | 预检 | 第一次 | 第二次 | 场景 wall | 新 mock 派发 | 合成调用 |
|---|---:|---:|---:|---:|---|---|
| 正常完成与原样重复 | 0.550 秒 | 96.278 秒，`synthetic_complete` | 130.091 秒，`synthetic_complete` | 230.610 秒 | 2 → 0 | 6 → 0 |
| 确认失败后只重试失败单元 | 0.540 秒 | 65.044 秒，`incomplete` | 141.103 秒，`synthetic_complete` | 209.910 秒 | 2 → 1 | 6 → 0 |
| 普通超时后按原任务对账 | 0.531 秒 | 53.470 秒，`incomplete` | 128.380 秒，`synthetic_complete` | 185.427 秒 | 2 → 0 | 6 → 0 |

六次 invocation 各有 19 个 SDK 任务且状态均为 Completed，114 个 `taskRunId` 互不相同。未知派发确认为 0。正常重复没有新派发；失败恢复只新增 1 个 mock job；超时恢复沿原 job 对账，保存摘要里有 2 条 reconciliation。failure 与 timeout 的历史错误在第二次成功后仍各保留 2 条，账本完整性均为 consistent。canonical 事件数：happy 454、failure 468、timeout 424。

| 场景 | plan SHA256 |
|---|---|
| happy | `2aad57927fe21c79948db0d597d489f9bd3d6e25d3cc9ab0bd92bf4589f5597f` |
| failure | `33952d33d86a1c4d80b53c837aa75b157b77d0390276a97ae00854e5ef2e82ca` |
| timeout | `6192d3565e503e07f9bd7f9f6cd6ce682962d7335d62d5a7befcb643952841b0` |

机器可读摘要见 [receipt.json](../evidence/2026-10-02-merged-dev-mock-dag/receipt.json)。

## 保存位置与产物复核

完整日志、账本和媒体在 Git 忽略目录 `artifacts/pr224-merged-sdk-58b4676/`。该目录当时没有单独的 `audit-result.json`。记录本回执时只读复核了已保存的 7 份 `fixture.wav`：每份 4,844 字节，均为 16 kHz、mono、PCM16，`ffprobe` 与 `ffmpeg` 完整解码退出码都是 0。failure 的三份字节 SHA 相同；happy 与 timeout 各两份、SHA 各不相同。这次复核没有重派任务。源 WAV 归档不计入 mock 产物。这些 fixture 不能当作真实语音质量或生产音频。

事后对仍留在该目录里的文件做了只读 SHA-256，没有重跑 DAG，也没有补写 `audit-result.json`。7 份 `fixture.wav` 的字节摘要与各自 worker receipt 里已经保存的 `artifact.sha256` 一致：

| 场景 | SHA-256 |
|---|---|
| happy | `0746f869d4327215c71fa109f0f0034eb072ce1ec47f8be7fcdb774474474e27` |
| happy | `110c1de333c9012c4833800102fb2d7b2fe5bd7dd51efc8489477994ff3ebfa8` |
| failure（三份相同） | `b0f089889040ce0e8557f2b4f6ef75f732f88140684a8eb140f63aea8d9c9e9f` |
| timeout | `24d19501dde2145f8f2b45fc0355e23d4b49bec6353e78364f92e32096b252e9` |
| timeout | `1d7f1c67b79d598aebc5d7cbf818e25c49bb1ec74af26868206c9471cfbad5c7` |

已发表计数所抄的文件摘要在 [receipt.json](../evidence/2026-10-02-merged-dev-mock-dag/receipt.json) 的 `savedOutputBindings`：三份 `source-summary.json`、`progress.jsonl`、三份账本 `accounting/events.jsonl`（行数与上面的 canonical 事件数一致：happy 454、failure 468、timeout 424），以及六份 invocation summary、运行 summary 和三份场景 timing。真实模型调用仍为 0。范围仍是 `58b46767` 上的两单元本机合成 mock，没有生产资格。

## 仍开放

跨机 mock adapter、Spark 真实 preload／batch 1/2/4、39/128-unit 规模、controller crash-window、断网或服务重启、真实模型质量和客户端／网页验收仍沿 `017 / DEV-SPD-006 / 018` 开放。本回执只关闭“合并后精确 dev SHA 的两单元本机 mock 复测尚未记录”这一项。
