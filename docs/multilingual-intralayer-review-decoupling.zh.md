# 四层内的局部审核与增量失效设计

状态：**第一阶段代码已实现并通过合成测试；真实整篇验收尚未完成**。现有 v1/v2 正式包仍按完整来源、完整 locale candidate、完整音轨门禁运行；本文不授权未审核段进入正式 TTS 或发布。第一阶段保存段级人审收据；跨候选复用默认按整候选失效，审核者明确确认无跨 block 依赖时才允许保留未变 block 的决定。整语言全部获批后聚合成原正式收据；Layer 3 可在新完整 speech job 已通过人审门禁后复用未变单元的原始音频。段级审核尚不能使其他已审段在同语言待审时进入正式 TTS。

## 先区分三个状态

| 状态 | 含义 | 能否复用或继续 |
| --- | --- | --- |
| 单元已审 | 某个稳定 source/translation/audio 单元的内容及其明确上下文已获人审收据 | 可准备此单元的下一步候选；不代表整篇已审 |
| locale 已齐 | 本 locale 所有必需单元均已审，覆盖、顺序、跨段衔接与整轨同步检查通过 | 可形成正式同 locale 包 |
| page 可发布 | 本次要求的全部 locale 包、页面信息与发布目标均符合政策 | 可进入 Layer 4 部署和 HTTP 核验 |

一段的人审决定只作用于该段及**声明的依赖范围**；`locale 已齐` 是聚合结果，不应成为启动其他已审段计算的条件。本次 Dev 发布仍要求中文、韩语、西语三条正式音轨齐全。

## 当前实现的耦合点

1. Layer 1 的 `downstreamInvalidationKey` 改变会令全部 locale 失效；媒体或批准窗口变化确实应全局失效，但单个英文词／时间修订也被同样处理。
2. Layer 2 的 v2 candidate 和独立正式人审收据要求全部 group ID 按序获批。`approve-batch` 只降低完整审核后的填表成本；新增 `record-group` 可局部留证，`approve-groups` 只在全部有效组获批后聚合。正式 speech job 仍拒绝任一未审 group。
3. Layer 3 renderer 的原始单元缓存身份包含整个 job 与 candidate 的哈希。新增显式 `--reuse-from` 验证旧 intent、commit、音频 hash、完整解码及除整包 hash 外的全部单元渲染身份，再把未变 WAV 复制到新 job 并生成新单元收据；变更单元重新合成。整轨、排程、字幕和全文听审收据仍需重新生成与审核。
4. Layer 4 的正式三语 stage 要求三个 locale 的全部已审文字和音频；这是发布汇合点，不应反向阻塞各层内部的候选准备。

## 目标依赖图

```text
媒体 hash + 批准窗口（全局门禁）
  └─ English unit + 句界/上下文依赖 → L1 单元审核
       ├─ zh-Hans group → L2 单元审核 → TTS 单元 → L3 单元听审 ┐
       ├─ ko group      → L2 单元审核 → TTS 单元 → L3 单元听审 ├→ locale 整体覆盖、排程与衔接
       └─ es group      → L2 单元审核 → TTS 单元 → L3 单元听审 ┘     → 三语发布汇合
```

单元审核身份至少包含 `media/window identity`、`sourceUnitIds`、该范围的英文文字与时间／句界 hash、明确的上下文依赖 hash、`targetLocale`、翻译策略 hash、目标文字及分组边界 hash、审核者和时间。它**不以整份 candidate 的 hash 作为唯一复用键**。模型复核和人工决定分开存放，状态为 `pending | approved | rejected | invalidated`。拒绝或缺失只阻止受影响单元；不自动把机器结论升级为人工批准。

## 四层内的失效范围

| 变化 | 保留 | 失效并重算 |
| --- | --- | --- |
| 媒体、批准窗口或全局策略改变 | 原始证据仅供追溯 | 所有相关单元及其下游 |
| 一个英文单元的文字、时间或句界改变 | 无依赖的其他英文单元与目标语言审核 | 该单元、引用它的翻译组及显式上下文邻接；拆分／合并时所有涉及组 |
| 某 locale 的一个翻译组改变 | 其他 locale；本 locale 无依赖组的已审文字和原始音频 | 该组文字审核、TTS、音频审核，以及可能受其时长影响的排程区间 |
| 一个 TTS 单元或时长改变 | 其他原始音频单元及其声学审核 | 该单元听审；从该单元至下一个独立时间锚的排程、字幕与衔接审核；新整轨 hash |
| 仅页面信息改变 | Layer 1–3 | 对应 locale 页面内容与 Layer 4 发布候选 |

跨段经文、否定、指代、术语或句界可能把多个单元连成一个审核域。默认先按段落／block 建立保守上下文依赖；依赖不能证明独立时扩大失效范围，不静默复用。音频单元可独立合成，排程却可能因前段时长改变而影响后段；不得把音频缓存可复用等同于同步审核可复用。

## 迁移步骤与验收

1. **已实现，待真实整篇验收：** 增加版本化的 group-review receipt sidecar。审核身份绑定完整 Layer 1 来源和 policy，单元 row 及上下文；默认 `whole_candidate` 还要求与原整份候选 hash 完全相同，只有明确提供 block 独立性人审说明才使用 `connected_blocks`；未知 source ID 格式拒绝 block 范围，必须改用整候选。`record-group` 只写审核者给定的单组决定；一组待改不删除其他有效收据。
2. **已实现，待真实整篇验收：** `approve-groups` 验证每组收据、来源／policy、上下文和同一审核者，缺组、拒绝、修订后的旧收据全部 fail closed，再输出原有 `human_translation_approved` 包、独立收据和段级聚合清单。当前正式包只容纳一个 reviewer，混合审核者仍需新版本 schema。
3. **已实现合成测试，待真实音频 A/B：** renderer 通过 `--reuse-from <old-render-dir>` 显式读取旧原始单元。旧证据／字节损坏时停止；身份不同时正常重新合成。新 job 仍须先通过现有完整文字、人审、音色和授权校验；旧排程／字幕／整轨／听审收据绝不复用。
4. Layer 3 将单元听审与整轨排程／衔接审核分开记录。先保留当前“新整轨全文听审”门禁；是否改为仅重听变更段及连接处，须用真实整篇对照、漏读检出率和审核者确认后另行修订合同。Layer 4 仍要求完整、同 hash、已审的正式包。

操作时先用现有 `review_target_language_candidate.py prepare` 展示完整候选；审核者只对亲自检查的组运行 `record-group --group-id <id> --decision approved|rejected --evidence <说明> --reviewer <姓名> --reviewed-at <带时区时间> --out <新收据文件>`，并传入与 `prepare` 相同的 source、anchor、candidate、policy。默认任何其他组修订都会令此收据失效；审核者检查跨段指代、引文和语义上下文后，才可附加 `--context-scope connected_blocks --context-evidence <无跨block依赖的具体说明>`。修订后对当前候选运行 `approve-groups --group-receipt <已审组收据>`（每组一次）和同样四个输入；过期组会被拒绝。得到完整 speech job 后，renderer 可选 `--reuse-from <旧渲染目录>`，仅复用身份相同且旧字节、旧 intent/commit 完整的单元。

验收 fixture：一组待审时其他组的已审收据仍有效但正式整包拒绝；修改某组后其他 block 可复用且本 block 失效；英文窗口变化全局失效；拆分／合并不遗漏组；跨 locale 不串用；TTS 单元复用不跳过排程与最终音轨审核。真实整篇还须记录复用率、返工时长和人工等待时间，再决定是否升级为新的正式 schema 或允许已审组提前合成。
