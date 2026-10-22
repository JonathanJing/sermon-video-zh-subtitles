# 逐句优先、代理直做的配音实验

状态：实验线，2026-10-21 建立。用户决定（2026-10-21）：**这条线不走现有流水线，不做哈希绑定校验，所有工作在代理会话里直接完成。** 它用来验证[逐句优先设计](../../docs/design/sentence-first-dubbing-path.zh.md)的路径本身成不成立，不产生发布物。要进 App 的内容仍走正式四层。

读完本文即可开工；需要连 Spark 时读 `dgx-spark-connect` skill。不要为了这条线读 controller、speech job、豁免或 Registry 的文档。

## 边界（只有三条）

1. 产物只写在忽略的 `artifacts/sentence-first-agent/<run>/`。原声切片是讲员原声，不出这个目录，不进 Git。
2. 这里出来的译文、配音、字幕都是机器产物，标 `experiment_only`。不往正式候选、音频包或发布目录拷。
3. 讲员声音只用 Registry 里已授权配音用途的 checkpoint；不下载、不换别人的声音。

其余一切（模型选择、分句粒度、提示词、重跑、改字）由当前会话的代理自行决定并写进 `run.md`。

## 目录

```text
artifacts/sentence-first-agent/<run>/
  run.md              代理的工作日志：来源、决定、改动、听感
  clip.wav            窗口音频，16 kHz 单声道
  words.json          词级时间（见第 2 步）
  sentences.jsonl     每句一行：id, english, start, end, pauseAfter, words
  slices/<id>.wav     每句原声切片
  translations.jsonl  每句一行：id, target, locale, reviewNote
  speech.jsonl        每句一行：id, spokenText, language, speaker, hint, budgetSeconds
  tts/<id>.wav        每句配音
  track.wav           合并音轨；schedule.json 记每句实际起点
  dub.mp4             可选，音轨混回视频
```

辅助脚本都在本目录，只用标准库和 `ffmpeg`；`tts_sentences.py` 在 Spark 上跑，另需 `torch` 与 `qwen_tts`。每个脚本 `--help` 可看参数。

## 步骤

### 1 取窗口音频

操作者给起止时间。代理直接跑：

```bash
ffmpeg -nostdin -v error -i <video> -ss <start> -to <end> -map 0:a:0 -ac 1 -ar 16000 -c:a pcm_s16le artifacts/sentence-first-agent/<run>/clip.wav
```

把来源文件名、起止时间写进 `run.md`。

### 2 词级时间

有现成的 MFA 结果（anchor manifest v2 或任何含 `start`/`end` 的词列表）就直接用；没有就按 `sermon-mfa-word-alignment` skill 跑一次 MFA，拿到词时间。统一存成 `words.json`：

```json
[{"text": "Grace", "start": 0.42, "end": 0.71}, ...]
```

时间相对 `clip.wav` 起点。只要词和时间，不要别的字段。

### 3 拆句

```bash
python3 experiments/sentence-first-agent/split_sentences.py --words words.json --out sentences.jsonl
```

默认在句末标点处断句，长于 `--max-seconds`（默认 12 秒）的句子再在最长可听停顿（默认 ≥ 0.45 秒）处断开。输入是 anchor manifest v2 时直接沿用它的 `sourceUnits`。代理读一遍结果：觉得断得不对就直接改 `sentences.jsonl`（合并、拆开、改时间都行），在 `run.md` 记一句为什么。

### 4 切原声

```bash
python3 experiments/sentence-first-agent/slice_sentences.py --audio clip.wav --sentences sentences.jsonl --out slices
```

每句一个 WAV，前后各留 `--pad`（默认 0.08 秒），不越过邻句。切片给第 5、6 步听，也给 `budgetSeconds`。

### 5 逐句翻译与复核（代理自己做）

代理按顺序对每句工作，不调用任何外部翻译 API：

1. 读这一句英文、前 3 句后 2 句英文、[术语表](../../docs/series-terminology.zh.md)里本系列的条目。
2. 译出目标语言的这一句。完整覆盖本句；经文出处、数字、人名、系列名按英文和术语表；不借邻句内容。
3. 复核：换一个角度（或开一个子代理，只给英文与译文），判漏译、增译、否定、数字、人名、经文、意思偏移。有问题就改，在 `reviewNote` 写一句。
4. 写一行到 `translations.jsonl`：

```json
{"id": "s0007", "locale": "zh-Hans", "target": "……", "reviewNote": "pass"}
```

一次写完一个 locale 再做下一个。中断后从最后一行续。

### 6 口播规格（代理自己做）

对每句，代理听或看它的原声切片时长，写 `speech.jsonl`：

```json
{"id": "s0007", "spokenText": "……", "language": "Chinese", "speaker": "<speakerKey>", "hint": "", "budgetSeconds": 3.41}
```

- `spokenText` 从 `target` 派生：经文章节、数字写成读法；中文韩文给停顿标点。意思不变。
- `budgetSeconds` = 切片时长 + `pauseAfter`。译文念出来明显超预算时，代理精简口播：只删重复、填充、同义复述，不删论点、否定、数字、人名、经文出处。字幕仍用 `target`。
- `language` 用 Qwen3-TTS 的语言名（`Chinese`、`Korean`、`Spanish`）；`speaker` 用 checkpoint 里的 speaker key。
- `hint` 可选，一句自然语言的朗读提示，进 `instruct`。

### 7 本地模型配音（Spark）

按 `dgx-spark-connect` 连上 Spark，把 `speech.jsonl` 和脚本放到 Spark 的工作目录，在带 `qwen_tts` 的环境里跑：

```bash
python3 tts_sentences.py --speech speech.jsonl --checkpoint <checkpoint-dir> --out tts --device cuda:0 --seed 7
```

逐句合成（batch 1，2026-10-21 用户决定），已有的 `tts/<id>.wav` 跳过，所以可以断点续跑。合成完把 `tts/` 拉回本机。不拉伸、不变速。

### 8 合并

```bash
python3 experiments/sentence-first-agent/merge_track.py --sentences sentences.jsonl --tts tts --out track.wav --schedule schedule.json
```

每句放在它英文起点；放不下就紧接上一句结束加 `--gap`（默认 0.25 秒）。`schedule.json` 记每句计划起点、实际起点、落后秒数。要听带画面的：

```bash
ffmpeg -nostdin -v error -i <video> -ss <start> -to <end> -i track.wav -map 0:v:0 -map 1:a:0 -c:v copy -c:a aac -shortest dub.mp4
```

### 9 听一遍，记下来

代理用 `sermon-dubbing-asr-sync-check` skill 回转写抽查，或直接听。把落后最多的句、读错的句、译得别扭的句写进 `run.md`，要改就改对应的一行，只重跑那一句的第 7、8 步。

## 完成的样子

`run.md` 能让另一个人复现：来源、窗口、模型与 checkpoint、每步的决定、哪些句改过、听感结论、这条路径哪里顺哪里卡。这就是实验的交付物；音频留在本机。

## 退出条件

- 一个片段三语走通，且代理能说清每步花了多久、卡在哪，这条线的结论写进 `docs/reports/`，由用户决定是否把哪些步骤接回正式路径。
- 或者路径本身不成立（分句、时长预算或声音任一环节过不去），同样写报告后关闭。
