# 2026-10-04 制作日志复盘

## 范围与结论

本次来源 `resi-20261004-69ba7a66`，三语每种 474 个单元，最终音轨约 32:22。分析直接读取本地实际执行诊断、模型修订结果、ASR 收据、元数据修正和发布读回收据。下列证据来自不同尝试，不能合并为一次成功运行，也不能由当前发布成功抹去早期失败。

正式站与 Dev 的最终 HTTP 收据均为 pass，每个环境核验 15 个文件及 3 个 Range 请求；三语浏览器目录及媒体就绪读回有独立记录，三语 playbackTest 仍为 not_run。最终每环境15项覆盖韩西与共享资产，未重新覆盖全部中文资产；中文有独立检查。deviceAcceptance 与 venueAcceptance 仍为 not_run。网页媒体加载与人工听审不等于实体设备完整播放或视频同步验收。

## 1. 完成单句生成后，整轨排程仍会失败

12:27:49 UTC 的 release-attempt 状态明确为 `blocked_on_native_schedule_and_audio_package_gates`，`publicationNotPerformed=true`。中文 edge40、韩语 edge20 后处理均 `compactExitCode=1`，CPU 测量本身 `measurementExitCode=0`、`gpuCalled=false`：测量命令成功不能覆盖排程失败。

| 语言 | 后处理排程问题数 | 最大结束滞后 | 对应组 |
|---|---:|---:|---|
| zh-Hans | 239 | 58.479951 秒 | translation-0-u172 |
| ko | 122 | 58.869958 秒 | translation-0-u172 |

这些数字证明排程滞后超出当时 8 秒门槛。后续逐句核对发现 u172 源长2.96秒、初始中韩音频约61秒，前一句 lag 尚不足1秒；这段峰值主要由单句异常跳升再向后传播。韩文原始与最终文字相同，不能归为译文过长；旧61秒 WAV 未找到，声学根因尚未判定。见 [完整复盘](20261004-full-production-retrospective.zh.md)。最终采用本次用户明确接受的容差与音频处理后完成交付，不代表原 8 秒目标达成。

改进：在整批 TTS 前验证高风险连续段，记录实测与预测的区别；排程错误返回失败单元、累计滞后、策略版本、可复用缓存及唯一下一步。调整容差必须保存独立授权，不应成为默认修复。

## 2. 语义审核与插件准入是两个关口

首轮实际结果如下，来自 timing-revision-outcome，而非按诊断组数推算模型调用量：

| 语言 | revision brief 组数 | 文本实际变化 | 语义通过 | 插件拒绝 |
|---|---:|---:|---:|---:|
| zh-Hans | 198 | 197 | 474/474 | 2 |
| ko | 94 | 92 | 474/474 | 1 |
| es | 31 | 31 | 474/474 | 2 |

中文 u202/u219 被显式数字 one 筛查拒绝；韩语 u174 被来源绑定的 Y2K 术语规则拒绝；西语 u014/u018 的自然读法 quince 被精确数字映射拒绝。日志证明模型语义通过不保证插件通过，不能据此认定五处均为译文语义错误。应明确展示规则、匹配依据和修复差异，按失败点续跑并复用有效证据。

## 3. ASR 筛查不能被写成人工批准

最终 MP3 绑定的筛查均覆盖 474/474、阈值 0.88：韩语 429 pass / 45 requires_review；西语 436 pass / 38 requires_review。原机器收据保留 `status=requires_review`、`humanListeningStatus=pending`。后续实际用户听审与批准属于另一个版本绑定的证据，不能回写原机器结果为 pass，也不能将 45/38 直接当作确认的配音错误数。

改进：疑点队列绑定当前 unit WAV 和最终 track 哈希；裁切或重做后检查哈希是否改变，再决定缓存可复用范围及是否需新听审。

## 4. 元数据发生上线后的补修

metadata-title-fix 收据记录了独立修正。内容上线后才补齐标题、系列、讲员、经文，并纠正页面旧时长文字。元数据修正不应改变已批准源稿或配音。

改进：发布预检拒绝占位标题、缺失讲员和显示时长与媒体不符；读回同时检查 catalog、content、页面及客户端可见标题。把元数据证据纳入版本身份，而非发布后的附带工作。

## 5. 日志与恢复设计需要保留真实状态

今天的诊断、收据和汇总分散在多个目录；一份旧 blocked/pending 记录不是最终状态，而最新 HTTP pass 也不证明所有历史阶段通过。统一 CLI 应汇总真实收据并保留尝试历史，明确生成完成、排程通过、机器筛查、人审、发布和设备验收。

建议对每次 attempt 保留 run/job/locale/stage、输入及输出 SHA、后端与策略身份、起止时间、退出码、质量状态、阻塞原因、重试或缓存来源、授权收据和下一步。HTTP 发布需另记环境、origin、部署版本、catalog SHA 和读回结果。

后续专项审计已补充 [耗时与 token 统计](20261004-production-time-tokens.zh.md)，可核对已有账本中的根 stage 耗时和模型用量；仍不具备全部流程、Codex 对话和人工等待的完整统计，也未证明性能提升。模型服务共驻留造成资源压力是待验证假设，不能仅凭停用后资源增加断言为此前失败的根因。

## 下一轮验收重点

1. P0：整批 TTS 前的连续段实测预检，保留预测偏差；不自动放宽质量阈值。
2. P0：元数据完整性门禁与发布后客户端标题读回。
3. P0：失败状态和唯一恢复入口，unknown 不自动重跑，有效缓存不重复付费。
4. P1：疑点队列绑定最新音频；机器状态、人审和同步例外分别保存。
5. P1：先补齐 attempt 时间序列与请求账本，再做性能和成本对照。

这些是 [统一 CLI 与持久化执行](../unified-cli-pipeline.zh.md) 与 [协议](../unified-cli-protocol.zh.md) 的真实运行输入；本次仅补充文档，不宣称这些改进已实现。

## 本地证据索引

原始产物继续留在 ignored artifacts，未提交媒体、逐句私有输出或凭据。以下路径相对于 `artifacts/post-live-runs/2026-10-04/resi-69ba7a66/`，SHA-256 可用于核对分析输入；它们不是 GitHub 可下载附件。

| 路径 | SHA-256 |
|---|---|
| `formal-layer3-release-attempt-v1/release-attempt-status-v1.json` | `c15225fce1511cbe3eb4abcfee04ea047114cedc7217055147dff4b15874d131` |
| `formal-layer3-postprocess-execution-v1/plan-preparation/zh-Hans-measurement.json` | `dd02acb97cc1bf804ddee22b0813cdb8fec13f38f9a7c72e6bd03787f8d1168c` |
| `formal-layer3-postprocess-execution-v1/plan-preparation/ko-measurement.json` | `ecd4f48ba84f055f98ffb7c7ee77b7172fce22cc38394c5c2f5b07364c0a48b4` |
| `formal-layer2-timing-revision-v1/timing-revision-outcome-v1.md` | `766c993b78e24ece8f9ed50f07517c5707fe61c444f60a1f632542541e3f6cc2` |
| `ko-publication-v1/canonical-leading60-v1/asr-screening-receipt-v1.json` | `15b0dd809fe0da7b4c2f42b8be90d8029e277ff40a437fef593393edb9899b65` |
| `formal-layer3-execution-v2/es-publication-v1/canonical-leading60-v1/asr-screening-receipt-v1.json` | `4d25f2124a1be058ccf74bef5c1065e7f620c665a651c9f96c865476ce596888` |
| `metadata-title-fix-v1/prod/metadata-revision-receipt.json` | `25f4d7f1812a058867f28d27ad11d8f0aab24aba28970e48d4475a498a4805d8` |
| `multilingual-publication-v2/catalog-ko-es-v1/prod-es/final-http-ko-es-receipt-v1.json` | `edca40a09691b30ee2db8a6d83a6717c5b7abd75eb9a753f552b5beb22067712` |
| `multilingual-publication-v2/catalog-ko-es-v1/dev-es-v3/final-http-ko-es-receipt-v1.json` | `003e499c61d0a02ed7cfe5ff9a752ebcb6f0ffea8c5219e70a8c17ac1ef3a601` |
| `multilingual-publication-v2/browser-readback-three-locales-v1.json` | `4df9465a2b90664f7d78e8acb0ada5622dca7536688f99104c0e5cd36e61d79a` |
