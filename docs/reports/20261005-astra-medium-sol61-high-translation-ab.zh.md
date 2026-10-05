# GPT 6 Astra medium 与 GPT 6.1 Sol high 翻译对比

2026-10-05，太平洋时间。本次复用已生成的三分钟英文讲道样本及 Astra medium 原始初译，只新增 13 次 Codex CLI Sol high 独立初译。**Sol high 有局部质量优势，但累计耗时为 Astra 的 2.18 倍；这个样本不足以支持全面替换初译模型。** 正式生产配置与候选审批没有改变。

## 输入和方法

同一 `zh-Hans` 样本共 39 个英文单元、13 组，来源媒体时长 180.013167 秒。旧稿取自 `artifacts/codex-cli-layer2-180s-20261005/`，每组使用 `group-*-astra.raw.json` 内的初译，未使用旧 Sol 审校稿。所有 baseline 的 payload 加 transport identity 指纹均重新核验通过。

两臂使用完全相同的英文、上下文、术语、翻译指令、CLI no-tools 包装及 JSON schema。新增调用使用 `gpt-6.1-sol`、`model_reasoning_effort="high"`、`service_tier="default"`；旧 Astra 为 `gpt-6-astra`、medium、default。两臂均顺序执行，使用 ChatGPT 登录的独立 CLI 会话；Sol 看不到 Astra 译文。CLI 版本与实际二进制 hash 和 baseline 相同。CLI 参数用法参照 [OpenAI 官方 Codex 示例](https://developers.openai.com/cookbook/examples/codex/build_iterative_repair_loops_with_codex)。

质量评审由独立子 Agent 仅读取匿名 X/Y 对照进行，逐组交替摆放两臂，评审结束后才映射模型。评审分为首批 7 组和剩余 6 组，核对忠实度、遗漏增义、否定、数字人名、语境词义与口语自然度。这是一次机器盲评，不是人工审批，也不是外部评审服务的独立验收。

## 速度

| 指标 | Astra medium 旧记录 | Sol high 本次调用 |
| --- | ---: | ---: |
| 初译组数 | 13 | 13 |
| 累计 CLI 进程耗时 | 144.15 秒 | 314.87 秒 |
| 单组中位数 | 11.12 秒 | 25.66 秒 |
| 单组最小至最大 | 8.42–13.77 秒 | 15.39–29.12 秒 |
| 配对组更快次数 | 13 | 0 |
| 输入 token | 210,723 | 211,499 |
| 其中缓存输入 token | 24,576 | 24,832 |
| 输出 token，包含推理 | 2,916 | 7,162 |
| 其中推理 token | 0 | 4,286 |

累计耗时比为 2.18，中位数比为 2.31。耗时包含 CLI 启动、排队、推理与输出；累计数是 13 个初译进程耗时之和，不是原三分钟媒体的播放时长，也不包含质量评审。CLI 用量中的推理 token 是可见计数，不代表完整内部计算量。

两臂缓存输入比例接近，分别约 11.66% 和 11.74%。但这是历史 baseline 对新调用，未做同期随机交错或多次重复；服务负载、时间与缓存分布仍可能影响结果。只能说本次样本 Sol 更慢，不能将倍数推广为稳定模型延迟。未估算订阅调用的美元价格。

## 翻译质量

| 判断 | Astra medium | Sol high |
| --- | ---: | ---: |
| 盲评占优组数 | 1 | 4 |
| 打平 | 8 | 8 |
| 发现的中等局部语义偏移 | 1 | 0 |
| 发现的重大错误 | 0 | 0 |

占优组：Sol 为 g001、g007、g009、g012；Astra 为 g006。前三个 Sol 优势与 Astra 优势主要是轻微语气、原文重启句处理或口语表达差异。g012 的差异涉及上下文关键词义，不能只用胜组数评价。

| 英文及组 | Astra 原稿 | Sol 原稿 | 评审依据 |
| --- | --- | --- | --- |
| `He oversees everything.`，g012 | 祂看顾着一切。 | 祂统管着一切。 | 前文为宝座和掌管一切，后文为人类发明不能掌控事态；“统管”更准确。“看顾”偏向关怀保护，局部弱化统辖含义。 |
| `the heir apparent ... over Austria-Hungary`，g009 | 法定继承人 | 王储 | Sol 更清楚地表达王位继承语境，口语也较自然；Astra 不是实质身份误译。 |
| `We're in a dystopian view`，g006 | 转向了反乌托邦式的悲观 | 看法变成了反乌托邦式的 | Astra 表达较完整，Sol 的“的”收尾略悬空；这是风格差异。 |

主 Agent 对上述证据重新对照原文，接受这个局部判断。13 组均保留了核心论点、数字和否定；“检查通过”不等于已经人工逐句认可。样本主要是 AI、电报历史与《启示录》开场，没有直接经文引用，不能据此判断整篇长讲道、完整经文、韩语或西语能力。没有修正或验证讲员的历史叙述，评审目标是忠实翻译。

## 产物和验证

原始输出、CLI events、提示词、schema、command、收据、匿名对照和映射位于本机 Git 忽略目录 `artifacts/codex-astra-medium-sol61-high-ab-20261005/`。可机读统计与 hash 见[实验收据](20261005-astra-medium-sol61-high-translation-ab-receipt.json)，实验工具见[脚本](../../scripts/experiments/codex_translation_ab.py)。

本次真实运行使用的脚本保留为产物目录中的 `frozen-runner.py`，其 hash 与原 identity 一致。后续审查补强了当前脚本的缓存收据、原始 command/schema、baseline fingerprint、二进制身份与缺失汇总恢复；不覆盖原实验 identity。

实际验证包括：13 次新 Sol 调用退出成功；schema、组和源单元身份、coverage 全部通过；会话独立且无工具调用；13 组 baseline 的 prompt/response 绑定通过；当前脚本重新检查了全部 13 组缓存及 exact command/schema。汇总恢复改动用真实缓存的临时副本验证了零模型调用重放、缺失 blind/summary 修复；篡改缓存结果与冲突汇总均被拒绝。已执行 `git diff --check`。

同版本、同目录的成功缓存可续跑；未知 started 结局禁止自动重试。脚本升级后严格身份会拒绝旧输出目录，应保留冻结脚本和原收据，不要改 identity 冒充同次运行。模型身份是 CLI 请求身份；CLI 没有返回服务端模型字段，不能声称另有服务端身份回执。

本次决策是保留现行生产策略。Sol high 的局部改进可支持进一步针对神学词义和长文本的实验，但目前没有证据说明其质量收益值得所有初译统一付出约两倍耗时。
