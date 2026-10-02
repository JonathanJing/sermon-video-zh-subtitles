# 2026-10-02 保留完整性保证的日志校验 cache 修复

## 结论与资格

本轮只减少重复的 schema 校验 CPU 工作。原 binding、immutable delivery records、ledger 与 pending 的实际字节读取、hash / scope / conflict 检查、完整 union replay 和 sequence 分配全部保留。没有引入已验证 prefix、mtime 信任、可变高水位或延迟发现损坏的新合同。

`017 / DEV-SPD-006` 的 **39/128-job 完整 DAG 规模验收仍 open**；runtime 准入仍为最多 2 units。本记录中的 unit 指 locale-specific TTS job（translation group × locale），不是 English source unit。先前真实三分钟记录有每语 13 组、三语 39 WAV；39 English source units 是另一个数量。这里没有运行该三分钟真实任务。

基线为 `dev@8bee25447d62504cb99a4b4b6b05b3e052042f10`，tree `c0ede510d5bd56455053d3bef796603ebc3a34c6`。PR #217 / #218 已由仓库 owner 合并；该 tree 与 PR #218 最后测试 tree 相同，push CI [37010346514](https://github.com/JonathanJing/sermon-video-zh-subtitles/actions/runs/37010346514) 通过。集成状态不代表规模 P1 通过。

## 有界评估与已排除的方向

先在独立工作树评估 pure reconciliation index，保持 writer 不变。26 个有硬预算的 sample 中 21 个完成、5 个在 180 秒整组预算内被截停；10 对完整操作持久化 bytes 一致，86 对已完成 phase hash 一致。被截停部分没有恢复或补为通过。39-job 正常日志样本的串行 prepare + deliver 为基线 20.674 秒、index 21.147 秒；含 reconciliation / controller-pending 的样本为 27.559 / 25.951 秒。这不足以证明有意义改善，index 未包含在本修复。

上述评估的原始归档 SHA-256 为 `438d928968caaa74c192bd4d80d296a1fd102253fd0c8fb1d26f9409f6ae9f98`，保持独立。128-job 的不完整 paired writes 继续 unverified，不能从前面几个一致 phase 推出完成。

实测瓶颈是 2,048-entry success LRU 的 working-set 抖动：39-job 首次日志有 3,396 个可缓存事件、4,816,163 bytes；带 reconciliation 的日志有 4,293 个、5,996,700 bytes，均未达到原 16 MiB payload 上界，却因条目数被逐出。warm replay 可出现 0 hit，完整 writer 内再次 schema 校验占主要 CPU 时间。

## 最小修复

- success cache 同时限制 **8,192 entries** 与 **16 MiB canonical payload bytes**；每事件 8 KiB 准入上限不变
- key 仍为 exact canonical event bytes、exact immutable typed schema bytes、contract version；严格 Python 类型 / JSON / size 检查仍先执行
- 只有完整校验成功才缓存；异常不插入、也不为失败请求驱逐现有成功项
- RQC 的外部 policy-dependent semantic 校验和较大事件仍走 uncached 路径
- LRU 驱逐同时扣除对应 payload byte 数；stats / clear / lookup / insert 使用原同一把可重入锁
- fork child 重新初始化锁、schema snapshots、success entries 和计数器，避免继承另一线程在 dict 与计数器两次更新之间的状态
- schema snapshot 的原有两个 slot 和大小限制保留；schema eviction 仍先清 success cache

16 MiB 是保留的 canonical payload 总量，不是整个进程 RSS 上限。额外 key / container overhead 由 entry cap 有界；schema / validator 的已有单独限制保留。没有扩大 producer、execution 或 storage authority，不需要改事件 schema version。

## 验证方法

脱路径数字摘要见 [measurement-summary.json](../evidence/2026-10-02-cache-bound/measurement-summary.json)。基线和候选在独立子进程中，从同一 bytes 构建的 fixture 副本运行；完整 contract 模块先安装为 canonical module name，避免 consumer 混用不同 cache。比较 normal prepare / deliver 的结果和所有持久化文件 hash，时间与比较分开。

候选 source SHA-256 `6f27582152da84d53cc2accf1258c9d2c690f3916c8bcdabb9746fa5934f068f` 下，四个 sample / 28 个 phase 全部完成，两对完整持久化 bytes 一致。首次样本的 prepare + deliver 为 **20.788 → 2.705 秒**，reconciliation / controller-pending 样本为 **27.517 → 4.267 秒**。这是各一次串行配对的描述性测量，不作统计显著性或生产速度承诺。候选 20 项 pure-cache tests 与原 durable/schema/accounting 回归合计 **63 tests / 11.138 秒**通过。

cold pure replay 没有改善：两类样本分别为 4.414 → 4.428 秒、5.124 → 5.292 秒；收益来自重复使用已经验证过的 exact bytes。发布前正常集成 owner 随后合入的 PR #216 / `dev@6f84d30636b15630be9e1bbfb6b0e14f2d11e8c7`，保留其 iOS archive guard 与 CI 路由改动；上述 cache source bytes 没有变化。

每组固定 180 秒 wall budget，测试计划先声明：两类 39-job 样本的 warm prepare + deliver 须各出现至少 2 倍描述性改善，且所有完整性 / bytes 条件成立。这是本地样本 go/no-go，不是 CI 微秒阈值、生产延迟承诺或提高 workflow admission 的理由。

样本沿实际 two-unit Fresh full-DAG synthetic 日志的事件类别和 payload 形状外推：首次 `103 + 19L + 85U` rows，reconciliation history `176 + 34L + 107U` rows；本轮 `(U,L)=(39,3)`。opaque metadata / dependency payload 保留 two-unit template 形状，没有生成或验证更大 DAG 的完整 edges / CP。因而这是 observed-shape extrapolation，不是保守 upper bound。cache-cold 指清 Python schema/event cache，不指清 OS page cache。

controller-pending 样本将原最后一个 controller fact 保持为普通未 append 的 pending，union 不变且不制造 overlap；新 sequence 必须等于已验证 pending 最大值 + 1，正常 delivery 先排出该旧 fact。没有新增进程中断、ACK 丢失或被冻结 request / receipt 的故障测试。

验证矩阵：

- 原 durable / schema-snapshot / accounting contract 回归
- pure cache 的 byte / entry / exact 8 KiB 边界、LRU、多项驱逐、UTF-8 bytes、失败不缓存、schema/version 变化、nested mutation、strict types、clear、并发和 fork-hook reset
- 完整 39-job shape 的 baseline / candidate byte equality 与 cold / warm timing
- 冻结提交的现有真实 Prefect continuation、Fresh Source 和 Fresh full-DAG SDK 用例；exact-head CI 的通过、skip 与 artifacts 在对应 PR 记录，未完成前不借用旧 head 的结果

逻辑 memory-accounting 和 direct fork-hook tests 不等于整体 RSS 上限或新的 crash-recovery 验收。先前受工具安全筛查阻断的 controller crash 测试缺口保持原样。

## 后续仍须完成

本 cache 修复消除已观察到的计数上限抖动，不消除逐操作全量读取 / replay 的 O(N) 工作和累计 O(N²) 成本。下一步须在同样的原字节、记录、冲突、scope、sequence 保证下进行完整 39-job 生命周期 / deadline / resource / restart 验收，再评估更大规模；不得仅凭本 microbenchmark 调高 cap 2、关闭 P1 或放宽 timeout。若将来改变验证 cadence 或 storage trust boundary，须单独版本化设计与审查，不属于本修复。
