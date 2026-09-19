# 配音与 PDF 并发的证据边界

配音可在阅读稿和大纲均审核完成后，与两份 PDF 的渲染重叠。大纲仍提供已核对的讲员、周次与术语证据；本次不在大纲完成前合成中文。原声对齐与中文合成的并行由配音执行器负责。

`continue_saturday_dubbing.start_producer_candidate(config_path, week, run, executor)` 是生产调用点：调用者拥有该来源的 generation lease，在阅读稿及大纲就绪时调用，并在生成阶段结束前等待返回的 Future。它只读上游产物，将来源、人工窗口、中文稿、术语、声音训练及授权证据绑定到独立的配音任务；正常 bridge CLI 仍等待上游 lease 释放。实际执行失败或来源／哈希验证错误会向调用者传播，已完成的模型产物保留供恢复。缺少配音配置、当周元数据、声音训练资料或授权范围属于 `CandidateNotReady(status, reason)`，上游记录等待状态并继续独立 PDF 分支；不会将输入损坏或 TTS 失败伪装成普通等待。

## 任务版本

- `sermon-weekly-dubbing-job-v1` 保持原合同：准备时已有两份 PDF 和 QA。
- `sermon-weekly-dubbing-job-v2` 必须同时带 `pdfPackagePolicy: deferred_until_release`。配音候选的输入不包括尚未完成的 PDF、PDF QA 和 generation report；这些状态明确记为 pending/false。
- v2 不修改现有 v1 任务，不覆盖旧音频或审核。命令行使用 `weekly_dubbing.py prepare --defer-pdfs` 可显式创建新 v2 候选。
- `validate_review` 在最终验收时重新读取完整 PDF 包，要求所有非 PDF 输入与配音冻结版本一致，并继续执行原 Saturday PDF/GCS 完成校验以及人工音频审核、声学锚点与音轨检查。补齐 PDF 不会改写 `job.json`，不需要仅为 PDF 完成重跑 TTS。
- archive-caption 路径仍使用原完整交接合同，不接受 `--defer-pdfs`。

## 原声指纹的两阶段处理

原声 landmark 可与 ASR 并发；它是确定性信号处理，不占模型槽。

```sh
node experiments/sermon-dubbing-poc/build_fingerprint_index.mjs \
  --mode precompute --source ORIGINAL --source-sha ORIGINAL_SHA256 \
  --start START_SECONDS --end END_SECONDS --out source-landmarks.json
```

输出 `sermon-source-landmarks-v1`，只有原声 SHA 与窗口，没有中文音轨或页面绑定；控制台收据给出该缓存的 SHA。中文音轨确实完成后再绑定：

```sh
node experiments/sermon-dubbing-poc/build_fingerprint_index.mjs \
  --mode bind --precomputed source-landmarks.json --precomputed-sha CACHE_SHA256 \
  --source-sha ORIGINAL_SHA256 --start START_SECONDS --end END_SECONDS \
  --track ACTUAL_CHINESE_MP3 --page-id PAGE_ID --out fingerprint-index.json
```

绑定检查缓存 SHA、算法、原声与窗口，并直接计算实际中文文件的 SHA；不重新解码原声。最终仍输出原 `sermon-landmark-index-v1`，现有页面协议不变。原一次性 build 调用兼容保留。上述命令只生成本地产物，不发布页面。
