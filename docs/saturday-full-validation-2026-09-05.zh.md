# 2026-09-05：复用 8 月 30 日视频与分段的周六流程验证

本次使用 [8 月 30 日目标周的直播归档](https://www.youtube.com/watch?v=-BeFX5G2oAw)，在隔离目录实际执行周六生产流程。已完成双 PDF、Context Pack 导出、云端文件校验，以及 29 分 30 秒的中文同步配音候选。本报告记录实际生成与模型复核结果；人工听审及真实场地验收仍待完成。

## 输入与隔离

- 讲员：Eric Geiger；题目：当我愤怒时；主要经文：诗篇 137 篇。
- 沿用有效的原始人工窗口审批：`00:29:00–00:58:30`，共 1770 秒。没有新建或冒充人工审批。
- 来源实际发布时间按洛杉矶时区为 2026-08-29，目标周日为 2026-08-30；保留两者的差别。
- 完整来源音频 SHA-256：`a003ec5afad8604fb1e5d4f4516f73d35fe8c04514fe9848d81c2ceccb3d5571`。
- 证道片段 SHA-256：`a47904be9108e8ac164d194d9e519620684b5becda7fedc3699b6925d7ad3711`。
- 复用已核验的 `gpt-transcribe` 转写、76 个原始分段及片段音频，未重复整篇转写。55 个阅读段落的时间边界与历史版本完全相同。
- 工作目录：`artifacts/saturday-validation/2026-09-05-aug30-astra/`。云端只写入独立的 `validation/saturday-full-20260905-aug30-astra` 前缀。147 个被复制的历史文件均保持原字节。

## 实际执行与恢复

1. 重新完成 76 段 `gpt-6-astra` Medium 中文翻译；空译、时间重叠及 ID 错配均为 0。
2. 在独立审核层应用此前由原音频采样支持的英文纠错：`committed tonight to shield` → `committed to not shield`。原始 ASR 不变；阅读段落仅第 32 段英文改变。
3. 完成两轮 `gpt-6-astra` Medium 阅读版编辑／审核。首次执行被 `unexpected_english_tokens` 正确阻止，没有发布不合格阅读版。
4. 本对话两次完整英中复核形成 14 项修订，涉及 9 个段落：删除重复英文括注、中文化专名，并澄清三处语义。标准修订清单通过正式生成入口应用；续跑复用了刚完成的模型缓存，没有手工伪造通过状态或缓存指纹。
5. 中英对照阅读版 37 页、证道解读 5 页；文本 QA 均通过，42 页均经 Poppler 渲染及逐页视觉检查。
6. 25 个上传文件均实际读回并与本地 SHA-256／字节数一致。Supervisor 最终建议为 `complete`，第二次驱动退出码为 0。

第二次运行记录的 `pipeline=0`、`reviewed≈0.106s` 是恢复时复用缓存的耗时，不能解释为首次翻译或两轮审核的耗时。首次失败记录和完整日志仍保留。

## Context Pack 的实际限制

导出了 76 个英文来源分段与对应清单。由于验证使用历史目标周日，当前检查得到 `pack_expired`；讲道同一性也仍是 `unknown`，并未自动变成人工确认。因此 `runtimeMode=none`、`alignmentEnabled=false`，没有向实时提示词放入机器中文，机器中文违规数为 0。这验证了过期／身份未确认时的禁用行为，不代表该历史包当前可供周日使用。

## 配音扩展

独立配置使用本次完成的生产目录，不复用旧 v4 任务的 PDF 完成标签。新任务创建了 55 个段落、126 个语音单元，`inheritedReview.generationComplete=true`，使用既有授权与 Eric 的已记录训练检查点，在 DGX Spark 实际生成中文语音。

首版时间预算发现 15 段超时。针对这些段落及一处容易被 ASR 混淆的措辞，在本对话完成两次模型文本复核后，按正式修订入口生成 v2：119 个单元中 90 个经身份与哈希核验复用、29 个重新合成。原英文与 PDF 输入绑定保持不变。

- 最终自然音轨 1518.46 秒；同步候选 1770 秒，与已审批证道窗口等长。
- 55 个段落时间预算全部通过，9 个弱对齐锚点保留绑定当前任务的模型复核证据。末段中文独立采用提前 0.8 秒的播放位置；英文锚点不变，源音频间隙与前段边界均有检查记录。
- 逐样本比较同步 WAV 的 55 段与自然 WAV：全部相同，无裁切、变速或重叠，未分配区域为零帧。同步 MP3 完整解码通过，含 119 个提示单元。
- 同步 MP3 SHA-256：`27cccc3e6e9a3f9aea0a9cfea40338a1ba6855fef2decf87cfe5f5ed9dea8c82`。
- 119 个单元的 ASR 证据及模型复核完成；90 个复用项逐项核对身份后继承、29 个新生成项重新审读。51 处文字替换中 49 处为同音／写法差异，2 处为待听审的姓名／声调问题，没有 ASR 文本层的插入或删除差异。
- 真实缓存续跑退出码为 0，工作流为 `candidate_ready_for_extended_saturday_review`。Bridge 最终只读检查选中本次 v2，保留 `waiting_conversation_review` 交接状态，不写人工批准。

定点听审问题为 unit 5 的姓名「波／伯」与 unit 112 的「雪／血」，分别位于自然中文音轨 57.76–71.36 秒和 1451.45–1463.61 秒；这些不是同步音轨时间。新表述的「那片土地」「甘愿在十字架上舍命」已与 ASR 一致，但不能据此声称旧音频实际读错。

机器 ASR 筛查与模型文字复核不等同于听审。音色相似度、自然度、发音和视频实际播放同步仍须人工确认；不会因为时间预算通过而自动发布到周日。

## 本次修复与回归验证

- 增加绑定来源音频、ASR、原文及证据哈希的英文纠错 sidecar；保留不可变原始 ASR。
- 将对话中文修订清单接入 Supervisor 和标准阅读版生成入口，并纳入缓存身份。
- 缓存命中时仍重建并核对全部原始英文分段、纠错证据和中文修订；阅读修订入口拒绝英文变更，避免绕过来源审核。
- 修复配音 Bridge 对 Python 可执行文件解析时丢失虚拟环境路径的问题。
- 来源纠错、路由与现有生成回归共 74 项通过，Bridge 15 项通过；实际最终产物的两类修订缓存核验通过。总计 89 项定向测试，未以测试代替实际生成。

## 证据入口

上述隔离工作目录中保留：

- `accounting-report.md`、`accounting-report.json`、`accounting-stages.csv`、`accounting-history-audit.json`：本次耗时／Token／费用补录。已知新 API 小计 $0.53283 只覆盖解读响应；114 条新初译／阅读缓存缺原始用量，整次费用仍未知。后续自动记录见[流程记账说明](workflow-accounting.zh.md)。
- `input-copy-manifest.json`、`original-preservation-check.json`、`source-reuse-verification.json`：输入与历史文件完整性。
- `source-text-review.json`、`review/astra-reading-review.json`、`review/reading-corrections.json`：模型审核及精确修订证据。
- `generation.log`、`generation-result.json`、`supervisor-final.json`：真实执行与恢复结果。
- `pdf-review/visual-review.json`：绑定最终 PDF 哈希的逐页视觉检查。
- `bridge-before.json`、`dubbing-launch-identity.json`、`bridge-result.json`、`bridge-final-inspect.json`：首次真实执行及最终 v2 衔接检查。
- `review/spoken-review-v1.json`：完整 55 段的模型文本复核与 16 段修订依据。
- `review/revised-audio-screen-review-v2.json`：119 个语音单元的最终 ASR 差异复核、357 份单元文件哈希核验及两处待听审问题。
- `dubbing/revised-v2-astra/workflow-receipt.json`、`synchronization/report.json`、`synchronization/assembly.json`、`synchronization/wave-integrity.json`：最终配音、时间预算、装配与波形完整性证据；后三项相对于该 v2 目录。
- `source-regression-tests.log`、`bridge-regression-tests.log`、`post-fix-real-cache-validation.json`、`preservation-final.json`：相关测试、真实缓存校验和原工作保护结果。

本项目是独立个人项目，生成资料不代表 Mariners Church 官方材料或人工核验逐字稿。此次验证覆盖直播归档 fallback；尚未提供的同版本证道专用视频路线及定时任务接线不能据此宣称完成。
