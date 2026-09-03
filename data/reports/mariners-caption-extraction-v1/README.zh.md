# Mariners 主证道英文字幕提取结果

- 最终审计：**通过**
- 主证道 VOD 库存：190 条
- YouTube 自动英文字幕已验证：180/180 条
- 无英文字幕、待单独授权 ASR：10 条
- 下载阶段失败：0 条
- 音视频文件：0 个
- 规范化时间轴：149,570 条 cue
- 规范化文本：5,411,630 字符
- 对应视频总时长：112.84 小时
- 语料目录大小：157.3 MiB
- 时间轴覆盖率：最小 0.9660，中位数 1.0007

## 数据边界

这些文本来自 YouTube 自动英文字幕，状态统一为 `unreviewed_raw`，不能直接当作 Gold 训练标签。当前保留完整 VOD 时间轴，开场通知、主持和结束段落可能仍在；本阶段没有切证道边界，也没有翻译。

10 条待 ASR 项目仅保存公开视频元数据。本阶段没有下载其音频或视频；后续需用户另行授权媒体下载和 ASR。

## 主要产物

- `final-verification.json`：全量集合、哈希、结构、去重和批次收据审计
- `pending-asr.jsonl`：10 条无英文字幕视频的待授权队列
- `data/raw/mariners-sermon-captions-v1/<video-id>/source/*.vtt`：原始 `en-orig` VTT
- `data/raw/mariners-sermon-captions-v1/<video-id>/normalized/*.jsonl`：原始及去滚动重复时间轴
- `data/raw/mariners-sermon-captions-v1/<video-id>/normalized/*.txt`：规范化英文文本

生成时间：2026-09-03T02:46:44.427996Z
