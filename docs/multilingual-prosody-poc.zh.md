# 多语言配音语速与停顿最小 POC

状态：2026-09-22 已完成韩语第一轮与同模型 pace-instruct 对照；产物是 Layer 3 shadow POC，未人工听审、不可发布。

## 决策

第一轮不引入新模型。复用现有 Eric Geiger `Qwen3-TTS-12Hz-1.7B-Base` 单讲员 SFT checkpoint、韩语 Layer 2 候选和 Layer 1 六个 source units，只增加：

1. 每个 source unit 独立生成一条自然语速 WAV；
2. 按 Layer 1 的真实句间停顿确定性插入静音；
3. 记录每句实测语音时长、句尾累计偏差和完整解码；
4. 对超出 `±0.4s` 的单元使用同一 Qwen 模型的 pace instruct 生成第二候选。

脚本为 [`run_multilingual_prosody_poc.py`](../scripts/run_multilingual_prosody_poc.py)。它不修改 Layer 1/2 冻结接口，不做时间拉伸，也不把机器审核译文升级为人工批准。

## 实测结果

英文六句窗口为 `40.880001s`；其中真实句间停顿依次为 `0.66 / 2.01 / 2.270001 / 0 / 1.450001s`，末句后的 `24.399999s` 不进入片段装配。

| 候选 | 模型变化 | 音轨时长 | 最大单句时长偏差 | 最终句尾偏差 | 结论 |
|---|---|---:|---:|---:|---|
| 原多语言 demo | 无 | `28.96s` | 未实测逐句 | 不适用 | 整段生成，字幕只是按字数估算 |
| unit + source pauses | 无 | `35.83s` | `2.959999s` | `-5.050001s` | 停顿可精确复用，局部语速不匹配 |
| unit + source pauses + pace instruct | 无 | `35.59s` | `2.16s` | `-5.290001s` | 指令有方向性作用，但不是时长控制 |

同模型 pace instruct 将第一句从 `8.64s` 调整到 `7.36s`，接近英文 `7.32s`；第五句从 `7.68s` 增至 `8.48s`，仍短于英文 `10.639999s`；第六句从 `3.44s` 增至 `3.52s`，仍短于英文 `5.68s`。因此当前 Qwen checkpoint 可以粗调语速，但一次自然语言指令不能保证所有句子进入 `±0.4s` 时间槽。

两条候选均使用固定 checkpoint hash、seed `42`、`natural_no_time_stretch`，完成 PCM WAV 全文件读取验证。ASR 复筛和韩语母语人耳听审尚未执行，不能据此判断发音、强调或自然度更好。

## 下一步的最小添加

继续复用现有模型，不立即引入新的 expressive/duration-conditioned TTS：

1. 只对超时单元生成 `fast / neutral / slow / very_slow` 小型候选梯度；
2. 以实测时长选择最接近 source slot 的候选，不改变文本、不裁切、不拉伸；
3. 为强调词加入独立 instruct 候选，但与语速候选分开比较；
4. 完成 Qwen3-ASR 文本筛查和韩语母语盲听；
5. 如果候选梯度仍不能让关键单元进入时长门线，或强调不稳定，再对照一个支持 duration/prosody conditioning 的新 adapter。

引入新模型的触发条件不是“总时长不完全相等”，而是：同一文本、同一音色 checkpoint、多个 pace instruct 候选仍无法满足单元时长和母语自然度门线。

## 第二轮：句内强调与停顿

第二轮继续复用同一个 Eric Qwen checkpoint，选择中文末句“而他的吼声压倒了撒但的吼声。”做焦点实验。对应英文 Layer 1 词时间轴在 `roar → overwhelms` 间有约 `1.20s` 停顿，在 `overwhelms → Satan's` 间有约 `0.61s` 停顿。

固定比较三条焦点音频：

1. 现有句级 pace-instruct 音频，作为基线；
2. 整句只调用一次 Qwen，用自然语言要求重读“吼声／压倒了／撒但”并在指定短语后停顿；
3. 将不变的中文句子切成三个短语分别生成，确定性插入 Layer 1 的两段句内静音。

[`run_internal_prosody_poc.py`](../scripts/run_internal_prosody_poc.py) 将实验配置绑定到基线 plan 和 Layer 1 anchor 的 canonical hash，检查英文词覆盖完整且有序，并要求三个中文短语无损拼回原句。整句指令是否真正落在目标词上、短语拼接是否自然，都必须通过人耳判断；完整解码、时长或 ASR 一致不能代替这一步。

首轮实测：上一轮句级基线为 `3.20s`；整句句内指令候选为 `3.12s`，仅从总时长不能看到要求的两段长停顿已稳定实现；短语装配候选为 `6.13s`，相对英文 `5.68s` 晚 `0.45s`，并确定性保留 `1.20s / 0.61s` 两段停顿。三条 MP3 均已完整解码，重音位置与短语拼接自然度仍为 `humanListeningStatus=pending`。

### 锚点驱动的动态停顿

Layer 3 不应机械复制英文静音长度。它先测量目标语言短语音频，再以**下一英文短语开始时间**为锚点补静音：`pauseBefore = max(0, sourcePhraseStart - currentTargetCursor)`。如果目标语音已经越过锚点，只记录 overrun 并进入语速候选／译文／重分段修复，绝不使用负停顿、裁切或时间拉伸。

[`assemble_adaptive_phrase_audio.py`](../scripts/assemble_adaptive_phrase_audio.py) 对当前末句复用同一组三段中文语音，动态插入 `0.70s / 0.94s`，使第二、第三短语分别从 `2.30s / 4.28s` 的英文锚点开始；最大短语起点误差为 `0.000001s`（采样舍入），无短语越界。成品为 `5.96s`，相对英文句尾晚 `0.28s`。

Layer 4 只公开完整中文句子和整句时间范围；内部三段短语、锚点和动态静音保留在发布包的 `internalSchedule` 证据中，不把工程分段显示成三条用户字幕。该候选仍是 Dev POC，完整解码与 HTTP 可取不等于人耳审核通过。

### 六句长样本

长样本把同一机制扩展到完整的六句、`40.880001s` 英文窗口。配置文件 [`2026-09-20-zh-Hans-long.json`](../experiments/multilingual-prosody-poc/2026-09-20-zh-Hans-long.json) 将六个完整中文译句无损映射为 18 个内部短语；[`prepare_longform_adaptive_prosody_poc.py`](../scripts/prepare_longform_adaptive_prosody_poc.py) 验证每句英文词 ID 完整、有序覆盖，且短语重新拼接后与 Layer 2 候选逐字一致。

实测成品为 `41.08s`，相对英文窗口最终晚 `0.199999s`。其中 7 个短语因自然语音超过下一英文锚点而记录 overrun，最大短语起点偏差为 `0.850001s`；调度器没有压速、裁切或删除文字，并在后续有余量的锚点重新对齐。此样本的用途是校对跨多句的停顿、拼接、重音和 App 字幕行为，不代表已经达到正式 Layer 3 门线。

Layer 4 的 `long-adaptive-pauses` 版本只提供六条完整句子 cue，内部 18 个短语只作为 `internalSchedule` 指标。WAV 与 Dev MP3 均完成全文件解码；中文母语人耳试听仍为 `pending`，因此 `humanApproval=false`、`productionEligible=false`。

### 纠正：原声停顿先由 Layer 1 提供

上面的 18 短语版本暴露了错误的层级责任：Layer 3 把每个预设短语的英文词起点当成补静音目标，连没有真实停顿的词边界也被切开；中文读得较短时还会为追时间轴补出过长的静音。`long-adaptive-pauses` 现在保留为旧版对照，Dev 默认改为 `source-acoustic-pauses`。

新的 [`extract_english_pause_evidence_poc.py`](../scripts/extract_english_pause_evidence_poc.py) 只读取英文原声和冻结的 Layer 1 词时间轴，输出独立的 [英文声学停顿证据](../experiments/multilingual-prosody-poc/2026-09-20-en-acoustic-pause-evidence.json)。它分别记录词对齐空档与原声低能量区间；只在两者重合时标为 `supported_pause_candidate`，单靠词间距不能通过。这是 Layer 1 的 shadow 侧车文件，不修改已冻结的正式包或把机器候选写成人工确认。

新的 [中文短语配置](../experiments/multilingual-prosody-poc/2026-09-20-zh-Hans-acoustic.json) 绑定声学证据 hash；Layer 3 准备器仅接受有 Layer 1 声学候选的句内边界，因此六句由 18 个降为 15 个合成单元，其中 9 个是句内停顿。Layer 3 生成目标语音后，按该边界的原声停顿长度限制插入静音；目标语音越过锚点时仍保留最多 `0.2s` 的可听停顿，并如实记录时间偏差。句间若只有对齐空档、声学低能量被背景声掩盖，POC 保留该句间空档为待听审候选，不能把它说成已由声学检测确认。

最终候选 `40.67s`，相对英文窗口早 `0.210001s`；有 1 个短语越过锚点，最大局部起点偏差 `0.970001s`。第一句复用了同一模型已经验证有方向性作用的慢速指令，使句间不再因为它读得过短而补出额外静音。最终总时长接近不代表逐句同步合格。Layer 1 声学侧车文件还有 2 处对齐与声学冲突，需听原声确认边界；中文合成语义、音色和接缝也仍待人工听审。Dev MP3 完整解码通过，本候选的 ASR 复筛尚未运行。正式生产还需要把审核后的英文语气、停顿和词边界纳入版本化 Layer 1 合同，再由 Layer 3 消费相应 hash。

### 听审反馈：总时长不能替代中文自然度

2026-09-22 用户听 `40.67s` 版后指出：句内语速变化和中文词组接缝不舒服。这是明确的自然度负反馈；不是正式盲听结果，也不代表其它候选已通过。原版保留为问题对照，不再作为 Dev 默认音频，已经打开过它的浏览器也迁移到 `source-pauses`。新的默认是**已有** `30.43s` 整句自然语速对照：每句只合成一次，不在中文句内拼接；没有重新训练或生成音色。它短于英文 `40.880001s` 窗口约 `10.45s`，所以只用于隔离“句内拼接”变量，不是同步达标版本。

层级修正：Layer 1 输出讲员英文原声的停顿位置、长度、词时间轴及置信度；这些是源语事实，不直接命令中文在哪里切开。Layer 3 须先判断英文停顿在中文是否存在**完整、自然的语义边界**，再决定保留、迁移到邻近中文标点或省略。比如 `You have / an enemy` 不应强制切成 `你有一个 / 仇敌`，`Who's seeking / to destroy you` 不应切成 `正伺机 / 毁灭你`。若只能靠独立生成半句和补静音来追总时长，应记录 `naturalness_failed`，而不是用全片时长合格掩盖接缝。

下一轮要从完整句子或自然分句语音出发，在完整语流中评估原声停顿的可迁移性；关键门线是中文母语盲听的语气/接缝自然度、文本完整性和局部时间偏差，三者分别报告。若同一 Qwen checkpoint 的整句指令无法稳定控制句内停顿，才对照支持显式韵律/时长条件的新模型；不能重新引入逐词组独立合成作为默认路径。

本周新建的中文周更配音 job 已把上述**已选的合成切分方式**固化为 `complete_chinese_sentence_natural_pace_v1`，见[周末生产 Runbook](codex-local-production-runbook.zh.md)。它只调整新 job 的 Layer 3 legacy 中文 TTS 单元及校验，不会修改此前 POC 音频、旧 job、Layer 1 英文锚点或 Layer 2 译文，也没有绕过后续同步和人耳审核。
