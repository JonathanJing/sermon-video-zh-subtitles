# Sol high fast 与既有翻译组对比

2026-10-05，太平洋时间。在[三臂实验](20261005-astra-sol61-high-low-translation-ab.zh.md)基础上增加 GPT‑6.1 Sol high fast，复用既有 Astra medium、Sol high default 和 Sol low default 全部输出。相同三分钟样本共 39 个英文单元、13 组；本次只新增 13 次 high fast 初译。

**High fast 累计耗时 181.61 秒，相比普通 high 节省 42.32%，比 low 慢 13.30%；本轮未观察到相较普通 high 的明显质量下降。** 这是单批、不同时间调用的观察，不能直接解释为 fast 档位的稳定因果收益。正式生产配置没有改变。

## 速度与用量

| 指标 | Astra medium | Sol high default | Sol low default | Sol high fast |
| --- | ---: | ---: | ---: | ---: |
| 累计初译进程耗时 | 144.15 秒 | 314.87 秒 | 160.30 秒 | 181.61 秒 |
| 单组中位数 | 11.12 秒 | 25.66 秒 | 12.55 秒 | 14.12 秒 |
| 单组最小至最大 | 8.42–13.77 秒 | 15.39–29.12 秒 | 9.27–17.80 秒 | 9.45–18.48 秒 |
| 输入 token | 210,723 | 211,499 | 211,410 | 211,408 |
| 其中缓存输入 token | 24,576 | 24,832 | 12,416 | 49,664 |
| 输出 token，包含推理 | 2,916 | 7,162 | 2,879 | 7,308 |
| 其中可见推理 token | 0 | 4,286 | 0 | 4,409 |

Fast 在 13 组全部比旧 high default 快，在 3 组比旧 Astra 快。累计比 Astra 慢 25.98%。Fast 仍为 high 推理配置，其可见推理 token 与普通 high 接近，不是 low 组改名。

Fast 的缓存输入比例为 23.49%，普通 high 为 11.74%，low 为 5.87%。服务负载、调用时间与缓存分布都未控制，不能把全部提速归因于 fast。耗时含 CLI 启动、排队、推理与输出，累计数为各进程耗时之和，不含盲评。没有费用或订阅扣额回执，本报告不做成本排名。

## 翻译质量与评审尺度

新的独立子 Agent 仅读取匿名 A/B/C/D 文件，位置逐组轮换；先评 6 组，再评剩余 7 组，结束后才映射模型。该评审把 13 组全部判为四版并列，未标记中等或重大实质问题。没有观察到 high fast 比普通 high 新增明显遗漏、否定、数字或人名错误；同义词与口语组织差异没有被强行排序。这仍是单次机器判断，不构成人工审批或统计质量证明。

| g012 英文 | Astra medium | Sol low | Sol high | Sol high fast |
| --- | --- | --- | --- | --- |
| `He oversees everything.` | 祂看顾着一切。 | 祂看顾着一切。 | 祂统管着一切。 | 祂统管着一切。 |

此前双臂和三臂评审将“看顾”列为一处中等局部语义偏移：宝座与掌管一切的语境强调治理，而“看顾”偏关怀。本轮评审也承认词义侧重不同，但认为前一句已经保留“掌管一切”，因此整段仍可接受，未列中等错误。原评审收据全部保留，不覆盖为统一结论。

主 Agent 对照原文仍认为“统管”更贴近该句治理含义。High fast 保留了普通 high 的这项具体措辞优势；错误严重性和是否足以拉开整体质量，机器评审并未达成一致。因此不以“通过组数”宣称某臂绝对更好。

样本主要涵盖 AI、新技术的乐观与悲观、电报历史以及《启示录》开场，没有直接经文引用。未核查讲员历史断言，也不能据此推广到长篇讲道、完整经文或其他语言。

## 配置与验证

使用 ChatGPT 登录的 Codex CLI，配置为 `gpt-6.1-sol`、`model_reasoning_effort="high"`、`service_tier="fast"` 和 `--enable fast_mode`。与旧 high 相比，翻译输入、上下文、术语、prompt、JSON schema、顺序执行和无工具约束相同；13 份完整提示词与旧 high/low 逐字节一致。Fast 看不到其他译文。

13 次新调用退出成功，组及源单元身份、schema、coverage、独立会话、无工具事件、命令和收据均核验。baseline fingerprint、实际 CLI 二进制及冻结 runner hash 也通过。相同 fast identity 实际续跑得到 **13 次缓存复用、0 次新增模型调用**；fast 缓存冒充 default 被拒绝，既有 26 组 default Sol 缓存验证仍通过。

CLI 返回的信息只证明请求模型和请求配置，未返回服务端实际模型或服务档位。因此准确说法是“请求 high fast 的成功调用及其观测耗时”，不能声称另有服务端 fast 交付回执。

原始产物在 Git 忽略目录 `artifacts/codex-astra-medium-sol61-high-fast-ab-20261005/`，包含冻结脚本、提示词、command/schema、CLI events、收据、匿名四臂文件和映射。机器统计与 hash 见[实验收据](20261005-sol61-high-fast-translation-ab-receipt.json)，工具见[实验脚本](../../scripts/experiments/codex_translation_ab.py)。本次增加 `--tier default|fast`，默认仍为 default，缓存身份包含档位。

报告链接、JSON、产物 hash 与 `git diff --check` 已核验。这个样本支持将 high fast 作为后续保持 high 推理配置而降低观测耗时的候选；若要决定正式生产档位，还应同期交错重复测量，分离缓存和服务负载影响。
