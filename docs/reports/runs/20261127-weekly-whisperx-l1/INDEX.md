# 运行报告：20261127 weekly-auto Layer 1 接入 WhisperX

## 结论先行

- **交付类型**：自动生产流程代码与测试，不是页面/音频/发布。
- **状态**：`integration_tested_pending_production_deploy`。`weekly_auto` 的 `l1.whisperx` 阶段、真实脚本运行和 65 项测试已完成；生产 worktree 尚未部署，完整 Drive→英文表演练和真实周六运行未做。
- **证据边界**：测试覆盖驱动/gate/tracks/publish 的合成流程；真实 2026-11-08 只验证了 `l1_whisperx.py → l1_anchor build`，没有重新下载、付费转写或打开审核页。

## 改动

| 文件 | 作用 |
|---|---|
| `experiments/sentence-first-agent/l1_whisperx.py` | 新增：把 timing-pass 分段用 WhisperX 对齐，写 `raw-whisperx.json`/`words.json` |
| `experiments/sentence-first-agent/l1_anchor.py` | 可配置 `--timing-basis`/`--timing-source`，从 WhisperX raw 建句表 |
| `experiments/sentence-first-agent/l1_english_source.py` | `--timing-model whisperx` 与动态 timing note；包内 `transcript.model=whisperx` |
| `tools/ops/weekly_auto.py` | 新增 `l1.whisperx` 阶段，排在 `l1.transcribe` 与 `l1.anchor` 之间；英文表批准后包直接进 `sfa.py` |
| `config/weekly-sermon-auto.json` | `transcription.timelineBackend` 默认 `whisperx`；可设 `whisper-1` 回滚 |
| `tools/ops/whisperx_align_runtime.py` | 移除逐 chunk 的硬性 word 数等于 token 数检查；token 序列仍严格校验 |
| `tests/test_l1_whisperx.py`、weekly-auto 测试 | 新增脚本测试；65 项通过 |

阶段顺序：

```text
l1.transcribe → l1.whisperx → l1.anchor → l1.rows → gate.english → wait.review
```

英文表页显示 WhisperX 时间，批准英文表即批准这份时间轴；不需要第二次人工审核。之后 `l1_english_source` 生成 `transcript.model=whisperx` 的批准包，`sfa.py` 自动识别为 timeline package，继续 L2/L3/发布。

## 真实脚本验证（2026-11-08）

输入：`raw-whisper.json`（791 segments / 6,136 words）与 `sermon-16k.wav`；运行环境 WhisperX 3.8.6 / torch 2.8 / CPU。

| 项 | 值 |
|---|---|
| 对齐耗时 | 53.6 秒（2,147 秒音频） |
| 输出词数 | 6,124（WhisperX 分词与 whisper-1 不完全同形；逐 chunk token 序列校验通过） |
| `l1_anchor build` | 462 个单元、0 个 >12 秒单元 |
| 最长单元 | 11.87 秒 |
| 证据 | `artifacts/weekly-auto/whisperx-l1-test/`（忽略目录） |

产物哈希：

| 产物 | SHA-256 |
|---|---|
| `raw-whisperx.json` | `bc680ecc7686821d33d5e4597642aa1caa7c623a513c40282e3c366db6730877` |
| `words.json` | `8f337be568785f49d85f70e294163a71374160ed8e7b2cdcfeca0f5e7d1c7ad1` |
| `anchor-manifest.json` | `6215d16e1f4aa98751d6d27e9aa054f9b48b809b90f6ea4f1572db8f06a64ec9` |
| `whisperx-request.json` | `c66cde8b280dfa0155dd052f247ac7619d666c31cdd257db72ba223222cf4a34` |
| `whisperx-result.json` | `59f1ab1e6e2602af4c44801340bfd21e42d4aedcfae636a87ed328a2587b5792` |

## 测试

```bash
uv run --with pytest --with jsonschema --python 3.13 python -m pytest \
  tests/test_weekly_auto.py tests/test_weekly_auto_tracks.py \
  tests/test_weekly_auto_publish.py tests/test_l1_whisperx.py -q
# 65 passed
```

覆盖：新阶段在 `l1.transcribe` 后执行、fake WhisperX 输出进入 `l1_anchor`、英文表批准包模型为 `whisperx`、tracks/publish 继续调用 `sfa.py`、rehearsal 走父时间轴回退、缺 runtime 时 fail closed（脚本级）。

## 部署（待执行）

```bash
cd artifacts/worktrees/weekly-auto
git fetch origin dev
git checkout --detach origin/dev
# local.json: "whisperxPython": "<...>/artifacts/whisperx-timeline-ab/runtime/bin/python"
.venv/bin/python tools/ops/weekly_auto.py agents install --port 8444
.venv/bin/python tools/ops/weekly_auto.py agents status
```

部署后先跑一次到英文表的 rehearsal（不发布），确认 `l1.whisperx` 通过、英文表页时间来自 WhisperX、`english-source.json` 的 `transcript.model=whisperx`。再等周六真实文件。

## 覆盖范围

- **代码/测试**：执行（65 项）。
- **真实 2026-11-08 脚本**：执行（`l1_whisperx` + `l1_anchor build`）。
- **生产部署**：`not_run`。
- **完整 Drive→英文表 rehearsal**：`not_run`。
- **真实周六运行**：`not_run`。
- **L2/L3/发布**：`not_run`（weekly-auto 测试覆盖到发布分支的合成流程，不是真实运行）。

## 外部可见变化

无部署、无发布、无通知。Git 变更合并后才会进入生产 worktree。

## 相关

- [周六自动开工文档](../../../weekly-auto-production.zh.md)
- [WhisperX 时间轴生产手册](../../../whisperx-layer1-timeline-production.zh.md)
- [复盘](RETROSPECTIVE.md)
