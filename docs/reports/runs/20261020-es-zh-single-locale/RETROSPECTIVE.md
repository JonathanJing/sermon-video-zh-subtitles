# 复盘：20261020 es/zh 三语尝试与单语发布

数据见同目录 `INDEX.md` 和 `manifest.json`；原始产物在忽略的 `artifacts/` 下。

## 结论先行

- 逐组编排与报告（PR #1206–#1210）已合并；本轮新增代码在 draft PR #1218。
- es 完整 L3、zh 完整 L3、es 单语新一轮全部跑通；ko 音频 QC 始终停在
  `translation-chunk-0005-u007`，三语发布未完成。
- 单语发布**实际跑通**：`mockup-dev-clip-20261020-es-solo-v2` 已在 live v4 目录，
  `targets={es}`，HTTP 200；发布后首次浏览器 smoke 中 es 通过。
- 累计结算 **$1.674**（批准总额 $8），无未结算付费调用。

## 时间线

| 阶段 | 事件 | 结果 |
|---|---|---|
| 1 | 合并 #1206–#1210；es 完整 L3 | 通过；$0.299；机器音频豁免 |
| 2 | 三语 L4 prepare | 成功；Dev 发布被“必须三语”拒绝 |
| 3 | ko seed 42/43/44 | u007 反复 `requires_repair`；seed 44 遇 HTTP 503 |
| 4 | zh L3 | 音频 QC pass；机器豁免因 `dropped_key_word` 校准覆盖被拒 |
| 5 | zh 人工听审 | 记录 human_reviewed 收据 |
| 6 | 账本 v5 | 503 对账为确定性失败；测试通过 |
| 7 | ko 文本 QC 重跑 | 新豁免签发；音频仍卡 u007 |
| 8 | 单语代码修复 | 诊断页允许 1–3 语 |
| 9 | es 单语新一轮 | 文本+音频 QC 全过；$0.658 |
| 10 | Dev 发布 | 412 → 发现部署已成功 → reconcile |
| 11 | catalog overlay | 页面进入 live v4 目录，`targets={es}` |
| 12 | smoke | es 曾 pass；之后 observer 报错 |

## 数字

- es 完整 L3：render 94s / compact 17s / screen 36s / package 5s / audio QC 280s；239 次 API。
- zh：$0.360；音频 QC pass，机器豁免被校准覆盖拒绝；人工收据已记录。
- ko：$0.357；seed 42/43/44 均失败于同一单元；503 对账 $0。
- es 单语：$0.658；音频豁免 `935a37aa…` 已签发。
- 总计：**$1.674**。

## 技术根因

1. **三语假设散落 5 处**：`run_dev_simulated_delivery`、`baseline.asset_first`、
   `bound_release_plan`、`machine_checked_overlay` 的目标数、smoke 默认 locale。
   逐个撞门、逐个补，造成 4 轮返工。
2. **豁免绑定实现哈希**：生产出 es/ko 豁免后又改代码，旧豁免立即失效，被迫重跑
   文本/音频 QC。代码变更与付费产物交错是最大浪费源。
3. **发布失败分类缺失**：firebase CLI 在“实际已部署”后因本地配置写权限退出 2，
   系统记为 `outcome_unknown`，随后 lease 导致 412；`reconcile` 只覆盖“已成功但
   未知”，没有“部署前失败”的放弃路径。
4. **账本无确定性失败终态**：一次 503 就能永久阻塞；v5 已补 `failed_definitive`。
5. **run 目录被反复移动/删除**：workflow、baseline、prepared 挪来挪去，预算身份、
   远端输出名、attempt 反复失效。

## 流程根因（代理侧）

1. 没有先全局侦察 locale 硬编码，而是撞一个修一个。
2. 在“脏”run 目录上反复修复；正确做法是代码冻结后新建干净 run，旧目录只读。
3. 先产出 L3 豁免、再改代码，导致豁免失效重跑。
4. 破坏性清理（删除 `l4/work` 与 prepared 产物）丢掉证据并重建。
5. 进度估计过于乐观：多次给出“10–20 分钟”，实际每步都触发新的隐藏门。

## 做对的部分

- 全程没有伪造 waiver 或人工批准；人工收据明确 `human_reviewed` 并引用操作者原话。
- 未知结果不硬闯：503、lease、部署未知都用显式对账，而非删标记或换目录。
- v5 与 reconcile 收据可审计；不是一次性补丁。
- 单语发布最终真的跑通（资产 + 目录 + HTTP），不是纸面结论。
- 代码提交、PR、证据索引完整保留。

## 改进

1. 增加 `locales_for(manifest)` 策略函数，所有 locale 校验只调用它，并补 1/2/3 语单测。
2. 冻结代码再跑付费轮：commit + tag → 再 plan 预算 → 再跑 L3；一轮内不改代码。
3. 发布预检：`FIREBASE_CLI_DISABLE_UPDATE_CHECK=1`、可写 `XDG_CONFIG_HOME`；CLI
   非零退出后立即探测 live version/catalog，先分类成功/失败/未知。
4. 补 `failed_before_deploy` 放弃路径，覆盖部署前失败的 lease 释放。
5. 用 journal 续跑而不是移动目录；每个 attempt 一个不可变目录。
6. smoke 稳定化：唯一 user-data-dir、观察器健康检查、失败换 profile 重试；默认
   按页面实际 locale 跑（本轮已修）。
7. 每个 run 结束导出正式 run report；本轮报告即本目录。

## 遗留

- ko 音频未通过（u007），三语未发布。
- zh 人工收据已记录，但机器 L4 路径尚不消费人工音频收据。
- smoke 观察器需修复后补一次干净的单语 smoke。
- #1218 仍为草稿，需评审合并。

## 重来一次的原则

> 先冻结代码、先 grep 全部 locale 门、先做干净 run；不在脏目录上修，不在产出豁免后再改实现。
