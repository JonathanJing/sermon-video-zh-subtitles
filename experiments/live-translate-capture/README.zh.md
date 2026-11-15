# 周日现场讲道：translate.pastors.ai 采集端

这个实验解决一件事：周日讲员现场讲道、没有提前制作素材时，在固定时间窗内把翻译页面的**英文原文字幕**、**普通话译文音频**和**普通话字幕**一起录下来，并在服务结束后取回服务端的会话日志（带精确时间戳），供后续 Layer 1/Layer 2 和阅读版 PDF 使用。

它只负责采集，不做 ASR、翻译、审校或发布。

## 结论先看

- 2026-11-14 用正在直播的 `mariners-irvine-outdoor` 做了两次真实采集：
  - 直接运行 60 秒：英文 7 条 final，普通话音频 56.75 秒；同窗口会话日志 7/7 条英文 final 完全匹配。
  - 经 `run-capture.sh` 完整链路 74 秒：英文 22 条 final，普通话音频 73.75 秒；会话日志 39 条英文行，22/22 完全匹配（归一化后逐条相同）。
- 采集、断线续传、音频封装、会话日志取回、LaunchAgent 定时启动都已在本机跑通；18 个本地测试通过（含一个本地 WebSocket 假服务器，覆盖断线后带 `since` 重连）。
- 另做了一次 **10 分钟 demo 房间长测**：597.25 秒连续音频、0 次重连、0 个到达空隙；期间捕获到提供商会话轮换（540 秒 `goAway`、587 秒 `cutover`，`droppedMs=0`），音频没有断。
- 默认定时已装好：**每周日 09:55 启动，10:00 开始录，11:20 自动截断**，房间 `mariners-north-irvine`（2026-11-14 已确认）；LaunchAgent 见 `~/Library/LaunchAgents/ai.pastors.live-capture.plist`。
- 依赖只有仓库 venv 里的 `websockets` 和 `requests`，见 `requirements.txt`。

## 采集的是什么，不是什么

| 流 | `lang=` | 内容 | 用途 |
|---|---|---|---|
| 英文原文 | `captions` | 服务端 ASR 的英文 partial/final，**没有音频** | Layer 1 英文底稿的首选实时来源 |
| 普通话 | `zh` | 机器翻译后的普通话 TTS 音频（24 kHz PCM）+ 普通话字幕 | 音频版、人工与机器译文对照 |

**不是**：

- **不是英文原声。** 这个服务不提供讲员原声通道；`lang=en` 在实测中直接返回 HTTP 400。英文原声要另录：现场麦克风（可接现有的 `experiments/local-live-poc`）、教会直播流或调音台。
- **不是已批准的译文。** `zh` 的字幕和音频都是机器翻译/机器合成，只能做对照，不能当作 Layer 2 的批准文本，也不能把机器中文写进阅读版而不经过我们自己的翻译与审校。
- **不是在采集端切讲道。** 10:00–11:20 的整段服务全部保存（含敬拜、报告）；讲道起止由人工事后写入 `sermon.window.json`，后续流程按这个窗口取正文。

## 为什么这样采集

1. 英文 caption 流是提供方对现场英文的 ASR 结果，比录下音频再本地 ASR 更接近原文，也避免二次识别误差；这正符合“从英文来提取，然后我们自己翻译”的思路。
2. 同时录 `zh` 有两个价值：一是拿到页面的机器中文做对照，二是拿到普通话音频；但两者都明确标注为机器产物。
3. 服务端在服务结束后仍保留会话日志，里面的 `source`/`zh` final 行带**精确时间戳**。实时采集解决“断线也有副本 + 音频只有实时这一份”，会话日志解决“时间轴准”。两者都保存、都绑定哈希。

## 传输协议（实测）

```text
wss://translate.pastors.ai/ws/listen?room=<room>&lang=<code>&v=2[&since=<seq>][&lid=<uuid>]

二进制帧：4 字节大端 seq + int16 小端单声道 PCM，24 000 Hz，250 ms/帧（12 000 字节）
文本帧：status / caption / heartbeat / health / resumed / handoff
```

- 音频帧和字幕消息**共用一个 seq 空间**；断线后带 `since=<最后收到的 seq>` 重连，服务端回放字幕和很短的音频窗口。
- 服务端每 5 秒一个 heartbeat；客户端 12 秒没有任何消息就判死连接并重连。
- 提供商会话大约每 7–9 分钟轮换一次（`goAway`/`cutover`），采集器会重连，但轮换瞬间可能有很短的音频缺口。
- 以上协议在 2026-11-08 与 2026-11-14 两次公开面观测中一致；不是官方文档承诺，服务端改动时可能失效。

## 产物

一次运行一个目录，默认 `artifacts/live-capture/<room>/<YYYY-MM-DD>/`：

| 文件 | 内容 |
|---|---|
| `capture.json` | 清单：窗口、流统计、音频时长、哈希、广播状态时间线、warnings/notes |
| `capture.log` / `events.jsonl` / `status.jsonl` | 运行日志、连接/断线/重续事件、每 30 秒快照 |
| `english.captions.jsonl` | 每条英文 partial/final，带到达时间 `received_at` 和相对 `t_ms` |
| `english.finals.jsonl` / `english.txt` | 去重后的英文 final 行 |
| `mandarin.captions.jsonl` | 每条普通话 partial/final（partial 是累计文本） |
| `mandarin.finals.jsonl` / `mandarin.txt` | 普通话 final 行（短窗口可能只有 partial，见 notes） |
| `mandarin.audio.wav` | 24 kHz 单声道 WAV，接收到的音频；服务端声明跳过的部分补静音 |
| `mandarin.frames.jsonl` | 每个音频帧的 seq、到达时间、PCM 偏移 |
| `session.english.jsonl` / `session.mandarin.jsonl` | 服务端会话日志的 final 行，带精确 `ts` |
| `session.json` | 会话元数据（已去掉听众遥测和 ingest URL）、行数、哈希、与实时采集的匹配统计 |
| `sermon.window.json` | 人工事后提供的讲道起止；绑定 `capture.json`/`session.json` 的 SHA-256（见“人工讲道起止”） |
| `sermon.english.jsonl` / `sermon.english.txt` / `sermon.english.timed.txt` | 人工窗口内的讲道英文；JSONL 带时间戳，timed.txt 带相对采集起点的偏移（见“取讲道正文”） |
| `sermon.manifest.json` | 讲道正文导出的输入哈希、窗口、行数、覆盖率和 warnings |
| `reading/segments_timed_en_raw.json` / `reading.plan.json` | 阅读适配器的确定性分段和计划（不调用模型） |
| `reading/sermon_zh_en_reading.pdf` | `--execute` 成功后生成的阅读版 PDF；同目录还有 `reading.manifest.json`、`qa_report.json`、`reading-edition-v2/` |
| `run.status.json` / `wrapper.log` | 定时包装脚本的退出码和日志 |

实时采集的音频是**按到达顺序写入**的：正常连续时与真实时间一致；断线时服务端声明的 `audioSkippedMs` 会补静音，未声明的空隙不补。`mandarin.frames.jsonl` 和 `capture.json` 保留每帧时间，供需要严格对齐时使用。

默认在 WAV 校验通过后删除原始 `.pcm`（约再省一半磁盘）；要保留就加 `--keep-pcm`。

## 运行

### 手动试采（不会等到 10:00）

```bash
.venv/bin/python experiments/live-translate-capture/capture.py \
  --room mariners-irvine-outdoor \
  --start-at now --duration 2m \
  --out-root artifacts/live-capture-test
```

`--start-at`/`--stop-at` 接受 `HH:MM`（本机时区）或 ISO-8601；`--out` 可指定运行目录。停止时间一到，进程自己收尾并写 `capture.json`。

### 完整链路（采集 + 会话日志）

```bash
CAPTURE_ROOM=mariners-irvine-outdoor \
CAPTURE_START=now CAPTURE_STOP=16:48 \
CAPTURE_OUT_ROOT=artifacts/live-capture-test \
bash experiments/live-translate-capture/run-capture.sh
```

包装脚本会做主机/电量/磁盘/房间配置预检，跑 `caffeinate` 防止空闲睡眠，采集结束后调用 `fetch_session.py` 取回会话日志，并写 `run.status.json`。

### 只取会话日志

```bash
.venv/bin/python experiments/live-translate-capture/fetch_session.py \
  --capture-dir artifacts/live-capture/mariners-north-irvine/2026-11-15
```

只读公开接口；保存前去掉 `listenerTelemetry`、`listenerSocket`、`timeline` 和 ingest URL。`session.json` 里的 `comparison_with_live` 会给出实时英文 final 与会话 `source` 行的匹配数。

## 人工讲道起止

采集端**不切讲道**：10:00–11:20 整段保存。人工回看后，再把讲道起止写成 `sermon.window.json`：

```bash
.venv/bin/python experiments/live-translate-capture/mark_window.py \
  --capture-dir artifacts/live-capture/mariners-north-irvine/2026-11-15 \
  --start 10:29:35 --end 11:02:10 \
  --approved-by "Jony (chat)" \
  --evidence "回看整场；讲道从宣布后开始，到回应诗歌前结束"
```

也接受相对采集实际起点的偏移：`--start-offset 1775 --end-offset 3730`（秒、`MM:SS` 或 `HH:MM:SS`）。

写入前会校验：

- start/end 在 capture 的实际窗口内，end > start，长度至少 60 秒；
- 绑定 `capture.json` 的 SHA-256；有 `session.json` 时也绑定它的哈希；
- 同值重复执行是幂等的；要改值必须加 `--force`。

校验已有文件：

```bash
.venv/bin/python experiments/live-translate-capture/mark_window.py \
  --capture-dir artifacts/live-capture/mariners-north-irvine/2026-11-15 --check
```

`sermon.window.json` 是采集元数据，**不是** Layer 1 的 `approvedWindow`；下游 Layer 1 仍要按自己的证据和审批流程绑定。阅读版 PDF 只应使用人工确认后的窗口；窗口之前的敬拜/报告保留在原始文件里，但不进入讲道正文。

## 取讲道正文

窗口写入后，用确定性步骤取讲道英文（不调用任何模型）：

```bash
.venv/bin/python experiments/live-translate-capture/extract_sermon.py \
  --capture-dir artifacts/live-capture/mariners-north-irvine/2026-11-15
```

- 优先用 `session.english.jsonl`（provider 精确时间戳）；没有会话日志时用 `--source live` 回退到 `english.finals.jsonl` 的到达时间。
- 输出 `sermon.english.jsonl`、`sermon.english.txt`、`sermon.english.timed.txt`（`[HH:MM:SS.mmm] 文本`，相对采集起点）。
- 同时输出 `sermon.mandarin.jsonl`/`sermon.mandarin.txt`，标注 `comparison_only: true`；它不是批准译文。
- `sermon.manifest.json` 记录 capture/window/source 的 SHA-256、行数、首末时间和覆盖 warnings；如果窗口内行数过少或首末行离边界太远，会写 warning，不自动改写正文。
- 英文仍是 provider ASR，必须走 Layer 1 修正和人工审校；这一步只做时间窗过滤。

## 生成阅读版 PDF（适配器）

`build_reading_pdf.py` 把窗口内英文接到现有生产链：

```text
sermon.english.jsonl
  -> 阅读分段（caption 到达时间，synthetic reading timing）
  -> 英文清理 correct_english（OpenAI，可关）
  -> 中文翻译 translate_chinese（OpenAI，带缓存/账本）
  -> 阅读版编辑 scripts/build_sermon_reading_edition_with_openai.py（现有 2-pass）
  -> 中英对照阅读版 PDF workflows.dual_pdf.mobile_pdf --layout reading（现有）
```

默认只出计划，不调用模型：

```bash
.venv/bin/python experiments/live-translate-capture/build_reading_pdf.py \
  --capture-dir artifacts/live-capture/mariners-north-irvine/2026-11-15
```

它写 `reading/segments_timed_en_raw.json` 和 `reading/reading.plan.json`，打印段数、字符数和后续命令。付费运行必须经过显式环境：

```bash
python3 tools/ops/run_with_openai_environment.py --environment dev -- \
  .venv/bin/python experiments/live-translate-capture/build_reading_pdf.py \
  --capture-dir artifacts/live-capture/mariners-north-irvine/2026-11-15 --execute
```

模型默认 `gpt-6.1-sol`、reasoning high；可覆盖 `--en-model`、`--zh-model`、`--reading-model`、`--reasoning-effort`、`--translation-workers`。`--max-segments`/`--max-chars` 是预检上限，超过要显式 `--allow-large`。

门禁：

- 英文只来自人工窗口内的 provider ASR；`timingQuality=caption_arrival_synthetic_not_for_subtitles`，不能当作字幕时间或视频同步时间。
- 只有阅读编辑的 `reading-quality-report.json` 为 `pass` 才生成 PDF；没有绕过开关。
- 中文是我们自己的机器翻译，不是 `session.mandarin` 的机器中文，也不是人工批准。
- 不下载 YouTube、不跑 ASR/MFA、不伪造视频时间；PDF 不写点击跳转的视频链接。
- 计费走现有 accounting；`--execute` 前请确认 dev/prod 环境和预算。

本地验证：18 个测试；5 分钟 demo 窗口 plan 得到 61 行 caption → 13 个阅读段 / 4,262 字符。**真实付费链路尚未跑**，等周日素材和显式环境/预算确认。

## 定时

```bash
# 安装/重装（默认周日 09:55，房间 north-irvine，10:00–11:20）
bash experiments/live-translate-capture/install-schedule.sh

# 看状态和下次触发时间
launchctl print gui/$(id -u)/ai.pastors.live-capture | grep -E 'state|runs|next fire'

# 换房间/时间
bash experiments/live-translate-capture/install-schedule.sh \
  --room mariners-irvine-outdoor --start 09:00 --stop 10:20 --weekday 0 --hour 8 --minute 55

# 卸载
bash experiments/live-translate-capture/install-schedule.sh --uninstall
```

要点：

- 需要 Mac 在周日早上**开机、联网、已登录**；launchd 会在唤醒后补跑错过的日历任务，但它不能自己唤醒睡眠中的 Mac。`run-capture.sh` 用 `caffeinate -i -m -s` 保持运行期间不休眠（`-s` 仅在接电源时有效）。
- 采集进程发现已有另一个 `capture.py` 在跑时会拒绝启动，避免重复开提供商会话。
- 若 09:55 的实例在 10:00 前失败，本次不会自动重试；可手动跑 `run-capture.sh`，或重新 `install-schedule.sh`。`KeepAlive` 没有启用，避免 11:20 后反复启动已过窗口的任务。
- 空跑验证（2026-11-14，`mariners-north-irvine` 未直播）：capture 正常在窗口结束时写 `capture.json`（`status: empty`，广播状态全程 false），`fetch_session.py` 因没有重叠会话而失败并把 `session_fetch_exit: 1` 写进 `run.status.json`；包装脚本仍以 0 退出，不会把“没有直播”误报成采集进程崩溃。

## 交给后续流程

1. **Layer 1**：先跑 `extract_sermon.py`，得到人工窗口内的 `sermon.english.jsonl`；它的时间戳来自 `session.english.jsonl`，`english.finals.jsonl`（我们实际收到的副本）作审计对照。讲道起止用人工写入的 `sermon.window.json`（见上）；窗口里的敬拜/报告保留在原始文件里，但不进入讲道正文。英文 ASR 会有术语和人名错误（实测出现过 `Kent Bshore` 这类），按现有 Layer 1 规则修正并保留修正记录。
2. **Layer 2**：`build_reading_pdf.py --execute` 用现有 `translate_chinese` 从修正后的英文出发；`session.mandarin.jsonl` / `mandarin.*` 只作对照，**不得**作为批准译文或训练/提示的“已验证样例”。
3. **Layer 3**：`mandarin.audio.wav` 是机器 TTS 译文音频，不是讲员原声。若音频版需要原声或更高质量，另走录音/配音路径；不要把这段 TTS 直接标成原声。
4. **诚实标签**：阅读版必须标明英文来源是现场 ASR、中文是我们自己的机器翻译、人工审校状态按实际记录；机器审校不等于人工批准。
5. **实时直播** 仍是独立的 `live_session`；这次采集的录像/文本如果用于耐久内容，从 Layer 1 重新开始，不把直播机器中文提升为 Layer 2 批准。

## 本机验证记录

| 运行 | 目录（本机，gitignored） | 时长 | 英文 final | 普通话音频 | 会话日志 | 匹配 |
|---|---|---|---|---|---|---|
| 直接采集 | `artifacts/live-capture-test/mariners-irvine-outdoor/2026-11-14` | 60.5 s | 7 | 56.75 s | 7 行 | 7/7 |
| 包装链路 | `artifacts/live-capture-test/wrapper/mariners-irvine-outdoor/2026-11-14-164445` | 74.5 s | 22 | 73.75 s | 39 行 | 22/22 |
| launchd 临时任务 | `artifacts/live-capture-test/launchd/mariners-irvine-outdoor/2026-11-14` | 58 s | 14 | 57.00 s | 48 行 | 14/14 |
| 10 分钟 demo 长测 | `artifacts/live-capture-test/soak/demo/2026-11-14` | 600.4 s | 139 | 597.25 s | 143 行（同一进行中会话） | 139/139 |

本地测试：

```bash
.venv/bin/python -m pytest tests/test_live_translate_capture.py -q
# 18 passed
```

这些是**采集链路**证据，不是周日本身、教会现场声学、人工 ASR Gold、翻译质量或发布验收。

## 已知限制与风险

- 房间在窗口内没有直播时，采集为空；清单会写 `status: empty` 和广播时间线。定时任务不会因此重试。
- 英文 caption 是 ASR，专有名词/经文引用可能错；必须走 Layer 1 修正和术语表。
- 普通话字幕经常只有累计 partial、final 很少；短窗口内 `mandarin.finals.jsonl` 可能为空，对照要看 `mandarin.captions.jsonl` 或 `session.mandarin.jsonl`。
- 断线超过服务端音频回放窗口（约 2 秒）会丢音频；`resumed.audioSkippedMs` 会补静音并记录。字幕回放窗口更长，但仍可能缺行，所以要做会话日志对照。10 分钟长测里没有断线，轮换切缝也没有丢音频；这只证明一次正常轮换，不证明所有网络/提供方故障。
- 提供商会话轮换、网络抖动、macOS 睡眠都会造成缺口；`events.jsonl` 和 `warnings` 是判断依据。
- 打开 `zh` 流会为该语言启动/占用提供商会话；服务自己的估算约 `$0.0368/语言分钟`，80 分钟约 3 美元（仅估算，不是账单）。请只在获授权的场景使用。
- 会话日志是公开可读接口；本工具只读、只取本次窗口，并去掉听众标识和 ingest 地址。仍然不要把 `session.json` 当公开材料传播。

## 下一步

1. 周日目标房间已确认：`mariners-north-irvine`，窗口按 10:00–11:20。2026-11-14 用该房间做了一次空跑，确认“未直播时正常收尾”的路径。
2. 确认是否需要**英文原声**；需要的话，把现场麦克风或教会直播流作为第二条音频输入接进来（当前只录页面提供的普通话 TTS）。
3. 用一次真实周日的产物跑 11:20 → 英文清理 → 我们自己的翻译 → 阅读版 PDF 的下游链路，并记录它和既有 post-live 工作流的差异。
