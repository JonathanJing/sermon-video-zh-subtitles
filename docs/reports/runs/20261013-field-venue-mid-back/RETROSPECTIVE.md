# 复盘：20261013-field-venue-mid-back

数据见同目录 INDEX.md 和 manifest.json。分析与建议见 [基准报告](../../20261013-field-venue-mid-back-benchmark.zh.md)（PR #388）。

## 实际覆盖范围

不属于 L1–L4 生产。只做了 `DEV-FIELD-001`／`FIELD-09` 的离线回放：两段 10/11 主日中后排会场录音（iPhone 内置麦、AirPods，语音备忘录录制），对生产已发布的 `resi-20261011-54475d42` 索引 `ebe4a4f40bf36271` 做滑窗匹配；负样本为同一 Resi 录音审定窗口外的干净音频，以及另外 4 篇已发布索引。复用了已有 Resi 源音频和本机的线上索引快照，没有下载或生成内容。

## 结果和结束信号

`summary.json`：`completed_no_false_match`。生产匹配器的 checkpoint 锁定：iPhone 混合 18/35、左 23/35、右 18/35，AirPods 27/27；3248 次负样本比较 0 命中。查询端变体只是开发集实验。

## 耗时

本机单进程全量运行 351 秒（5 个变体 × 4 路输入 + 负样本），没有等待。上一轮没有可比运行。

## 错误

无运行错误。ffmpeg 无法解码 `.qta` 中的 4 声道 APAC 轨；afconvert 输出的与 AAC 轨结果完全相同，所以 APAC 未纳入比较，报告中已写明。

## 占用资源之后才暴露的错误

无。

## 遗留状态

本机 `artifacts/field-benchmark/20261011-venue-mid-back/` 保留两段录音副本和 `run-v1/report.json`（1.3 MB 逐窗口明细），作为基准的本地输入，不删除。

## 外部可见的变化

没有部署、TestFlight 或受保护分支推送。PR #388（draft，目标 dev）只有清单、脚本、测试和文档。`deviceAppAcceptance=not_run`，`venueAcceptance=not_run`。

## 后续

- 下周在同一座位用两台设备同时录制 3–5 分钟，加录 App 采集路径、近排／远排和负样本，作为保留集：用户在会场执行，跟踪 `FIELD-09`。
- 真机核对 Web／iOS 的输入声道数，并试单声道 profile：`FIELD-04`。
- 版本化的 `cmn` 查询 profile 做保留集 A/B，并补 Swift parity：`FIELD-10`。
