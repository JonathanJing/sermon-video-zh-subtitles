# Prompt、AGENTS 与 Skill 审计修复

2026-09-12。根据 [Rethinking skills and prompts for GPT-6 Astra](https://developers.openai.com/blog/rethinking-skills-and-prompts-for-gpt-6-astra) 的按需上下文、明确完成条件和决策边界建议，修复当前工作区。用户确认继续生成两个 PDF：`sermon_zh_en_reading.pdf` 和 `sermon_interpretation_zh.pdf`。此次未更换工作负载模型，未执行真实模型生成、生产、发布或 Git 提交。

## 已实施

| 优先级 / 审计项 | 实际变更 |
|---|---|
| P1 同行范围与验收 | [prompt](../scripts/review_prompts.py)、[生成器](../scripts/generate_notes_with_openai.py)和[PDF QA](../scripts/render_sermon_interpretation_pdf.py)统一到 notes schema v3 / `sermon-companion-v3`。删除生成式讨论题、指南与祷告字段；取消可选内容最低配额，保留核心内容、来源与精确引文校验。 |
| P2 提前结束 | [Supervisor](../scripts/run_sermon_production_supervisor_agent.py)为 SDK/API 提供各自真实字段契约。[API 提交工具](../scripts/sermon_agents_supervisor.py)重新检查并拒绝尚有未尝试可执行阶段的最终提交；host 同时阻断提前完成。失败已尝试阶段可恢复停止，每阶段一次、审批和 lease 不变。 |
| P2 上下文冲突 | [content pack](../experiments/local-live-poc/backend/content_pack.py)只注入当前源文匹配的已审术语/经文，同词高相关项优先；保留 cursor 与参考片段顺序、来源信息及 A0。 |
| P2 exact-only 文档冲突 | [POC AGENTS](../experiments/local-live-poc/AGENTS.md)按已有 DESIGN/README 明确受限 A2 参考例外：最多两条、分数至少 1.5、已审且只作另一版本参考；不代表现场验收。 |
| P2 fallback 重提取 | [SKILL](../skills/live-caption-zh-fallback/SKILL.md)优先从已有报告构建预览；新来源使用独立目录。自动发现 VOD 也要核实同篇与偏移。已有文件单独上传，不为发布再次提取。 |
| P2 部分字幕误报 ready | [翻译](../scripts/translate_playback_with_openai.py)与[稳定化](../scripts/stabilize_realtime_deltas_with_openai.py)校验重复/未知 ID 与非空文本。缺失 cue 保留部分产物，状态 `partial`，CLI 返回 3 且不自动发布。翻译续跑使用 raw cue ID，不使用展示层重分段 ID；模型不能改写输入经文/注释。 |
| P2 单篇审校规则 | [旧审校工具](../scripts/review_sermon_subtitles_with_openai.py)移除固定讲员、经文表、按 ID 覆盖及固定 1545 秒偏移；保留原始英文。绝对时间导出须传已核实的 `--sermon-start-seconds`，省略则仅导出相对字幕。人名消歧限于明确身份上下文。缓存绑定完整请求内容，校验通过后才写入。 |
| P2 过期定时说明 | [中文 Supervisor 文档](sermon-production-supervisor-agent.zh.md)区分 2026-09-11 初查与后续创建回执；判断当前健康须另读实时状态，不能按旧说明重复创建。 |
| P3 文档测试范围 | [iOS AGENTS](../apps/tongxing-ios/AGENTS.md)拆开文档与 CLI 验证，纯文档不再触发 Xcode dry-run。 |

## 兼容与恢复

- 两份 PDF 文件名、生产入口和完成门禁保留。notes v3 仅适用于新生成，旧 v2 保留原内容及来源验收，不重标旧产物、不重做已完成周次。
- PDF QA 报告升级为 schema v3，记录输入版本与质量规则版本。未知输入版本、v3 携带旧练习字段、无效来源或伪引文均不能通过。
- 字幕输出结构保持兼容，新增失败完成状态 `partial`。有效条目保存在输出中，缺失内容不能计作完成；旧实时循环可逐条消费有效 correction，整体 JSON 仍保留部分状态。翻译工具会保留已有成功 raw cues，后续只选择剩余项。
- 审校缓存使用新 prompt 版本和完整输入摘要，旧缓存不会误命中。已有损坏缓存报出路径，核验后移开再续跑；无效新响应不写缓存。
- 所有人工审批、来源/hash、录音独立持久化、机器审核不等于人工 Gold、真实现场与回放证据边界保留。

## 验证

定向验证覆盖 Supervisor 三个既有模块和 API/client、notes/同行与阅读 PDF、字幕转换与旧实时循环、content pack/replay/Gateway；没有扩大为全量模型或硬件运行。新增回归包含：提前提交后继续两阶段、审批/等待/失败不重复执行、部分输出续跑、无效 ID/类型、来源字段保留、缓存污染、人名误触发及上下文冲突。

通过的模块计数：Supervisor/API 116、notes/双 PDF 48、POC context/replay/Gateway 31、旧字幕与播放 66、post-live 编排 21，共 282 项（重复复跑不累加）。`git diff --check`、56 条本地链接与 skill discovery symlink 检查通过。Skill Creator 的 Python validator 因环境缺 PyYAML 未能启动；改用系统 Ruby Psych 解析 YAML，并核验同一 frontmatter 的字段、命名、长度和未完成占位项，全部通过，未修改依赖环境。

合成双 PDF 位于本地忽略目录 `output/pdf/prompt-audit-v3/`，各一页、QA pass，完整 PNG 均已查看，无裁切、重叠或缺字；同行文本不含讨论节。其 SHA-256、版本与限制记录在该目录 `verification.json`。这些证明本地生成及验收行为，不证明真实模型语义质量、长篇分页表现、远端 Agent 运行或现场可用性。

本次修改后的真实内容验证可在下一次已授权生产时，沿现有人工窗口审批和双 PDF QA 执行；live context 语义收益需使用同源录音固定 A/B 与人工评审，不以模板断言替代。

## 提交边界

本次提交包含 Supervisor 修复所需的 Agents API client/adapter、入口参数转发及计量兼容；这些前置文件在审计时尚未跟踪。SDK 可由 `--agent-backend sdk` 显式选择。其余工作区中的 lease、Temporal、配音、界面、术语和生产恢复变更不在此次提交范围。上述测试记录是审计工作区验证，提交前另在 HEAD 干净快照上验证实际选入文件，避免依赖未提交工作。

提交候选干净快照：根目录定向 281 项通过，POC 定向 31 项通过；快照只叠加实际提交文件，没有引用工作区未提交的业务代码。Gateway 测试使用本机随机端口模拟服务。
