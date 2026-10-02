# FIELD-01：Web 会话诊断首批实现

本批是代码与本地模拟证据，`FIELD-01` 仍为 **in_progress**，不表示真机、Safari 或会场验收通过。

## 已接入的路径

- 真实采集 attempt 在释放 tracks、AudioContext、port 后报告权限、输入启动、采集和已观察占麦时长。现有最多三次的中断重试逐次累计；诊断 callback 抛错不改变采集结果或资源清理。取消后晚到授权仍按原逻辑立即停止。
- Worker 在已验证索引上计算指纹；输出区间化 RMS 音量和削波比例、特征数量、支持 anchors、votes、runner-up、覆盖区间，以及索引验证、特征和匹配耗时。没有改动 DSP、匹配阈值、算法版本、十秒采集合同或 seek 接受规则。
- 控制器记录整次操作的单调时钟耗时、Worker 总耗时、同步 seek 调用及 native play promise 完成时间。整次耗时不是各阶段之和；Worker 总耗时包含子阶段，不应再次相加。重启后的旧 callback 不能污染新会话。
- 定位对话框显示仅本机的折叠诊断摘要；静音、特征不足、无共识、重复片段含糊及版本不兼容使用不同提示。新增模块进入已有 build/deploy 文件白名单。

## 隐私与数值含义

`getDiagnostics()` 每次重新构造 `sermon-fingerprint-diagnostics-v1` 白名单副本。仅允许公开 source/track/index SHA、固定状态与错误码、`raw-v1` profile、unknown route、粗粒度质量、计数和取整到 100 ms 的耗时。没有设备 ID、蓝牙名称、URL、现场 PCM、landmark 数组、字幕、任意异常文本、说话者身份或 confidence 百分比。没有持久化、网络发送、统计开关联动或自动导出；本批尚未提供用户分享按钮。

RMS 是现有重采样后 query 的音量值；削波区间按原采集 PCM 的绝对值 ≥0.99 计数，仅作为诊断，不是新的拒绝门槛。音量不等于信噪比，计数不等于正确率。错误时未知值保留 null/unknown，不补零。

`microphoneObservedMs` 只覆盖 getUserMedia 已返回至调用 stop 的可观察区间，不等于硬件精确占用；取消后晚到的授权由原清理路径立即停止，本批不测该不可观察区间。`captureMs` 是首帧回调至停止的单调时间，不宣称物理首样本时钟。seek 只测同步调用，play promise 只表示浏览器允许开始播放，不能代表实际可听输出。`audibleOutputMs` 和 `captionAlignmentMs` 始终为 null。

## 本地验证与剩余门槛

- 全 Web 测试 202 项通过，包括新增隐私白名单、重试累计、旧会话隔离、真实 DSP 静音、Worker 失败清 PCM、诊断 callback 失败仍清理的测试。
- Python 指纹 build/release 测试 17 项通过；新增模块通过现有发布文件合同检查。
- 仍需完整失败注入矩阵、用户显式分享流程、连续帧/窗口的更多可观察质量项，以及 FIELD-09 冻结数值 fixtures、真机和现场受控验证。此实现没有授权收集或上传现场录音，也没有部署。
