# 20261114 周日直播翻译采集端：三次真实试跑

日期：2026-11-14（PST）。范围：新增 `experiments/live-translate-capture/`；不改生产管线、翻译策略或发布。这是一次采集链路的实验，不是周日现场验收。

## 结论

- **采集链路跑通。** 对正在直播的 `mariners-irvine-outdoor` 做了三次真实采集（直接运行、包装链路、launchd 临时任务）：英文 final 分别 7、22、14 条，普通话音频 56.75、73.75、57.00 秒；服务端会话日志的 `source` 行与实时英文 final **分别 7/7、22/22、14/14 完全匹配**（归一化后逐条相同）。
- **采集端不切讲道。** 10:00–11:20 整段保存（含敬拜、报告）；讲道起止由人工事后写入 `sermon.window.json`，并绑定 `capture.json`/`session.json` 的 SHA-256；`extract_sermon.py` 再按该窗口确定性导出正文。`sermon.window.json` 是采集元数据，不是 Layer 1 的 `approvedWindow`。
- **10 分钟 demo 长测通过。** 597.25 秒连续音频、2,389 个音频帧、0 次重连、0 个到达空隙；期间捕获到一次提供商会话轮换（540 秒 `goAway`、540 秒 `standby_ready`、587 秒 `cutover`，`droppedMs=0`、`cutover=deadline`），音频没有断。英文 final 139 条，会话日志同一进行中会话的 143 条 source 行 **139/139 匹配**。
- **页面只提供英文文字 + 普通话音频。** `lang=captions` 是英文原文字幕、无音频；`lang=zh` 是机器翻译后的普通话 TTS 音频 + 普通话字幕；`lang=en` 实测 HTTP 400。**没有讲员英文原声。** 需要原声时必须另接现场麦克风或教会直播流。
- **普通话字幕 final 很少。** 三次运行的实时普通话 final 只有 0/1/1 条，累计 partial 有 56/73/56 条；会话日志的 `zh` 行只有 4/3/3 条。它只能做对照，不能作为 Layer 2 的批准文本或英文底稿。
- 本机 LaunchAgent 已安装并验证（周日 09:55 启动、10:00–11:20、房间 `mariners-north-irvine`）；这是本机状态，不在仓库里。还没跑满 80 分钟的真实周日。
- 阅读适配器已用 5 分钟 demo 跑通真实 dev 付费链路（13 段、13 块 × 2 轮、PDF 7 页 QA pass）；周日真实 80 分钟场次、真实讲员内容和发布验收尚未跑。

## 运行

| 运行 | 时长 | 英文 final | 普通话音频 | 实时普通话 final/partial | 会话日志英文行 | 匹配 |
|---|---:|---:|---:|---:|---:|---:|
| 直接采集 | 60.5 s | 7 | 56.75 s | 0 / 56 | 36 | 7/7 |
| 包装链路 | 73.9 s | 22 | 73.75 s | 1 / 73 | 39 | 22/22 |
| launchd 临时任务 | 57.3 s | 14 | 57.00 s | 1 / 56 | 48 | 14/14 |
| 10 分钟 demo 长测 | 600.4 s | 139 | 597.25 s | 9 / 576 | 143 | 139/139 |

前三次真实直播都在同一个服务端会话 `20261114-235501-f0a1` 内，窗口是 2026-11-15 00:42–00:49 UTC（16:42–16:49 PST）；10 分钟长测跑在循环参考讲道的 `demo` 房间，落在该房间自 2026-11-08 起持续的同一会话 `20261108-170841-dbdd` 内，所以“会话日志行数”大于实时 final 数，比较的是同一窗口内的 143 行。`summary.json` 记录每次运行的窗口、计数、音频帧数、会话行数、轮换事件和五个关键文件的 SHA-256；原始音频、字幕和日志留在本机 gitignored `artifacts/live-capture-test/`。

## 采集到什么

- **英文原文字幕**：`lang=captions`，服务端 ASR 的 partial/final；客户端按到达时间写 JSONL，final 去重后另写 `.txt`。
- **普通话音频**：`lang=zh`，24 kHz 单声道 int16 PCM，250 ms/帧，封装为 WAV；服务端声明 `audioSkippedMs` 时补静音并记录。
- **普通话字幕**：同一 `zh` 流的 partial/final，只作对照。
- **服务端会话日志**：服务结束后只读公开接口取回 `source`/`zh` final 行，带精确 `ts`；保存前去掉 `listenerTelemetry`、`listenerSocket`、`timeline` 和 ingest URL。
- **断线处理**：12 秒静默看门狗、带 `since=<最后 seq>` 重连、`resumed` 回放记录；本地假服务器测试覆盖了掉线后重连和补静音。

## 验证

```bash
.venv/bin/python -m pytest tests/test_live_translate_capture.py -q
# 19 passed
```

测试覆盖：本地日期/跨 UTC 午夜的窗口解析、迟到开始、已过窗口拒绝、caption final 去重、WAV 封装与补静音、会话选择、遥测/ingest 脱敏、本地 WebSocket 断线重连，以及人工讲道起止的记录/边界校验/哈希绑定和窗口内正文导出。

代码 PR 后续加入 `mark_window.py`、`extract_sermon.py` 与 `build_reading_pdf.py`（共 9 个测试）：采集端保存整段 10:00–11:20，人工回看后记录讲道起止，确定性导出窗口内英文正文，并接到现有阅读链生成 PDF（默认只出 plan；付费执行必须走显式 OpenAI 环境和阅读质量门禁）。这不改变本报告三次采集和 10 分钟长测的证据。

## 真实 dev 付费试跑（5 分钟 demo，非发布）

2026-11-14 用 `artifacts/live-capture-test/soak/demo/2026-11-14` 的 16:55–17:00 窗口，经 `tools/ops/run_with_openai_environment.py --environment dev` 跑通适配器的真实付费链路：

| 指标 | 结果 |
|---|---|
| 输入 | 61 行 caption → 13 个阅读段 / 4,298 英文字符 |
| 英文清理 / 翻译 | 13/13、13/13 |
| 阅读编辑 | 13 块 × 2 轮（编辑 + 校对） |
| 阅读质量 | `reading_quality_report.json` = pass |
| PDF | 7 页，168,500 bytes；`sermon_zh_en_reading.qa.json` = pass（allPagesChecked） |
| 调用 / token | 45 次 API；输入 73,910 / 输出 19,306（reasoning 13,485） |
| 费用 | 按 `gpt-6.1-sol` 列表价估算约 **$0.38**；不是账单/发票 |
| 产物 | `artifacts/live-reading-tests/20261114-demo-5min/sermon_zh_en_reading.pdf`，标题“Demo 5-minute reading test（非发布）” |
| 哈希 | PDF `21623d8b…`；PDF QA `184695bc…`；质量报告 `a1edd509…`（完整值见 `summary.json`） |

第一次失败：英文修正 240 秒窗口和 420 字符阅读块超过 legacy provider 的 8,192-byte 输入上限（`provider_input_bound_exceeded`，未产生付费调用）；阅读编辑 batch 3 同样超限；QA 把零值 `hardFailures` 当成失败。修复在 [#1573](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/1573)：

- 英文修正窗口 45 秒；
- 阅读编辑 `--batch-size 1`，块目标 12 秒 / 150 英文字符，硬上限 30 秒 / 300 字符；
- QA 只在 `hardFailures` 有非零值时中止。

边界：英文仍是 provider ASR，可能保留 `uh` / `you know`；中文阅读正文由阅读编辑清理。周日真实 80 分钟场次尚未跑；按 ~200 个阅读块 × 2 轮估算，预算会明显高于本次 5 分钟 demo。

## 边界与未验证

- 这是**采集链路**证据，不是周日本身、教会现场声学、人工 ASR Gold、翻译质量、音频质量或发布验收。
- 三次真实直播窗口都只有约 1 分钟；10 分钟长测只覆盖一次正常轮换，没有覆盖 80 分钟连续运行、多次轮换、真实网络抖动、macOS 睡眠/唤醒或周日房间（`mariners-north-irvine` 当周未直播）。
- 英文 caption 是 ASR，专有名词和经文引用可能错；必须走 Layer 1 修正。
- 普通话 TTS 音频不是讲员原声；普通话字幕不能当批准译文。
- 服务端会话日志是公开可读接口；本工具只读、只取本次窗口，并去掉听众标识和 ingest 地址。仍然不要把 `session.json` 当公开材料传播。

## 复现

```bash
# 采集（短窗口试跑）
.venv/bin/python experiments/live-translate-capture/capture.py \
  --room mariners-irvine-outdoor --start-at now --duration 1m \
  --out-root artifacts/live-capture-test

# 长测（循环参考讲道，覆盖一次 provider 轮换）
.venv/bin/python experiments/live-translate-capture/capture.py \
  --room demo --start-at now --duration 10m \
  --out-root artifacts/live-capture-test/soak

# 完整包装链路（采集 + 会话日志）
CAPTURE_ROOM=mariners-irvine-outdoor CAPTURE_START=now CAPTURE_STOP=16:49 \
CAPTURE_OUT_ROOT=artifacts/live-capture-test/wrapper \
bash experiments/live-translate-capture/run-capture.sh

# 只取会话日志
.venv/bin/python experiments/live-translate-capture/fetch_session.py \
  --capture-dir artifacts/live-capture-test/<run>
```

## 关联

- 代码 PR：[#1571](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/1571)
- 实验说明：`experiments/live-translate-capture/README.zh.md`
- 本机定时：`~/Library/LaunchAgents/ai.pastors.live-capture.plist`（不在仓库）
- 证据摘要：`summary.json`（本目录）
