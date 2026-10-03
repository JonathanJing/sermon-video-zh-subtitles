# 正式 Layer 3 配音 renderer

`scripts/render_formal_target_language_speech.py` 只接受已人工审核的 v2 speech job。先验证 Layer 1/2、独立人审、音色授权与能力收据、clip timeline、adapter/registry、音频操作策略三项哈希以及部署 checkpoint 的权重 SHA。它逐组使用 job 的原文合成自然速度 WAV，完整解码并写 unit receipt，按 clip-relative 首个源单元起点排程。默认 reaction lag 0.05 秒、组间 gap 0.05 秒、末单元源结束后最大 8 秒；最终音频必须在片段媒体时长内。越界时保留已解码的单元与 `render-diagnostics.json`，不写成功 manifest，不调速、不裁剪、不跳过。

可选 `--instruct` 将自然口播要求送入 Qwen TTS，并纳入每单元缓存身份；改指令必须写入新 job 目录，保留原音频。只测量并移除前导静音时，可对已完整提交的单元运行 `scripts/compact_formal_target_audio.py --source-job <原 job> --destination-root <新目录>`，其余身份参数与 renderer 相同。此工具逐单元复核原始 intent、commit、WAV 和收据，以 10 ms RMS 窗口和 0.01 阈值寻找首个有声窗口，默认保留 60 ms 前垫、每组最多移除 750 ms；保存原／新 SHA、精确移除时长和独立 `silenceTrimEvidence`。原目录不变，新目录重新排程并只在无溢出时写 manifest。音频包构建器会核验裁剪证据；是否有吞字或不自然起音仍须回转录和人耳听审。

### 单元口播指令输入

`--unit-instructions <JSON 文件>` 接受现有 `sermon-unit-delivery-instructions-v1` 输入，由 [renderer 的 unit_instructions](../scripts/render_formal_target_language_speech.py) 校验。它绑定完整 speech job 的 JSON 身份、locale 和已批准文字；不能借口播指令更改批准文本或授予音色／发布资格。可只列需要覆盖的单元，但 `units` 必须是非空数组。

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
| `schemaVersion`、`targetLocale`、`speechJobJsonSha256` | 必须分别匹配上述版本、job locale 与完整 job 的 JSON hash；错版本、错语言或旧 job 绑定均拒绝 |
| `translationGroupId` | 必须存在于 job，且同一输入内不重复；未知或重复组拒绝 |
| `approvedTextSha256` | 必须匹配该组原始批准 text 的 UTF-8 SHA-256；旧稿或任意改字拒绝 |
| `instruction`、`operatorEvidence` | 均须为非空字符串，纯空白拒绝；instruction 去除首尾空白后使用。操作员依据不代替既有独立人审收据 |
| `spokenText`（可选） | 仅 `zh-Hans` 支持，且须为非空字符串，通过现有 `_spoken_equivalent`；其他 locale 或不等价文字拒绝 |

当前等价检查移除非字母数字字符，并将 `第3章第16节`、`3:16`、`第三章第十六节` 归一为相同形式，用于已确认的启示录 3:16 读法。这是既有检查的描述，不扩大任意换词、改数字、增删内容或一般经文读法的权限；批准文字仍原样保留，口播形式另绑定 `spokenTextSha256`。

列出的单元以其 `instruction` 覆盖全局 `--instruct`；未列出的单元继续使用全局指令。指令或口播形式变化时用新 job／render 目录，重新生成输入绑定，保留原 intent、commit、WAV 和收据。batch>1 的窗口身份包含邻组输入：一个单元的指令变化可能使整个窗口的声音身份变化，不承诺只重合成该单元。

### 缓存与 renderer 身份

9 月 20 日新版韩／西语已批准文字的末段合成仍接近片段末端，因此正式候选采用 `--trim-trailing` 测量首尾静音，另显式记录 `--padding-seconds`、`--inter-utterance-gap-seconds` 和 `--reaction-lag-seconds`。韩语保留首尾各 20 ms、零组间空隙、零反应延迟；西语保留首尾各 40 ms、零组间空隙、50 ms 反应延迟。原始单元、裁剪单元和独立证据均保留；没有时间拉伸。韩语约 28 ms 的末端余量只说明排程没有越界，不代表自然度或衔接已合格。

重跑时按 job、源与候选、adapter、checkpoint map/权重、策略文件、文本、renderer SHA 与合成参数比较缓存身份；变化的单元文字或音色不得复用，新候选中的不变单元可按 `--reuse-from` 核验。一个单元在 WAV 写出后中断时，可凭已写的 SHA commit 记录恢复。`render-manifest.json` 的机器筛查为 `not_run`，人工听审仍待完成。

2026-10-01 引入 `--batch-size 1|2|4|8`，生产默认仍为 1，显式 Dev test profile 默认 2。当前实现先校验整个 job，再按固定窗口处理缺失单元；窗口内有已提交或准入复用的邻组时，恢复合成仍重放完整绑定窗口，但只提交缺失单元，保留已有音频字节。每批一次驻留模型调用，短尾批完整校验映射与数量。intent 绑定 batch size、设备、窗口输入及 seed 策略，commit 记录实际生成索引；seed 为基础值加窗口起始索引。batch=1 保留原 intent/逐单元 seed 格式，其他 batch 使用批处理身份，不能混用缓存或绕过人审。恢复验证不等于随机采样结果与不中断运行逐字节相同。

缓存必须通过当前 producer 的完整身份核验。`rendererSha256` 使用固定的 `RENDERER_SOUND_IDENTITY_SHA256` 表示声音身份；batch>1 另以 `batchImplementationSha256` 绑定 renderer 实现文件的字节 SHA。实际执行代码身份仍单独记录。声音身份相同不自动允许批处理代码复用：即使只改 CLI help，文件 SHA 也会改变，旧 batch 缓存必须通过完整身份或代码已有的明确兼容规则；不手改 hash、不跳过校验、不扩大兼容名单。

旧声音身份只可按现有兼容分支复用：`--reuse-from` 的无 spoken-form 旧版本兼容须保持其余单元声音输入一致；集成父版本兼容须保持其余身份一致，不是所有批处理路径的通用豁免。preview admission 另走预生成校验，当前只支持 batch=1 且无 spokenText 覆盖。批处理修复兼容仅接受代码列出的旧实现身份及其允许的 seed／cached-unit 策略映射，其他身份字段仍须匹配。`--reuse-from` 允许在新 job／候选中复用不变单元，但仍核对 source/anchor、文字、voice/checkpoint、adapter、策略、合成参数、原 intent/commit 与 WAV SHA，并完整解码；不兼容身份不得当成可复用音频，篡改 WAV 或 commit 须拒绝。

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
  --path-map /work/path-map.json
```

中文已有全局人审能力时可省略 `--clip-voice-capability`。以上命令是路径模板；2026-09-23 的真实结果见 [Layer 2/3 backlog](multilingual-layer-2-3-backlog.zh.md)。`build_target_language_audio_package.py` 以 renderer 的 manifest 构建最高为 `candidate` 的 Layer 3 包。三语均有完整 Qwen3-ASR 筛查收据，机器结果仍为 `requires_review`。`review_target_language_audio.py prepare` 从候选包和同一整轨／单元 hash 的筛查收据生成待审工作表；只在真人完成全文 1 倍速播放、视频同步及每个 ASR 疑点的显式裁决后，`approve` 才能产出 `human_reviewed` 包与 v2 人审收据。Dev staging 继续核对该收据及原机器筛查，不把机器状态改写为通过。
