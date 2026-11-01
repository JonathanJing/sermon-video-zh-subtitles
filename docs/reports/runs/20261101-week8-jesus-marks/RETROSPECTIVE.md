# 复盘：20261101-week8-jesus-marks

数据见同目录 INDEX.md 和 manifest.json。

## 结论先行

- **交付类型**：`four_layer_release`（逐句优先代理直做路线），2026-11-01 第 8 周「耶稣为属祂的人盖印」（Eric Geiger，启示录 14），三语 zh-Hans / ko / es，各 477 句。
- **最终状态**：已发布到正式站 `ai-for-god-sermon-audio`，部署版本 **`85b9364afa0ae230`**；HTTP 核验 12/12 通过、三次部署 readback 通过（含 `/english-reference/`）、浏览器 smoke（含 `/api/session`）三语 pass；反馈统计目录已按线上源码包重建（43 sources／42 localized）并重新部署函数。
- **结束信号**：审核收据 `human-review-verdict.json`（`verdict=approved`、`reviewMode=flagged_only`、reviewedAt 2026-10-31T21:12:12-07:00）；Spark 会话 `sfa-jm-20261101` 已 `closed`、服务恢复；publish 的 outcome/timings 见 `20261101-jesus-marks-publish`。
- **证据边界**：真机与现场 `not_run`；海报与公告 sidecar `not_run`（由用户独立海报 agent 负责，无海报收据）；审核是播放器抽查（flagged_only，非整轨）；英文词级时间来自本机 mlx-whisper，不是 MFA。

## 总时间

墙钟 **约 1 h 47 min**（19:37→21:24 PDT）：来源冻结与 ASR 5 min、英文表人审 6 min、翻译+审计 6 min、TTS 首轮 24 min、三语同步精简与重配 35 min、用户审核 4 min、中文改句重配 4 min、发布与核验 12 min。

## 各层模型、耗时与速度

| 层／阶段 | 模型或后端 | 推理强度／tier | 调用次数 | 计算耗时 | token 或音频秒数 | 速度 | 费用（list 估算） | 证据 |
|---|---|---|---|---|---|---|---|---|
| L1 来源 ASR | 本机 `mlx-whisper large-v3-turbo`（非 MFA） | — | 1 | 约 3 min | 2019.4 s 音频 / 6258 词 | — | 0 | `20261101-sermon-source/transcript.json`、`anchor-manifest.json` |
| L1 英文人审 | 用户逐句审 `english-review.csv` | — | 1 | 6 min（人） | 477 句 | — | 0 | `english-source-review.json` |
| L2 初译 | Claude CLI `claude-opus-5-5` | — | 12（3 语 × 4 分片） | 约 4 min（4 并发） | 477 句/语 | — | $5.90 | `translate/usage-<locale>-<k>.json` |
| L2 独立审计 | Claude CLI `claude-opus-5-5` | — | 3 | 约 2 min | 477 句/语 | — | $1.46 | `audit/usage-<locale>.json`（zh 5／ko 12／es 2 条修订） |
| L2 同步精简（改短） | Claude CLI `claude-opus-5-5` | — | 31 分片 | 约 9 min（4 并发） | zh 253／ko 462／es 451 句入选 | — | 约 $10.8 | `review.json` revisions（`sync trim (opus)`） |
| L3 配音（TTS） | Spark `Qwen3-TTS-12Hz-1.7B-Base`，Eric checkpoint `75d28ce6…` | batch 8，8 副本 | 3 轮整期 + 3 窗口修补 | 首轮 400/408/439 s；重配 386/364/363 s；修补 3×约 60 s | 三语各约 1700 s 音频 | 4.4–5.0× 实时 | 0（本地 GPU） | `tts/tts-log.jsonl`、`tts-batches.jsonl` |
| L3 回转写筛查 | 未执行（2026-10-28 起退役） | — | — | — | — | — | — | not_run |
| L4 构建与发布 | `sfa_publish.py`（本次修补 2 处，见 PR） | — | 3 次部署 | 约 8 min | 3×477 cues / 3×40 MB MP3 | — | 0 | `20261101-jesus-marks-publish/`（verify、readback、smoke、http-verification.json） |

## 与上一轮同类运行的差异

- 首次用单一发布驱动 `sfa_publish.py` 发布**整期**页面（此前是 10 分钟片段与播客页）；首次在 `production` 用 `mode: table` 标题门禁。
- 首次走 Claude CLI Opus 翻译链路（此前是子代理或 DeepSeek）；用并行分片替代 `lag_loop.py` 的 DeepSeek 顺序窗口后，三语同步精简从预估约 50 min 降到约 9 min。
- 首次在发布后重新部署反馈函数并修复 service account；`/api/session` 从 503 恢复到 200。

## 问题与修复

| # | 问题 | 影响 | 修复 |
|---|---|---|---|
| 1 | `sfa_publish.py` 的 `stage2` 不更新 `defaultPageId` | 新页不会成为目录默认页 | 本 PR 修补：追加页面时同时设默认页，投影检查改为比较「其他页与元数据」；实际 stage2 已把 defaultPageId 切到本页 |
| 2 | `sfa_publish.py` 的 `assets` 假定每句有 `speakerId` | 单讲员 run 直接 `KeyError` | 本 PR 修补：缺 `speakerId` 时从 `speech.jsonl` 的 `speaker` 取 |
| 3 | 首轮合轨 maxLag zh 27.06 s / ko 65.81 s / es 140.79 s | 不能发「可审」 | Opus 分片精简（203/373/371 句），重配后 4.3 / 2.84 / 3.05 s，over8 = 0 |
| 4 | `lag_loop.py` 的 DeepSeek 8 句顺序窗口太慢（zh 预计 30+ min） | 阻塞发布 | 改用 `trim_opus.py` 并行分片（4 并发×40 句），三语合计约 9 min |
| 5 | 反馈函数首次部署误用 build service account | `/api/session` 503 `storage_unavailable` | 用原运行时账号 `sermon-feedback-runtime@` 重新部署；smoke 恢复 pass |
| 6 | 标题表第 8 周中文旧值 | `titleCheck` 失败 | 先合并已获批的标题 PR #1535，再做发布门禁 |

## 未做与风险

- **海报与公告 sidecar**：`weekly-announcements-v1.json` 无本页条目（需要海报收据绑定），由用户的海报 agent 完成；主生产线未生成海报，也未推送。
- **真机与现场**：`not_run`；页面在 headless Chrome 中通过，但未在已安装的 iOS 版本上刷新确认，也没有现场验收。
- **审核深度**：`reviewMode=flagged_only`，用户按播放器标记抽查（约 4 分钟），不是三条整轨通听；收据如实记录。
- **英文时间轴**：本机 ASR 词级时间，不是 MFA；英文参考按单元覆盖 477/477，但词级时间精度低于 MFA。
- **反馈目录同步**：本次用线上源码包 + `build_language_listening_catalog.py` 重建并部署；第一次部署的 503 已修复，但当时约 2 分钟的 503 会产生窗口。
