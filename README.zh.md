# 证道视频中文字幕

<p>
  <a href="./README.md">
    <img src="https://img.shields.io/badge/Language-English-blue" alt="English README" />
  </a>
  <a href="./LICENSE">
    <img src="https://img.shields.io/badge/License-MIT-green" alt="MIT License" />
  </a>
</p>

这个仓库只有一个产品目标：帮助中文会众听懂英文证道。目前真正需要展示的，是两条可以落地的工作流——周六的 post-live PDF 生产，以及周日的本地实时字幕 POC。其他代码都属于这两条路径周边的研究、评估或基础设施。

完整流程图、产物契约、本地延迟预算与测试门槛见：[两条工作流完整说明](docs/workflows/README.zh.md)。

> **现状校准日期：2026-09-04。** 下文的“当前能力”只依据 `main` 上可复核的代码、测试或已纳入版本控制的报告，不代表本机服务此刻在线，也不代表现场已经验收。每次运行的录音、转写和 PDF 按策略不进入 Git；经过审核且保留 provenance 的 benchmark 衍生数据可以版本化。文中的输出文件名是产物契约，不是仓库内附带的交付文件。

> 这是一个独立的个人开源项目，不属于 Mariners Church 官方项目，也没有获得其隶属、背书、赞助、批准或运营支持。只应处理公开或已获授权的媒体，不得绕过访问控制、DRM 或平台限制。

![项目工作流全景](docs/diagrams/project-map.svg)

## 1. Working workflows

### A. 周六：从直播/归档生成两个经过审核的 PDF

周六工作流负责发现或接收公开直播链接、保存完整 post-live 媒体、由 operator 确认证道时间窗、生成英文转写与中文阅读稿，最后在周日前形成两个 canonical 交付物：

1. `sermon_zh_en_reading.pdf`：中英翻译稿 / 阅读版。
2. `sermon_interpretation_zh.pdf`：中文“证道同行”/证道大纲，只保留与证道直接相关的辅助信息。

<table>
  <tr>
    <th>中英对照阅读版</th>
    <th>中文证道同行</th>
  </tr>
  <tr>
    <td><img src="docs/assets/pdf-examples/sermon-zh-en-reading-real-page-1.png" alt="真实中英对照阅读版 PDF 第一页" /></td>
    <td><img src="docs/assets/pdf-examples/sermon-interpretation-zh-real-page-1.png" alt="真实中文证道同行 PDF 第一页" /></td>
  </tr>
</table>

_图片来自 2026-08-30 真实运行的第一页；两份 PDF 各自的 QA 都为 `pass`，完整运行产物仍保持在 Git 之外。来源和校验信息见[示例 provenance](docs/assets/pdf-examples/README.md)。_

![周六 post-live 双 PDF 流程](docs/diagrams/saturday-post-live-workflow.svg)

这是当前更成熟的 post-live 路径。只有 source、人工批准的时间窗、阅读稿 QA、两个 PDF 以及两个 PDF QA 都存在并通过，才算完成。

关键文档：

- [稳定的 post-live 阅读版 PDF 工作流](docs/stable-post-live-reading-pdf-workflow.zh.md)
- [Codex 本地周末生产 runbook](docs/codex-local-production-runbook.zh.md)
- [证道生产 Supervisor Agent](docs/sermon-production-supervisor-agent.zh.md)

### B. 周日：从本地麦克风生成实时中文字幕

周日工作流在 MacBook 本地运行：浏览器麦克风采集、录音和事件持久化、本地英文 ASR、MiLMMT 英译中，以及单页大字号中文字幕。

![周日本地实时字幕流程](docs/diagrams/sunday-live-workflow.svg)

当前 POC 已实现麦克风选择、持久录音、Qwen3-ASR 0.6B/MLX、MiLMMT 4B Q8 token streaming、大字号字幕、带随机 token 的只读手机页、冻结英文的 replay/A-B，以及完整 session 指标证据。修复后的真实浏览器/扬声器/麦克风 60 分钟长测达到 ASR final 99.92%、翻译 final 100%。在明确排除的教会现场彩排完成前，它仍是 POC，而不是 production-ready。

关键文档：

- [周六/周日完整工作流与延迟预算](docs/workflows/README.zh.md)
- [本地实时字幕 POC](experiments/local-live-poc/README.md)
- [本地实时字幕设计](experiments/local-live-poc/DESIGN.zh.md)

## 2. Discovery、缺口与下一步

### 已经证明的能力

| 方向 | 当前证据 |
|---|---|
| 周六 PDF 生产 | 工作流代码、测试、带日期的 QA 证据、人工确认证道时间窗和可恢复状态；生成 PDF 保持本地且被忽略 |
| 周日 live POC | 真实麦克风、Qwen3-ASR、MiLMMT token stream、60 分钟长测、大字号 UI、只读手机页 |
| 周六到周日 context | 有序 weekly pack、受控 runtime policy、基于 provenance 的安全自动启用 |
| Replay 与 A/B | 冻结 ASR final、确定性 context-policy 重放、盲评 CSV、source/model hash |
| 运行维护 | 一键启动/停止、监督恢复、session 保留策略、fail-closed ASR Gold 门 |

### 正在探索和仍需补齐的门槛

- **正式 ASR 准确率：** 五位讲员和 edge case 已有机器参考的临时证据；六个 case 的人工逐词 Gold 队列仍必须由真人校正签名，之后 WER 才能用于模型 promotion。
- **已验证延迟：** 修复后的 60 分钟 Qwen + MiLMMT 长测中，音频结束到浏览器中文首字 p50 1.419 秒 / p95 1.486 秒；到完整中文 p50 1.530 秒 / p95 1.720 秒。现场声学可能不同。
- **Content-pack 质量决策：** 工具链已经完成；每周仍要用真实周六 pack，并由人工完成盲评结果。机器中文不会静默注入。
- **本地 runtime 选择：** 当前 A0 使用 Ollama；直接 MLX serving 继续作为 Discovery 备选，只有在相同 frozen 输入和延迟/质量门槛下通过后才考虑替换。
- **现场边界：** 一小时本机 soak 与 MLX 受控故障恢复已通过；剩余 production gate 是正式教会现场彩排。手机只读页还依赖现场 Wi-Fi 允许设备互访。
- **资源上限：** 一小时内 Ollama 内存增长，但没有发生延迟崩溃，run 结束后的 swap 为 0 MB。主采样器的逐点 swap 字段无效，因此不能据此声称全程零 swap；在多场连续测试完成前，每场从干净的一键启动进入。

### 后训练方案

后训练继续作为独立项目，不把训练复杂度放进 live POC：

1. 从既有字幕、周六/周日经过审核的译文、术语修订和选定音频证据构建保留 provenance 的平行语料。
2. 按整篇 sermon 固定 train/dev/test，防止 segment 泄漏；只有人工批准的 `Gold` 数据可以进入 promotion 集合。
3. 用强 teacher 生成初译，再做独立双语 review；仅对高风险片段和固定抽样进行音频核验。
4. 对较小 student model 做 SFT/LoRA，并与 MiLMMT A0 比较术语、经文名称、忠实度、幻觉率和延迟。
5. 只有 frozen evaluation gate 通过才允许 promotion。前端契约保持不变，通过替换 `LOCAL_LIVE_OLLAMA_MODEL` 更换后端模型。

其他架构、provider 对比、Cloud 实验、历史 realtime prototype 和部署笔记统一放在[文档索引](docs/README.zh.md)，不再挤进项目首页。
