# Translation unit A/B：2026-09-04

**结论：不将 `bounded_semantic_v1` 提升为默认。** 合并修复了一些断句造成的语义错误，也引入了否定、因果和经文关系的严重退化。保持 `legacy` 默认，候选仅用于后续独立评估。

## 样本、方法与证据边界

- 输入为现有 session 的 **开发切分集**：429 个 immutable ASR finals，经候选聚合为 387 个单位；本轮只比较发生变化的 **42 个单位 / 84 个原始 finals**。
- A：每个原始 final 单独翻译；B：对应合并英文翻译。总计 **126 次真实 MiLMMT 请求，126 次完成、0 次失败；总耗时 51.425 秒**。
- 相同模型、官方 A0 prompt 和参数，顺序调用；先跑 `rarely` 例，再按原顺序运行其余单位。没有运行 ASR、Gateway、麦克风或浏览器。
- **这是机器辅助评阅，不是 human Gold，不是盲测，也不是独立留出测试。** 样本已被用于开发聚合规则；以下例子是有意选择的诊断材料，不能据此声称总体准确率提升。
- 原始 ASR 中已有错词与未完成句。合并不能修复这些事实来源错误，流畅中文也不代表忠实。

| 冻结项 | 值 |
|---|---|
| Source events SHA-256 | `55c34501716e891e93aa544d2aa6727f62dc1ef639a2aae2f1d3ebb14140e431` |
| Assembly input SHA-256 | `1a141e53cd2538a3020ce522dc1f2db4622333eda28e00138ffd48c63996f756` |
| Model | `sermon-milmmt-46-4b-v1-q8:benchmark` |
| Model digest，运行前后相同 | `e607c5905ff664410afc93961c9a44e19b0429602b2897ac17e362cbb0895b96` |
| Ollama | `0.33.3` |
| Prompt version | `milmmt-46-official-english-to-chinese-simplified-v1` |
| Context / request | `none` / `raw=true`, `stream=false` |
| Decode options | `temperature=0`, `top_p=1`, `top_k=1`, `repeat_penalty=1`, `seed=42`, `num_predict=256` |
| Result JSONL SHA-256 | `4ed6bf3b792570aee6e5b3bf1fad32590539a78f3efcc287c4427f7ed10d4f3e` |

## 三个改善例子

### `unit-seg-000082--seg-000083`：恢复否定范围

- A 原文：`But sometimes the source of our anger isn't.` / `Really clear because it's just the reality.`
- A 输出：`但有时我们的愤怒并非源于此。` / `这非常清晰，因为这就是现实。`
- B 原文：`But sometimes the source of our anger isn't Really clear because it's just the reality.`
- B 输出：`但有时我们愤怒的根源并不真正清晰，因为它只是现实的反映。`
- 判断：`isn't really clear` 的否定关系恢复；不代表整句已获人审。

### `unit-seg-000136--seg-000137`：`rarely` 重新连接补语

- A 原文：`Buried anger is rarely.` / `Dead anger.`
- A 输出：`埋藏的愤怒很少见。` / `死气沉沉的愤怒。`
- B 原文：`Buried anger is rarely Dead anger.`
- B 输出：`埋藏的愤怒很少会变成死气沉沉的愤怒。`
- 判断：避免将“埋藏的愤怒”本身说成少见；“变成 / 死气沉沉”仍生硬，改善是局部的。

### `unit-seg-000187--seg-000188`：火与愤怒的比喻

- A 原文：`Was throwing more wood on the fire of my.` / `Own anger.`
- A 输出：`我把更多的木柴扔进了火堆里。` / `自己的愤怒。`
- B 原文：`Was throwing more wood on the fire of my Own anger.`
- B 输出：`这无异于是向我自已的怒火上添柴加油。`
- 判断：把割裂的实物描述恢复为愤怒的比喻；引文保留模型的“自已”原字。

## 三个退化例子

### `unit-seg-000408--seg-000409`：否定与因果关系改写

- A 原文：`No, he's not suppressing his anger because he actually wrote a psalm, but he's not.` / `In Babylon, just expressing his anger to.`
- A 输出：`不，他并不是在压抑自己的愤怒，因为他确实写过一首圣诗，但他并没有这样做。` / `在巴比伦，他只是表达了自己的愤怒。`
- B 原文：`No, he's not suppressing his anger because he actually wrote a psalm, but he's not In Babylon, just expressing his anger to.`
- B 输出：`不，他并不是因为真的写了一首圣诗才压抑自己的愤怒，而是因为他不在巴比伦，所以只是把愤怒发泄出来而已。`
- 判断：B 重新组织了 `not / because / but`，将“不在巴比伦”变成解释原因；A 也不完整，不能因此接受 B 的额外推断。

### `unit-seg-000422--seg-000423`：凭空生成书名

- A 原文：`We, the modern reader, struggle with.` / `With divine vengeance, we struggle with a.`
- A 输出：`我们这些现代读者对此感到困惑。` / `在神的审判之下，我们挣扎着前行。`
- B 原文：`We, the modern reader, struggle with With divine vengeance, we struggle with a.`
- B 输出：`我们这些现代读者，在《神圣的复仇》这部作品中，与一个难题作斗争。`
- 判断：B 凭空把 `divine vengeance` 解释为作品名称。

### `unit-seg-000382--seg-000383`：并列经文关系改写

- A 原文：`Happy is the one who pays you back what you've done to.` / `Happy is He who takes your little ones.`
- A 输出：`善待他人，善待他人所做的一切。` / `收留你们孩子的人是幸福的。`
- B 原文：`Happy is the one who pays you back what you've done to Happy is He who takes your little ones.`
- B 输出：`对你行善的人是幸福的；对你行恶的人就是夺走你孩子的人。`
- 判断：A 已误译；B 又将两个 `Happy is` 关系重写，并加入本输入没有的“行善 / 行恶”，属于不可接受的额外推断。

## 耗时与后续门槛

| 指标 | P50 | P95 |
|---|---:|---:|
| 原始单段请求 wall time | 302 ms | 588 ms |
| 两个原始请求 wall time 总和 | 601 ms | 974 ms |
| 合并请求 wall time | 533 ms | 777 ms |
| 按开发 ASR 事件时间戳模拟的合并等待 | 2,995 ms | 3,016 ms |

请求 wall time 包含当时的模型加载、缓存和主机状态，**不能视为现场 E2E 延迟**。合并等待来自离线时间戳模拟，不含模型排队；一次合并调用稍省总计算，并不能抵消模拟中第一段约 3 秒的额外等待。后续应分别评估真实音频分段和合并策略，在独立音频、人审文本与盲评上检查否定、代词、经文、增译及首段等待，不能从本轮提升默认。

完整逐项结果、逐请求 prompt/参数/完成 receipt、runner 和机器评阅保存在本机被忽略的 `artifacts/benchmarks/sunday-readiness/semantic-model-ab*`；Git 仅保存本报告的紧凑证据与判定。
