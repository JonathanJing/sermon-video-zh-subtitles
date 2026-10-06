# Decisions API 每周流程实验：发现与执行记录

日期：2026-10-06。状态：实验设计完成，隔离 runner 正在实现，尚无在线 A/B 胜负。生产入口及审批保持原状。

## 已核验的发现

| 环节 | 真实基线 | 实验含义 |
|---|---|---|
| E01 英文审核 | 程序硬检查 + Sol 6.1 high，输入为文本／时间元数据 | 可对比机器判断；不包含听音频能力 |
| E02 翻译审核 | Sol 6.1 medium 会修正译文后返回 verdict/evidence | 必须分开比较标签与完整修订交付，不能把 final pass 与原草稿的 B 判断直接相比 |
| E03 修复分流 | 规则路由；歧义分支只有 proposal 接口 | 不存在既有默认 Luna responder；歧义分支另作人工辅助对照 |
| E04 配音筛查 | 共用 ASR 后，相似度／短句规则 | B 比较文本差异判断；队列排序 A 为原单元顺序，无已核验语义 ranker |
| E05 时长判断 | 确定性 scheduler／算术诊断 | 识别试验输入原始 measurements，移除 A 答案；如何修复另以人工选择为 A |
| E06 大纲／默想 | 生成模型 + 结构／引用程序校验 + 人工审核 | 无独立自动语义 triage 基线，需人工直接／辅助试验 |
| E07 异常／Supervisor | provider 规则；Luna CLI 选 allowlist，程序验证 | 规则、Supervisor、模糊人工诊断分层；不合并成全面根因分类器 |
| E08 反馈 | 用户类别 + 程序入库 + 管理员人工处理 | 无自动评论分类基线；用户自选类别不是 gold |

## 设计及证据边界

详细方案见 [配对 A/B 设计](../decision-api-weekly-ab-design.zh.md)；机器计划见 [v1 plan](../../config/decision-api-weekly-ab-plan-v1.json)。

- 同一冻结输入，AB/BA 交错，逐环节报告。
- 证据准备、请求、有效验证、人工 active／wait、修订返工分别计时。
- 12-case 协议 smoke → 20-case 校准 → 至少 60 独立真实案例；pilot 是探索性结果，之后扩大及做 10 分钟／全长 canary。
- 二元质量不能用零分歧退化 bootstrap 宣告非劣；标签更快而完整产物不等价不得判全流程胜出。
- historical cache、模拟响应、live 请求、provider usage、估算成本和人工 gold 各自记录。
- 605 秒来源样本只有历史模型判断，不能当独立 gold 或新 API 时间；9/20 音频 11 个 flags 全部人工批准，缺严重异常阳性样本。

## 本轮执行范围与进度

独立分支基于 `85a3f5ff` 的已提交代码，实验 PR 暂时叠在 `codex/dev-rerun-20261005`（PR #250）之上，避免混入该 PR 的生产修复差异。原 checkout 的未提交工作不进入实验。最终每次调用记录实际 dependency／payload hash；基线变更会创建新实验身份。

| 环节 | 初始执行状态 | 当前能证明什么 |
|---|---|---|
| E01 | pending_runner | 已核验输入／现有模型入口，未在线测 |
| E02 | pending_runner | 已核验审核会修稿，未在线测 |
| E03 | pending_runner | 规则／歧义身份已核验，未测 |
| E04 | pending_runner | 差异规则已核验，未测 |
| E05 | pending_runner | 时长判据已核验，未测 |
| E06 | needs_human_baseline_and_gold | 不存在同任务自动 A；无胜负 |
| E07 | pending_runner | 已核验程序／CLI 分层，未测 |
| E08 | needs_human_baseline_and_gold | 无自动 A；无胜负 |

本地 dev 配置检查通过，只证明配置存在，不证明 provider 权限、账单或模型可用。在线预算金额正在等待操作者选择；此期间创建 PR、实现 runner、协议及程序基线测试继续推进。

## 已完成验证

- 设计 JSON：8 个 stage 与子任务主指标绑定、范围／无副作用字段验证通过。
- 文档 26 个本地链接与 14 个基线源码引用存在。
- 设计提交 git diff --check 通过；模型请求数为 0。
- runner／真实在线结果将在后续提交更新，不以设计文件代替实测。

