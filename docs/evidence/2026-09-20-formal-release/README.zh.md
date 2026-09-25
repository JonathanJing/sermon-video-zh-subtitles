# 9 月 20 日三语 Dev 页面发布证据

页面 ID 为 `2026-09-20-revelation-clip`，来源是原录像 35:09.16–38:07.32 的 2:58 片段。用户批准中文、韩语、西语完整音轨与机器标红组后，正式资源准备器及 `stage_formal_multilingual_dev.py` 通过，生成本目录的三语候选 Release Package、v2 catalog 与 staging 收据。`stage-receipt.json` 保留构建当时的 `deploymentStatus=not_deployed`，没有事后改写。

随后部署到 Firebase Dev 站点 `https://ai-for-god-sermon-audio-dev.web.app`。`http-verification.json` 记录部署后 13 个文件逐个 GET／SHA、3 条 WAV 的 Range 206，以及三种语言深链的 HTTP 200。浏览器实际打开三语页面，显示各自标题、2:58 音轨与 45／44／44 组字幕，点击播放后计时前进。旧 POC 的两份 catalog 与 18 条音频在部署后仍通过 SHA 核对。首次上线暴露播放器完整性读取器只接受 MP3，现已增加 WAV 白名单和 MIME、重部署并完成上述浏览器检查。

本目录只提交不含媒体和本机路径的目录、Release Package 及收据。正式 WAV、内容和字幕文件仍在受控的忽略目录；此证据不宣称 iOS 实机或现场验收通过。Release Package 保留其不可变 `candidate`／`httpVerification=not_run` 原始字段，线上 HTTP 结果由独立收据记录，避免事后更改包和 catalog 的哈希。
