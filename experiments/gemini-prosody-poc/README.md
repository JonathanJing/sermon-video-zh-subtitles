# Gemini 音频断句 POC（Discovery）

目的：同一份去标点英文 ASR，比较纯文字与音频＋文字的句界、重音候选和近似时间；不接入生产字幕或配音。

## 2026-09-17 实测

模型请求及返回均为 `gemini-3.8-flash`。源为公开讲道
[l8ucqF9uA9A](https://www.youtube.com/watch?v=l8ucqF9uA9A)，原时间 A=2820–2880 秒、B=2880–2940 秒；两者处于既有批准讲道窗内。
原始媒体 SHA256：`13a67515a63431c13449b717253abb9dc89a2f9184f95b02b125185ad0572f03`。
文本来自既有 `gpt-transcribe` 固定30秒块，合并为每组60秒。固定块时间可信；没有人工词级/句界标准答案。首尾可能截断句子。

共8次独立 generateContent 请求（temperature=0.2，maxOutputTokens=8192；其他参数使用API默认）。音频以16kHz单声道PCM WAV内联发送。每次请求无历史上下文。

| 条件 | 句段数 | 重音候选数 | 观察 |
|---|---:|---:|---|
| A 纯文字 | 16 | 0 | 无音频时间 |
| A 音频＋文字 | 17 | 13 | 自报 matched；识别末尾截断 |
| B 纯文字 | 10 | 0 | 无音频时间 |
| B 音频＋文字 | 11 | 7 | 自报 matched；识别开头截断 |
| A 音频重复 | 17 | 13 | 句界与首次相同 |
| A 静音＋文字 | 17 | 9 | **失败：自报 matched，虚构降调、停顿、重音** |
| A 音频＋B 文字 | 12 | 0 | 正确报告 mismatch；不输出音频时间 |
| A 静音＋空文字 | 0 | 0 | 自报 mismatch，仍未正确识别 no_speech |

静音文件实测60秒，1,920,000字节PCM全部为零；API usage计入1500 audio tokens，说明请求包含音频，但不证明模型有效使用音频。静音＋文字第一句声称0.68秒结束、完整降调、约0.6秒停顿，这些不可能来自该音轨。

去除强制末尾边界后，文本/音频句界集合 Jaccard：A=0.8235，B=0.9000；这是差异度，不是准确率。A 两次音频的句界 Jaccard=1.0；共同有效句末时间平均相差0.131秒、最大0.340秒，这是重复偏差，不是真实定位误差。仅两个样本、一次重复，无法推广稳定性结论。

所有结果词索引完整覆盖、没有缺词或重叠。通过结构检查不表示声音判断正确。B文字直接讨论“until”的重要性，重音候选可从文字猜出，不能据此证明听出了重音。

结论：可生成待回听的断句/重音候选，并在此样本识别明显音文错配；不能独立作为声学证据、精确字幕对齐或情绪标准。应先加本地静音/VAD及强制对齐，再测“同一文字、不同读法”的受控音频，并由听音人员标注句界/重音，才能评估音频增益。此次未合成音色、未改变配音、未调用视频能力；没有人工听音准确率。

## 运行与复核

本次配置、源文本路径、输入音频、完整prompt、原始响应、usage、模型版本、哈希及HTML回听页位于忽略目录：
`artifacts/gemini-prosody-poc/20260917/`。入口 `review.html`，配置 `config.json`。

```sh
# 本地准备/重新校验已有结果，不会调用API
python3 experiments/gemini-prosody-poc/run.py artifacts/gemini-prosody-poc/20260917/config.json
# 显式运行缺失的case；已完成case校验身份后复用
python3 experiments/gemini-prosody-poc/run.py artifacts/gemini-prosody-poc/20260917/config.json --run
python3 -m unittest discover -s experiments/gemini-prosody-poc -p 'test_*.py'
```

依赖Python标准库、ffmpeg、已解锁的1Password CLI。密钥只从 `Local / Gemini Sermon API Key / credential` 临时读入内存，不保存、不输出。失败或状态不明的调用留下attempt记录，阻止静默重试；已有raw响应但无解析结果时应离线修复，不重新付费。更换来源/裁剪/模型/prompt需使用新运行目录；输入指纹不匹配会拒绝复用。

配置需含 `source_audio`、`source_sha256`、`canonical_url`、`source_id`、`clips`（id/start/duration/text及文本来源）和 `cases`（id/clip/mode，可选text_clip/text_override）。模式text不送音频；audio送真实音频；silence送同长零PCM。去标点使用英文词token，连字符会拆词；本实验不是中文分词方案。

本实验为独立个人项目，不隶属于或获 Mariners Church 背书。所有输出保留为机器候选。
