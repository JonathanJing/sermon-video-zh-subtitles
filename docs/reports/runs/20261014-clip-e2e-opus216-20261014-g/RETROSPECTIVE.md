# 复盘：20261014-clip-e2e-opus216-20261014-g

脱敏证据见同目录 INDEX.md、manifest.json、timings.tsv、质检摘要和 Layer 4 回执。下列耗时包含工具等待，不等于纯模型推理时间。

## 实际覆盖范围

- Layer 1：复用 2026-10-11 来源、已批准的片段边界与时间线；本轮重建绑定输入，不重新裁定边界。片段 16 句、约 96 秒。此前 Sol 轮 D 使用同一片段。
- Layer 2：按已合并 PR #430 的 claude_cli_opus 路径重新生成韩语、西语、简体中文。译者均为 Claude Opus 5.5 / high，审核者均为 Claude Opus 5.5 / medium；共 48 组、96 次初始调用。三语言文本机器质检首轮通过并获机器豁免；没有人工内容批准。
- Layer 3：三语言重新配音、压缩、筛查、打包并正式音频质检。西语和中文首轮获机器豁免；韩语 u007 首轮要求修复，原产物保留，用 seed 44 和绑定该句的发音说明重制后复检获豁免。两次 Spark 独占会话均有 closed 回读。
- Layer 4：隔离 Dev page mockup-dev-clip-20261011-u216-231-opus-g 发布三语言机器审核版本。工作流终态 diagnostic_dev_http_verified，浏览器冒烟检查三语言均 pass。覆盖 Dev HTTP、浏览器渲染与反馈会话；真机音频播放、TestFlight 和现场验收未运行。

## 结果和结束信号

G 轮 summary.json 为 stopped=[]，所有阶段（含 layer4、report）为 done。文本质检三语言均为 text_waiver_issued；最终音频质检三语言均为 audio_waiver_issued。韩语首次 requires_repair 和 seed 44 复检均保留。Layer 4 workflow/run-report.json 为 diagnostic_dev_http_verified，browser-smoke-retry-1.json 三语言 pass。机器豁免不是人工批准，页面维持机器审核披露。

同一 USD 30 总上限中，E 前累计已结算 6.759385，E 后 8.010202，F 后 8.735465，G 后 **10.422771 / 30**；G 增量 USD 1.687306。G 的 Claude 订阅 CLI 严格账本为 **USD 3.814896 标价等值**，按 PR #430 单独上限记录，不当作现金扣款，也不计入 USD 30 API 总额。

## 耗时与模型速度

G 的 timings.tsv：输入 7 秒；文本质检韩/西/中为 134/116/121 秒。初次音频的渲染、压缩、筛查、打包、质检分别为韩 101/18/38/3/23 秒，西 88/17/36/3/134 秒，中 88/17/39/3/133 秒。韩语 seed 44 修复同五阶段为 86/17/41/3/373 秒；最后 373 秒主要包括机器质检校准预取 208.5 秒与校准 139.0 秒。Layer 4 基线、发布工作流、浏览器检查为 12/184/54 秒；工作流内部 wall clock 181.24 秒，资源发布与目录发布各约 54 秒。运行器阶段耗时合计 1,926 秒；输入完成 19:03:42 UTC 至报告完成 19:38:07 UTC 的跨阶段墙钟时间约 34 分 25 秒，包含修复决策与阶段间等待。

同一片段的三语言初始请求均为 48 组，每组译者和审核者各一次。以下来自 l2/text/*/accounting/model-calls.csv 的已完成初始调用。“窗口”指最早开始至最晚结束；因并发，不能把单次耗时相加。

| 轮次与 Layer 2 模型 | 调用数 | 译者中位数 | 审核者中位数 | 96 调用窗口 |
|---|---:|---:|---:|---:|
| D，GPT-6.1 Sol / OpenAI API | 96 | 5.52 秒 | 6.69 秒 | 37.95 秒 |
| E，Opus 5.5 / Claude CLI | 96 | 4.99 秒 | 6.79 秒 | 63.70 秒 |
| F，Opus 5.5 / Claude CLI | 96 | 4.46 秒 | 7.21 秒 | 38.32 秒 |
| G，Opus 5.5 / Claude CLI | 96 | 4.68 秒 | 7.22 秒 | 39.34 秒 |

相对 D，G 译者中位数短约 15%，审核者长约 8%，整体窗口长约 4%；E 的长尾使窗口达 63.70 秒。G 各语言译者/审核者中位数为韩 4.97/7.63、西 4.32/7.18、中 4.68/7.09 秒；D 对应为韩 6.62/7.73、西 4.44/5.60、中 5.57/6.76 秒。这里混合了模型、API/订阅 CLI 传输、服务负载、输出量和并发，不能推断模型本身的固定速度。机器文本及音频质检仍走 OpenAI 路径，上表仅比较 Layer 2。

## 错误与处理

- E：韩语 u007 音频质检要求新 seed；中文音频机器豁免因 dropped_key_word 校准 8/9 被拒。注入器从“一起”中删除“一”造成无效试验；修复见代码 PR #432 的 e28204ef，失败回执见报告 PR #431。
- F：中文文本质检要求修订时，Claude 缓存身份包含变化的预算授权哈希，修订调用未派发即报 prior model payload does not match cached response。稳定传输缓存身份、逐次独立验证预算，修复见 PR #432 的 45b0f7ba；失败回执见报告 PR #433。
- G：三语言文本质检首轮通过；韩语音频 u007 要求 resynthesize_new_seed。依质检梯级用 seed 44 和该句“8장”读法说明重制，复检通过。初次 render.* 及修复 render.ko.seed-44 的 fail(1) 是预压缩筛查状态；后续压缩、筛查、打包及最终质检各有终态，不能把它当成整个音频失败。
- Dev 发布与浏览器检查后，报告阶段因 run.mark(..., name=name) 的重复参数异常退出。修复为 reportName（PR #432，564576a1）；续跑遇到同名已导出报告，加入同源 manifest 与脱敏复核后复用（3cf70a4d）。最终 report=done，未重复发布。定向 tests.test_clip_real_e2e 16 项及 git diff --check 通过。

## 占用资源之后才暴露的错误

E 的中文校准注入器和 F 的缓存身份问题分别在音频、文本修订时暴露，均已补定向回归。报告参数冲突直到 Dev 发布后才触发；今后应在离线集成测试执行一次真实 stage_report 与同名报告恢复。韩语读法问题依赖真实 TTS/ASR 输出，静态预检无法证明通过。

## 遗留状态与外部可见变化

- Dev 页面：https://ai-for-god-sermon-audio-dev.web.app/?week=mockup-dev-clip-20261011-u216-231-opus-g&contentLang=zh-Hans；同一 week 配 contentLang=ko 或 es 可看韩/西语。Dev HTTP 回读和浏览器冒烟通过；真实手机播放、现场听感、TestFlight 均未运行。
- Spark：G 的两次独占会话均 closed；最后一次 19:33:02 UTC 的回读见 spark-finish.log。媒体、语音及运行目录留在忽略的 artifacts/ 中，未入 Git，保留失败及修复证据。
- 代码修复在草稿 PR #432；本脱敏报告单独开 docs-only PR。Sol 对照 D 的报告为 PR #427，E/F 失败报告为 PR #431/#433。机器豁免不构成人工批准。

## 后续

- 项目维护者审阅 PR #432 的 Claude CLI 接线、跨预算修订缓存身份和报告恢复逻辑，及本报告 PR 的回执范围。
- 如需宣称设备播放或场地可用性，按 iOS/现场流程另做真机音频与现场验收，并单独记录回执。
