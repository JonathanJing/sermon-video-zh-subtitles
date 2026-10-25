# 复盘：20261024-sat400-sermon-zh-ko-es

数据见同目录 INDEX.md 和 manifest.json。本报告由执行本次运行的 agent 填写；自动汇总的数值已核对，与本机 `artifacts/` 及线上 HTTP 读回一致。

## 结论先行

- **交付类型**：`four_layer_release`（逐句优先线：单讲员证道配音页，非正式四层哈希链）。
- **最终状态**：已发布并逐项 HTTP 核验。生产页 `revelation-jesus-wins-20261025`，语言 zh-Hans / ko / es，418 句；三个 release 均 `published_http_verified` + `human_reviewed`；英文对照 `/english-reference/revelation-jesus-wins-20261025.json` 已上线（`reviewState human_approved`，三语各 418 blocks）。
- **结束信号**：`finish_run.py` 写 `outcome.json`（`track_ready_for_review`；发布驱动不写 outcome，本报告以部署版本与 HTTP 读回为准）；独占 Spark 会话以 `spark_exclusive_session.py finish` 的 `closed` + `model_health_restored` 行为准（02:33:46–02:33:52Z），不是 `tts exit 0`。
- **证据边界**：
  - 内容来源是 **2026-10-24 16:00 场直播录像**（YouTube `4gcPgvARNaM`），不是正式 Broadcast Message 文件；用户 2026-10-24 明确"已经确定是周日正式版"，页面按正式页发布，但来源身份与正式周更的来源不同。
  - 英文来源包是**本地 ASR 词级时间**（mlx-whisper large-v3-turbo），`implementation.notMfa=true`、`transcript.provenance.model=mlx-whisper`，批准收据写明 "timing is ASR-derived, not MFA"；没有 MFA 对齐。
  - 页面是音频+文字+字幕页（`mediaType=podcast` 是复用驱动里的技术标记），**没有发布视频**；31 分钟 `dub.mp4` 只在本地。
  - iOS 真机／TestFlight、浏览器播放、现场验收均 `not_run`。

## 总时间

墙钟 **1 小时 53 分**（2026-10-24 17:40:36 → 19:33:52 PDT）。拆分：

| 阶段 | 起止（PDT） | 耗时 | 性质 |
|---|---|---|---|
| 环境预检、来源确认、既有产物调查 | 17:40–17:41 | 1m | 计算 |
| 切片 + 本地 ASR（1861 s 音频） | 17:41–17:43:16 | 2m16s | 计算（ASR 81 s） |
| 英文表校对、分句、切片（418 句） | 17:43–17:57 | 14m | 计算 |
| 三语翻译（12 个子代理，4 段 × 3 语） | 18:00–18:11 | 11m | 计算 |
| 合并、保真审计、术语落地、中文润色 | 18:11–18:31 | 20m | 计算 + 3 轮子代理 |
| 预检／一致性／口播稿 | 18:31–18:36 | 5m | 计算 |
| Spark 会话 + TTS/ASR 队列（三语） | 18:36:44–19:01:08 | 24m24s | 计算（GPU） |
| 合轨、打分、MP3、播放器、dub（三语） | 19:01–19:10 | 9m | 计算 |
| 命名修改重配 + ASR 刷新（并行） | 19:04–19:08 | 4m | 返工 |
| 对齐复核 + 三语重出音轨 | 19:12–19:17 | 5m | 返工 |
| 海报交接包与内容 brief（独立交付） | 19:20–19:24 | 4m | 计算 |
| 英文来源包 + 发布（资产/基线/两次部署/回读/英文对照） | 19:24–19:33:52 | 10m | 计算 |
| 等用户（中文通过、三语通过、海报决定） | 分散 | ≈5m | 等待 |

journal 自动汇总（核对后保留）：三个 run 的 `l3.finish` 计算合计 231 + 303 + 160 s，返工 150 + 152 + 75 s（每个 run 各 3 次 `finish_run`：首跑、重配后、对齐后）。没有 `waiting` 记录——等待发生在对话里，没进 journal，这是本轮的方法缺口（见改进项）。

对比上一轮同类（2026-10-23 片段，187 句、两语、Dev）：本轮句子数 ×2.2、语言 ×1.5、多一次生产发布和英文对照，墙钟 1h53m 对上一轮约 4h（含人工听审等待）。TTS 段明显更快：本轮 batch 8 + 8 副本 4.3–4.5× 实时，上一轮记录 1.36×（batch 1）。

## 各层模型、耗时与速度

| 层／阶段 | 模型或后端 | 推理强度／tier | 调用次数 | 计算耗时 | token 或音频秒数 | 速度 | 费用 | 证据 |
|---|---|---|---|---|---|---|---|---|
| L1 来源 ASR | mlx-whisper large-v3-turbo（本机 Metal） | ? | 1 | 81 s | 1861 s 音频 → 5,411 词 | **23× 实时** | $0（本地） | `artifacts/tmp/20261024-sat400/sermon.json`（未导出） |
| L1 词级对齐（MFA） | — | — | 0 | — | — | not_run | — | 包内 `implementation.notMfa=true` |
| L1 英文机器评审 | — | — | 0 | — | — | not_run（人工审阅 418 行英文表 + 16 处手改 + 术语表） | — | `20261024-sat400-review/english-review.csv` |
| L2 初译 | 子代理（DeepSeek），3 语 × 4 段 | ? | 12 | ≈11 min 墙钟 | 418 行 × 3 | 105 行/代理，2–4 min/段 | $0（本地 harness，无外部 API） | `translate/output-*.jsonl` |
| L2 独立审核 | 子代理，保真审计 3 + 中文润色 2 | ? | 5 | ≈6 min | 1254 行审计，zh 改 54 行 | — | $0 | `translate/audit-*.json`、`refine-zh-*.json` |
| 文本质检（回译） | — | — | 0 | — | — | not_run（文本无回译；音频侧用回转写替代） | — | — |
| L3 配音（TTS） | Qwen3-TTS-1.7B-Base，Eric `75d28ce6…`，batch 8，8 副本，seed 7 | ? | 1,262 句（418×3 + 7 重配 + 5 追加） | zh 337.0 s / ko 363.9 s / es 367.1 s | 音频 1488.6 / 1576.0 / 1645.8 s | **4.42× / 4.33× / 4.48× 实时** | $0（本地 GPU） | `tts/tts-log.jsonl`、`dub` 摘要 |
| L3 回转写筛查（ASR） | Qwen3-ASR-0.6B，batch 8 | ? | 418 × 3（+2 次刷新） | 53 / 69 / 63 s（含模型加载） | 1,860 s 音频/语 | ≈30× 实时 | $0 | `asr.jsonl`、`asr-report.json` |
| 音频质检 | ASR 相似度 + `asr_triage.py` | — | 3 | <5 s | 418 句/语 | 均值 0.968 / 0.969 / 0.978；低于 0.85 的 31 / 26 / 20 句，全部同音 | $0 | `asr-triage.json` |
| L4 构建与发布 | 本仓库驱动 + Firebase Hosting | — | 3 次部署 | ≈10 min（含两次基线快照） | 12 个新资产 + 3 release + 3 catalog + 1 英文对照 | 部署各 ≈60 s | $0（Hosting 免费额度内） | 部署版本 `22e320b695949faf` → `21663e72c2408249` → `c3890bd4d3b193e3` |

已复制收据里出现的模型（自动汇总）：英文包 `implementation.notMfa=true`、`mlx-whisper large-v3-turbo`；其余模型身份只在本机 `tts-log.jsonl`／`asr-run.log` 中，未进报告副本。

## 错误

| 层／阶段 | 现象 | 原因 | 发现时机 | 处理 | 回归测试 | 提交或 PR |
|---|---|---|---|---|---|---|
| 工具（预检/一致性/分诊/规整） | 脚本方式运行必抛 `NameError: _mark` | `_mark` 定义在 `if __name__ == "__main__"` 之后，import 时不报、脚本运行时未定义 | 预检（第一次 `preflight.py`） | 四份脚本把 `_mark` 移到 `__main__` 之前 | 三语 `preflight`/`consistency_check` 均通过；本轮路径实测 | `84927194` |
| L1→L4 身份字段 | `preflight --english-package` 报 `english:unit-coverage missing=[None]` | `split_sentences.py` 不写 `sourceUnitId`，手写路径没补；只有带英文包的预检才会查这项 | **占用 Spark 之后**（TTS 已跑完、发布前） | 给三语 `sentences.jsonl` 按锚点顺序补 `asr-u0001…u0418`，重跑预检通过 | 预检 `pass`；三语 content/captions/英文对照 `textGroupId` 顺序一致 | 本轮产物内修复，未改脚本 |
| L4 发布 | `stage-english-reference` 报 `Asset escapes public directory` | `build_clip_reference` 的 `public_path` 用未 `resolve()` 的相对根做 `is_relative_to` | 发布前（第三次部署之前） | 传绝对 `--base` 路径后通过；驱动本身仍是相对路径才正确 | 英文对照三语各 418 blocks，HTTP 200 | 待修（改驱动 `Path(...).resolve()`） |
| L3 对齐 | 默认 `merge_track --gap 0.25` 把连续句逐句推后：zh 60 句、ko 78 句、es 144 句落后 >1 s，es 中位 0.43 s | 句间最小间隔叠加在首尾相接的英文句上 | **发布前、用户追问"现场音频对齐"后** | 三语 `finish_run --gap 0.05` 重出：中位 0 s，≤0.1 s 占 76.6/75.1/60.5%，最大 4.46/2.19/3.36 s | 帧核对 `dub.mp4` t=0/600/900 与源 1716/2316/2616 逐字节相同 | 本轮产物内修复；`finish_run` 默认值未改 |
| L2 韩语 | 术语替换把 `고발을/이/은` 机械替换成 `참소을/이/은`，产生 13 处助词错误；其中 3 处朗读也被带错 | 全局字符串替换忽略助词音变 | 合轨后（首次 ASR 打分） | 文本改 `참소를/가/는`；s0097、s0208、s0228 以 batch 1 重配，ASR 回到 1.0 | 重跑 ASR 刷新 | 本轮产物内修复 |
| L2 中文 | 早期译文过度压缩（"父死狱中"式标题体） | 同步预算给的 `maxChars` 偏保守 + 译者在预算内继续压缩 | 合轨前自查 | 两段中文润色，改 54 行；总字数仍只占预算 78% | 逐句保真审计通过 | 本轮产物内修复 |
| L4 发布 | 首次 `verify` 抛 404 | CDN 传播延迟（新版本刚上线） | 第一次 `verify` | 等 25 s 后重试，12/12 通过 | HTTP SHA + MP3 Range 206 | 本轮重试 |
| 报告工具 | `INDEX.md` 把每个 stage 都列为 `Failed stages` | `export_run_digest.py` 把 `timings.tsv` 第 2 列当状态列；逐句优先线写的是 `computeSeconds` | 本报告首次生成时 | 按表头判断是否存在 `status` 列；无状态列不再标记 | `tests/test_export_run_digest.py` 26 passed | 本轮修复（另提交） |
| 审核收据 | 用户 19:07 通过的中文音频在 19:04 已被重配（水手教会）、19:16 又被对齐重出 | 修改发生在审听之后 | 记录收据时 | 收据分开记"听过的音频哈希"与"发布时音频哈希"，标 `unheardAfterApproval`；用户 19:30 再次确认三语 | — | `human-review-verdict.json` |

## 可以改进的地方

| 类别 | 改进 | 依据（本报告的数值或错误） | 预期收益 | 负责人 | 跟踪 |
|---|---|---|---|---|---|
| 预检 | 带 `--english-package` 的预检必须在 TTS 之前跑 | 本轮 `sourceUnitId` 缺失是在 Spark 跑完之后才暴露 | 省一次返工，避免"资源占用后才发现身份缺失" | agent | 本轮错误表第 2 行 |
| 预检 | 片段页发布驱动在入口处 `resolve()` 所有路径 | `Asset escapes public directory` | 去掉一次手工重试 | agent | 本轮错误表第 3 行 |
| 质量／流程 | 同步合成把 `--gap` 写进驱动默认或 run.md 模板 | 默认 0.25 s 让三语分别有 60/78/144 句落后 >1 s | 首版即对齐，省三语各一次重出 | agent | 本轮错误表第 4 行 |
| 流程 | 人工等待写进 journal（发出/收到听审结论时 `waiting`/`resumed`） | 自动汇总等待为 0，实际 ≈5 min；本轮忘记记 | 复盘时间拆分可信 | agent | 本报告"总时间"节 |
| 质量 | 术语替换后自动检查助词/助数词音变 | 韩语 13 处 `참소을` 类错误 | 减少重配 | agent | 本轮错误表第 5 行 |
| 成本／速度 | 中文同步预算按实测 4.95 字/s 校准后允许更接近预算 | 中文只用到预算 78%（1445/1859 s） | 少删内容、音轨更饱满 | agent | 本报告 L2 行 |
| 报告 | 发布型运行也写 `outcome.json` 的 published 状态与 timings | 本轮 publish 目录无 outcome/journal，报告只能手工补 | 报告自动完整 | agent | 本报告"总时间"节 |

## 实际覆盖范围

- **L1**：执行了本地 ASR（mlx-whisper）+ 英文文本手工校对 + 英文表人工批准；**未执行** MFA 词级对齐、英文机器评审、正式窗口批准（窗口由用户给的 28:36–59:37 直接采用）。
- **L2**：执行了三语代理翻译 + 独立保真审计 + 术语表 + 称呼/数字一致性检查 + 中文润色；**未执行** 回译质检、外部翻译 API。
- **L3**：执行了 Eric checkpoint 逐句 TTS（batch 8，8 副本）、回转写、ASR 分诊、合轨/打分/MP3/播放器/`dub.mp4`；**未执行** 人工整轨听审的机器收据绑定（听审由用户在对话里确认，收据手工记录）。
- **L4**：执行了资产构建、两次基线快照、两次页面部署、HTTP/SHA/Range 核验、目录与 release 回读、第三次部署加英文对照；**未执行** iOS 真机/TestFlight、浏览器播放、海报生成、推送。

## 遗留状态

- Spark：会话 `sfa-sat400-20261024` 已 `closed`，`llama-server.service` 已恢复；10 个停止的会话容器已 `docker rm`。
- 本机：`artifacts/sentence-first-agent/20261024-sat400-*`（三语 run、发布快照、英文包、审核表）与 `artifacts/sermon-poster/2026-10-25/prepare/`（海报 brief，待主视觉）保留在忽略目录；三语 `dub.mp4`、`review.mp3`、`tts/`、`slices/` 都在本地。
- 报告服务器：`python3 -m http.server -d artifacts/sentence-first-agent 8765` 仍在后台，供听审回看；不再需要时可停。
- 未结束的 job hold：无。

## 外部可见的变化

- **生产 Hosting**：`sites/ai-for-god-sermon-audio/versions/22e320b695949faf`（资产）→ `21663e72c2408249`（release + v5/v4/v3 目录）→ `c3890bd4d3b193e3`（英文对照，最终 live）。页面、三语文稿/字幕/MP3、英文对照均 200，SHA 与发布字节一致。
- **Git**：`84927194` 推送到 `docs/sat400-prep-design-20261024`（四个脚本 `_mark` 顺序修复 + 本页生产驱动），未跳过分支保护。
- **TestFlight／App Store**：无。
- **设备与现场**：`not_run`。
- **海报与推送**：未生成、未发送；交接包与准备目录已就绪。
