# 复盘：20261012-clip-ko-sino-chapter-rerun

本复盘只依据本目录已导出的 INDEX、summary、日志和收据；不补造未导出的运行状态。

## 实际覆盖范围

本轮记录韩语 Layer 3 渲染、回转写筛查及片段音频候选；L1/L2 输入作为既有依赖，本报告不证明重新生成或重新批准。音频质检另有独立 summary。

## 结果和结束信号

`l3e` 的 accounting summary 保留原渲染 `failed`；render.log 明确失败于调用 ffmpeg 时 FileNotFoundError。compact.log 另记录 candidate 和 16 个 trimmedUnits，不能用候选结果覆盖原失败终态。

`aqc-out3/summary.json` 的韩语状态为 audio_waiver_issued，audioQc=pass、failedGroups=[]；这是匹配该轮产物的机器豁免证据，不是人工听审、Layer 4 发布或设备验收。原 l3e 渲染失败继续独立保留。

## 耗时

accounting summary 的原渲染 wallSeconds=76.611250 秒，包含失败前执行，不是成功全链路耗时。音频质检 timings.tsv 分列 discover 0.0、track-check 0.3、secondary-asr 0.0、audio-qc 0.3、calibration.prefetch 0.8、calibration 133.8、audio-waiver 0.1 秒；零值仅是该计时收据，不推断零实际工作。等待与计算未完整拆分，费用未在此摘要可靠结算，均保持 unknown；不据不同轮次数字宣称性能提升。

## 错误与占用资源后暴露的问题

渲染已执行后才在 track assembly 发现 ffmpeg 不可用；应在真实渲染前核对执行环境依赖。ONNX GPU device discovery 警告与最终 ffmpeg 缺失异常分开，不把警告自动认定为失败根因。

## 遗留状态

媒体和原日志保留本地 ignored artifacts，未复制进报告。该次 Spark 会话释放、服务恢复、遗留 job hold 的完整终态未在本目录提供，保持未核验，不声明已清理。

## 外部可见的变化

这份证据不建立 Dev/Production 发布、TestFlight、设备播放或现场验收；相应发布与验收未在本报告核验。机器候选或豁免不等于 humanApproval。

## 后续

工程维护者核对 ffmpeg 预检、筛查合同和恢复路径；相关实现审查分别在 #360/#362 处理，本报告不改其代码或替代其验证。运行负责人若需续跑，应复用匹配身份的已完成产物并先对账未知状态；本报告不授权新增模型调用或发布。

## 报告副本与 CI 修复

报告初始 CI 的 changes 因导出日志行末空白未通过 git diff --check，unittest 为依赖失败。仅清理报告中日志副本的行末空白，不改错误内容或原运行文件；manifest 的 sha256/bytes 仍表示原来源，新增 exportedCopy 记录规范化副本的哈希、字节数和处理方式。此文档修复没有重跑模型、连接 Spark 或发布。
