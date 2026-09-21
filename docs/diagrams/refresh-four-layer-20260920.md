# 四层生产图更新记录 · 2026-09-20

本次重新调用 Codex 内置 ImageGen，生成四层多语言生产的信息图视觉参考；最终交付不是模型图片，而是按仓库冻结接口校正并重建的原生 SVG 与中英双语 HTML。

## ImageGen 参考

用途分类：`infographic-diagram`。提示要求横向四张层级卡，分别写明 Input、Process、Models、Output/Gate；Layer 1–4 使用蓝、紫、橙、绿，并显示 `zh-Hans`、`ko`、`es` 从共享英文主干分叉。还要求显示人工门禁、`audio_unavailable`、Sunday live 独立旁路，以及“模型是工具而非事实来源”。

实际发送的归一化提示：

```text
Use case: infographic-diagram
Asset type: visual reference for a repository-native SVG and HTML workflow page
Primary request: create a polished, wide 16:9 four-stage production workflow infographic for multilingual sermon production. The four stages flow left to right and are clearly separated but connected.
Scene/backdrop: clean light canvas with subtle technical grid, no photography
Style/medium: modern editorial systems diagram, crisp cards, accessible high contrast
Composition/framing: one large card per layer; each card has Input, Process, Models, Output/Gate; a lower strip shows zh-Hans, ko and es branching after the shared English layer
Color palette: Layer 1 blue, Layer 2 violet, Layer 3 amber, Layer 4 green
Required content: Shared English Source & Anchors / English Source Package; Target-Language Text / Target-Language Candidate; Target-Language Audio & Synchronization / Target-Language Audio Package; Multilingual Delivery & Playback / Target-Language Release Package; gpt-transcribe, MFA, Qwen ForcedAligner, GPT/Astra review and translation, Qwen3-TTS, Qwen3-ASR screening, deterministic scheduler, FFmpeg, Firebase and Web/iOS validators
Constraints: models are tools, not the source of truth; show human gates; text-only release passes Layer 3 as audio_unavailable; Sunday live is a separate lane; no logos or watermark
Avoid: 3D effects, dark background, decorative religious symbols, people, illegible tiny text, extra stages or a circular workflow
```

内置工具返回的原始 PNG 保存在 Git 忽略目录：

`artifacts/diagram-refresh-four-layer-20260920/four-layer-workflow-reference.png`

生成图只作为构图和颜色参考。最终文字、模型职责、完成状态和连接关系均依据[四层接口](../multilingual-production-interfaces.zh.md)、[本地生产 Runbook](../codex-local-production-runbook.zh.md)及各层 schema 重写；未直接嵌入生成 PNG。

## 正式产物

- [four-layer-production-workflow.svg](four-layer-production-workflow.svg)：原生可编辑 SVG，四层分别展示输入、流程、模型／工具、输出与门禁。
- [tongxing-video-to-page.html](../tongxing-video-to-page.html)：中英双语响应式解释页，展开每个模型的职责和硬边界。
- [diagram-specs.json](diagram-specs.json) 与 [render_diagrams.py](render_diagrams.py)：可复现 SVG 来源。

## 2026-09-21 模型与音频指纹补充

再次对照当前生产入口、周日 live 路径和每周发行代码后，补入此前图中被压缩的职责：GPT-6 Astra 还承担英文校订／断句、中文阅读版两轮编辑、证道同行大纲及 CUV 相关重译／复核；Sunday live 当前默认模型链为 Qwen3-ASR + MiLMMT Q8，仍保持为独立 `live_session`。

原声音频指纹生成改为明确归属 Layer 3：使用 Layer 1 原始录制／批准窗口和 Layer 3 实际同步音轨，通过 FFmpeg 与确定性频谱地标算法生成并绑定索引。Layer 4 只发布该索引并由 Web/iOS 本地消费约 10 秒麦克风采集进行匹配；麦克风声音不上传、不保存。当前 legacy `build_weekly_app.py` 仍代为触发生成，文档明确把这一代码位置列为待迁移边界，而不是改变层级职责。本次没有重新调用 ImageGen，沿用原始视觉参考并更新原生 SVG／HTML 事实内容。

## 事实边界

- Layer 1 producer 已进入 shadow；没有英文人工审核收据时不能进入正式 Layer 2。
- 通用 Layer 2–4 producer 仍在迁移；现有中文工具属于 legacy adapter。
- 韩语和西班牙语分别走英文主干，不以中文为中转；真实翻译、TTS、同步和发布须各自验收。
- Sunday live 是独立 `live_session`；Supervisor Agent 只编排，不能自授人工批准或把旧 `complete` 升级为 `four_layer_release`。

## 验证

- `diagram-specs.json` 通过 JSON 解析；`render_diagrams.py` 通过 Python 编译，并可重复生成 12 张原生 SVG。
- 新 SVG 通过 XML 解析及 Quick Look 实际渲染；长 package/status 文本调整换行后，四层卡片、语言分支和两条边界栏均在画布内。
- HTML 内嵌脚本通过 Node 语法检查；本地 HTTP 实际返回 HTML 与 SVG。
- Codex in-app browser 在 1440×1000 和 390×844 两种 viewport 完成英文／中文切换、四层 DOM、图片加载和水平溢出检查；文档宽度分别等于 viewport，手机端仅模型表自身保留可滚动宽表，没有页面级横向溢出；控制台无 warning/error。
- 这是图表与文档验证；没有运行翻译、TTS、部署或现场播放。
