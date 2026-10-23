# 逐句优先、代理直做的配音

这条线不走正式流水线和哈希绑定校验，所有工作在代理会话里直接完成：英文按句拆开，代理逐句翻译与复核，Spark 用讲员自己的声音逐句配音，合并成整轨，经用户人工审核后可以发布成正式页面。单讲员证道和双人播客都按本文走，每周重复使用。路线的完整说明（何时用、检查、用时与花费、限制）见[路线文档](../../docs/sentence-first-agent-production.zh.md)，路径设计见[逐句优先设计](../../docs/design/sentence-first-dubbing-path.zh.md)；正式四层的双人播客另见[双人播客制作规范](../../docs/podcast-dual-speaker-production.zh.md)。

读完本文即可开工；连 Spark 时读 `dgx-spark-connect` skill。不需要读 controller、speech job 或豁免的文档。

## 边界

1. 产物只写在忽略的 `artifacts/sentence-first-agent/<run>/`。原声切片是讲员原声，不出这个目录，不进 Git。
2. 可以只读正式生产已有的产物（批准窗口、锚点清单、说话人区分与标签映射、已人工批准的译文），不写入正式生产的目录。
3. 译文、配音、字幕在用户人工审核前都是机器产物。只有用户亲自听完整轨、审过译文，并要求发布时，才按[发布](#10-发布到正式页面)以 `human_reviewed` 发布；每一次正式部署都要用户在对话里授权。
4. 讲员声音只用 Registry 里已授权配音用途、且有本语言能力的 checkpoint；不下载、不换别人的声音。

其余（分句微调、提示词、重跑、改字）由代理自行决定，写进 `run.md`。

## 脚本

都在本目录，每个 `--help` 可看参数。本机脚本只用标准库和 `ffmpeg`；Spark 上的脚本在固定镜像里跑。

| 脚本 | 在哪跑 | 做什么 |
|---|---|---|
| `prepare_clip.py` | 本机 | 从锚点清单裁音频：clip.wav、clip.json、words.json、sentences.jsonl、原声切片、run.md 表头 |
| `split_sentences.py`、`slice_sentences.py` | 本机 | 没有锚点清单时拆句、切原声（prepare_clip 会调用后者） |
| `assign_speakers.py` | 本机 | 双人：按说话人区分结果给每句定讲员 |
| `translate_parts.py` | 本机 | 把句表拆成几份交给并行翻译子代理（`split`），再按句序合并、检查（`merge`） |
| `build_speech.py` | 本机 | 套用复核修订和口播读法，写 speech.jsonl |
| `spark_queue.py` | 本机 | 把所有语言、所有讲员的配音与回转写排成一条任务队列 |
| `spark_session_job.py` | 本机 | 在 Spark 独占会话里把一步登记成任务并等它结束（spark_queue 调用它） |
| `spark_run.sh` | Spark | 一个语言、一位讲员的逐句 TTS（batch 1）或回转写，可续跑 |
| `tts_sentences.py`、`asr_check.py transcribe` | Spark 容器内 | 由 spark_run.sh 调用 |
| `finish_run.py` | 本机 | 拉回、合并、打分、混回视频、出手机预览，打印落后与回转写摘要 |
| `merge_track.py`、`asr_check.py score` | 本机 | 由 finish_run.py 调用 |
| `review_sheets.py` | 本机 | 每种语言一张人工审核表（CSV），标出要重点听的句子 |
| `publish_podcast_page.py` | 本机 | 正式页面发布驱动；页面信息是文件顶部的常量 |

## 目录

```text
artifacts/sentence-first-agent/<run>/
  run.md              工作日志：来源、决定、改动、用户结论
  clip.json           媒体路径、媒体起止、单元范围
  clip.wav            音频，16 kHz 单声道
  words.json          词级时间，相对 clip.wav
  sentences.jsonl     每句一行：id, english, start, end, pauseAfter, words, sourceUnitId（双人另有 speakerId）
  speakers.json       双人：讲员分配与一致度低的句子
  slices/             每句原声切片；slices.json 记 budgetSeconds
  translate/          并行翻译的 input-<k>.jsonl 与 output-<k>.jsonl
  translations.jsonl  每句一行：id, locale, target, reviewNote
  review.json         复核修订、备注、口播读法、讲员声音
  speech.jsonl        每句一行：id, spokenText, language, speaker, hint, budgetSeconds, estimatedSeconds
  tts/                每句配音；tts-log.jsonl 记时长和墙钟
  asr.jsonl           回转写；asr-report.json 是打分结果
  track.wav           合并音轨；schedule.json 记每句计划起点、实际起点、落后
  dub.mp4             视频 + 配音；dub-preview-640.mp4 是手机预览
```

每种语言一个 run 目录。第一种语言裁音频，其余语言用 `--share-from`／`--clip-from` 指向它，不重新裁。

## 每周步骤

命令里的 `$EXP` 指 `experiments/sentence-first-agent`，`$RUN` 指本语言的 run 目录，`SPARK` 指 `achillesjing@192.168.1.152`。

### 0.5 环境预检（本机，开工前几分钟）

1. 确认代码与脚本齐：`git fetch origin`，`git rev-list --left-right --count origin/main...HEAD`。落后很多时（2026-10-23：落后 2759 个提交，实验目录缺 11 个脚本），在 `artifacts/worktrees/sfa-main` 建 origin/main worktree，不要改当前分支。
2. 确认导入的是 worktree 的包：主 checkout 的 `.venv` 是 editable 安装，指向旧包；运行发布驱动时用 `PYTHONPATH="packages/production/src:."` 把 worktree 放最前，并 `python -c "import tongxing_production; print(tongxing_production.__file__)"` 核对。
3. 确认 run 目录位置：`slices/slices.json` 存仓库相对路径（`artifacts/sentence-first-agent/<run>/slices/...`），所以 run 放在主 checkout 的 `artifacts/sentence-first-agent/`，所有本机步骤从仓库根运行；不要放 worktree。
4. 要发布时确认 Firebase 与 ADC：`XDG_CONFIG_HOME=<可写 configstore 副本> firebase login:list` 和 ADC token 各一次；沙箱下 `~/.config/configstore` 不可写会让 firebase 报 “credentials no longer valid”。
5. 确认 Spark 会话空闲、checkpoint 路径存在；有别人的会话先问用户。

### 0 开工前向用户问清

写进第一个 run 的 `run.md`：

1. **目标语言和讲员。** 逐一查每位讲员在每种语言的 Registry 授权与能力；缺一项的讲员不能配，先告诉用户。
2. **跟不跟视频同步。** 不同步：独立音轨，自然语速，不精简。要同步：第 5 步按 `budgetSeconds` 精简口播稿，并请用户认可精简后的稿子（对谈通常要删约四分之一）。
3. **发不发正式页面。** 要发就是 `human_reviewed`：用户要听完每条整轨（时长约为原片的 1.25–1.3 倍）并审译文，先把这个工作量告诉用户。页面标题、类别小标题、讲员栏一起问。发布的页面都带英文对照（字幕和全文下的英文），不需要问；先确认正式 Layer 1 的英文来源包已经人工批准，没批准就先补英文审核，否则第 10 步的英文对照会被拒。

### 1 开自己的 Spark 独占会话

1. 用会话工具（`packages/production/src/tongxing_production/compute/spark_exclusive_session.py`，`--help` 看参数）的 `status` 看有没有别人的会话；有就问用户，不要收尾别人的会话。
2. `begin` 开自己的会话。之后所有容器都通过 `spark_queue.py` 或 `spark_session_job.py` 登记，不直接 `ssh … docker run`：未登记的容器会让会话收尾失败（`unmanaged_running_container`）。

### 2 裁音频、拆句（本机）

```bash
python3 $EXP/prepare_clip.py --anchor <anchor-manifest.json> --media <video> --window-start <窗口起点秒> --units <LO:HI> --run $RUN --title "<一行说明>"
```

锚点清单（`sermon-sentence-anchor-manifest-v2`，时间相对批准窗口）取正式 Layer 1 已有的那一份。`--units` 是锚点单元下标，两端都含；整期就是全部单元。分句沿用锚点单元。没有锚点清单时，按 `sermon-mfa-word-alignment` skill 拿词时间，存成 `[{"text","start","end"}]`，再用 `split_sentences.py`、`slice_sentences.py`，并手写 clip.json。代理读一遍句表，断得不对就改 `sentences.jsonl`，在 `run.md` 记原因。改句界时，每个锚点单元仍要按原顺序恰好出现一次（`sourceUnitId`），不改单元里的英文：App 的英文对照逐单元取自正式英文来源包，覆盖不全就整页没有英文。

### 3 双人：定讲员，用户确认后再往下

```bash
python3 $EXP/assign_speakers.py --run $RUN --segments <segments.json> --mapping <speaker-label-mapping.json> --use-text
```

说话人区分结果和用户确认过的标签映射取正式生产已有的那一份，不重跑区分模型。每句写入 `speakerId`；`--use-text` 按转写逐词对齐投票，短附和不会落到对方名下。`speakers.json` 里一致度低于 0.8 的句子交给用户确认，确认后再翻译、再配音。

没有正式 segments/mapping 时（例如 artifacts 已清理），不要重跑区分模型或换声音：按上一期已人工审核并发布的整期 `speech.jsonl` 逐单元复用讲员。先核对 `id ↔ sourceUnitId` 的偏移与英文/译文对齐，再写入 `speakerId`；`speakers.json` 记明“未重算置信度”，整轨听审时核对声音归属。这条回退不替代新句的独立审核。

### 4 逐句翻译与复核

不调用外部翻译 API。逐句要求：

1. 读这一句英文、前 3 句后 2 句英文、[术语表](../../docs/series-terminology.zh.md)里本系列的条目；韩语、西语参照该周正式译文的用词约定（如 하나님、에스겔；Dios、Ezequiel、ustedes）。
2. 完整覆盖本句；经文出处、数字、人名、系列名按英文和术语表；不借邻句内容。
3. 全部写完后做独立的第二遍复核，判漏译、增译、否定、数字、人名、经文、意思偏移。

已有人工批准的中文译文时，按句对过去直接用，不重译。其他语言用子代理并行：

```bash
python3 $EXP/translate_parts.py split --run $RUN --parts 4 --reference-run <中文 run> --name "john_thomas=JT (John Thomas)" --name steve_bang_lee=Steve
```

每个子代理只拿一份 `translate/input-<k>.jsonl`，提示里给出本语言的术语表条目与用词约定、上面三条要求，以及输出格式：每句一行 `{"id","locale","target","reviewNote"}`（`reviewNote` 为 `pass` 或 `revised: …`），写到 `translate/output-<k>.jsonl`。约 750 句分 4 份，每份几分钟。全部写完后：

```bash
python3 $EXP/translate_parts.py merge --run $RUN --locale <locale>
```

缺句、多句、空译文都会报错；它列出改过的句子和仍含数字的句子。复核结论写进 `review.json`：

```json
{"locale": "ko",
 "speakers": {"steve_bang_lee": "steve_bang_lee", "john_thomas": "john_thomas"},
 "revisions": {"s0036": {"target": "이 메시지가 왜 달콤한지 아십니까?", "note": "revised: …"}},
 "notes": {"s0084": "note: …"},
 "spokenForms": {"19쪽": "십구 쪽", "12장 10절": "십이장 십절"}}
```

单讲员用 `"speaker": "<speaker key>"` 代替 `speakers`。`spokenForms` 把字幕写法换成 TTS 读法，字幕仍保留阿拉伯数字。

### 5 口播规格（本机）

```bash
python3 $EXP/build_speech.py --run $RUN --review $RUN/review.json [--share-from <第一种语言的 run>]
```

它把修订写回 `translations.jsonl`，生成 `speech.jsonl`，列出粗估超预算的句子和仍含数字的口播句。`spokenForms` 有一项没对上任何句子就报错；仍含数字的句子要补读法。不同步时超预算不用处理；要同步时精简只删重复、填充、同义复述，不删论点、否定、数字、人名、经文出处。

### 6 Spark 配音与回转写：一条队列

讲员 checkpoint 路径从 Registry（`config/speaker-voice-registry.json`）的 checkpointRef/hash 与 Spark 上的实际目录核对；Spark 上没有 `speaker-checkpoints.dgx.json`（2026-10-23 核实）。当前两位讲员：Steve `~/dgx-spark-benchmark/results/sermon-speaker-bank-20260905/steve_bang_lee/checkpoints/checkpoint-epoch-0`（sha256 `b480bc6a…`）；John `~/dgx-spark-benchmark/results/john-thomas-voice-20261021/checkpoints/checkpoint-epoch-0`（root 所有，本机不能重算 hash；Registry 记 `3f722b17…`）。路径或 hash 对不上就停。上传脚本和每种语言的口播规格：

```bash
ssh SPARK 'mkdir -p ~/sentence-first-agent/tools ~/sentence-first-agent/<run>'
scp $EXP/spark_run.sh $EXP/tts_sentences.py $EXP/asr_check.py SPARK:sentence-first-agent/tools/
scp $RUN/speech.jsonl SPARK:sentence-first-agent/<run>/
```

会话一次只接纳一个运行中的任务，所以所有语言、所有讲员排成一条队列，作为本机后台任务运行（不要在远端用 `nohup … &`）：

```bash
python3 $EXP/spark_queue.py --session <session> --owner sentence-first-agent --remote-tools /home/achillesjing/sentence-first-agent/tools --locale zh-Hans=<Spark 上的 zh run> --locale ko=<Spark 上的 ko run> --voice <speaker key>=<checkpoint> [--voice <第二位讲员>=<checkpoint>]
```

每种语言每位讲员一个 TTS 任务，然后一个回转写任务。逐句合成（batch 1），不拉伸、不变速，约 1.35 倍实时；改批量要先问用户。中途失败时队列停下并打印怎么续跑；已完成的句子和回转写行会跳过，重跑队列只补缺的。登记的容器不带 `--rm`，会话结束后再删。

### 7 每种语言完成就收尾（本机）

队列打印 `locale done <locale>` 后立刻跑这种语言，不必等全部结束：

```bash
python3 $EXP/finish_run.py --run $RUN --remote SPARK:sentence-first-agent/<run> [--clip-from <第一种语言的 run>]
```

它拉回 `tts/` 和回转写，合并音轨（每句放在英文起点，放不下就接在上一句后 0.25 秒），打分，混回视频，出手机预览，并打印落后最多的句、配音与原声时长比、TTS 速度和回转写相似度低的句。

### 8 人工审核：边配边审

```bash
python3 $EXP/review_sheets.py --out <审核目录> --window-start <窗口起点秒> --run <locale>=$RUN [--doubt doubts.json]
```

一种语言收尾后就把整轨和审核表发给用户，用户听这一条时下一种语言还在配。`--doubt` 传翻译时发现的可疑英文源句（`{"s0043": "原因"}`）。回转写的同音字差异（它/他、再/在）不算问题；人名、数字、否定词不一致要人听；分数只是提示，不是听审。用户的结论写成审核收据，放在审核目录，并记进 `run.md`。

### 9 改句

改 `translations.jsonl` 或 `review.json` 里那一行，重跑第 5 步，删掉 Spark 上该句的 `tts/<id>.wav` 和 `asr.jsonl` 里那一行，再跑第 6、7 步，只重做这几句。改过的句子请用户再听。

### 10 发布到正式页面

只在用户审核通过并要求发布时做。复制一份 `publish_podcast_page.py`，改顶部常量（pageId、语言、run 目录、窗口、标题、类别、讲员、来源、日期），不要改已发布页面那一份的常量。顺序固定，每步一个子命令：

1. `assets`：生成每种语言的页面、文稿、字幕、MP3 和 release 模板；要求审核收据为 `approved`。文稿 `durationSeconds` 取窗口终点的媒体时间，并逐句跑与 iOS `validateCues` 相同的检查。
2. `baseline`：取线上完整快照。线上 v4/v3 和 v5 的投影只在页面默认语言上不同时，`stage1` 按 v5 重新投影并记下改了哪几页；其他差异一律拒绝。
3. `stage1` → `publish`：第一次部署，只加资产（和上面的投影修正）。
4. `verify`：逐个 GET 新资产比对 SHA，MP3 查 Range。
5. `stage2` → `publish`：第二次部署，release 与 v5/v4/v3 目录。
6. `readback`：回读线上目录和 release，与 stage2 逐字节比对。
7. `baseline` → `stage-english-reference` → `publish`：第三次部署，加 `/english-reference/<pageId>.json`。App 的字幕和全文靠它显示英文；没有它，页面照常能播，但只有译文（2026-10-22 播客首次发布就漏了这一步）。它的英文逐单元取自已人工批准的英文来源包，并绑定每种语言 release、文稿、字幕的哈希，所以必须在 release 上线之后生成；以后任何一种语言的 release、文稿或字幕变了，都要重新生成并部署这个文件，否则 App 会悄悄不显示英文。英文来源包未经人工批准时这一步会拒绝，先补英文审核。

每次 `publish` 都要用户在对话里授权；权限检查拒绝时不要绕过，把命令交给用户。发布后按 App 的读取路径（目录 → release → 文稿与字幕）再查一遍线上文件，然后请用户在手机上刷新确认。

**发布到 Dev（实验页）**：目标是 `ai-for-god-sermon-audio-dev` / `https://ai-for-god-sermon-audio-dev.web.app`，channel `dev`。`publish_podcast_page.py` 写死 production（`stage()`、`baseline()` 的 environment、`ORIGIN`、句数、run 目录名、verdict 路径），复制后必须改成 dev 并参数化这些值，不能只改顶部常量（2026-10-23 实测）。Dev 目录有 25 页，v4 还有 v5 没有的 edition fan-out（26 页）；`baseline` 用 `allow_default_locale_drift=True`，`stage1` 修默认语言漂移。

**片段页的英文对照**：规范 `build_reference` 要求页面覆盖英文来源包的全部单元，10 分钟片段只有连续子集，会被拒绝（2026-10-23 在本地合成快照验证）。用 dev 驱动里的 `build_clip_reference`：沿用同样的审批/哈希检查，只把覆盖改成连续有序子集；先在本地合成快照上验证每种语言的 `blocks` 等于本页句数（例如 187），不是整期 746。以后给规范 builder 加子集模式时，保留“整期页必须全覆盖”的检查。

页面、文稿、字幕的路径是固定的：`/pages/<pageId>/<locale>/index.html`、`/content/<pageId>/<locale>.json`、`/captions/<pageId>/<locale>.json`。正式版 App 遇到别的路径会把这种语言、乃至整页隐藏（开发版不做这项检查，所以开发版里看得到不代表正式版看得到）。要修已发布的文稿或字幕，就在原路径写入修正后的字节，先部署、HTTP 核验，再部署改了哈希的 release 和目录；不要换新路径。发布合同 `validate_v2_release_target` 会拒绝不在固定路径上的 release。

列表里的小标题只来自目录页面的 `displayCategory`（两个早期页面在 App 里写死为“正式播放版”）；新页面要显示小标题，就在 v5 页面上写这个字段，投影会带到 v4/v3。

### 11 结束

`finish` 关闭会话，再按会话标签删掉停止的容器（`docker rm $(docker ps -aq --filter label=tongxing.spark.session=<session>)`）。按[运行报告](../../docs/test-run-retrospective.zh.md)导出本次报告。

发布后保留小文本表（`sentences.jsonl`、`translations.jsonl`、`speech.jsonl`、`speakers.json`、`review.json`、`schedule.json`、`run.md`、审核表），只删 `tts/`、`slices/`、`clip.wav`、`track.wav`、`dub*.mp4`；否则下一轮无法 resume 或复用讲员分配/已批准译文（2026-10-23 实测：上一期 run 目录被清理，只能从 Spark 拉回 `speech.jsonl`）。

## 完成的样子

每种语言的 `run.md` 能让另一个人复现：来源、窗口、模型与 checkpoint、每步的决定、改过哪些句、用户结论、每步用时。审核收据在审核目录；音频留在本机；发布了的话，报告里写明线上版本号和哪些检查没做。发布的页面要同时满足：每种语言在正式版 App 的解码规则下都能显示（固定路径、文稿时间），英文对照已上线且每一句都有英文。缺英文对照不算发布完成。
