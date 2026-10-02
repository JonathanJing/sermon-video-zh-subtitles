# 同行开发晨间交接（2026-09-30）

本轮交付保留在独立 PR 中，未合并、部署或发布 App。用户最后明确的验收目标是：**修好日志，再用 dry run 检查能否收集足够信息**。本轮已实际复跑并独立对账，支持“有限真实离线样本的日志可解释”，不支持“整条生产流水线已经完成验收”。

## 用户现在能核对的结果

主交付：[PR #161](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/161)。[日志充分性报告](https://github.com/JonathanJing/sermon-video-zh-subtitles/blob/7250a72a6d88261ae23b74b037e9f0b64a43348f/docs/reports/20260930-observability/README.zh.md)、[实际复跑对账](https://github.com/JonathanJing/sermon-video-zh-subtitles/blob/7250a72a6d88261ae23b74b037e9f0b64a43348f/docs/reports/20260930-observability/timing-rerun/reconciliation.json)、[代表事件](https://github.com/JonathanJing/sermon-video-zh-subtitles/blob/7250a72a6d88261ae23b74b037e9f0b64a43348f/docs/reports/20260930-observability/timing-rerun/representative-events.json)。完整事件、JSON/Markdown report、命令及独立执行记录均随 PR 保存，不依赖审核者访问 ignored 本地文件。

| 实际路径 | 观测与独立验证 | 范围 |
|---|---|---|
| 138s 真实视频、三语各11组历史翻译缓存 | 66个历史 translator/reviewer 的模型、缓存/raw/request/response hash、usage 与独立原件 oracle 一致；视频 SHA 出现在 decode 和三语 admission；3个 candidate hash 不变 | 新执行缓存验证与候选重建，0次新 transport；不是新付费翻译 |
| 178.16s 窗口新本地 MLX ASR | decode 0.202493s、设置 1.548344s、模型调用 9.618410s、输出 0.003893s；checkpoint/input/output hash 一致 | 模型调用仍含库内部工作，未拆GPU内核；不是正式 ASR/内容质量签字 |
| 33个历史音频单元重新全解码 | 33 starts/completions、音频/job hash 与原包一致；真实 zh-Hans→ko→es 顺序边；active path与wrapper小计同为6.388333s | 没有新TTS、人审或声音授权；逐单元验证小计5.567545s不是端到端总时长 |
| 真实插件绑定拒绝及受控故障 | 拒绝原因与预期/实际 hash；等价/冲突/同event-ID/跨run/SDK用量一致性；中断未知结果与并行图 | 绑定拒绝为实际路径；其他标为synthetic，不是付费provider故障实测 |

执行代码为干净 `ebaea29e857afba3bf6d6313ce9a8e3ccb8d66ec`；后续 `7250a72` 包含证据与测试报告。历史 tokens不当作当前消费；未知费用和未观测工作不填0。`projected`仅表示记录的DAG可计算。原媒体、缓存、音频、原审批未变，新候选仍为human-pending。

冻结 head `7250a72a6d88261ae23b74b037e9f0b64a43348f` 已在15:16 UTC核验：Python两个分片及`unittest`汇总均SUCCESS；[该head CI](https://github.com/JonathanJing/sermon-video-zh-subtitles/actions/runs/36734526472)。iOS/contract validation仍SKIPPED。第二轮独立artifact复核也已确认媒体hash、ASR分段计时、音频串行边和未变输出；这不扩展到完整生产telemetry验收。

## 集成验证与交付边界

完整组合快照 **`a709561e5a8fa4ca5fe8df78cc2c2f9df7cd21e8`** 已在本机重新跑Root Python：**2084 reported / 2078实际通过 / 6条件跳过**。包含#161的最新代码与实际trace回归。快照未推到dev/main。

Web、Feedback API和全部iOS源树与完整验证的`8f608a9733f8928b654084e95046200e6e2ae43b` Git tree SHA相同；该基线实际通过Web363、API61、dubbing343、Swift Core61（另6skip）、Storage39（另5skip）、iOS27与17.5模拟器各37。这里没有把旧结果当作新快照重跑。远端draft的iOS/contract jobs仍skipped，不是原生验收。

| 改动类别 | 已有行为 | 到用户的交付要求 |
|---|---|---|
| 后端/本地产线 | 既有durable jobs的只读检查、确定性controller/L2准入恢复、预算/崩溃保护、source/release校验、账务与日志导出 | 仍需按依赖review/合并及适用部署；日志代码本身不要求App Store审核 |
| Web | catalog/Release合同、fingerprint预检/缓存、保留新点击录音权限、采集预算与诊断 | 仍需Web交付及Safari/实际设备/现场验证；没有本轮部署 |
| 原生Swift | `TongxingCore/MultilingualCatalog.swift`的catalog/Release准入行为以及共用夹具 | **必须新iOS binary及适用的审核/发布流程才能到已安装用户**；Apple 1.1.0 Ready for Distribution不覆盖这批代码 |
| CI/测试/文档 | 路由、共享合同、故障注入、trace对账和准确门槛 | 不等于设备/人工/现场签字 |

## 未完成的工作与需要外部证据的门槛

可继续本地实施：完整canonical L1/L3/L4 durable adapters、production bounded responder与锁内admission、跨run资源限制、跨进程DAG/usage关联、真实queue/ready采集、统一release身份与完整Stage0接线。现有L2与shadow planner不能当作这些已经完成。

本次日志尚不能回答：完整生产队列/ready时间、调度开销、跨进程关键路径、fresh paid provider telemetry、历史账单费用和page-ready。已观测的耗时差额不自动解释为调度时间。后续应先按实际调用边界增加采集，再用对应路径验证，不为填满表格改变业务调度。

以下门槛不能由代码或模拟补签：完整Stage0独立签字；短片段→10分钟→完整历史视频→第二个真实周；三语人工翻译/1x听审/声音授权；物理iPhone、Safari拒绝重试、锁屏/耳机/中断/现场麦克风与字幕误差盲测。原指标未下调。若未来仅为验证真实provider telemetry发起新付费调用，应单独给出服务/模型/输入与预算上限请求，当前未获此新增支出授权。

[38项详细对照及分批证据](20260930-overnight-implementation-checkpoint.zh.md)继续保留，不把文档、代码、synthetic或历史审批标成整项完成。所有PR依赖保留，后续合并/部署/App Store发布另需授权。
