# 2026-10-07 播客正式页面发布

2026-10-02《如果我有更多时间 · 耶稣配得》已追加到正式 Firebase catalog。`pageId` 为 `if-i-had-more-time-jesus-is-worthy`，类别为播客，中、韩、西各 839 句。讲员为 Eric Geiger · Steve Bang Lee；保留原双人音轨顺序、译文、字幕时间轴和已批准页面字段。10 月 4 日证道仍为默认页面。

## 发布与审核边界

正式站为 `https://ai-for-god-sermon-audio.web.app`，没有重新提交 IPA。现有正式版 1.26.16 的 Core 数据解码检查通过。原正式客户端只接受 MP3，历史播客为 WAV；本次仅以 libmp3lame 192 kb/s 转码，不重新合成、不剪辑、不伸缩。三语 MP3 完整解码通过，实测时长分别为 3804.68、4609.72、4112.92 秒，与原音轨相同。

用户在看到格式转换说明后明确回复“允许”，授权本次沿用原整轨听审。独立 codec 授权收据绑定原 WAV、派生 MP3 和核验结果；新 Layer 3 派生包绑定原已审核包，Release 改绑派生包 hash。原审核收据不回写，不宣称重新完成 MP3 全文听审。韩、西语后续全文批准与历史口播候选的差异只有审核元数据，839 句文字及来源组绑定一致，分别保留身份。

## 验证结果

- 先部署资产，最后更新唯一可变 catalog。初始正式快照 127 文件，最终追加 16 文件；未删除历史文件，仅修改 catalog 和 Web 读取器。旧周次、API rewrite 和视频 redirect 保留。
- 17 项线上 GET / SHA 检查通过：三语页面、内容、字幕、MP3、Release，以及英文对照和 catalog。三条 MP3 均返回 HTTP 206，Range 长度和 Content-Range 匹配。catalog 为 `Cache-Control: no-store`。
- 三语正式 Release、独立阅读／音轨时钟及英文对照均通过正式版 Core 原生解码检查。每语均保留 839 个组。
- 补齐 Web 播客源地址、v2 独立音轨时钟、对象形式大纲和双讲员显示。正式选页入口可选播客，三语音轨均实际开始播放且进度前进，无 media error。中文字幕观察到从第 1 句前进到第 4 句。读取器 38 项测试通过。
- iPhone 实机刷新、播放和离线下载验收尚未执行；设备与现场状态仍为 `not_run`。播客未提供现场声音定位索引，不宣称视频同步或听音定位可用。

## 发布凭据

最终 Hosting version：`sites/ai-for-god-sermon-audio/versions/34d2ef41dc4bb6c1`。

Catalog SHA-256：`03adb35eccd495624542182bb1e3a77e4edc441999ac4db5b526f599a41949e6`。

本机忽略产物 `artifacts/podcast-production-20261007/` 保存发布尝试、HTTP 文件哈希、codec 授权和原生／Web 检查记录，不提交音频或私人上游原件。

## 实机验证

在正式 App 刷新证道列表，选择 2026-10-02 的播客，分别切换中文、韩语、西语。检查类别、双讲员、播放进度、逐句字幕和英文对照；下载后切到飞行模式验证离线播放。
