# Layer 3 正式音频包构建器（合成夹具验证）

入口：`scripts/build_target_language_audio_package.py`。输入为已人工批准的 Layer 2 candidate、原 Layer 1 source/anchor、冻结的目标语言 policy 与独立人审收据、Speaker Registry、由 `prepare_target_language_speech_job.py` 创建的 verified v2 job/adapter 与片段范围 voice 收据，以及独立 renderer 写出的 `render-manifest.json`。构建器不合成、剪辑、加速或改写文字；产出最高状态为 `machine_screened`，`humanReview` 保持 pending。

```bash
.venv/bin/python scripts/build_target_language_audio_package.py \
  --source english-source-package.json --anchor anchor-manifest.json \
  --candidate target-language-candidate.json --job job.json \
  --adapter speech-adapter.json --policy target-language-policy.json \
  --human-review-receipt human-review-receipt.json \
  --speaker-registry speaker-voice-registry.json \
  --clip-voice-authorization clip-voice-authorization.json \
  --clip-voice-capability clip-voice-capability.json \
  --clip-timeline-map clip-timeline-map.json \
  --render-manifest render-manifest.json \
  --artifact-root render-output --out target-language-audio-package.json
```

`render-manifest.json` 必须绑定 `englishSourcePackageJsonSha256`、`targetLanguageCandidateJsonSha256`、`targetLanguageSpeechJobJsonSha256`、`clipTimelineMapJsonSha256`、`targetLocale` 和 voice 的 provider/model/revision/voice/speakerId/checkpoint，均须与 Registry 验证后的 adapter 一致。`voiceAuthorization` 指向带文件及规范 JSON hash 的 `sermon-clip-user-rights-attestation-v1` 用户声明。先用 `scripts/prepare_clip_voice_authorization.py` 为一个 candidate 和 locale 派生 `sermon-clip-voice-authorization-v1` 收据。韩语与西语还须用 `scripts/prepare_clip_voice_capability.py` 把短样音、长句探针的人审收据和两个音频 hash 绑定到 L1/locale/checkpoint；此凭据只允许该片段的能力准入，不将 Registry 的 `unverified_poc` 状态提升为全局通过。以 `prepare_target_language_speech_job.py --clip-voice-authorization --clip-voice-capability --clip-timeline-map` 建立 v2 job，job inputs 锁定三份收据。已有全局中文人审能力的 adapter 可不传 `--clip-voice-capability`。Registry 的全局 `multilingual_dubbing` 用途保持原样。经文许可文件与署名条款属于 Layer 2/4 的独立门禁，不由音色收据替代。

每个 `units[]` 按 speech job 顺序列 `textGroupId`、UTF-8 `targetTextSha256`、`audio` 文件 hash、实测 `durationSeconds`，以及现有 `sermon-target-language-audio-unit-receipt-v1` JSON 收据。单元收据由 `validate_target_language_audio_unit.py` 绑定 v2 job、locale、group、文字和音频 hash；音色、checkpoint 与授权由 job inputs 锁定。构建器重新运行 `ffprobe` 和 `ffmpeg -xerror`，完整解码每个单元及音轨。

`scripts/clip_timeline_map.py` 要求显式 `--anchor-offset-seconds`，以 L1/anchor/clip/人工窗口证据 hash 校验源锚到片段媒体的时间映射。2026-09-20 片段的已审锚点为证道相对 320.16–498.32 秒，片段视频为 0–178.16 秒，map 显式记录 320.16 秒 offset；构建器只在验证该 map 后换算。`schedule` 为 JSON：`targetLocale`、`timingKind=measured_target_audio`、`status=pass`、`issues=[]`、实测 `trackDurationSeconds`、`policy` 中的 `reactionLagSeconds` / `interUtteranceGapSeconds` / `maxEndLagSeconds`，以及按组排列的 `entries:[{textGroupId,sourceUnitIds,plannedStart,plannedEnd}]`。每组从首个英文源单元的片段相对起点加反应延迟起播，仍须等待前组结束和间隔；`maxEndLagSeconds` 则相对该组最后一个英文源单元的终点检查尾延迟。构建器从实测单元时长重算排程，拒绝溢出、顺序错误、超出音轨或 1 倍速片段边界；最后一个源单元的英文终点不得误作配音最早起点。`captions` 为 JSON `cues:[{textGroupId,text,start,end}]`，文字必须等于 Layer 2 `targetText`，时间需与 schedule 一致。track、schedule、captions 均须在 `languages/<locale>/` 目录。

`scripts/screen_target_language_audio_units.py` 对 renderer 原 manifest 中的每个单元做目标语言 ASR 回转录，复核 job／文字／音频哈希，并把相似度、差异与需复核单元写入独立 `sermon-target-language-audio-screening-v1` 收据和新的 screened manifest；原 manifest 不被改写。低于固定阈值的单元保持 `requires_review`，简短单元要求规范化文本完全一致。若 `machineScreening.status=pass`，构建器重算每组识别文本的相似度，要求收据按顺序覆盖全部 group ID、文字和音频 hash、同一个 job 和 locale。机器筛查通过不会产生人工全文听审结论。正式完成还需三语真实 renderer、自然音轨与视频 1 倍速人工审核，再据审核收据推进 `human_reviewed`。本构建器未生成 `audio_unavailable` 包，也未实现人工审核状态推进。

## 已批准源窗口与单次人工例外

`sermon-source-voice-authorization-v2` 与 `sermon-source-user-voice-attestation-v2` 用于母版中已人工批准的证道窗口，仅授权该源、该窗口及指定语言的正式音频生产。`sermon-clip-timeline-map-v3` 同时绑定母版、窗口批准、抽取收据与实际片段；v1/v2 历史文件不改写，新输入须重新绑定其文件与规范 JSON hash。

`--anchor-exception-receipt` 接收独立的 `sermon-human-anchor-exception-receipt-v1`。它仅允许本次中文、唯一 `0-s202` 的完整经文 9.199951 秒锚点，在源文件和锚点 hashes 均未改变且用户明确授权时继续构包。原问题、上游包及其 hashes 保留；输出包旁的 `.anchor-exception.json` 绑定最终音频包与人工例外，不将问题改写为机器通过。

`review_target_language_audio.py approve --publication-exception <receipt>` 保留 v3 中文例外合同，并新增 v4 多语言例外合同。v3 仍只接受精确绑定的中文音轨；v4 每张收据只绑定一个 `zh-Hans`、`ko` 或 `es` locale，以及该 locale 的源包、候选译文、审核音频包和音轨 hash。两者都要求用户明确接受先发布且视频同步尚未单独验收，输出 `videoSync1x=not_run`、`checks.synchronization=not_run`，保留完整播放、人审及全部 ASR 复核项决定。没有例外收据时仍按 v2 合同要求 1 倍速视频同步批准。发布例外不证明设备、视频同步或现场验收。

完整经文锚点例外 v1 保持中文专用。新增 v2 只覆盖同一个 `0-s202` 完整经文句及其单一 `clause_unit_exceeds_target_without_safe_boundary` 问题；按 locale 分别绑定英语源包、锚点清单和候选译文的文件及规范 JSON hash。它不替其他锚点问题或其他 locale 生成批准，也不改变 ASR 和完整音频审核门槛。
