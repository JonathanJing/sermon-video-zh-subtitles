# 生产 finding 与复测后的下一轮开发规划

依据[周日真实分层返工审计](20261005-sunday-layer-rework-analysis.zh.md)和[修复后三分钟复测](20261005-sol61-high-fast-fixed-180s-retest.zh.md)，下一轮先减少不必要返工，再缩短验证和加载开销，最后增加并发。本文件定义工作顺序与验收，不将设计记作已经实现。

执行进展：第一批三项 P0 的实现、定向验证和边界见[开发验收报告](20261005-production-recovery-p0-development.zh.md)。后续迁移、receipt 快路径、驻留和 DAG 仍按下文验收推进；这份进展不代表完整实际规模的 production run 已通过。

## 第一阶段：可解释的局部恢复

| 优先级／工作项 | 证据与拟议实现 | 验收标准 |
|---|---|---|
| P0 L3 异常音频留存与诊断 | 周日 u172 约 61 秒旧 WAV 缺失；本轮 g003–g005 先累积延迟。保留原始 WAV、文本／speaker/checkpoint／seed／batch/runtime 身份、错误、时长、hash；记录首尾静音测量及 lag 传播，分开声学异常与文字过长 | 异常停止后仍能完整回放、解码和对账；只读诊断不修改音频、不触发模型。ASR 低相似不能自动判定重合成 |
| P0 recovery plan | 输出完整复用、需重验证、需重计算、unknown 待对账四类；逐组给变化输入、上下文依赖、batch 窗口和下游失效原因。保持 formal package 失效与 model request 变化两个维度 | 同输入中断仅补缺项；修改一组只扩大到实际依赖／batch；未知 owner 持槽不重发；计划计数和实际新调用、输出 hash 一致 |
| P0 L2 规则在开跑前统一冻结 | 周日中文引文／韩文引用规则迟加，共 6,473,094 token 新调用。核验 translator、reviewer、plugin、candidate 消费同一术语／引文规则版本，开跑前检验 model-facing 输入 | 不匹配时在首调用前失败且调用为 0；覆盖该系列引文、未口述编号和数字上下文。plugin-only 修复重验证，不无条件重译 |

保持完整经文和语义，不默认压缩所有超窗译文。修复顺序先确定波形／锚点是否异常；文字正确时优先 L3 局部处理，经听审再决定是否重新合成。确需口播修订才回 L2，执行规定译审/plugin 链并重建同语言包。音频改变后同语言整轨排程、cue、听审和 release 必须重新闭合；不要求所有语言重新算模型。

本轮预定回归样例：g003 最早超窗但未违规；g005–g008 lag 传播；g011 在边界内；g013 小幅自身超窗但尾端溢出。计划必须同时覆盖累计时长下界和逐锚点约束，不能称仅缩短 1.517 秒就必然解决所有同步问题。

## 第二阶段：安全迁移与验证快路径

| 工作项 | 边界与实现方向 | 验收标准 |
|---|---|---|
| L1 入口覆盖 | 已有统一 cache namespace、single-flight、started/unknown 保护。审计生产 CLI/controller/prewarm 是否共同消费，取消剩余手写旁路 | 两入口相同 payload 同时运行只有一次模型 dispatch；结果未知不重发；namespace 与迁移证明可对账 |
| L1/ASR 逐组迁移 | L1 全局 anchor hash、ASR 整 speechJob hash 导致跨版本未变片段不能直接命中。新增版本化迁移证明，精确核对内容、上下文、音频、speaker、规则和 runtime；不能只忽略总 hash | 修改单句，依赖外模型结果经迁移验证后复用；上下文改变、音频 hash 不符、伪造 receipt、实现不兼容均拒绝；批准不随缓存复制 |
| 已冻结上下文的 receipt 快路径 | 周日中／韩 cache 重建约 21 分钟、91%–92% 耗于 receipt。冻结并一次验证 job interface，通过身份绑定复用一致结果；安全校验仍保留 | 用同一个真实 474 单元 manifest 比较原路径／快路径：全部产物一致、新模型调用 0；分别记录校验 CPU/I/O、墙钟。身份或产物改变必须回完整验证。三分钟本地恢复 11 秒不能代表此优化已完成 |
| L4 环境／attempt 收据 | 资产复制曾携带旧部署／HTTP 收据。部署、环境、commit、release/asset/catalog hash 和读回 attempt 单独绑定 | 复制资产不能继承“已部署／当前已验”；仅修改 metadata/environment 时上游模型调用 0；HTTP 与真机验收分别报告 |

迁移 schema 需版本化，保留历史收据和拒绝原因。formal package 身份变化仍按合同重验与匹配审核；局部计算复用不自动沿用旧批准。

## 第三阶段：接入正式链路与提速

1. **正式 CLI→plugin→candidate 的策略化接入。** 本轮 Sol 6.1 配置只在 simulation 入口运行，真实 controller 尚未支持此生产策略。先建立独立版本化角色策略和 admission 合同，验证授权后端、模型/effort/tier、lease、unknown 和各 locale 的门禁；保留 API 及 CLI 的精确身份隔离。生产模型选择须明确，不能将本轮测试 override 自动提升为生产默认。
2. **驻留 session 的 GPU 许可与冷暖对比。** 本轮 TTS/ASR 两次加载合计 54.125 秒；现有 session 精确复用测试不证明实际暖启动提速。新增 session 级许可、模型切换清理及 unknown 对账后，用同 checkpoint/batch/input 的独立冷暖运行记录加载、推理、显存／主机内存、输出与听审差异。未建立许可前不将整个驻留进程当成已释放 GPU。
3. **有界 DAG 与跨主机容量。** 本轮 CLI→TTS 的确定性接续约 0.51 秒，阶段间不必再发一次监督模型判断。先减少冗余验证再增加合法独立组的并发；只在完整依赖、冻结版本、显式资源容量和审阅条件满足时放行下游。当前 canonical L2 同 run 单 locale owner 限制必须保留。全局 broker/lease、公平性和跨主机 unknown 对账未完成前，host-local 槽不是跨机器统一 24 路生产调度。

上线顺序：先用现有固定片段的零调用 fixture 覆盖拒绝与局部恢复；再用新身份做必要的真实组件测试；最后验证一篇实际规模的 production run。每阶段独立记录新增 CLI/API 请求、本地推理批次、复用/重验证/重计算/unknown 数量、墙钟、交接等待、版本迁移范围和质量门禁，不以 CI、机器评审或 HTTP 代替人工和设备验收。

本轮结论是现有资源与恢复机制在真实组件路径奏效；未测得以上未来改进的节省时间或 token。下一轮第一批实现范围建议为异常留存、recovery plan、规则冻结前检及相应回归，之后按其真实 finding 决定迁移／快路径／驻留／并发的投入顺序。
