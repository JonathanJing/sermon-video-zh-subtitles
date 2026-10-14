# 复盘：20261012-weekly-clip-refused-attempts

数据见同目录 INDEX.md 和 manifest.json。这是同一次上周片段彩排的两次被拒尝试，完整复盘在 `docs/reports/runs/20261012-weekly-clip-rehearsal-u216/`。

## 结果和结束信号

- `clip-20261012T045611Z`：构建时拒绝。剪片用的视频不是英文源包绑定的媒体（源包绑定的是同一录音的 `audio-clean.flac`）。改为 clip spec 同时写明视频哈希与源包媒体，并要求两者时长相差不超过 0.1 秒。
- `clip-20261012T045656Z`：资产已上传 Dev，overlay 拒绝「Default or existing page changed」：v3 人工投影把默认页挪到了日期最新的测试页。PR #351 修正。

## 遗留状态

第二次尝试上传的 `/media/mockup-dev-clip-clip-20261012T045656Z/` 及其 release 文件留在 Dev，无人引用。
