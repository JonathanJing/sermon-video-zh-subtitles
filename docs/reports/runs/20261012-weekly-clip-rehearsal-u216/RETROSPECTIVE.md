# 复盘：20261012-weekly-clip-rehearsal-u216

数据见同目录 INDEX.md 和 manifest.json。首次用上周（2026-10-11 `resi-20261011-54475d42`）自己的片段做周六彩排，在 dev（de929581）加 PR #351 的代码上跑，零模型 API，审核为模拟。此前两次被拒的尝试见 `docs/reports/runs/20261012-weekly-clip-refused-attempts/`。

## 实际覆盖范围

第 216–241 句（26 个英文单元，每语 26 组，约 130 秒），含「chapter eight」两处章节引用、哈巴谷书引用、几段经文朗读和一段约 9 秒的静默。源视频按批准窗口起点 1749 s 加片段偏移剪下；片段音频与英文源包的 `audio-clean.flac` 在该偏移处互相关，延迟 0 ms、峰值 1.0。译文、单句音频沿用本周已发布的 c5 包，不生成新内容；L4 发到 Dev 隔离页并做三语浏览器冒烟。不证明翻译或配音质量，设备播放与现场验收 `not_run`。

## 结果和结束信号

通过。Dev 隔离页 `mockup-dev-clip-20261012T050250Z-u216` 三语冒烟通过（`--no-session`，Dev 反馈功能关闭），Dev v3 默认页仍是 `resi-20261004-69ba7a66`。另外两次脚本本地预检：带 `CLIP_SPEC` 与 `BASELINE_CACHE` 通过；不带缓存停在 baseline（Dev 09-27 整场视频下载约 560 MB 处被截断，第三次复现）。

## 耗时

build-inputs 18 s（含剪片与三语拼轨）、baseline 7 s（缓存）、preflight 2 s；发布 63 s 后因回读 404 停下，续跑 100 s 完成。

## 错误

1. **测试页成了默认页（前一次尝试）。** Dev 的 v4 默认页是机器质检页，v3 人工投影把默认页挪到日期最新的人工页；日期为 10-11 的片段页正是最新的，overlay 拒绝。PR #351 修正：投影选默认页时跳过模拟、诊断页；overlay 标记测试页后恢复原默认页。
2. **发布后立即回读 404。** 资产刚上传，refresh-baseline 取新文件拿到 404，是 CDN 传播延迟；失败阶段留下的半成品目录要先移走才能续跑（本次移到 `live-baseline-partial-404`）。
3. **代码变更后不能续跑同一运行目录**，已上传的同名源视频也不能覆盖，所以换了新 run ID。

## 占用资源之后才暴露的错误

错误 1 本可在 release-plan 阶段发现：那里只检查 v3 合并，没有模拟 seal 时的 v4→v3 投影。错误 2 可以给 refresh-baseline 和回读加有限次等待重试。

## 遗留状态

Dev 上 `/media/mockup-dev-clip-clip-20261012T045656Z/` 及其 release 文件来自被拒的尝试，无人引用。

## 外部可见的变化

Dev Hosting 新增隔离测试页 `mockup-dev-clip-20261012T050250Z-u216`。生产、TestFlight 未改动。

## 后续

- PR #351 合并后，周六彩排一条命令：`CLIP_SPEC=… BASELINE_CACHE=… scripts/run_dev_180s_beta_e2e.sh --execute`。
- refresh-baseline 与发布回读加等待重试；release-plan 阶段同时检查 v4→v3 投影的默认页。
- 本次只覆盖 L4。真模型片段测试（Layer 2、文字质检、Spark 配音与回转写、音频质检）另行进行。
