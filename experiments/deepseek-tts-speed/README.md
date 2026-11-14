# DeepSeek 云 TTS 速度对照（Discovery）

目的：用我们自己的分句产物（`speech.jsonl` 的逐句中文单元）实测 DeepSeek 云 TTS 的生成速度、成本和时长，并与我们生产上的 Spark/Qwen3-TTS 配音比较。**实验性质**，没有人工听审，不签发、不替换讲员声音、不改 L3 政策。

报告：[DeepSeek 云 TTS 与我们 Spark 配音的速度对照](../../docs/deepseek-tts-speed-ab-20261114.zh.md)。

## 文件

| 文件 | 作用 |
|---|---|
| `bench_deepseek_tts.py synth` | 每单元一次 `POST /v1/tools/tts`；记 `timing.jsonl`（首字节、整句延迟、音频时长、重试）与 `summary.json`（RTF、分位、成本） |
| `bench_deepseek_tts.py stats` | 从一个 `timing.jsonl` 汇总速度与成本 |
| `bench_deepseek_tts.py compare` | 与同批单元的 Spark `tts-log.jsonl` 对照时长 |
| `bench_deepseek_tts.py assemble` | 按单元顺序拼接 WAV（固定 gap），写试听轨与时间轴 |
| `bench_deepseek_tts.py ab` | 同句 Spark → DeepSeek 交叉试听轨 |

## 必须知道的边界

- 服务返回的 WAV 头 data 长度是占位值（`0xFFFFFFFF`），脚本落盘前回填，否则合并与播放会读成未知长度。
- 端点没有语言参数、没有语速控制、不支持中断续传；一次请求最多 10,000 计费字符、30 分钟音频，账户最多 50 并发。
- 每请求约 1.1 秒固定开销，短句按请求数计时而不是按字数。
- 配对对象是历史生产 run 的 `tts-log.jsonl`，不是同分钟复跑；Spark 数字不含模型下载和冷启动。
- 只做速度与时长测量。音频是否可发布必须走人工整轨听审，机器检查不能代替。
