# 正式 Layer 3 配音 renderer

`scripts/render_formal_target_language_speech.py` 只接受已人工审核的 v2 speech job。先验证 Layer 1/2、独立人审、音色授权与能力收据、clip timeline、adapter/registry、音频操作策略三项哈希以及部署 checkpoint 的权重 SHA。它逐组使用 job 的原文合成自然速度 WAV，完整解码并写 unit receipt，按 clip-relative 首个源单元起点排程。默认 reaction lag 0.05 秒、组间 gap 0.05 秒、末单元源结束后最大 8 秒；最终音频必须在片段媒体时长内。越界时保留已解码的单元与 `render-diagnostics.json`，不写成功 manifest，不调速、不裁剪、不跳过。

可选 `--instruct` 将自然口播要求送入 Qwen TTS，并纳入每单元缓存身份；改指令必须写入新 job 目录，保留原音频。只测量并移除前导静音时，可对已完整提交的单元运行 `scripts/compact_formal_target_audio.py --source-job <原 job> --destination-root <新目录>`，其余身份参数与 renderer 相同。此工具逐单元复核原始 intent、commit、WAV 和收据，以 10 ms RMS 窗口和 0.01 阈值寻找首个有声窗口，默认保留 60 ms 前垫、每组最多移除 750 ms；保存原／新 SHA、精确移除时长和独立 `silenceTrimEvidence`。原目录不变，新目录重新排程并只在无溢出时写 manifest。音频包构建器会核验裁剪证据；是否有吞字或不自然起音仍须回转录和人耳听审。

### 单元口播指令输入

`--unit-instructions <JSON 文件>` 接受 `sermon-unit-delivery-instructions-v1` 或 `-v2` 输入，由 [renderer 的 unit_instructions](../scripts/render_formal_target_language_speech.py) 校验。它绑定完整 speech job 的 JSON 身份、locale 和已批准文字；不能借口播指令更改批准文本或授予音色／发布资格。可只列需要覆盖的单元，但 `units` 必须是非空数组。

```json
{
  "schemaVersion": "sermon-unit-delivery-instructions-v1",
  "targetLocale": "zh-Hans",
  "speechJobJsonSha256": "<冻结 job 的 json_sha256>",
  "units": [
    {
      "translationGroupId": "<job 中已有的组 ID>",
      "approvedTextSha256": "<该组 text 的 UTF-8 字节 SHA-256>",
      "instruction": "Pause at the sentence boundary.",
      "operatorEvidence": "<实际操作员确认的发音或停顿依据>",
      "spokenText": "<可选的中文等价口播形式>"
    }
  ]
}
```

占位符必须替换；没有口播形式覆盖时删除 `spokenText`。在仓库根目录，用 `scripts.sermon_sentence_interpretation.json_sha256(job)` 计算 `speechJobJsonSha256`，不要用 job 文件字节 SHA 代替。`approvedTextSha256` 使用 `hashlib.sha256(unit["text"].encode("utf-8")).hexdigest()`，不先 strip、改标点或重写文字。job 或批准文本改变后重建绑定。

| 字段／规则 | 现有校验与拒绝条件 |
| --- | --- |
| `schemaVersion`、`targetLocale`、`speechJobJsonSha256` | 必须分别为 v1 或 v2、job locale 与完整 job 的 JSON hash；错版本、错语言或旧 job 绑定均拒绝 |
| `translationGroupId` | 必须存在于 job，且同一输入内不重复；未知或重复组拒绝 |
| `approvedTextSha256` | 必须匹配该组原始批准 text 的 UTF-8 SHA-256；旧稿或任意改字拒绝 |
| `instruction`、`operatorEvidence` | 均须为非空字符串，纯空白拒绝；instruction 去除首尾空白后使用。v2 中带 `spokenText` 的行可省略 `instruction`，该单元沿用全局 `--instruct`。操作员依据不代替既有独立人审收据 |
| `spokenText`（可选） | v1 仅 `zh-Hans`；v2 支持 `zh-Hans` 与 `ko`。须为非空字符串并通过 `_spoken_equivalent`；其他 locale 或不等价文字拒绝 |

当前等价检查移除非字母数字字符，并将 `第3章第16节`、`3:16`、`第三章第十六节` 归一为相同形式，用于已确认的启示录 3:16 读法。这是既有检查的描述，不扩大任意换词、改数字、增删内容或一般经文读法的权限；批准文字仍原样保留，口播形式另绑定 `spokenTextSha256`。

韩语等价检查只允许 [ko_spoken_numerals](../scripts/ko_spoken_numerals.py) 的 `ko-sino-chapter-verse-numerals-v3`：明确韩文圣经书名紧接的引用链，将 `장`、`절`（`시편` 另含 `편`）前的阿拉伯数字读作汉字词数字；例如 `하박국 2장` 读作 `하박국 이장`，`요한복음 3장16-17절` 连写也完整转换。书名锚定链还支持 `부터`／`에서` 连接的范围终点，例如 `요한복음 3장부터 4장까지` 和 `창세기 1장 1절에서 3절`；重复 counter 的 `-`／`~`／`–` 范围也支持；连接词后若出现普通正文则停止匹配。v3 起（2026-10-13 用户决定），讲道正文里不带书名的 `N장`、`N절` 也按章节读汉字词数字，例如 `8장의 맨 첫 절` 读作 `팔장의 맨 첫 절`、`16-17절` 读作 `십육-십칠절`；不带书名的 `N편` 不转换，紧跟在计数名词（`사진`、`종이`、`편지`、`카드`、`표`、`티켓`、`페이지` 等）后的计数也不转换，例如 `사진 2장`、`영화 2편`。书名后的引用上下文不跨越普通文字。等价检查只忽略列明的停顿标点和空格，保留数字间小数点及分隔标点、`%`、金额、数学、比例及范围符号，不能删除可发声的符号。Qwen TTS 常把这些数字读成固有词（`여덟 장`、`두 장`），2026-10-11 周更和 10-12 片段测试的音频质检都因此判为需要修复。`3:16`、`3,000장`、`1.5장` 等不改。字幕、阅读文本和批准文字仍保留阿拉伯数字；ASR 初筛和音频质检把汉字词数字折回阿拉伯数字比较，固有词读法仍会被标出。

### 规范化策略 v2：周更自动口播形式

新的周更 Layer 3 使用仓库内的 [config/layer3-audio-operation-policies.json](../config/layer3-audio-operation-policies.json) 和 [config/layer3-adapters/](../config/layer3-adapters/) 的三个 adapter。其 normalization 策略为 v2 `exact_approved_text_with_registered_spoken_forms`，为 `ko` 登记上述规则 v2；规则 v1 的实验策略哈希不复用，新 adapter 的 normalization hash 随规则版本变化，旧实验 job 不静默迁移。adapter 的 `normalizationPolicySha256` 绑定它，`prepare_target_language_speech_job.py` 再把该哈希冻结进 speech job。renderer 发现 job 绑定 v2 时，按规则为韩语单元自动生成口播形式，不需要 `--unit-instructions` 文件，因此调度器无需额外步骤；恢复导出与统一音频 adapter 使用同一推导。显式指令文件仍可为同一单元加 `instruction`，但给出不同 `spokenText` 会被拒绝。`zh-Hans`、`es` 在 v2 下没有登记规则，合成文字不变。

已绑定 v1 `exact_human_approved_target_text_no_rewrite` 的旧 job 保持原文与声音身份，不原地迁移。旧 job 的显式韩语 Sino spokenText override 不在 synthesisIdentity 内，无法绑定对应预算／压缩／时长 QC，因此 renderer 与统一 adapter 在合成或冻结 plan 前拒绝该组合；旧 v1 instruction-only 配音指令及其他语言原有角色保留。需要韩语改读时，先按 v2 normalization 重新冻结新 job；下面的命令只为该新 job 生成与 policy 完全相同的可选 v2 指令文件，再传给 `--unit-instructions`（没有需要改读的单元时输出 `no_change` 且不写文件）：

```sh
.venv/bin/python scripts/ko_spoken_numerals.py --job <韩语 speech job.json> --out <新的 unit-instructions.json>
```

改读会改变受影响单元的声音身份，需在新的 render 目录重新合成。提前配音（speculative）renderer 仍只接受 v1 策略。

列出的单元以其 `instruction` 覆盖全局 `--instruct`；未列出的单元继续使用全局指令。指令或口播形式变化时用新 job／render 目录，重新生成输入绑定，保留原 intent、commit、WAV 和收据。batch>1 的窗口身份包含邻组输入：一个单元的指令变化可能使整个窗口的声音身份变化，不承诺只重合成该单元。

### 缓存与 renderer 身份

9 月 20 日新版韩／西语已批准文字的末段合成仍接近片段末端，因此正式候选采用 `--trim-trailing` 测量首尾静音，另显式记录 `--padding-seconds`、`--inter-utterance-gap-seconds` 和 `--reaction-lag-seconds`。韩语保留首尾各 20 ms、零组间空隙、零反应延迟；西语保留首尾各 40 ms、零组间空隙、50 ms 反应延迟。原始单元、裁剪单元和独立证据均保留；没有时间拉伸。韩语约 28 ms 的末端余量只说明排程没有越界，不代表自然度或衔接已合格。

重跑时按 job、源与候选、adapter、checkpoint map/权重、策略文件、文本、renderer SHA 与合成参数比较缓存身份；变化的单元文字或音色不得复用，新候选中的不变单元可按 `--reuse-from` 核验。一个单元在 WAV 写出后中断时，可凭已写的 SHA commit 记录恢复。`render-manifest.json` 的机器筛查为 `not_run`，人工听审仍待完成。

2026-10-05 增加[异常留存与只读恢复清单](production-recovery-plan.zh.md)：保存 timing 风险、失败／待替换 partial 和显式 quarantine 的原字节及身份；保存失败不删除原件。低能量边缘只是测量，不自动裁剪或重合成。恢复计划解释 reuse/revalidate/recompute/unknown 与完整批窗重放、缺项提交数量，仍由原 producer 在锁内准入。

2026-10-01 引入 `--batch-size 1|2|4|8`。未使用下述 8×8 生产入口的兼容路径仍默认 batch1，显式 Dev test profile 默认2；新建单讲员周日 Spark 任务使用下述 `--spark-production`。当前实现先校验整个 job，再按固定窗口处理缺失单元；窗口内有已提交或准入复用的邻组时，恢复合成仍重放完整绑定窗口，但只提交缺失单元，保留已有音频字节。每批一次驻留模型调用，短尾批完整校验映射与数量。intent 绑定 batch size、设备、窗口输入及 seed 策略，commit 记录实际生成索引；seed 为基础值加窗口起始索引。batch=1 保留原 intent/逐单元 seed 格式，其他 batch 使用批处理身份，不能混用缓存或绕过人审。恢复验证不等于随机采样结果与不中断运行逐字节相同。

缓存必须通过当前 producer 的完整身份核验。`rendererSha256` 使用固定的 `RENDERER_SOUND_IDENTITY_SHA256` 表示声音身份；batch>1 另以 `batchImplementationSha256` 绑定 renderer 实现文件的字节 SHA。实际执行代码身份仍单独记录。声音身份相同不自动允许批处理代码复用：即使只改 CLI help，文件 SHA 也会改变，旧 batch 缓存必须通过完整身份或代码已有的明确兼容规则；不手改 hash、不跳过校验、不扩大兼容名单。

旧声音身份只可按现有兼容分支复用：`--reuse-from` 的无 spoken-form 旧版本兼容须保持其余单元声音输入一致；集成父版本兼容须保持其余身份一致，不是所有批处理路径的通用豁免。preview admission 另走预生成校验，当前只支持 batch=1 且无 spokenText 覆盖。批处理修复兼容仅接受代码列出的旧实现身份及其允许的 seed／cached-unit 策略映射，其他身份字段仍须匹配。`--reuse-from` 允许在新 job／候选中复用不变单元，但仍核对 source/anchor、文字、voice/checkpoint、adapter、策略、合成参数、原 intent/commit 与 WAV SHA，并完整解码；不兼容身份不得当成可复用音频，篡改 WAV 或 commit 须拒绝。

## 周日单讲员：Spark 生产按 8×8

2026-10-03 决定：新建的单讲员周日证道任务在 Spark 使用 **8 个常驻模型副本 × 每批 8 句**，正式入口增加 `--spark-production`（等效于 `--replicas 8 --batch-size 8`）。保留上述正式输入、文字人审、音色授权及 checkpoint 校验；只改变 Layer 3 TTS 调度。CUDA:0、BF16、SDPA 固定为此次测量设置；不支持多讲员分路，回转写 ASR 与其他 Layer 配置不变。在包含完整正式输入与授权参数的原命令末尾追加 `--spark-production`。下方 staged 模板已包含该参数。

八个独立 spawn 进程各加载同一授权 checkpoint，全部 ready 后按 job 原始索引的固定八句窗口分配，seed 为基础值加窗口起始索引；419 句分为 53 个窗口，末批 3 句。最多八个未消费窗口，加上父进程正在处理的当前窗口，返回音频最多驻留九个窗口。模型副本跨窗口驻留；不让八个完整 renderer 同时操作同一目录。主进程按原顺序校验数量、身份、有限波形和采样率，保存、完整解码、hash、commit、receipt，再执行原排程与整轨组装。artifact root 的非阻塞文件锁覆盖正式输入校验、单元写入及组装，重复执行直接拒绝。

模型加载前、等待结果期间及每次派发／取出结果时检查 Linux `/proc/meminfo` 的 `MemAvailable`，低于 **24 GiB** 即停止本次拥有的子进程；默认加载和单窗口生成超时均为 600 秒。等待轮询为 0.2 秒，但单批 IPC 反序列化和父进程媒体验证期间不是连续内存采样。保护基于宿主统一内存，不能把 CUDA、cgroup 与宿主数值相加；此路径要求 Spark/Linux，未自动退回 MacBook。

失败后保留已写的 SHA commit 和正式收据，只清理当前 pool 拥有的进程；续跑重新准入整个 job，只合成包含缺失单元的固定窗口，完整重放该窗口的全部成员，已提交的邻居字节不变。全部音频可复用时不创建模型进程。任意未来单元身份或音频 hash 不符会在加载前失败。`replica-runtime.json` 记录 worker PID、加载／生成耗时、窗口索引及采样到的最低可用内存，不记录证道正文；`closed` 仅表示 pool 关闭。成功依然以完整 manifest／单元收据为准，ASR 与人耳听审仍独立待完成。原逐单元 accounting 计量父进程的有序写入和等待，真实重叠计算耗时见 replica runtime，不把等待时间相加作为 GPU 墙钟。

缓存迁移：旧的串行单元保持 `sermon-formal-target-speech-render-v1`，不带生产参数时 CLI 仍为单副本／batch1，旧 Dev profile 仍使用其原设置，避免隐式改变现存任务。新八副本 intent 使用 `sermon-formal-target-speech-render-v2`，绑定 replicaCount、调度策略与 pool／scheduler 实现 hash；必须使用新 render root，禁止与旧串行缓存混写。此次直接 dev 父版本的串行完整窗口音频，在其他输入、参数、窗口和字节 hash 匹配时可继续准入。切换 batch size、设备或单／八副本模式都不能绕过身份检查。正式 speech job 和 Audio Package schema 未改变。

选择证据和 419 段预算见[单讲员 Spark 测量报告](reports/20261003-spark-production-8x8.zh.md)。8×8 的 64 句重复实测中位数 56.81 秒，最低可用内存 38.43 GiB；16×4 两次触发 24 GiB 保护，没有有效速度结果。419 句的约 6.2 分钟热 TTS／7.1 分钟加 cold load 为组件外推，不代表整篇实际完成或语言质量通过。

`screen_target_language_audio_units.py` 同样新增 `--batch-size 1|2|4|8`（默认 1），CLI 只加载一次 ASR 模型；可用 `--unit-cache <artifact-root 内的新缓存目录>` 保存逐单元不可覆盖的识别回执，续跑只转写缺失单元。cache 绑定 job、locale、文字、音频 hash、模型 revision 和 batch 设置，错身份或错映射直接停止。Qwen 高层接口返回值不暴露 EOS/finish-reason；这里只验证函数返回、数量、身份、可解码音频和全单元覆盖，实际截断风险仍需回转写及人工听审。性能／质量验收见[提速 backlog](local-production-speed-backlog.zh.md)。

若 Layer 2 的独立机器复核已通过而文字人审仍待定，可先在独立目录用 `scripts/render_speculative_target_language_speech.py` 按组生成 `preview_only` WAV。它不创建正式 speech job 或 Audio Package。文字获批并准备好完整正式 job 后，给本 renderer 增加 `--speculative-from <预生成目录>`；正式来源、人审、音色能力与授权先过门禁，随后只复制候选快照、单元文字、来源、参数和音频 hash 全部匹配且可完整解码的 WAV，并重新签发正式单元收据。改文单元重新合成，整轨排程、ASR 和全文听审重新执行。具体命令与失效范围见[层内解耦设计](multilingual-intralayer-review-decoupling.zh.md)。

Mac 绝对输入路径可用 `--path-map` 映射到容器中的 staged 文件。JSON 形状：`{"schemaVersion":"sermon-deployment-path-map-v1","paths":{"/原始/绝对/文件":"/work/staged/文件"}}`。必须列出 job 的每个不可访问 input 路径以及 source/voice/timeline 收据中引用的不可访问文件。renderer 在建立临时路径别名之前逐项重新核对文件 SHA 和提供的 JSON SHA，绝不改写 job JSON。为了让现有验证器沿用不可变 job 内的原路径，容器需要 `/Users` 与 `/private` 两个临时文件系统；只在隔离容器里创建别名。

在 Spark 上，9 月 23 日长探针对应镜像是 `nvcr.io/nvidia/pytorch:26.06-py3`。已经只读验证镜像内 `/usr/bin/python` 可以从旧 venv 的 `site-packages` 导入 `torch`、`qwen_tts` 和 `jsonschema`，GPU 可见。Eric checkpoint 的宿主权重在 `/home/achillesjing/dgx-spark-benchmark/results/sermon-voice-poc-20260905/checkpoints/checkpoint-epoch-0`，SHA 与 Registry 一致。以下是 staged 目录准备完成后的一语执行模板；`SEP20_STAGE` 应指向操作员已校验的实际目录，其中 `repo/` 是含本脚本及依赖的仓库代码、`inputs/ko/` 是原始字节的正式输入、`output/ko/speech-job/job.json` 是未改字节的 job、`path-map.json` 映射所有原始绝对路径。

```bash
SEP20_STAGE=/home/achillesjing/dgx-spark-benchmark/results/sermon-formal-sep20-stage
docker run --rm --gpus all --ipc=host --read-only --network none \
  --tmpfs /tmp:rw,exec,nosuid,size=512m --tmpfs /Users:rw,nosuid,size=64m \
  --tmpfs /private:rw,nosuid,size=64m \
  -v "$SEP20_STAGE":/work:rw \
  -v /home/achillesjing/dgx-spark-benchmark/results:/results:ro \
  -v /home/achillesjing/dgx-spark-benchmark/results/sermon-voice-poc-20260905/venv/lib/python3.12/site-packages:/voice-packages:ro \
  -e PYTHONPATH=/work/repo:/voice-packages -e NUMBA_CACHE_DIR=/tmp/numba \
  -e TRITON_CACHE_DIR=/tmp/triton -e XDG_CACHE_HOME=/tmp/cache \
  -e HF_HOME=/tmp/hf -e HF_HUB_OFFLINE=1 -e TRANSFORMERS_OFFLINE=1 \
  --entrypoint python nvcr.io/nvidia/pytorch:26.06-py3 \
  /work/repo/scripts/render_formal_target_language_speech.py \
  --source /work/inputs/ko/english-source-package.json \
  --anchor /work/inputs/ko/anchor-manifest.json \
  --candidate /work/inputs/ko/candidate.approved.json \
  --policy /work/inputs/ko/policy-v2.json \
  --human-review-receipt /work/inputs/ko/human-review-receipt.json \
  --speaker-registry /work/inputs/ko/speaker-voice-registry.json \
  --adapter /work/inputs/ko/speech-adapter.json \
  --clip-voice-authorization /work/inputs/ko/clip-voice-authorization.json \
  --clip-voice-capability /work/inputs/ko/clip-voice-capability.json \
  --clip-timeline-map /work/inputs/ko/clip-timeline-map.json \
  --job /work/output/ko/speech-job/job.json \
  --checkpoint-map /results/sermon-voice-sep20-long-probe-20260923-v1/work/speaker-checkpoints.dgx.json \
  --audio-operation-policies /work/inputs/audio-operation-policies.json \
  --path-map /work/path-map.json \
  --spark-production
```

中文已有全局人审能力时可省略 `--clip-voice-capability`。以上命令是路径模板；2026-09-23 的真实结果见 [Layer 2/3 backlog](multilingual-layer-2-3-backlog.zh.md)。`build_target_language_audio_package.py` 以 renderer 的 manifest 构建最高为 `candidate` 的 Layer 3 包。三语均有完整 Qwen3-ASR 筛查收据，机器结果仍为 `requires_review`。`review_target_language_audio.py prepare` 从候选包和同一整轨／单元 hash 的筛查收据生成待审工作表；只在真人完成全文 1 倍速播放、视频同步及每个 ASR 疑点的显式裁决后，`approve` 才能产出 `human_reviewed` 包与 v2 人审收据。Dev staging 继续核对该收据及原机器筛查，不把机器状态改写为通过。

韩文引用的 ASR 初筛以 scoring v5 按书名锚定的完整引用链折叠汉字词数字，含单 counter 范围首端、连写章/节及 Psalm `편`；普通词内不放宽。旧 v4/v3 收据按原评分语义重评分，不自动升级。新实现改变初筛身份，旧 #361/#363 的真实音频 QC 不验证此 v5；新规则的真实模型/音频/校准尚未重跑。口播规则仍为本 PR 未合并的规则 v2，normalization policy hash 不另改；ASR runtime scoring 和实现 hash 与口播 policy hash 分别绑定。

引用 counter 后须为词边界、相邻完整引用或列明且完整的韩文助词后缀（含 `에는`、`입니다` 等）；`3장면`、`2편지`、`2편의점` 不转换，不从任意 Hangul 前缀推断引用。scoring v5 仅在书名锚定引用片段内（含紧接的范围终结标记）额外比较有序完整数字串、范围标记与引用 counter/范围助词结构，拒绝 `12-3` 与 `1-23` 的字符摊平等价及范围连接符插删；旧 v4/v3 路径保持原样。

实现身份：当前 screening v5 的 implementation hash 覆盖 screen、ko_spoken_numerals、auto_qc_text_common 与 common；单文件 hash 的旧实验 v5 收据需重新筛查，不能重标。QC/calibration/waiver 的实现闭包也含该韩语 helper。统一 audio adapter 对韩语 registered-normalization-v2（含与 policy 一致的显式 unit-instructions-v2），把 helper／共享规则加入 inspect plan code hash；依赖变化后 execute 在 dispatch 前拒绝旧 plan。exact-text v1 未使用新指令时不加这些依赖；renderer 的实际 spokenTextSha256 声音身份仍保留。合法完整助词 `이`／`이라고` 在生成和 ASR 引用边界采用相同规则。

引用链连接词由 generator 与 ASR 共用 `_CONNECTOR`：原有连接、三种横线及列明的 `이나`／`이든` 替代连接、`에서부터`／`부터는`／`부터만`／`부터도` 范围连接，允许空格或连写，但仍不跨正文、不应用于普通计数。

范围终点支持列明的完整叠加助词／系词（例如 `까지입니다`、`까지였어요`、`까지라고`、`까지의`、`까지를`），仍拒普通词后缀。明确书名紧接引用时也支持配对 `()`／`[]` 及全角括号；引用链须完整位于同一对括号内，不由不配对括号或跨正文推断口播规则。ASR 在同一书名引用范围内折叠这些形式。

校准 TTS、语速拟合／预算及传入冻结 speech job 的音频时长 QC 使用同一 job-bound registered spoken form；v1 或未提供 job 的旧 QC 调用保留原文计数。音频 QC 的 ASR/text hash 仍绑定批准文本，口播长度仅用于实际合成时长判定。校准实现闭包包含 formal renderer、transport、driver 与 policy activation helper；旧校准不能作为新实现的当前证据。
