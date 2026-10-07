# 统一owner的持久资源准入

2026-10-05实现，设计对应S0与S1的资源准入增量。使用既有统一CLI、durable owner和CAS存储，没有新建另一套调度owner。原先统一CLI和审核后continuation已在代码中存在；此前设计把它们笼统写为未完成，实际部署和四层端到端能力仍须各自验收。

## 接入方式

新资源策略：[sermon-unified-resource-policy-v1](../schemas/sermon-unified-resource-policy-v1.schema.json)。在现有v2 manifest的`bindings`加入`resourcePolicy`，值仍为原有`path`和文件`sha256`引用。没有向旧manifest schema静默添加字段；绑定字节参加planHash、执行代码参加closure。

```json
{
  "schemaVersion": "sermon-unified-resource-policy-v1",
  "brokerRoot": "/absolute/path/to/shared-resource-broker",
  "capacities": {
    "cpu": 1,
    "online_api": 24,
    "codex_cli": 0,
    "spark_tts": 1,
    "publisher": 1
  }
}
```

这是配置示例，不是已应用的生产默认。cpu允许0–64，API／CLI允许0–24，heavy TTS／publisher允许0–1；0禁止该类新准入。brokerRoot需绝对安全目录，同协调主机上的受管run必须共用它。不同目录／其他主机／未接入的脚本不会被此账本限制。

已有`run plan`只读验证策略、路径及绑定，不创建broker。`run submit`冻结绑定，owner在派发前进行资源准入。未绑定策略的既有manifest保持兼容，不据此宣称已纳入共享预算。

## 本轮实际计量粒度

| adapter | 资源预留 |
|---|---|
| media.verify／fixture.replay／review.gate等 | cpu一份 |
| source.prepare／canonical.layer2／study.produce | online_api整池，保守串行跨run线上阶段 |
| canonical.audio | spark_tts一份，覆盖当前音频adapter内部阶段 |
| app.delivery | publisher一份，保守串行所有受管交付阶段 |

线上whole-stage adapter可能内部发出多个请求，所以本轮绝不把一个stage算作一个请求槽。`codex_cli`能力已在资源模块验证，尚无正式内容adapter消费该池；本轮没有把正式L2改成CLI。publish池是全broker保守上限，不替代原site远端lease。CPU许可是adapter任务数，不是MFA内部线程数。

当前每run的pump仍顺序执行一个adapter；不同run可以在不同资源池并行。阶段内组worker、单active locale、TTS副本与人审合同不变。全四层ready DAG公平调度、同run多worker和细粒度API／CLI调用预算尚未接通，S1没有因此全部完成。

## 持久化与恢复

[资源模块](../scripts/sermon_unified/resources.py)复用durable jobs的非阻塞flock和原子写入。broker账本固定策略身份，记录operation、owner、resource、units及held/released终态。held的units之和用于容量准入，不把running和unknown重复相加。容量漂移拒绝；尚无在线改容量／broker迁移工具。

reserve不是重复dispatch许可：同operation已预留或已终结均拒绝再次预留。进程退出、取消请求、flock释放不会移除持久held。只有runtime确认且保存匹配终态响应后才release；释放幂等，已用费用账本不回退。

owner接线顺序为：adapter预检与预算检查→broker reservation→保存intent→调用adapter→保存响应→验证并保存终态→释放资源。reservation与intent之间崩溃保守标为unknown，不重派；暂无自动证明未调用／回收孤立reservation的命令，需保留证据对账，不能删账本解锁。

资源不足保持`not_started`、reason=`resource_capacity_busy`，不写dispatch事件、不启动worker、不消费请求预算。常驻owner约每秒重新检查共享容量，因此其他run释放无需用户再发“继续”。这是低频重验，不是已完成的跨run事件通知机制。

终态先保存，资源随后释放。只读`job wait`可以先观察到成功；资源清理必须单独核验。若进程在这之间退出，下一次pump根据已保存响应补释放，新增模型调用为0。终态响应hash被改写时拒绝释放。revision复用旧成功步骤保留原operation／policy／broker身份，新policy不把旧许可错释放到新broker。

## 验证与边界

定向测试包括跨run容量、weighted units、进程退出unknown、重复派发、政策漂移、资源忙零调用、真实owner自动再准入、intent前崩溃、终态后崩溃、损坏响应与revision跨broker复用。

真实CLI／脱离聊天owner的零provider路径：

```sh
.venv/bin/python -m scripts.verify_sermon_unified_cli \
  --out artifacts/<new-empty-verification-directory> --with-resource-policy
```

只使用媒体核验与固定fixture，所有线上／GPU容量为0。验证100个步骤、100个持久reservation、完成后held为0，原有交接p95≤2秒约束仍检查。不能将该结果当成真实模型吞吐、24组CLI完整生产、GPU执行或发布证据。

相关测试入口：`tests.test_sermon_unified_resources`、`tests.test_sermon_unified_resource_runtime`及原CLI／owner／continuation回归。本轮没有新增模型调用或改生产配置。后续按[调度设计](production-concurrency-scheduler-design.zh.md)推进leaf预算、同run异步worker、正式CLI L2及跨层交错。

本轮实际收据：82项定向回归通过；ignored `artifacts/unified-resource-owner-20261005-final/acceptance.json`记录真实CLI／detached owner完成100步、墙钟48.9695秒、99次handoff的p95为0.410504秒、100个reservation全部released、held=0、newPaidRequests=0、runtimeCodexTurns=0、productionEligible=false。首轮验证观察到了“成功已保存、最后一个release尚在执行”的窗口，验收程序改为单独等待并核验资源清理；最终收据来自补强后的冻结实现，没有用旧运行冒称新代码验证。

## 逐调用和独立 GPU worker 接入补充

复盘后新增可选消费者：固定片段 Codex transport 按每个真实调用预留 `codex_cli=1`；独立诊断 TTS／ASR 按整个 job 共用 `spark_tts=1`。调用前准入，终态和释放证据持久化后归还；GPU job 另要求成功清理模型内存的身份绑定收据。容量忙不启动模型，未知结果不重试。详见[测试入口与边界](codex-layer2-test.zh.md#复盘后的资源与驻留增量)。

这完成了测试入口的 leaf CLI 接线，尚未接入正式 canonical Layer 2 或改变 owner 的同 run 顺序执行。生产参数未自动应用；未配置策略的脚本不受 broker 限制。单进程模型驻留实验与每 job GPU 许可互斥，整个驻留 session 的持久许可、跨主机统一协调、正式插件／candidate 链和冷暖性能验收仍待实现。
