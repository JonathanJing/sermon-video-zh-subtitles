# Clip timeline map v3：批准窗口派生音频

v1 与 v2 的格式和校验语义保持不变。完整媒体仍可用 v2；旧的提取片段仍按 v1 校验。新增 v3 专用于：Layer 1 保留完整原始媒体身份和绝对批准窗口，Layer 3 使用按该窗口抽取的独立音频片段。

## v3 绑定

v3 同时绑定：

- English Source Package 中的完整媒体 SHA-256、字节数和时长，并在准备与复验时对 `sourceMedia.path` 重新计算哈希；
- source package 内绑定的人工批准窗口收据，包括其文件哈希、规范 JSON 哈希、source ID 和绝对起止时间；
- `clip_and_normalize` extraction cache 的文件/JSON 哈希。校验器检查该记录中的源 SHA、大小、绝对起止时间和音频输出配置；原修改时间保留在不可变记录中，跨主机复制后不要求文件 mtime 相等；
- 派生 clip 的文件 SHA-256、字节数，以及通过 `ffprobe` 重新读取的 AAC stream、container 时长和解码采样数；
- 锚点坐标原点 `derived_clip_zero_equals_approved_window_start`。因此 `anchorOffsetSeconds` 固定为 0，锚点仍以剪出的片段为坐标系；其推导出的绝对源起点必须等于批准窗口的 start。

每个 English anchor unit 必须按顺序落在 `[0, approvedWindowSeconds]` 内。校验器不会把第一句或最后一句推到边界，所以锚点前后的真实静音仍保留。计划的批准窗口时长与解码音频实测时长分开记录；实际音频时长用于后续音频调度。

## AAC 时长规则

AAC 文件的 container/stream 时长可能包含 packetization padding。v3 固定要求 AAC、44.1 kHz、单声道，并读取解码帧的 `nb_samples` 总数作为实际音频时长。它将 container 时长换算的采样数与解码采样数之差记录为 `containerPaddingSamples`，并限定在四个 AAC frame（`4 × 1024 = 4096` samples）以内。这是有界 codec-specific 预算，不是一般时间容差。解码采样数必须在批准窗口长度换算出的采样数 ±1 sample 内；anchor unit 本身必须严格位于窗口长度内。

当前 `source_clip.m4a` 实测：窗口 2015.321–3957.444（1942.123 秒）；AAC 解码为 85,647,625 samples，即 1942.123016 秒；format 时长为 1942.200023 秒，rounded container/decoded 差值 3396 samples，低于 4096 sample 预算。`clipDurationSeconds` 记录解码时长，`approvedWindowSeconds` 独立记录 1942.123。

## 跨主机解码器核验

同一媒体哈希不代表所有解码器都会报告相同的末帧采样数。本次 `source_clip.m4a` 在 FFmpeg 6.1.1 中实际输出 85,648,384 个 PCM samples；FFmpeg 9.0.1 输出 85,647,625 个，后者与不可变 map 一致。差值是 AAC 末包的 759 个 discard-padding samples（约 17.21 ms）。两边末包 duration 都为 265，但旧版本输出整帧 1024 samples；这不是 container 时长的浮点舍入差异。

遇到这种差异时，保留旧失败记录、原媒体、批准窗口、map 和 ±1 sample 门槛。固定兼容解码器后，同时复核 `ffprobe` 帧采样总数和真实单声道 PCM 解码字节数；16-bit PCM 的 samples 数等于字节数除以 2。只有二者相等，并且符合原窗口门槛，才通过该主机的时间线检查。不能减去一个经验常数或修改 map 来迁就旧解码器。

本次在独立目录使用 [FFmpeg 官方源码及发布验签流程](https://ffmpeg.org/download.html) 构建了 ARM Linux 9.0.1，保存源码、签名校验、配置和二进制 SHA。正式容器只将独立的 `ffprobe` 目录放入 PATH；最小诊断 `ffmpeg` 仅通过绝对路径作 PCM 核验，未替换生产工具。若采用这种拆分，正式渲染仍须核验其实际 `ffmpeg` 支持所需编码器（本任务使用 `libmp3lame`）。源包／时间线预检通过仅证明这两个输入，不能替代真实 candidate、人工收据、voice authorization 和 speech job 的完整 `checked_context`。

## 准备 v3 map

向原 CLI 增加两个参数会选择 v3；需要一并提供真实完整源媒体和 `clip_and_normalize` receipt：

```sh
python scripts/clip_timeline_map.py \
  --source path/to/english-source-package.json \
  --anchor path/to/anchor-manifest.json \
  --clip-media path/to/source_clip.m4a \
  --source-media path/to/service.mp4 \
  --extraction-receipt path/to/source_clip.m4a.cache.json \
  --out path/to/clip-timeline-map-v3.json
```

v3 map 是不可变证据。源媒体、批准窗口、receipt 或 clip 内容改变时，应准备新 map；不能改写批准、源身份、anchor 或 clip 时长来迁就映射。v1/v2 调用方式和校验路径保持原样。
