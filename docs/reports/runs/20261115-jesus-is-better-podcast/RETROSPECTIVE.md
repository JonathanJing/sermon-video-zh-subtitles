# 复盘：20261115-jesus-is-better-podcast

数据见同目录 INDEX.md 和 manifest.json。

## 结论先行

- **交付类型**：`four_layer_release` 的播客页（`mediaType=podcast`，类别「证道播客」），三语 zh-Hans / ko / es。
- **最终状态**：正式站 `https://ai-for-god-sermon-audio.web.app` 页面 `if-i-had-more-time-jesus-is-better-than-this-world` 三语上线。三次部署：资产 `0c4115942fdaf008`、release 与目录 `400cab78227648ec`、英文对照 `6e795dbcdd1580d0`；`verify` 12/12，`readback` 6/6，`sfa_publish_gate` pass，浏览器 smoke 三语 pass（`--no-session`）。
- **音轨**：zh 2733.69 s（45:34）、ko 3064.89 s（51:05）、es 3058.49 s（50:58）；MP3 192 kb/s，54.7 / 61.3 / 61.2 MB；独立音轨、自然语速、不跟视频钟。
- **审核**：窗口、冻结决策、讲员映射与英文表由用户在对话中确认；三条整轨由用户 2026-11-15 06:53 PST 确认通过（`reviewMode=whole_track`，收据绑定三条 `track.wav` 与 `review.mp3` 哈希）。
- **证据边界**：统计目录未同步（本机无 `sermon-feedback-api` checkout），`/api/session` 未验证；真机、现场、海报 `not_run`。译文经 Opus 独立保真审计（zh 8 / ko 5 / es 9 条，采纳 19 条），是机器复核，不是逐句人工审校。

## 总时间

墙钟约 **7 h 25 min**（2026-11-14 23:16 → 2026-11-15 08:00 PST），其中用户听审约 5 h 50 min。

| 阶段 | PST | 时长 | 性质 |
|---|---|---|---|
| 下载、whisper、gpt-4o 两遍、修复丢段、说话人区分、句表 | 23:18–23:47 | 29 min | 计算 |
| 用户确认窗口、冻结决策、讲员映射 | 23:36–23:47 | 11 min | 等待（与上一行重叠） |
| 英文表审阅 | 23:47–23:57 | 10 min | 等待 |
| 三语 Opus 初译、保真审计、读法、build_speech | 23:49–00:12 | 23 min | 计算（含一次派发返工） |
| Spark 三语 × 两讲员 TTS | 00:01–00:39 | 38 min | 计算（GPU 串行） |
| 每语 merge、MP3、播放器 | 00:19 / 00:29 / 00:44 | 6 min | 计算（与 TTS 重叠） |
| 用户整轨听审 | 00:44–06:53 | 6 h 09 min | 等待 |
| 收据、发布三步、gate、smoke、报告 | 06:53–08:00 | 67 min | 计算（含 2 次 CLI 部署被系统杀死与一次 412 对齐） |

计算约 **1 h 35 min**，等待约 **6 h 20 min**，返工约 **1 h 12 min**（claude 派发 1 次、finish_run 视频 mux 1 次、零长句界与毫秒重叠 2 次、CLI 部署 2 次失败 + lease 412 1 次）。

## 各层模型、耗时与速度

| 层／阶段 | 模型或后端 | 调用次数 | 计算耗时 | token 或音频秒数 | 速度 | 费用 | 证据 |
|---|---|---|---|---|---|---|---|
| L1 whisper-1 词时间 | OpenAI `whisper-1` verbose_json | 1 | ≈2 min | 2604.48 s / 7485 词 / 608 segments | ≈21× 实时 | 未结算（脚本未落 usage 收据） | `layer1/raw-whisper.json`、`words.json` |
| L1 文本第二遍 | OpenAI `gpt-4o-transcribe` 240 s 分块 | 11 + 4 修复 | ≈6 min | 7354 词；两块丢段后各切半重转 | — | 未结算 | `layer1/gpt-4o-chunks.json`、`gpt-4o-repair.json` |
| L1 说话人区分 | OpenAI `gpt-4o-transcribe-diarize` 1350 s × 2 | 3（含第二块已知参考重跑） | ≈14 min | 1184 + 611 segments | 0.42× 实时 | 未结算 | `openai-asr/openai-diarize-raw.json` |
| L1 句表 | 本机 v3 builder + `assign_speakers.py --use-text` | 2 | <1 min | 790 句；Eric 442 / John 348；低一致度 21 | 0 | 0 | `layer1/anchor-manifest.json`、`english-review.csv` |
| L2 初译 | Claude CLI Opus 5.5 | 12 分片（3 语 × 4） | ≈7 min（6 并发） | 790 句/语 | — | 订阅额度，未结算 | `translate/output-*.jsonl` |
| L2 独立审计 | Claude CLI Opus 5.5 | 3（1/语） | ≈2 min（3 并发） | 790 句/语 | — | 未结算 | `audit/audit-<locale>.jsonl` |
| L3 配音 | Spark Qwen3-TTS 讲员 SFT：`eric_pilot`、`john_thomas` | 6 job（3 语 × 2 讲员），batch 8 | zh 689 s、ko 745 s、es 744 s（含加载） | 790 句/语 | 4.47–4.52× 实时 | 0（本地 GPU） | `tts/`、`tts-run.log`、`schedule.json` |
| L4 构建 | `sfa_publish.py assets/stage1/stage2/stage-english-reference` | 4 | ≈4 min | 3 语页面/文稿/字幕/MP3 | — | 0 | `assets/`、`stage*/` |
| L4 部署 | `tools/ops/hosting_incremental_publish.py`（Hosting REST clone+populate） | 3 | ≈1 min | 12 / 6 / 1 个文件，163 MB / 25 KB / 69 KB | — | 0 | `stage*/incremental-publish.json` |

## 错误

| 层／阶段 | 现象 | 原因 | 发现时机 | 处理 | 回归测试 |
|---|---|---|---|---|---|
| L1 文本 | `gpt-4o-transcribe` 两块静默丢段（191 词、152 词） | 模型在 240 s 块上漏转 | 占用资源后（对齐比对时） | 新增 `layer1/repair_text_gaps.py`：按 whisper 词时间找空洞，把该块切两半重转，空洞清零 | 修复后文本 7354 词（0.98× whisper） |
| L1 句表 | 第一版 v2 句表在句界串词（「room Our kids have no idea.」） | 整篇 difflib 对齐在丢失填充词时漂移 | 预检（人工看句表） | 改为按 whisper 停顿段内逐词分配（v3），漂移不能跨停顿 | 790 句人工审阅通过 |
| L2 派发 | 12 个 Opus 翻译分片全部 0 行 | `claude -p` 的 cwd 在源目录，目标文件在 cwd 之外被权限拒绝 | 占用资源后（派发返回） | 派发脚本改成 `cwd=仓库根`，一次重派成功 | 三语 790 行 |
| L1 句界 | `sfa_publish assets` 两次被 iOS cue 校验拒绝（零长、毫秒重叠） | whisper 有 7 个单字单元 start == end，三位小数舍入又造出 4 处亚毫秒重叠 | 发布前（assets 门禁） | 句子时间按 manifest 重算并强制单调，写 `timeline-normalization.json` | assets 通过，790 cues |
| L3 收尾 | `finish_run.py` 首次在 zh 收尾时失败 | 源媒体只有音频，脚本默认 mux 视频流 | 占用资源后 | 加 `--no-video` 重跑；记入本报告 | 三语收尾成功 |
| L4 部署 | `firebase deploy` 两次被 SIGKILL | 站点快照 2.9 GB，CLI 单进程整站哈希上传，36 GiB 机器 jetsam（low-swap）杀死 | 部署中 | 核对未上线、释放残留 lease、写 reconciliation，改走 Hosting REST 增量发布 | 三次增量部署各一次成功 |
| L4 部署 | 增量发布首次上传 HTTP 412 | 上传协议是 POST `uploadUrl/<hash>` + gzip 体积，不是 PUT 文件路径 | 部署中 | 按 firebase-tools 的 uploader 实现修正脚本 | 三次部署通过 |

## 可以改进的地方

| 类别 | 改进 | 依据 | 预期收益 | 跟踪 |
|---|---|---|---|---|
| 流程 | 把 `hosting_incremental_publish.py` 接到 `sfa_publish publish` 的默认路径（CLI 失败时自动回退） | 本轮 2 次 CLI 部署被系统杀死，占用约 40 分钟并留下 lease 冲突 | 大站发布不再依赖单进程 CLI | 新增，待登记 |
| 速度 | `finish_run.py` 自动识别纯音频媒体并跳过视频 mux | zh 首轮收尾失败重跑 | 每期省一次返工 | 新增，待登记 |
| 预检 | 句表生成后立刻跑一次 iOS cue 等价检查（零长、单调、时长上限） | assets 两次被拒 | 发布前不再暴露句界问题 | 新增，待登记 |
| 质量 | `gpt-4o-transcribe` 分块加逐块词数覆盖率门禁（<0.9 即重转） | 两块丢段到对齐阶段才发现 | L1 少一步返工 | `layer1/repair_text_gaps.py` 已覆盖检测，可前移 |
| 流程 | 统计目录 `sermon-feedback-api` 纳入发布意图的固定项或明确记 gap | 连续两期 `/api/session` 无法验证 | 收听统计不再缺 | `DEV-USAGE-001` |

## 实际覆盖范围

- **L1**：执行（下载、whisper-1 词时间、gpt-4o-transcribe 第二遍 + 丢段修复、gpt-4o 说话人区分两遍、句表、讲员映射、人工英文表批准）。未执行 MFA。
- **L2**：执行（Opus 初译三语、Opus 独立保真审计、读法、build_speech、一致性检查）。机器审计不是人工逐句审校。
- **L3**：执行（三语两讲员 TTS、合并、review MP3、逐句播放器、整轨听审收据）。回转写 `not_run`（2026-10-28 退役）。
- **L4**：执行（三语页面/文稿/字幕/MP3、release v2、v5/v4/v3 目录、英文对照、gate、smoke）；对齐 sidecar 与研读手册 `not_run`（播客页合同不含）；统计目录 gap；海报/公告/推送 `not_run`。

## 遗留状态

- Spark 独占会话 `sfa-20261115-jesus-is-better-podcast` 仍在 `exclusive_ready`（听审期间保留以便改句重配），收尾 `finish` 后服务恢复；容器按会话结束清理。
- 本机产物、原始音频与 790×3 wav 全部在忽略的 `artifacts/`，不进 Git。
- 上一轮证道会话 `sfa-20261115-jesus-is-better` 已 closed；其残留状态已恢复服务。
- 两个被 CLI 杀死的未 finalize 版本已删除；publisher lease 已按 generation 释放。

## 外部可见的变化

- 正式站页面三语上线（部署版本见上）；目录 `defaultPageId` 已指向本页。
- `/english-reference/if-i-had-more-time-jesus-is-better-than-this-world.json` 上线，`readback` 通过。
- App 真机、现场与推送 `not_run`。

## 本机内存复盘（macOS「应用程序内存不足」弹窗）

**结论**：弹窗不是 Chrome 撑爆的。把系统推到 critical 的是 L4 部署阶段 `firebase deploy` 的**单个 Node 进程**（整站哈希 + 上传 2.9 GB 快照），它触发全系统 jetsam；macOS「强制退出应用」只列 GUI App，CLI 子进程根本不在列表里。

### 机器口径（先纠正一个前提）

- `hw.memsize` = 38,654,705,664 B = **36 GiB**，MacBook Pro `Mac17,11`（M5 Max，18 核）。
- 不是 48 GB。这条差距决定了余量：实际比预期少 12 GB，而 `firebase deploy` 要在这台机器上把整站过一遍。

### 时间线（PST）

| 时刻 | 事件 | 证据 |
|---|---|---|
| 06:56:05 | CLI 部署开始（`firebase deploy --only hosting --non-interactive --json`），待传 124 个文件 | `stage1/firebase-debug.log` 首行 14:56:05Z |
| 07:00:02 | 系统内存压力 warning | `modelmanagerd` memory pressure |
| 07:13:54 | 压力升到 **critical** | 同上 |
| 07:17:53 | 上传卡在 60/124，请求大量重试 | firebase-debug.log 末行 15:17:53Z |
| ~07:36 | CLI 子进程被 SIGKILL(9) | `subprocess.CalledProcessError ... died with SIGKILL: 9` |
| 07:42:37 | 核对：两次 CLI 均被杀、线上未产生 release | `stage1/deployment-reconciliation.json` |
| **07:43:13** | **全系统 jetsam，largestProcess=node** | `JetsamEvent-2026-11-15-074313.ips` |
| 07:48:09 | REST 增量发布成功（12 文件 / 163 MB） | `stage1/incremental-publish.json` |
| 07:52:59 | 用户看到弹窗 | 截图 |

### Jetsam 读数（pageSize = 16384）

| 项 | 值 |
|---|---|
| largestProcess | `node` |
| node rpages 记账 | 19,969,519 页 ≈ **304.7 GB**（峰值 306.0 GB） |
| node CPU 时间 | **470.6 s** |
| node 打开的文件描述符 | 256 |
| 被处理进程 | 1781 项：low-swap **1085**、idle-exit 221、per-process-limit 1 |
| compressor | 18.35 GB，里面装着 **54.9 GB** 逻辑页 |
| swap | 已用 9.3–9.6 GB（上限约 10–11 GB） |
| App 汇总（rpages 口径） | Chrome 8.22 GB / DSH 1.82 / Codex 1.56 / Claude 1.16 |

305 GB 在 36 GB 机器上不可能是真实物理占用，它是 jetsam 账本对该进程的记账。但「记账 305 GB + 470 秒 CPU + 256 个 fd」与「单进程对 2.9 GB / 480 文件快照做整站哈希与上传、124 个待传、大量重试」完全对应，且该子进程确实死于 SIGKILL(9)。

### 为什么弹窗看起来像 Chrome 的锅

- 弹窗按 **App 聚合**排序，Chrome 8.23 GB 排第一；node 是 CLI 子进程，不进「应用」列表。
- 弹窗数字与 jetsam 时刻的 App 汇总对得上（Chrome 8.22 vs 8.23），说明两者是同一轮压力。
- 真正的触发源是 node；GUI 大户只是把余量吃掉的人，不是把系统推过线的人。

### 同一晚已发生过一次

- 23:19:46 也有一份 jetsam，largestProcess 同样是 node（325.1 GB、494 s CPU、256 fd），签名一致。
- 那一轮证道运行已记录处理：Node 26 的 firebase CLI 被 SIGKILL，**改 Node 22 后 35 秒发完**（`docs/reports/runs/20261115-jesus-is-better/INDEX.md`）。
- 本机默认 `node` 是 v26.13.0（`/opt/homebrew/bin/node`），firebase CLI 15.29.0 以 `#!/usr/bin/env node` 启动；`node@22` 同时装在 `/opt/homebrew/opt/node@22`。
- 本轮播客发布没有沿 Node 22 这条路，而是改用 Hosting REST 增量发布，同样绕开 CLI。

### 哪个环节吃内存

| 环节 | 峰值形态 | 是否元凶 |
|---|---|---|
| L1 whisper / gpt-4o ASR | 云端 API，本机只有 v3 builder | 否 |
| L2 Opus 翻译 | `claude` CLI，6 并发 | 否 |
| L3 TTS（Qwen3-TTS，本地 GPU） | 串行 2 讲员 × 3 语，4.5× 实时 | 否（jetsam 账户里 python 占比很小） |
| L4 部署 `firebase deploy` | 单 Node 进程整站哈希上传 | **是** |

### 改进

1. 大站（> 1 GB）把 `hosting_incremental_publish.py` 设为默认路径，而不是 CLI 失败后再切。
2. 必须用 CLI 时钉 `PATH=/opt/homebrew/opt/node@22/bin:$PATH`：同一站点已在 11-14 晚证明 35 秒完成。
3. `sfa_publish publish` 起整站上传前加一条内存预检：`memory_pressure` ≥ warning 时先让用户关掉 GUI 大户（Chrome 8.2 GB）。
4. `artifacts/sentence-first-agent/*-publish/` 下现有 6 份 2.9 GB 快照副本（合计约 17 GB），既占磁盘也拖慢 Synology 同步；保留 `stage1` 与最终 baseline 即可。
