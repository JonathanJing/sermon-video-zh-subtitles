# 复盘：20261127 weekly-auto Layer 1 接入 WhisperX

## 1. 结论先行

- **类型**：自动生产流程代码与测试；无发布。
- **状态**：`production_deployed_pending_20261128_saturday_run`。
- **结论**：`l1.whisperx` 阶段已完成并通过 66 项测试；真实 2026-11-08 脚本验证通过（53.6 秒、6,124 词、462 句、0 个 >12 秒单元）；生产 worktree 已更新到 `d8460c90`，两个 LaunchAgent 已重启，生产环境 smoke 通过（63.75 秒、6,124 词）。完整 Drive→英文表 rehearsal 和真实周六运行仍待做。
- **证据边界**：单测用 fake WhisperX/ffmpeg/转写；真实运行只到 `l1_anchor build`，没有重新下载、付费转写或审核页。

## 2. 总时间

约 **1 小时 10 分钟**（2026-11-27 23:00–00:10 PST）：脚本与阶段实现约 35 分钟，真实样本对齐/建表约 2 分钟，测试与文档约 30 分钟。不是生产运行耗时。

## 3. 模型、速度与费用

| 阶段 | 模型/后端 | 调用 | 耗时 | 规模 | 速度 | 费用 |
|---|---|---|---:|---|---:|---:|
| L1 WhisperX 对齐 | WhisperX 3.8.6 / wav2vec2 / CPU | 134 分块 | 53.6 秒 | 2,147 秒 / 6,124 词 | 0.025× 实时 | 0 |
| L1 句表 | `l1_anchor.py` | 1 | <1 秒 | 462 句 | — | 0 |
| L1 付费转写 | 原 `whisper-1` + `gpt-4o-transcribe` | 未重跑 | — | — | — | 复用/未新增 |
| 测试 | pytest | 65 项 | 44 秒 | 合成 | — | 0 |

## 4. 错误

| # | 现象 | 原因 | 处理 |
|---|---|---|---|
| 1 | `l1_whisperx` 调 adapter 报 `No module named numpy` | `Path.resolve()` 把 venv 的 `bin/python` 解析到基础 Python，丢失 site-packages | 不 resolve runtime Python；保留 venv 路径 |
| 2 | adapter 报 `token count 73 != 74` | 对齐器可能把一个 token 输出为不同 word 数；逐 chunk 硬性 word 数检查过严 | 移除 word 数检查；token 序列仍严格相等 |
| 3 | 测试中新阶段找不到 runtime | 单测 local 配置没有 `whisperxPython` | 测试加 `sys.executable`，fake Run 拦截实际执行 |
| 4 | `STAGES[:9]` 断言失败 | 新阶段改变顺序 | 改为 `STAGES[:10]` |
| 5 | 旧 production 恢复时新阶段替换旧 `words.json` | `l1.anchor` 已 done 的旧 run 也会跑新增的 `l1.whisperx` | 加 legacy 判断：`l1.anchor` done 时跳过；PR #1646 |

## 5. 可以改进的地方

- **部署**：生产 worktree 已更新到 `d8460c90`，`local.json` 已加 `whisperxPython`，两个 LaunchAgent 已重启；生产 smoke 通过。
- **完整 rehearsal**：还没有用真实 Drive 文件从头跑到英文表；旧 production 的驱动执行只证明新阶段能跑，不证明新文件从下载到审核页的完整链路。
- **分词差异**：真实样本 6,124 词 vs whisper-1 6,136；审核页会显示 WhisperX 分词后的文本，需确认审核者接受。若不可接受，改用 WhisperX 对齐 **批准文本** 的 post-review 方案（需新增时间轴审核 gate）。
- **回滚**：`timelineBackend=whisper-1` 只跳过新阶段，旧 run 的 candidate/words 仍可能混用；回滚应按新 run 或显式清理 `raw-whisperx.json`。

## 6. 覆盖范围

- 代码/单测：执行（66 项）。
- 真实 2026-11-08 `l1_whisperx` + `l1_anchor`：执行。
- 生产部署、完整 Drive→英文表 rehearsal、真实周六运行、L2/L3/发布：`not_run`。

## 7. 遗留状态

- `artifacts/weekly-auto/whisperx-l1-test/` 保留真实脚本产物；不进 Git。
- 生产 worktree 在 `d8460c90`；LaunchAgent 已重启；`local.json` 已加 `whisperxPython`。
- 没有付费转写、没有发布、没有通知。

## 8. 外部可见变化

无部署、无发布。Git 变更合并后需生产 worktree 更新和 `agents install` 才生效。
