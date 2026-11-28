# WhisperX Layer 1 时间轴：生产默认、批准与首次生产测试

状态：`default_enabled_pending_production_test`。生产工具、真实候选包、结构门禁、`prepare_clip` 消费验证和人工批准均已完成；逐句优先生产路线的默认时间轴已切到 WhisperX，**2026-11-28 做第一次真实生产测试**。

本页只讲生产化和批准。A/B 方法、MFA 对比与精度证据见[实验 README](../experiments/whisperx-timeline-ab/README.zh.md)和[运行报告](reports/runs/20261127-whisperx-timeline-ab/INDEX.md)。

**2026-11-27 21:59 PST 已批准**：用户听审后批准 timing-only revision，批准包为 `artifacts/sentence-first-agent/20261108-sermon-source/layer1-whisperx/english-source.approved.json`（SHA-256 `b51086be…`），批准收据 `timeline-approval-receipt.json`（SHA-256 `c00ec9e1…`）。批准语义是「时间轴」通过；英文文本和窗口继承父包原批准。

## 默认规则（2026-11-27 起）

逐句优先生产路线的默认时间轴是 **WhisperX 强制对齐的批准包**，不是父包的 `whisper-1` 时间轴：

- `sfa.py start` 传父 `--english-package` 时，自动寻找同一期目录下的 `layer1-whisperx/english-source.approved.json`（默认 sibling；也兼容 `<layer1>/layer1-whisperx/`）；找到就用它填 anchor/media/window/英文包。
- 没有批准包时 **fail closed**，提示先生成/听审/批准；不会静默退回父时间轴。自动选中前会核对批准包的 `evidence` 是否绑定当前父包 SHA-256，不同期或旧包会被拒绝。
- 显式 `--timeline-package <approved>` 仍然优先，用于页面/窗口与父包不同目录的情况。
- `--allow-parent-timeline` 是明确的回滚/旧路径：继续用父 `whisper-1` 时间轴；不要用它绕过缺失的批准。
- 候选包和未批准包都会被拒绝；2026-11-08 的批准只覆盖该期，其他期次逐期批准。

## 现在能做什么

对一份已人工批准的 `english-source.json`，在**不改英文文本、不改单元 ID、不改批准窗口**的前提下，用 WhisperX 重新生成词级时间轴，产出：

1. 新的 `anchor-manifest.json`；
2. 新的 `english-source.json` **候选包**（`translationEligible=false`、`review.humanApproval=false`）；
3. 逐单元 `timeline-review.csv` 和可听审的 `timeline-review.html`；
4. 绑定父包、媒体、窗口、文本、运行时、适配器和结果哈希的 `whisperx-timeline-receipt.json`。

听审通过后，`--approve` 写 `english-source.approved.json`。只有这个批准包可以进入每周开工。2026-11-08 已经批准：

```bash
# 默认：只给父 english-source.json；同一期目录 layer1-whisperx/english-source.approved.json 自动选中
python3 experiments/sentence-first-agent/sfa.py start \
  --run <run> --locale zh-Hans \
  --english-package <layer1>/english-source.json \
  --units 0:459 --title "<title>" --sync --publish

# 显式指定批准包（目录不同或审核包单独放置时）
python3 experiments/sentence-first-agent/sfa.py start \
  --run <run> --locale zh-Hans \
  --timeline-package <layer1-whisperx>/english-source.approved.json \
  --units 0:459 --title "<title>" --sync --publish
```

自动选中的批准包（或显式 `--timeline-package`）会校验并自动填 `--anchor`、`--media`、`--window-start` 和 `--english-package`；候选包会被拒绝（`not translation-eligible`）。它还会把 `--margin-before/--margin-after` **夹到批准窗口内**，避免首单元不在 0 或末单元离媒体结尾不足时 `prepare_clip` 越界。

## 2026-11-08 真实候选

| 项 | 值 |
|---|---|
| 父包 | `artifacts/sentence-first-agent/20261108-sermon-source/layer1/english-source.json`（已人工批准） |
| 媒体 | `Saturday_530pm_Live__1080-2.mp4`，2,147.055 秒，SHA-256 `daf51ba5…` |
| 输出 | `artifacts/sentence-first-agent/20261108-sermon-source/layer1-whisperx/` |
| 单元/词 | 460 / 6,136 |
| 对齐分块 | 123，`chunk_exact` 123/123，0 失败 |
| 对齐耗时 | 50.3 秒（0.023× 实时，M1 Max CPU） |
| 结构 | 0 零/负时长、0 相邻重叠、0 非单调；最长词 2.462 秒 |
| 单元起点位移 | P50 0.1275 秒、P90 0.4555、P95 0.5312、最大 4.104；>250 ms 139/460，>500 ms 34/460 |
| 单元终点位移 | P50 0.046、P90 0.180、P95 0.297、最大 2.076；>250 ms 26/460 |
| 与实验 B 复现 | 6,136 个词起点逐词最大差 0.000 秒（同一模型、同一文本、从批准媒体重新抽音频） |

候选包与批准包哈希：

| 产物 | SHA-256 |
|---|---|
| `anchor-manifest.json` | `1fccaa1b603747605f1a1f3f2bd0d2636e417e08ffc28e18968a3a9ff426b294` |
| `english-source.json` | `b1fdcd26941ebbf16fa29fa24045e5096d500829be3ff23dc72d8d6d1cbb989f` |
| `whisperx-words.json` | `b41c2d612110463c89d08a7147c0e07a4ea56e1f3514af0bc0c47a68bdf2b23b` |
| `whisperx-timeline-receipt.json` | `d4f3faac744832cfbee7fc4dafb14fe8ed8b4e4ad31b153a278a802291171393` |
| `timeline-review.csv` | `ae501cceea0bd732c992b7f7ff7c3356933894c4e5285a8b1fa0ca90d3ff92fc` |
| `timeline-review.html` | `b485d469e4e1e04217359092482fc829af0997143be440d83c2d8b194b49318e` |
| `english-source.approved.json` | `b51086be4e4cb5a56ccbe1342f5b6eb4099cbbdbf4c8f4df3449bdcc515ca879` |
| `timeline-approval-receipt.json` | `c00ec9e15c00817a78f647077ed74c0befc0ca8608840ddfaacfd4304e9dfed4` |

`source-clip.wav` 是批准媒体按批准窗口重新抽出的 16 kHz 单声道音频（66 MB），SHA-256 `27946c1f…`；它与实验中使用的 `sermon-16k.wav` 内容一致，逐词时间也与实验 B 完全一致。

## 已验证的生产门

| 门 | 命令/证据 | 结果 |
|---|---|---|
| 候选结构检查 | `python3 -m tongxing_production.source.whisperx_timeline --out <out> --check` | `pass` |
| `prepare_clip` 消费 | 用候选 anchor 建 460 句、460 个原声切片 | 句表单调、无缺失；`clip.json` 绑定候选 anchor |
| 候选包拒绝 | `sfa.py start --timeline-package <candidate>` | 拒绝：`not translation-eligible` |
| 批准包接受 | 真实批准后 `sfa.py start --plan --timeline-package <approved>` | plan 生成，`anchor/media/window/english-package` 自动填好；margin 夹到批准窗口 |
| 批准包字段 | `--check` 与候选包对比 | `translationEligible=true`、`review.humanApproval=true`、四项 `checks=approved`、`review.evidence` 绑定批准收据 |
| Setup preflight | `preflight.py --stage setup --english-package <approved>` | pass；460/460 单元、humanApproval、translationEligible 均通过 |
| 批准包开工 setup | `sfa.py start --timeline-package <approved> --no-sync --no-publish` | pass；460 句/460 切片；clip 2,147.055 秒；margin 自动夹为 0.526/3.094667 |
| 开工 plan | `sfa.py start --plan --timeline-package <approved>` | pass；自动填 anchor/media/window/english-package |
| 发布合同字段 | 逐项核对 `sfa_publish._build_clip_reference` 的绑定 | pass；anchor/transcript/receipt/unit IDs 全部一致 |

## 命令

### 1. 生成候选

```bash
PYTHONPATH=packages/production/src python3 -m tongxing_production.source.whisperx_timeline \
  --english-source <layer1>/english-source.json \
  --out <layer1-whisperx> \
  --runtime-python "$WHISPERX_PYTHON"
```

`WHISPERX_PYTHON` 指向独立 runtime（Python 3.11 + `whisperx==3.8.6` + torch 2.8；本机为 `artifacts/whisperx-timeline-ab/runtime/bin/python`）。不要把它装进生产轻量 `.venv`。模型缓存约 3.3 GB（faster-whisper-large-v3 2.9 GB + wav2vec2 360 MB）。

### 2. 检查与听审

```bash
PYTHONPATH=packages/production/src python3 -m tongxing_production.source.whisperx_timeline \
  --out <layer1-whisperx> --check
open <layer1-whisperx>/timeline-review.html
```

听审页按「父时间轴 vs WhisperX」位移最大的 20 个单元切原声片段。重点听：专名、数字、否定、掌声/长停顿边界、窗口首尾。CSV 给出全部 460 个单元。

### 3. 批准（2026-11-08 已执行）

只有用户亲口确认听审通过后才运行；本候选已于 **2026-11-27 21:59 PST** 批准，命令保留供下一期使用：

```bash
PYTHONPATH=packages/production/src python3 -m tongxing_production.source.whisperx_timeline \
  --out <layer1-whisperx> \
  --approve "<reviewer>" --approved-at "<ISO-8601 with timezone>" \
  --review-file <layer1-whisperx>/timeline-review.csv
```

它写 `english-source.approved.json` 和 `timeline-approval-receipt.json`，不改写候选包。批准语义是**timing-only revision**：英文文本和批准窗口继承父包；`wordAlignment` 是新的人工结论；`sourceIdentity`/`transcriptCompleteness`/`sentenceAndPauseBoundaries` 继承父包批准并在收据里注明。批准收据的 `reviewFileSha256` 绑定听审 CSV；事后改写 CSV 会使收据失效。

### 4. 开工（默认自动选批准包）

```bash
python3 experiments/sentence-first-agent/sfa.py start \
  --run <run> --locale zh-Hans \
  --english-package <layer1>/english-source.json \
  --units <LO:HI> --title "<title>" --sync --publish
```

传父 `--english-package` 时，`sfa.py start` 自动选同一期目录下的 `layer1-whisperx/english-source.approved.json`（默认 sibling；也兼容 `<layer1>/layer1-whisperx/`）；`--anchor`、`--media`、`--window-start`、`--english-package` 由批准包填。`--units` 仍按批准的锚点单元范围给。没有批准包会报错并给生成命令，不会静默用父时间轴。

显式 `--timeline-package` 仍可用于不同目录；显式 `--anchor`/`--media`/`--window-start` 与包冲突会报错。回滚用 `--allow-parent-timeline`。

## 失效与回滚

- **新 Layer 1 身份**：时间轴变化会使所有 locale 的下游失效；必须按新 run 重建 L2/L3，不能把新时间写回旧包。旧 run 的父包和旧媒体不受影响。
- **回滚（单次 run）**：加 `--allow-parent-timeline`；若同时给父 `--english-package`，`sfa.py` 会从父包填 anchor/media/window。继续用父 `whisper-1` 时间轴；或删除 `layer1-whisperx/`（它在忽略目录，未进 Git）。回滚只影响本次 run，不改变默认。
- **不要**把候选包（`translationEligible=false`）拿去翻译或发布；`sfa.py` 和发布 gate 会拒绝。
- **不要**在没有听审的情况下运行 `--approve`；批准收据会绑定 `reviewFileSha256`，事后改写 CSV 会使收据失效。

## 批准记录

| 项 | 值 |
|---|---|
| 批准人 | Jony（chat，2026-11-27 21:59 PST） |
| 批准时间 | `2026-11-28T05:59:19+00:00` |
| 批准包 | `english-source.approved.json`，SHA-256 `b51086be4e4cb5a56ccbe1342f5b6eb4099cbbdbf4c8f4df3449bdcc515ca879` |
| 批准收据 | `timeline-approval-receipt.json`，SHA-256 `c00ec9e15c00817a78f647077ed74c0befc0ca8608840ddfaacfd4304e9dfed4` |
| 绑定 | 候选 receipt `d4f3faac…`、anchor manifest `1fccaa1b…`、whisperx words `b41c2d61…`、听审 CSV `ae501cce…` |
| 语义 | timing-only revision；文本/窗口继承父批准；`wordAlignment` 是新的人工结论 |
| 未改变 | 没有改父包、没有发布、没有改默认值、没有跑 L2/L3 |

## 2026-11-28 首次真实生产测试清单

明天用新一期真实素材按下面顺序跑；任何一步失败先停下修，不带失败进下一步。

1. **父 Layer 1 英文包**：按原周更流程完成英文文本、窗口和人工批准，得到 `<layer1>/english-source.json`；确认 `translationEligible=true`、`review.humanApproval=true`。
2. **生成 WhisperX 候选**：
   ```bash
   WHISPERX_PYTHON=<isolated-python-3.11-with-whisperx-3.8.6> \
   PYTHONPATH=packages/production/src python3 -m tongxing_production.source.whisperx_timeline \
     --english-source <layer1>/english-source.json --out <layer1-whisperx>
   ```
   看输出：`units`/`words` 与父包一致、`chunk_exact` 全成功、0 结构问题。非 0 退出或分块回退即停。
3. **结构与听审**：
   ```bash
   PYTHONPATH=packages/production/src python3 -m tongxing_production.source.whisperx_timeline \
     --out <layer1-whisperx> --check
   open <layer1-whisperx>/timeline-review.html
   ```
   用户听审后批准；批准命令写入 `english-source.approved.json` 和收据。未经听审不批准。
4. **开工 plan**：
   ```bash
   python3 experiments/sentence-first-agent/sfa.py start \
     --run <run> --locale zh-Hans --english-package <layer1>/english-source.json \
     --units <LO:HI> --title "<title>" --sync --publish --plan
   ```
   计划里应有 `timelineSource: default_sibling` 和 `timelinePackage` 指向批准包；`windowStart` 来自批准窗口。plan 通过才正式 start。
5. **正式 start**：去掉 `--plan`。检查 `setup.json` 的 `inputs.timelinePackage`、`timelineSource`、`timelineMargins`，以及 `sentences`/`clipSeconds` 与批准包一致。preflight 必须 pass。
6. **L2/L3**：按周更继续翻译、复核、TTS；所有 locale 都以新 anchor 为准，旧 run 不复用。
7. **发布前**：`sfa_publish.py` 仍要求英文包 `status=ready_for_translation`、`translationEligible=true`、`review.humanApproval=true`、四项 checks approved；发布 gate 和 smoke 按原流程。
8. **回滚**：如果时间轴有问题，停在下游之前，用父包重开：
   ```bash
   python3 experiments/sentence-first-agent/sfa.py start \
     --run <run> --locale zh-Hans --english-package <layer1>/english-source.json \
     --allow-parent-timeline --units <LO:HI> --title "<title>" --sync --publish
   ```
   给了父 `--english-package` 时会从父包填 anchor/media/window；也可显式给 `--anchor`/`--media`/`--window-start`。不要手改批准收据或听审 CSV。

测试完成后把模型/适配器哈希、`chunk_exact` 结果、单元位移、`setup.json`、发布 gate 结果写进运行报告，并更新本页状态。

## 还剩什么

1. **2026-11-28 首次真实生产测试**：按上面清单跑一期；这是默认切换后的第一次真实运行。
2. 测试通过后保持默认；若失败，按回滚步骤回父时间轴，并记录失败阶段与原因。
3. 连续两期人工听审和真实周更通过后，才把默认写进更广的生产文档/其他形态；当前默认范围是逐句优先生产路线。

## 相关

- [A/B 实验与 MFA 精度证据](../experiments/whisperx-timeline-ab/README.zh.md)
- [A/B 运行报告](reports/runs/20261127-whisperx-timeline-ab/INDEX.md)
- [生产候选运行报告](reports/runs/20261127-whisperx-timeline-production/INDEX.md)
- [逐句优先生产路线](sentence-first-agent-production.zh.md)
- [逐句优先 runbook](../experiments/sentence-first-agent/AGENTS.md)
- [四层合同](multilingual-production-interfaces.zh.md)
