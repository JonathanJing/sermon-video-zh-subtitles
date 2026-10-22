# 逐句优先、代理直做的配音实验

状态：实验线，2026-10-21 建立。用户决定（2026-10-21）：**这条线不走现有流水线，不做哈希绑定校验，所有工作在代理会话里直接完成。** 它用来验证[逐句优先设计](../../docs/design/sentence-first-dubbing-path.zh.md)的路径本身成不成立，不产生发布物。要进 App 的内容仍走正式四层；正式播客翻译由另一个代理负责，本实验不读写它的目录（2026-10-22 用户说明）。

读完本文即可开工；需要连 Spark 时读 `dgx-spark-connect` skill。不要为了这条线读 controller、speech job、豁免或 Registry 的文档。首跑记录见[首跑报告](../../docs/reports/20261021-sentence-first-agent-first-clip.zh.md)。

## 边界（只有三条）

1. 产物只写在忽略的 `artifacts/sentence-first-agent/<run>/`。原声切片是讲员原声，不出这个目录，不进 Git。
2. 这里出来的译文、配音、字幕都是机器产物，标 `experiment_only`。不往正式候选、音频包或发布目录拷。
3. 讲员声音只用 Registry 里已授权配音用途的 checkpoint；不下载、不换别人的声音。

其余一切（模型选择、分句粒度、提示词、重跑、改字）由当前会话的代理自行决定并写进 `run.md`。

## 脚本

都在本目录，每个 `--help` 可看参数。本机脚本只用标准库和 `ffmpeg`；Spark 上的两个脚本在固定镜像里跑。

| 脚本 | 在哪跑 | 做什么 |
|---|---|---|
| `prepare_clip.py` | 本机 | 从锚点清单裁片段：clip.wav、clip.json、words.json、sentences.jsonl、原声切片、run.md 表头 |
| `split_sentences.py` | 本机 | 没有锚点清单、只有词列表时拆句 |
| `slice_sentences.py` | 本机 | 每句切原声，算 budgetSeconds（prepare_clip 会调用它） |
| `build_speech.py` | 本机 | 套用代理的复核修订和口播读法，写 speech.jsonl |
| `spark_run.sh` | Spark | 一个语言的逐句 TTS（batch 1）和回转写，可续跑，`--dry-run` 只打印命令 |
| `tts_sentences.py`、`asr_check.py transcribe` | Spark 容器内 | 由 spark_run.sh 调用 |
| `finish_run.py` | 本机 | 拉回、合并、打分、混回视频、出手机预览，打印落后与回转写摘要 |
| `merge_track.py`、`asr_check.py score` | 本机 | 由 finish_run.py 调用，也可单独用 |

## 目录

```text
artifacts/sentence-first-agent/<run>/
  run.md              代理的工作日志：来源、决定、改动、听感
  clip.json           媒体路径、片段媒体起止、单元范围
  clip.wav            片段音频，16 kHz 单声道
  words.json          词级时间，相对 clip.wav
  sentences.jsonl     每句一行：id, english, start, end, pauseAfter, words, sourceUnitId
  slices/             每句原声切片；slices.json 记 budgetSeconds
  translations.jsonl  每句一行：id, locale, target, reviewNote（代理写）
  review.json         代理的复核修订、备注、口播读法（代理写）
  speech.jsonl        每句一行：id, spokenText, language, speaker, hint, budgetSeconds, estimatedSeconds
  tts/                每句配音；tts-log.jsonl 记时长和墙钟
  asr.jsonl           回转写；asr-report.json 是打分结果
  track.wav           合并音轨；schedule.json 记每句计划起点、实际起点、落后
  dub.mp4             片段视频 + 配音；dub-preview-640.mp4 是手机预览
```

第二种语言用同一片段时，另开一个 run 目录，用 `--share-from`／`--clip-from` 指向第一个目录，不重新裁片段。

## 步骤

下面命令里的 `$EXP` 指 `experiments/sentence-first-agent`，`$RUN` 指本次的 run 目录。

### 1 裁片段（本机）

有锚点清单（`sermon-sentence-anchor-manifest-v2`，时间相对批准窗口）时一步到位：

```bash
python3 $EXP/prepare_clip.py --anchor <anchor-manifest.json> --media <video> --window-start <窗口起点秒> --units <LO:HI> --run $RUN --title "<一行说明>"
```

`--units` 是锚点单元的下标，两端都含。分句直接沿用锚点单元。没有锚点清单时，先按 `sermon-mfa-word-alignment` skill 拿到词时间，存成 `[{"text","start","end"}]`，再用 `split_sentences.py` 拆句、`slice_sentences.py` 切原声，并手写 clip.json。代理读一遍句表，觉得断得不对就直接改 `sentences.jsonl`，在 `run.md` 记一句为什么。

### 2 逐句翻译与复核（代理自己做）

不调用任何外部翻译 API：

1. 读这一句英文、前 3 句后 2 句英文、[术语表](../../docs/series-terminology.zh.md)里本系列的条目。韩语、西语参照该周正式全篇译文的用词约定（如 하나님、에스겔；Dios、Ezequiel、ustedes）。
2. 译出这一句。完整覆盖本句；经文出处、数字、人名、系列名按英文和术语表；不借邻句内容。
3. 全部写完后做独立的第二遍复核（或开子代理，只给英文与译文），判漏译、增译、否定、数字、人名、经文、意思偏移。
4. 译文写进 `translations.jsonl`，复核结论写进 `review.json`：

```json
{"locale": "ko", "speaker": "steve_bang_lee",
 "revisions": {"s0036": {"target": "이 메시지가 왜 달콤한지 아십니까?", "note": "revised: …"}},
 "notes": {"s0084": "note: …"},
 "spokenForms": {"19쪽": "십구 쪽", "12장 10절": "십이장 십절"}}
```

`spokenForms` 把字幕写法换成 TTS 读法，字幕仍保留阿拉伯数字。`speaker` 是 checkpoint 里的 speaker key。

### 3 口播规格（本机）

```bash
python3 $EXP/build_speech.py --run $RUN --review $RUN/review.json [--share-from <同片段的第一个 run>]
```

它把修订写回 `translations.jsonl`，生成 `speech.jsonl`，并列出粗估超预算的句子和仍含数字的口播句。`spokenForms` 里有一项没对上任何句子就报错。仍含数字的句子要补读法。超预算的句子第一遍可以先不精简，等合并后看实际落后再决定；要精简时只删重复、填充、同义复述，不删论点、否定、数字、人名、经文出处。

### 4 Spark 配音与回转写

先按 `dgx-spark-connect` 确认能连上，再看 GPU 有没有别人在用（`docker ps`、`nvidia-smi`）；另一个代理在用时等它。讲员 checkpoint 路径从 Spark 上的 `speaker-checkpoints.dgx.json` 查。

```bash
ssh achillesjing@192.168.1.152 'mkdir -p ~/sentence-first-agent/tools ~/sentence-first-agent/<run>'
scp $EXP/spark_run.sh $EXP/tts_sentences.py $EXP/asr_check.py achillesjing@192.168.1.152:sentence-first-agent/tools/
scp $RUN/speech.jsonl achillesjing@192.168.1.152:sentence-first-agent/<run>/
ssh achillesjing@192.168.1.152 'bash ~/sentence-first-agent/tools/spark_run.sh --work ~/sentence-first-agent/<run> --locale ko --checkpoint <checkpoint-dir>'
```

逐句合成（batch 1，2026-10-21 用户决定），不拉伸、不变速。已完成的句子和回转写行会跳过，所以中断后原样再跑一次就是续跑。先加 `--dry-run` 看一眼命令。88 句约 5 分钟配音加 1 分钟回转写；要在后台等，就把整条 `ssh` 放进后台任务，不要在远端用 `nohup … &`（会把 SSH 会话挂住）。要停时只停自己的：按 `docker inspect` 的挂载找出挂了本实验目录的容器再停。

### 5 收尾（本机）

```bash
python3 $EXP/finish_run.py --run $RUN --remote achillesjing@192.168.1.152:sentence-first-agent/<run> [--clip-from <同片段的第一个 run>]
```

它拉回 `tts/` 和回转写，合并音轨（每句放在英文起点，放不下就接在上一句后 0.25 秒），打分，混回视频，出约 9 MB 的手机预览，并打印落后最多的句、超过 8 秒的句、配音与原声时长比、TTS 速度和回转写相似度低的句。

### 6 听一遍，记下来

回转写的同音字差异（它/他、再/在）不算问题；人名、数字、否定词不一致要人听。分数只是提示，不是听审。把预览发给用户听，把落后最多的句、读错的句、译得别扭的句和用户结论写进 `run.md`。要改某句：改 `translations.jsonl` 或 `review.json` 里那一行，重跑第 3 步，删掉 Spark 上该句的 `tts/<id>.wav` 和 `asr.jsonl` 里那一行，再跑第 4、5 步，只会重做这一句。

## 双人播客

2026-10-22 播客整期首跑见[报告](../../docs/reports/20261022-sentence-first-podcast-full-episode.zh.md)。和单讲员相比多三步：

1. **说话人。** 拿到说话人区分结果和用户确认的标签映射后，在第 1 步之后跑

   ```bash
   python3 $EXP/assign_speakers.py --run $RUN --segments <segments.json> --mapping <speaker-label-mapping.json> --use-text
   ```

   每句写入 `speakerId`；`speakers.json` 列出一致度低于 0.8 的句子，要人看。`--use-text` 按转写逐词对齐投票，短附和不会落到对方名下。
2. **两种声音。** `review.json` 用 `"speakers": {"<speakerId>": "<speaker key>", ...}` 代替单个 `speaker`。两位讲员都要在 Registry 里有授权和本语言能力。
3. **按讲员分开渲染。** 每个讲员一个 checkpoint，一次只加载一个，所以 `spark_run.sh` 每次带 `--speaker <key>` 只跑一位，两位都跑完再跑一次 `--steps asr`。

**独占会话。** Spark 处于另一个独占会话时，不要直接起容器：会话收尾会因 `unmanaged_running_container` 失败。用 `spark_session_job.py` 在自己的会话里把每一步登记成任务（开任务、带标签启动、绑定容器、等待、结束）。会话一次只接纳一个运行中的任务，语言之间排队。登记的容器不能用 `--rm`，会话关闭（`finish`）后再按标签删掉停止的容器。

**时长。** 对谈几乎没有停顿，自然语速的整期配音比原片长约四分之一，落后会累积到十分钟以上。要跟视频同步，口播稿需要整体精简，或者不跟视频同步、作为独立音轨。

## 完成的样子

`run.md` 能让另一个人复现：来源、窗口、模型与 checkpoint、每步的决定、哪些句改过、听感结论、这条路径哪里顺哪里卡。这就是实验的交付物；音频留在本机。

## 退出条件

- 一个片段三语走通，且代理能说清每步花了多久、卡在哪，这条线的结论写进 `docs/reports/`，由用户决定是否把哪些步骤接回正式路径。
- 或者路径本身不成立（分句、时长预算或声音任一环节过不去），同样写报告后关闭。
