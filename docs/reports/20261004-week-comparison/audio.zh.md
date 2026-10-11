# 音频：9/27与10/4对照

只读对照已保留的最终音频manifest、manifest绑定schedule、机器ASR、人审及发布播放器证据。没有重新生成、听审或访问远端。

## 明确结论

- **同步结果退步，有直接可比证据**：上周三语最终schedule均 `status=pass/issues=[]/maxEndLagSeconds=8.0`，文件SHA与final render manifest一致；本周最终采用62秒policy，仍有中文167/韩137/西200句超原8秒。可以说原8秒目标的达成情况退步；不能据不同讲章、源边界、译文或模型输入据此断言TTS模型本身退步。
- **同步播放证据本周更弱**：上周三語人审receipt明确fullPlayback与videoSync1x=approved，浏览器receipt证明播放中可选三语dub、对应口播字幕可见、原视频静音；本周全轨听审有批准，但视频1×完整同步未单独验收。后者是证据覆盖差异，不能推断手机实际上播放失败。
- **机器疑点处理未改善**：两周机器都requires_review，再由人审放行；本周KO45/ES38依据仍整体批准，缺逐条正确转写/错误原因。不能声称误报率降低。
- **机器疑点比例变高是观察，不等于音质退步**：上周中文28/419=6.68%、韩23/420=5.48%、西27/420=6.43%；本周中文33/474=6.96%、韩45/474=9.49%、西38/474=8.02%。内容与句长分布不同、评估样本未对齐，不能据此给出模型退步或听觉错误率结论。
- **设备/现场验收未改善**：上周HTTP/browser均deviceAcceptance与venueAcceptance=not_run；本周同样未单独验收。不是本周新增退步。
- **本周生成/恢复可观测性更具体**：8×8运行加载hash、queue进程边界、reuse/synthesis阶段及320前缀续跑可核验；上周保留产物不足以给出同口径GPU耗时、worker容量或缓存占比。因此不把上周缺计量当作本周速度提升证明。

## 声音环境身份保持

两周三语final manifest均为Qwen/Qwen3-TTS-12Hz-1.7B-Base，同modelRevision `fd4b254389122332181a7c3db7f27e918eec64e3`，同speakerId `eric_geiger`、voice `eric_pilot`、checkpoint SHA `75d28ce6022b3df3a72df3dd6dbc01e53f584d685770d60ea04b341920968c9a`，authorizationStatus=authorized。没有证据表明更换声音身份导致本周同步差异；这不证明batch、seed或全部运行环境一致。

## 上周最终原始值

| locale | 单元数 | schedule | maxlag政策 | issues | ASR疑点 | videoSync1x人审 |
|---|---:|---|---:|---:|---:|---|
| zh-Hans | 419 | pass | 8.0 | 0 | 28 | approved |
| ko | 420 | pass | 8.0 | 0 | 23 | approved |
| es | 420 | pass | 8.0 | 0 | 27 | approved |

上周音轨1891.728秒，本周source clip1942.123秒；单元数分别419/420与474，工作量不同。上周full-video HTTP验证98/98文件pass，浏览器验证时间2026-09-27T13:26:21.035330Z，均不是实体设备验收。

## 不能比较的内容

未发现上周本专项所需的完整实际TTS argv/worker pool receipts与首末执行时间，不能把后来代码默认batch/replicas当上周实际值；不报告8×8带来多少速度提升。人审receipt的批准也不等于独立逐音素错误率测量。上周早期失败产物不覆盖最终通过结果，本次比较以最终manifest绑定schedule为准。

## 直接证据与SHA-256（仓库相对路径）

- `artifacts/drive-source-20260926-1730/layer3-analysis/spoken-script-drafts/zh-Hans/formal-audio-20260927-1100/compacted-xing/render-manifest.json` — `2992e1e5923fd999e26abe81d5279e4ec6c457806b65a3b56ea6e15b49e2ae51`
- `artifacts/drive-source-20260926-1730/layer3-analysis/spoken-script-drafts/zh-Hans/formal-audio-20260927-1100/compacted-xing/languages/zh-Hans/synchronization/schedule.json` — `1762a839e54067d934fa4488a216ed8e2131ef3df4170c8e4cb468e3b01c0615`
- `artifacts/drive-source-20260926-1730/layer3-analysis/spoken-script-drafts/zh-Hans/formal-audio-20260927-1100/compacted-xing/review/asr-screening.json` — `37e691c5403cca1dfb43e9e23c647e9b1d4e4bbf3e2d35deb605054ba4bd2ae7`
- `artifacts/drive-source-20260926-1730/layer3-analysis/spoken-script-drafts/zh-Hans/formal-audio-20260927-1100/human-reviewed-20260927-1312/audio-human-review-receipt.json` — `6edba6b38569553306eae3b46b64ef4a354238dff3347f0c9db21df5b1357544`
- `artifacts/drive-source-20260926-1730/layer3-analysis/spoken-script-drafts/ko/formal-audio-20260927-1100/compacted-xing/render-manifest.json` — `ae51af763611df0cf5afed26275b2e18290f9e9df1acca3bb8cdcb1194fa702d`
- `artifacts/drive-source-20260926-1730/layer3-analysis/spoken-script-drafts/ko/formal-audio-20260927-1100/compacted-xing/languages/ko/synchronization/schedule.json` — `b7ba936a48a62b83875762d2ef4eaf2120439bb0060d359cd550ca94942a6c46`
- `artifacts/drive-source-20260926-1730/layer3-analysis/spoken-script-drafts/ko/formal-audio-20260927-1100/compacted-xing/review/asr-screening-qwen3-0.6b.json` — `61b9e3ed045bbb8767d39a6f68d1d7b070319c17b207356f0fcb2374d4ebc9a1`
- `artifacts/drive-source-20260926-1730/layer3-analysis/spoken-script-drafts/ko/formal-audio-20260927-1100/human-reviewed-20260927-1312/audio-human-review-receipt.json` — `c01ff1b5de93a3ea4249b73ea051cae5f7484ce9b7e0af6c6618e4cc04407cb2`
- `artifacts/drive-source-20260926-1730/layer3-analysis/spoken-script-drafts/es/formal-revision/formal-audio-v6/job-compacted-mp3-v2/render-manifest.json` — `9805bf884fc39bf60478dc498d4d695c11ccc95268265942a7a874fd30ce74c5`
- `artifacts/drive-source-20260926-1730/layer3-analysis/spoken-script-drafts/es/formal-revision/formal-audio-v6/job-compacted-mp3-v2/languages/es/synchronization/schedule.json` — `fb646c90043bcb6aba74c8db237ec185a2ef1f68a9b8e1276a2a3f7b1e2694c8`
- `artifacts/drive-source-20260926-1730/layer3-analysis/spoken-script-drafts/es/formal-revision/formal-audio-v6/job-compacted-mp3-v2/review/asr-screening-qwen3-0.6b.json` — `1a29d1c5b92fad88542795cbddee51fed48570eab1272adf68da95269589de5f`
- `artifacts/drive-source-20260926-1730/layer3-analysis/spoken-script-drafts/es/formal-revision/formal-audio-v6/human-reviewed-20260927-1312/audio-human-review-receipt.json` — `0e6985754af8cc97ceaea2a90e35f01afee2a114d6dd478e48eb040313be04f0`
- `artifacts/drive-source-20260926-1730/full-video-audio-publish-20260927-v3/http-verification.json` — `ca9c1d48857c39be3e05f2ccd972c64492966a474d6395add155997db12d8722`
- `artifacts/drive-source-20260926-1730/full-video-audio-publish-20260927-v3/browser-verification.json` — `4610b8719586f531ca4bd7312e7588d771c5e2ac20afde75c18f4d9c90cdf1e5`
- `artifacts/post-live-runs/2026-10-04/resi-69ba7a66/full-retrospective-v1/audio-resources/metrics.json` — `b0f964400069ea026bb59688ff31950993055bd1b12a1f9eccbf7dcf98101291`
- `artifacts/post-live-runs/2026-10-04/resi-69ba7a66/zh-publication-v1/audio-render/render-manifest.json` — `8b8d0846ba4cd3d6c5eececaac5d666c4728a2f0171d184db6d16d6671136200`
- `artifacts/post-live-runs/2026-10-04/resi-69ba7a66/ko-publication-v1/canonical-leading60-v1/render-manifest.json` — `be328ff9066e945153e0fdb672c612957f53df9eb56179f44d86fabd1418ea69`
- `artifacts/post-live-runs/2026-10-04/resi-69ba7a66/formal-layer3-execution-v2/es-publication-v1/canonical-leading60-v1/render-manifest.json` — `1a6df4fd80a1e0480fbe08d5ec34502fbd083c0228871e8aa31e9494d65d2fef`
