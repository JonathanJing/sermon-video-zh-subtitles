# 9 月 27 日完整视频页：全文与精简口播双稿

当前已发布的 `/pages/2026-09-27-weekend-sermon-drive-530/index.html` 是独立完整视频页。`page-data.js` 与 `/content/2026-09-27-weekend-sermon-drive-530/{zh-Hans,ko,es}.json` 保存用户批准的三语**完整译文**。三语配音可以使用后来单独人审的精简口播 Layer 2 candidate，但它们不能覆盖完整译文，也不能把原有单候选 `sermon-target-language-release-package-v1` 伪装成双稿音频包。

`scripts/build_sep27_page_audio_extension.py` 为这页构建独立 `sermon-full-video-audio-extension-v1` 候选。manifest 按 locale 分开绑定显示全文 candidate hash、现有 content 文件 hash、精简口播 candidate hash、Layer 3 Audio Package hash、全文听审收据、机器筛查收据、MP3 和口播字幕的文件 hash。三语均须为同一完整英文来源；口播 candidate 覆盖与显示全文相同的全部 source units。音频包和字幕必须严格属于口播 candidate，真人完成全文听审及 1 倍速视频同步。构建器复制旧公共目录到新的忽略目录，逐字节保持 `page-data.js` 与三语 content 不变。

新页面保留“完整译文”列表与原始英文视频，另加“配音字幕”区域。所选语言的 MP3 与字幕校验期间显示“配音加载中”；仅在全文件 SHA-256 校验且字幕结构有效后显示配音按钮，失败则显示不可用提示。切换语言时自动回到英文原声，避免把上一种语言的配音配到另一种语言的全文。配音跟随视频播放、暂停、跳转、播放速度和音量；配音面板另有静音按钮，原视频声道在配音期间保持静音。时间漂移超过 0.3 秒时对齐到视频。浏览器播放仍需实机核验。

## 本地接入命令

在仓库根目录运行，并为所有 `LOCALE=PATH` 提供 `zh-Hans`、`ko`、`es` 各一项：

```bash
.venv/bin/python scripts/build_sep27_page_audio_extension.py \
  --base-public artifacts/drive-source-20260926-1730/text-only-production-candidate-20260927-v2/public \
  --source artifacts/post-live-runs/2026-09-27/drive-1wpixHcwnlS3WfOPdZ-oek_Y1YZG53NN5/pipeline/english-source-package-final-approved.json \
  --display-candidate zh-Hans=artifacts/post-live-runs/2026-09-27/drive-1wpixHcwnlS3WfOPdZ-oek_Y1YZG53NN5/layer2/approved/zh-Hans/final/candidate.approved.json \
  --display-candidate ko=artifacts/post-live-runs/2026-09-27/drive-1wpixHcwnlS3WfOPdZ-oek_Y1YZG53NN5/layer2/approved/ko/final/candidate.approved.json \
  --display-candidate es=artifacts/post-live-runs/2026-09-27/drive-1wpixHcwnlS3WfOPdZ-oek_Y1YZG53NN5/layer2/approved/es/final/candidate.approved.json \
  --spoken-candidate zh-Hans=ARTIFACTS/zh-Hans/short-candidate.approved.json \
  --spoken-candidate ko=ARTIFACTS/ko/short-candidate.approved.json \
  --spoken-candidate es=ARTIFACTS/es/short-candidate.approved.json \
  --audio-package zh-Hans=ARTIFACTS/zh-Hans/audio-package.human-reviewed.json \
  --audio-package ko=ARTIFACTS/ko/audio-package.human-reviewed.json \
  --audio-package es=ARTIFACTS/es/audio-package.human-reviewed.json \
  --audio-review-receipt zh-Hans=ARTIFACTS/zh-Hans/audio-human-review-receipt.json \
  --audio-review-receipt ko=ARTIFACTS/ko/audio-human-review-receipt.json \
  --audio-review-receipt es=ARTIFACTS/es/audio-human-review-receipt.json \
  --screening-receipt zh-Hans=ARTIFACTS/zh-Hans/audio-screening.json \
  --screening-receipt ko=ARTIFACTS/ko/audio-screening.json \
  --screening-receipt es=ARTIFACTS/es/audio-screening.json \
  --out artifacts/drive-source-20260926-1730/full-video-audio-candidate-v1/public
```

`ARTIFACTS/...` 是待真实音轨产生后替换的输入路径，不是可运行的现成收据。命令在任一语言未完成时失败；不生成配音占位，也不发布。输出目录为 Hosting `public` 候选，manifest 路径为 `/pages/2026-09-27-weekend-sermon-drive-530/audio-extension.json`。构建器只把旧 v1 Release Package 的 `page` 资产 hash 更新为新 HTML，并把 HTTP 状态重置为 `candidate/not_run`；其中 `audioStatus=unavailable` 仍明确表示该**旧单候选包**不承载精简口播音频。新 manifest 是独立的页面扩展候选，HTTP、设备与现场状态不得由构建成功推断。

部署前按周发布流程重新合并当前 Hosting 基线，核对旧周文件未被覆盖，检查三语全文文件和 `page-data.js` SHA 与现网一致；发布后分别核对 HTML、manifest、MP3 Range、字幕 SHA、网页实际播放和原生 iOS 可见性。现有 iOS 多语言客户端及 `formal-dev-adapter.mjs` 仍使用单候选 Release Package，尚不能消费此独立页面扩展；若要将精简口播放入通用目录或原生 iOS，需另做明确双候选版本的目录／Release Package 和客户端适配。
