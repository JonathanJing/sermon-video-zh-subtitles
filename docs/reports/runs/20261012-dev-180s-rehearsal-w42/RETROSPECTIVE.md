# 复盘：20261012-dev-180s-rehearsal-w42

数据见同目录 INDEX.md 和 manifest.json。这是 2026-10-11 复盘要求的「周六小样本彩排」，在 W42 全部合并后的 dev（de929581）上跑，零模型 API，模拟审核。

## 实际覆盖范围

固定的 10-01 三分钟片段（39 个英文单元，每语 13 组），L1–L4 全部用缓存与模拟审核重建，发到 Dev 站一个隔离测试页 `mockup-dev-180s-e2e-20261012T044117Z`，再用浏览器冒烟核对三语。没有生成新译文或新音频，没有构建 TestFlight，不证明翻译、配音质量或设备播放。

## 结果和结束信号

三次尝试。前两次（`e2e-20261012T043636Z`、`e2e-20261012T043844Z`）停在 baseline；第三次（`e2e-20261012T044117Z`）手动按同样阶段执行并给 baseline 加缓存，全部通过：verify-clip、build-inputs、baseline、delivery-preflight、发布、对账、浏览器冒烟。

## 耗时

第三次：verify-clip 4 s、build-inputs 4 s、baseline 8 s（524 个文件用缓存、39 个在线取）、preflight 2 s、发布 156 s。前两次 baseline 各 105 s、91 s 后失败。

## 错误

1. **baseline 下载大视频失败（两次）。** Dev 站的 `pages/2026-09-27-weekend-sermon-drive-530/full-video-browser.mp4` 用 gzip 分块传输，每次在约 560 MB、90–105 秒处被服务端截断（`IncompleteRead`）。不是偶发。处理：第三次给 `prepare_dev_simulated_publication.py baseline` 传 `--cache-public/--cache-receipt`，用 10-11 已核验的 Dev baseline（`weekend-live/layer4-54475d42/beta-baseline-v1`）的字节，逐文件按哈希核对后复用。`run_dev_180s_beta_e2e.sh` 目前没有传缓存的入口，需要补。
2. **发布后目录回读不一致。** 部署本身成功（新版本 `da82491111646b8c`），但紧接着回读 `/multilingual-v3.json` 拿到的是旧内容，发布器按规则记为 `outcome_unknown`。几分钟后再读，v3、v4 目录都与封存一致，用 `guarded_hosting_publish.reconcile()` 对账为 `deployed` 并释放租约，没有重复部署。是 CDN 传播延迟；回读可以带有限次等待重试。
3. **冒烟在 Dev 上误报。** Dev 站 `/engagement.json` 是 `enabled: false`，页面本来就不建反馈会话，冒烟默认要求 `/api/session` 而判失败。加 `--no-session` 后三语通过。冒烟应读 `/engagement.json`，关闭时自动跳过会话检查。

## 占用资源之后才暴露的错误

错误 1 本可以在预检发现：baseline 先查 live 清单里是否有超大文件、本地是否有可用缓存。错误 3 应由冒烟自己判断站点是否开启反馈。

## 遗留状态

Dev 站多了一个隔离测试页（模拟审核，默认生产阅读器隐藏模拟页）；Dev 默认页未变。发布租约已释放。

## 外部可见的变化

Dev Hosting 新版本 `da82491111646b8c`。生产、TestFlight、受保护分支均未改动。设备播放、现场验收 `not_run`。

## 后续

- `run_dev_180s_beta_e2e.sh` 支持 baseline 缓存（或 baseline 对大文件改用版本 API 校验）。
- 发布器回读加有限次等待重试，减少 `outcome_unknown`。
- 冒烟按 `/engagement.json` 自动决定是否检查会话。
