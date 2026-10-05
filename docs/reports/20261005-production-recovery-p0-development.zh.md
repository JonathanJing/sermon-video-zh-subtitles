# 下一轮开发：返工解释与首调用前检

根据[已提交规划](20261005-production-findings-next-iteration-plan.zh.md)完成第一批三项 P0，提交到 PR #248 的工作分支。上一轮真实 GPT-6.1 Sol high fast 翻译／Sol 独立复核的结果仍是实验验证；正式策略没有自动改为测试策略。本轮开发验证不新增 CLI/API 请求或本地模型推理。

## 已实现

1. **L3 异常留存与只读声学诊断。** renderer 在 timing 风险、partial 解码失败／替换，以及显式 quarantine 前留存原字节、job/unit、intent、commit、receipt 和已存在 runtime。复制、SHA、文件与目录 fsync 完成后才允许删除；落盘失败／证据损坏／路径变化阻塞操作。首尾低能量与自身超窗、传播延迟、clip 尾部超限分别记录，不推断根因，不裁剪或放宽政策。新增 anomaly v1 补充合同，旧 quarantine v1 保持兼容。
2. **逐单元／固定批窗恢复清单。** 对 canonical L3 输出 reuse/revalidate/recompute/unknown 和逐字段原因；整批模型求值数与缺项提交数分开，保持已提交邻句。包装身份变化不等于模型重算；上下文总 hash 变化但真实请求影响不明时明确 unknown。owner、缺 commit、started、产物损坏和读中变化均不能变成重发授权。清单不迁移跨 job ASR cache、不释放 owner。
3. **L2 规则冻结。** canonical controller 在 start_job 前前检；runner 将同一 modelRules 加入实际 translator/reviewer prompt 并在 started／调用前核验。controller 将同份 receipt 传入真实 plugin/candidate 准入再核验。完整／部分经文、术语、数字上下文、未口述引用均可在开跑前发现冲突。历史 carry-forward 若无规则 receipt 和真实 payload/source/context 证明先阻塞，新增调用为 0；已证明的新规则可零调用续跑。

规则入口见[规则冻结](../target-language-rule-preflight.zh.md)，L3 操作与输入快照格式见[异常留存与恢复清单](../production-recovery-plan.zh.md)。新诊断改动没有改变采样、声音输入、ordered full-window replay 或既有声音身份；只接受明确审查的直接父 renderer SHA，未知实现继续拒绝。

## 固定三分钟证据

同源媒体 SHA `79bada8f2e960adb470a146f183449db433308b53c20d03ea9c7e2e0a66e906b`，原 source 180.013167 秒。历史 mock 13 组／26 响应 replay 通过，未构造 live CLI；39 English units 和全部输入 hash 绑定保留。该入口没有真实 plugin，明确 `not_run_legacy_simulation`，不能把它记成新规则链路验收；新规则链路由真实 runner/plugin/controller + fake caller 的定向回归验证。

对上一轮 Sol 6.1 链路的 13 个真实 Spark WAV 只读完整 PCM16 解码，时长与 SHA 全相符；manifest、assessment 和 13 个原 WAV 共 15 个文件 hash 前后不变。测量用时约 0.395 秒，仅包括本机只读测量与排程计算，不是模型吞吐或全流程性能。没有重合成／ASR。

| 组 | 自身超源片段 | 首低能量 | 尾低能量 | 解释 |
|---|---:|---:|---:|---|
| g003 | 3.070001 s | 0.02 s | 0.07 s | 早期延迟来源之一，边缘测量远小于自身超窗 |
| g004 | 2.670002 s | 0.00 s | 0.00 s | 未测得低能量边缘，不能按静音修复假设处理 |
| g013 | 0.259999 s | 0.35 s | 0.15 s | 同时承接前组延迟；裁剪是否安全仍未知 |

13 组边缘低能量总量 5.90 秒，但该值不是可安全裁剪量。当前 unchanged WAV 排程仍 fail：g005–g008 超 8 秒 end-lag，尾部需要恢复 5.796834 秒；串行时长下界要求至少回收 1.516833 秒，只是必要条件。当前 `publicationEligible=false`，没有同步修复、人听审或正式发布证据。

## 验证与发现

最终相关回归共 **230 项不重复测试通过**，结果与源码 SHA 存于[结构化收据](20261005-production-recovery-p0-development-receipt.json)。覆盖规则／真实 prompt 变化零调用拒绝、同输入和有证明的 carry-forward 零调用、controller 实际传 receipt、坏路径／hash／owner、完整 batch replay 与仅缺项提交、解码失败留存、复制／目录 fsync 失败不删原件、重试 dedup 不跳过落盘、整轨资产保存、截断 PCM 与低能量测量。`git diff --check` 和相关文档链接检查通过。测试均使用 fake model／本地文件，不能当作真实生产运行。

整合回归发现原 batch fixture 扩为 5 个 job units 时仍仅保留 2 个 candidate groups，旧 zip 诊断静默漏覆盖。本轮补齐合成 fixture 对应的 groups，并使新异常入口拒绝缺覆盖／错组，原 batch／seed／邻句保留断言不变。代码审查同时发现新目录持久化和旧 quarantine 整轨资产落盘不足，已修复并增加失败重试回归。另补上带 transport identity 的 wrapped cache/raw hash 与纯 payload preview hash 分别核验，覆盖同身份、变化身份和坏 raw；原 CLI 跨 run 复用禁用合同保持不变。

## 下一阶段

先以完整 job/settings 生产者快照把恢复清单接到实际周日 run，核对计划次数与真实新增调用／hash；当前 helper 不自动生成该快照，也不替代完整生产准入。随后再开发跨 job 复用／ASR cache 迁移和 receipt 快路径，用实际 474 单元 manifest 比较墙钟与 I/O；本轮未测得这些优化的节省。

同步修复按分组听审和原 anchor 校对推进，优先检查 g003/g004；如确需改口播则回 L2 新 revision，保留完整经文与语义。模型驻留、跨主机容量 broker 和有界 DAG 仍是后续阶段，未在这批代码中放开并发或占槽限制。
