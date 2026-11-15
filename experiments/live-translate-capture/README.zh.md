# 周日现场讲道：translate.pastors.ai 采集端

这个实验解决一件事：周日讲员现场讲道、没有提前制作素材时，在固定时间窗内把翻译页面的**英文原文字幕**、**普通话译文音频**和**普通话字幕**一起录下来，并在服务结束后取回服务端的会话日志（带精确时间戳），供后续 Layer 1/Layer 2 和阅读版 PDF 使用。

它只负责采集，不做 ASR、翻译、审校或发布。

## 结论先看

- 2026-11-14 用正在直播的 `mariners-irvine-outdoor` 做了两次真实采集：
  - 直接运行 60 秒：英文 7 条 final，普通话音频 56.75 秒；同窗口会话日志 7/7 条英文 final 完全匹配。
  - 经 `run-capture.sh` 完整链路 74 秒：英文 22 条 final，普通话音频 73.75 秒；会话日志 39 条英文行，22/22 完全匹配（归一化后逐条相同）。
- 采集、断线续传、音频封装、会话日志取回、LaunchAgent 定时启动都已在本机跑通；9 个本地测试通过（含一个本地 WebSocket 假服务器，覆盖断线后带 `since` 重连）。
- 默认定时已装好：**每周日 09:55 启动，10:00 开始录，11:20 自动截断**，房间 `mariners-north-irvine`；LaunchAgent 见 `~/Library/LaunchAgents/ai.pastors.live-capture.plist`。
- 依赖只有仓库 venv 里的 `websockets` 和 `requests`，见 `requirements.txt`。

## 采集的是什么，不是什么

| 流 | `lang=` | 内容 | 用途 |
|---|---|---|---|
| 英文原文 | `captions` | 服务端 ASR 的英文 partial/final，**没有音频** | Layer 1 英文底稿的首选实时来源 |
| 普通话 | `zh` | 机器翻译后的普通话 TTS 音频（24 kHz PCM）+ 普通话字幕 | 音频版、人工与机器译文对照 |

**不是**：

- **不是英文原声。** 这个服务不提供讲员原声通道；`lang=en` 在实测中直接返回 HTTP 400。英文原声要另录：现场麦克风（可接现有的 `experiments/local-live-poc`）、教会直播流或调音台。
- **不是已批准的译文。** `zh` 的字幕和音频都是机器翻译/机器合成，只能做对照，不能当作 Layer 2 的批准文本，也不能把机器中文写进阅读版而不经过我们自己的翻译与审校。
- **不是完整礼拜。** 10:00–11:20 的窗口包含敬拜、报告和讲道；讲道起止仍需人工确认，或由后续流程切分。

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

## 交给后续流程

1. **Layer 1**：以 `session.english.jsonl`（精确时间戳）为主、`english.finals.jsonl`（我们实际收到的副本）作审计对照；两者都有哈希。讲道起止仍需确认，窗口里的敬拜/报告要切掉。英文 ASR 会有术语和人名错误（实测出现过 `Kent Bshore` 这类），按现有 Layer 1 规则修正并保留修正记录。
2. **Layer 2**：用我们自己的翻译链，从修正后的英文出发；`session.mandarin.jsonl` / `mandarin.*` 只作对照，**不得**作为批准译文或训练/提示的“已验证样例”。
3. **Layer 3**：`mandarin.audio.wav` 是机器 TTS 译文音频，不是讲员原声。若音频版需要原声或更高质量，另走录音/配音路径；不要把这段 TTS 直接标成原声。
4. **诚实标签**：阅读版必须标明英文来源是现场 ASR、中文是我们自己的机器翻译、人工审校状态按实际记录；机器审校不等于人工批准。
5. **实时直播** 仍是独立的 `live_session`；这次采集的录像/文本如果用于耐久内容，从 Layer 1 重新开始，不把直播机器中文提升为 Layer 2 批准。

## 本机验证记录

| 运行 | 目录（本机，gitignored） | 时长 | 英文 final | 普通话音频 | 会话日志 | 匹配 |
|---|---|---|---|---|---|---|
| 直接采集 | `artifacts/live-capture-test/mariners-irvine-outdoor/2026-11-14` | 60.5 s | 7 | 56.75 s | 7 行 | 7/7 |
| 包装链路 | `artifacts/live-capture-test/wrapper/mariners-irvine-outdoor/2026-11-14-164445` | 74.5 s | 22 | 73.75 s | 39 行 | 22/22 |
| launchd 临时任务 | `artifacts/live-capture-test/launchd/mariners-irvine-outdoor/2026-11-14` | 58 s | 14 | 57.00 s | 48 行 | 14/14 |

本地测试：

```bash
.venv/bin/python -m pytest tests/test_live_translate_capture.py -q
# 9 passed
```

这些是**采集链路**证据，不是周日本身、教会现场声学、人工 ASR Gold、翻译质量或发布验收。

## 已知限制与风险

- 房间在窗口内没有直播时，采集为空；清单会写 `status: empty` 和广播时间线。定时任务不会因此重试。
- 英文 caption 是 ASR，专有名词/经文引用可能错；必须走 Layer 1 修正和术语表。
- 普通话字幕经常只有累计 partial、final 很少；短窗口内 `mandarin.finals.jsonl` 可能为空，对照要看 `mandarin.captions.jsonl` 或 `session.mandarin.jsonl`。
- 断线超过服务端音频回放窗口（约 2 秒）会丢音频；`resumed.audioSkippedMs` 会补静音并记录。字幕回放窗口更长，但仍可能缺行，所以要做会话日志对照。
- 提供商会话轮换、网络抖动、macOS 睡眠都会造成缺口；`events.jsonl` 和 `warnings` 是判断依据。
- 打开 `zh` 流会为该语言启动/占用提供商会话；服务自己的估算约 `$0.0368/语言分钟`，80 分钟约 3 美元（仅估算，不是账单）。请只在获授权的场景使用。
- 会话日志是公开可读接口；本工具只读、只取本次窗口，并去掉听众标识和 ingest 地址。仍然不要把 `session.json` 当公开材料传播。

## 下一步

1. 确认周日目标房间是 `mariners-north-irvine` 还是 `mariners-irvine-outdoor`，以及 10:00–11:20 是否就是目标礼拜。
2. 确认是否需要**英文原声**；需要的话，把现场麦克风或教会直播流作为第二条音频输入接进来（当前只录页面提供的普通话 TTS）。
3. 用一次真实周日的产物跑 11:20 → 英文清理 → 我们自己的翻译 → 阅读版 PDF 的下游链路，并记录它和既有 post-live 工作流的差异。
