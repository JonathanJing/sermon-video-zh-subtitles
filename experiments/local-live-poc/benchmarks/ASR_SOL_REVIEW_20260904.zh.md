# ASR Gold 校正：GPT-5.6 Sol 模型仲裁（2026-09-04）

## 结论

本轮审核生成了 **6 条 Sol 模型候选参考文本**：4 条为 `approved_sol_candidate`，2 条因精确词界仍需听审而标记为 `needs_audio_human_review`。

这些结果**不是 human Gold**，不能改写为 `approved_human_gold`，也不能直接通过现有 `validate_human_gold` 门禁。审核过程中没有完成直接音频听辨；判断来自 GPT-transcribe 音频证据、YouTube 自动字幕及相邻片段、原 session 的 `asr.final`/suppression 边界、manifest，以及新增的 `whisper.cpp small.en independent ASR`。后者仍是机器 ASR，而且与实时事件使用同一 small.en 模型家族，不构成人工独立听审。

| Case | Sol 状态 | 置信度 | 关键结论 |
|---|---:|---:|---|
| Ed normal | `approved_sol_candidate` | 0.91 | 去掉 GPT padded 的 `Faith. No, no` 与 `So unity`；session 实际词界为 `No, we're...` 至 `They were still sisters.` |
| Jared long turn | `approved_sol_candidate` | 0.97 | candidate 开头的 `Preserved` 不可信；session 实际带入前段引语，尾部停在 `because I`。 |
| Eric prayer/music | `approved_sol_candidate` | 0.98 | session 确有前段 `On your screen...pray for you`，且没有 candidate 尾部 `I'd love if`；采用 `and worship`、`God used`。 |
| Doug two-speaker | `needs_audio_human_review` | 0.82 | session 确有 `Totally undrinkable...` 前导；`this verse` 与两个 small.en pass 的 `this first` 仍需直接听辨。 |
| Christine accent | `needs_audio_human_review` | 0.87 | 保留 Holy Spirit 整句并恢复 `But we're not`、`piercings, if any`；开头 `Joy / And / 无前导词` 需听辨。 |
| Ed low volume | `approved_sol_candidate` | 0.91 | 与 Ed normal 共用同一音频 reference 判断；单独记录低音量下的 filler、`their` 等遗漏。 |

## Sol 候选参考下的临时 WER

这批 hypothesis 来自历史 `whisper.cpp small.en` acoustic E2E 队列，不是 Qwen3-ASR 的新跑分。按现有 scorer 的英文分词与 Levenshtein 规则，以本轮 `proposedReferenceText` 作为**仅供诊断的 Sol candidate** 计算，micro-average provisional WER 为 **4.83%**（30 edits / 621 reference words）。

| Case | Sol 状态 | 临时 WER |
|---|---|---:|
| Ed normal | `approved_sol_candidate` | 7.46% |
| Jared long turn | `approved_sol_candidate` | 0.59% |
| Eric prayer/music | `approved_sol_candidate` | 1.11% |
| Doug two-speaker | `needs_audio_human_review` | 2.60% |
| Christine accent | `needs_audio_human_review` | 7.95% |
| Ed low volume | `approved_sol_candidate` | 13.43% |

该数字不能作为正式 Gold WER：Doug 与 Christine 仍有未解决词界，Ed 也建议抽听 fillers；人工完成 Gold 后必须重新运行正式 scorer。它目前只用于定位错误分布，以及比较 normal / low-volume 两次 Ed 录音。

## 仲裁原则与 provenance

1. **评分参考应匹配实际 session 捕获的语音，而不只是配置中的 YouTube target 时间窗。** Eric、Doug、Jared 的 session 明确含有 target 之前的语音；若仍用 target-only candidate，会把正确识别的前导内容错误计成 insertion。
2. **GPT-transcribe candidate 来自带边缘 padding 的 source-audio audit。** 因此 Ed 的 `Faith. No, no` / `So unity`、Christine 的 `Joy` / 下一段尾词、Jared 的尾部补全，都不能不经边界核对就视为 session Gold。
3. **YouTube reference 是自动字幕，不是人工逐词稿。** 它适合提供相邻片段、专有词和语义证据，但其重复词、拼写和精确切点仍可能错误。
4. **`whisper.cpp small.en independent ASR` 是独立运行的机器转写，不是独立模型，也不是人工听审。** 它能验证 session 里是否存在前导/尾部内容，但不能单独决定 Christine 被它漏掉的 Holy Spirit 句，或 Doug 的 `verse / first`。
5. **非语音标记不进入 proposedReferenceText。** `[BLANK_AUDIO]`、`[music]`、`[laughter]` 作为事件或环境证据保留，不当作口语词计分。

## 逐 case 审核

### 1. Ed Stetzer：normal 与 low-volume

两次运行使用同一源片段，所以 `proposedReferenceText` 完全相同；音量变化只影响 hypothesis 的错误类型。

- 共同边界：两次 session 的机器转写都从 `No, we're of one faith` 开始，到 `They were still sisters` 结束。
- source target 本身从 `We're of one faith` 开始；前一段以 `No. No.` 结束，后一段从 `So, unity...` 开始。因此 candidate 的首尾属于 padded context，不应全部进入 session reference。
- normal 主要错误：`over all → overall`、在 `any more` 前插入 `and`、`daughters' → daughter's`，以及重复 `or`。
- low-volume 额外漏掉两个 `you know`、`their`，并出现 `as... followers` 的分段显示痕迹。
- 仍建议人工抽听 fillers 与 `daughters'`，但现有多源证据足以形成高置信 Sol candidate。

### 2. Jared Kirkwood：长句与经文

- 首个 0–12 秒事件被 suppression 标为 `[BLANK_AUDIO]`；实际语音从 12.7 秒后开始。
- 首个 final 和 whole-session independent ASR 都含有前段引语 `I have said in my heart. I saw. I observed.`；candidate 的 `Preserved` 没有其他证据支持。
- 最后一个 final 与 independent ASR 都停在 `because I`，所以不能把 candidate 的 `didn't know what it was` 当作这次 session 已捕获文本。
- 主体的 `verse 9`、`Solomon`、`Ecclesiastes 12`、`cattle prod` 均保留。可见的小错主要是 `behind-the-scenes` 被写作 `behind the scene's`。

### 3. Eric Geiger：祷告与音乐过渡

- 两个开头 blank suppression 后，session 的第一段语音来自前一 source segment：`On your screen...they will pray for you.`
- session 在 `right where you are` 后停止，没有 candidate 的下一段开头 `I'd love if`。
- `presence and worship` 同时得到 YouTube、event final 和 independent ASR 支持；`presence in worship` 只出现在 GPT-transcribe。
- `God used` 得到 GPT-transcribe 与 independent ASR 支持；实时 hypothesis 的 `God use` 记为 tense substitution。
- `[music]` 不作为口语 reference。

### 4. Doug Fields：双讲员切换

- session 的首个 final 和 independent ASR 都确认实际捕获了前一段的 `Totally undrinkable...`，随后才是短问句 `What do you think?` 和 Doug 的回答。
- YouTube 相邻字幕与语义支持 `this verse`；两个 session small.en pass 都写成 `this first`。因为两者是同一模型家族，不能把一致性误当作人工确认。
- YouTube 中的 `I I`、`my to my` 等重复词可能是真实 disfluency，也可能是自动字幕重复；本轮采用较干净的 GPT/session 文本，但保持 `needs_audio_human_review`。

### 5. Christine Caine：口音与身体术语

- Holy Spirit 整句必须保留：YouTube target、GPT-transcribe、实时 chunk event 都包含它。whole-session independent ASR 漏掉此句，是机器 omission，不是删句依据。
- 实时 hypothesis 从 `supposed to idolise the temple` 开始，漏掉 `But we're not`，会局部反转含义，属于 major ASR error。
- `pins should I get? things, if any` 是跨 chunk 破坏；多源证据支持 `piercings, if any`。
- session 在 `morning` 后结束；candidate 的 `or how many times should we` 属于下一段/padding，不纳入。
- 开头究竟是上一句尾词 `Joy` 被捕获、target 的 `And`，还是直接从 `You` 开始，仍需直接听辨，因此保持 `needs_audio_human_review`。

## 后续人工 Gold 门禁

若要产出可正式计算 WER 的 human Gold，人工审核者至少应直接听辨：

- Doug：约 6.9–12.1 秒的 `this verse / this first`，以及重复词是否真实存在；
- Christine：约 7.7 秒起的首词边界 `Joy / And / You`；
- Ed：两个音量版本中 `you know` fillers 与 `daughters'` 的精确词形（建议抽听确认）。

人工完成后，应另建或填写 `asr-human-gold-review-v1` 文件，由真实 reviewer 填写 `correctedReferenceText`、`reviewer`、`reviewedAt` 并明确设为 `approved_human_gold`。本次 Sol 输出应继续作为审计证据保留，不能就地改名冒充人工结果。
