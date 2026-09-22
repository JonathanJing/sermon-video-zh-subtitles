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
