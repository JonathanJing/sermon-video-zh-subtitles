# Durable Layer 2 spoken revision：execution v2

本入口为完整翻译 evidence 派生短口播候选，保持原阅读候选。它复用现有 Astra → Sol → 固定语言插件 → 候选准入，不改模型角色、提示或人工批准。配置准入通过不证明文字或同步质量通过。

## 兼容与字段

`sermon-canonical-layer2-execution-v1` 保留旧严格字段：lane 为 `{outputDirectory, plugin}` 或额外 `partialRepair`。v1 不接受 spokenRevision。

新 `sermon-canonical-layer2-execution-v2` 顶层仍为 schemaVersion、productionRunId、inspectionConfig、jobRoot、locales。lane 可以增加以下对象，不能同时包含 partialRepair：

```json
{
  "outputDirectory": "/absolute/new-spoken-output",
  "plugin": "/absolute/frozen-plugin.py",
  "spokenRevision": {
    "reuseFrom": "/absolute/prior-complete-run",
    "brief": "/absolute/shorter-spoken-revision-brief.json",
    "cacheManifest": "/absolute/prior-cache-manifest.json"
  }
}
```

目录必须分离；reuseFrom 不得与 output 或 jobRoot 重叠。已有失败修复不能伪装成短口播修订。brief 沿用严格 `sermon-target-language-group-revision-brief-v1`，同源、同 anchor、同冻结 policy、同组计划；每个提案必须确实改变既有文字并绑定原文字 SHA。没有新增逐组秒数预算字段。

## 准备与调度

先冻结真实完整缓存：

```bash
python scripts/canonical_layer2_controller.py prepare-spoken-cache \
  --reuse-from /absolute/prior-complete-run \
  --out /absolute/prior-cache-manifest.json
```

生成器只读验证 prior request/evidence 一致、各组完整语义 pass、覆盖、Astra/Sol exact model/request、raw 完成状态及 raw/parsed/最终 reviewed text 一致。未知 paid-call started marker 阻止准备，不推测网络失败等于请求失败。manifest 保存 request/evidence canonical SHA 和所有 parsed/raw 文件 byte SHA；输出不可覆盖。

```bash
python scripts/canonical_layer2_controller.py tick \
  --config /absolute/execution-v2.json --mode deterministic_shadow
```

shadow 只读、零 API。检查同源/策略/原 request/完整证据/manifest/brief 后才会显示 ready；该 ready 仅表示允许启动机器修订。实际执行仍用同入口的 `--mode deterministic_execute`，同一 spoken run 的所有 locale 必须使用同一新 jobRoot 与 productionRunId，以共享任务锁和24请求槽。迁移前完整保存旧各root的request/state SHA及真实known-terminal审计；旧failed保留原状态，不能改为success。旧root不得再次调度，启动新run前必须重新核实没有active/unknown任务。新 productionRunId、输出和配置身份不能复用旧 job 身份。旧root含不同runId或失败记录时不能直接换runId原地复用；通用durable投影会正确拒绝。

controller 继续执行 one-active-locale、最多16组并发和共享24 API请求槽；没有直接runner绕过路径。旧配置/partialRepair路径不变。每次请求与最终候选准入重新检查 configuration/code/source/policy identity。

## 缓存不变性与成本

配置身份绑定 brief 与 manifest 内容。worker 启动全量验证原缓存，在新 durable job 目录下保存 `spoken-reuse` 只读快照，逐文件校验后只让模型runner读取该快照。旧原缓存不写入。已经存在的快照必须匹配，禁止覆盖不同字节；快照保留用于审计和恢复。

每次请求只复读配置、brief、manifest 等身份，不反复读取近1900个缓存。准入前重新完整校验快照，任何变化均阻止候选保存。不变组由既有 runner 按字节复用，改变组获得新 payload/cache；不重新合成音频。

## 人工审查与下游

输出仍为 `machine_review_pass_human_review_pending`、`releaseEligible=false`。短稿必须另行真实人审；人审、声音授权派生收据、speech job 与 Audio Package 绑定新 spoken candidate SHA。原来源窗口、允许范围内的声音能力证据和完整阅读候选可以保留，但不复制旧整篇人审为新候选批准。

预算 sidecar 或字符缩短比例不能证明音频8秒滞后门槛通过。完整阅读稿与 spoken 双候选既有Layer4合同不变。
