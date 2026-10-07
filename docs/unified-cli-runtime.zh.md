# 统一 CLI v2：执行、恢复与证据

本页描述 PR #242 的可执行接口。v1 schema/fixture 保留用于历史协议兼容；执行必须使用 `sermon-unified-run-manifest-v2`，返回 `sermon-cli-result-v2`。代码在工作分支、测试通过、合并、真实生产和设备验收分别记录，不能互相替代。

## 计划与冻结

```bash
.venv/bin/python scripts/sermon.py run plan --manifest /absolute/run.json --json
.venv/bin/python scripts/sermon.py run submit --manifest /absolute/run.json \
  --plan-hash <plan.planHash> --json
.venv/bin/python scripts/sermon.py job status --run-id <subject.id> --json
.venv/bin/python scripts/sermon.py job wait --run-id <subject.id> --timeout 30 --json
.venv/bin/python scripts/sermon.py run events --run-id <subject.id> --after-event <eventId> --json
```

`plan/status/result/events`不写运行状态、查询不触发对账；`wait`超时只结束等待。JSON 退出码：成功0、等待3、门禁4、执行失败5、未知6、CAS/身份冲突7、基础设施/输入异常8、查无记录9、取消10。`job.status`查询成功可返回0，同时其 JSON `outcome`仍反映实际状态。

v2额外冻结以下内容：

- `bindings`：每个文件的绝对或manifest相对路径及字节SHA。路径不参与plan hash；内容身份参与。
- `executionAdmission.modules/closureSha256`：全部脚本、schema、既有legacy producer/publisher与网页资源及共享术语表。实际模型、音频、发布阶段还必须填写`runtimeSha256`，由`sermon_unified_runtime_identity.snapshot()`的规范JSON摘要生成，绑定Python、已安装分发版本和ffmpeg/ffprobe及编解码能力。
- `executionWindow`：America/Los_Angeles窗口用带时区时间表示；到期关闭新派发，不撤销在途请求。
- `steps`：固定adapter、阶段、依赖、locale、配置binding、保守成本上限。无任意shell/import入口。
- `source.window`：沿用原Supervisor批准、timeline和source descriptor。manifest URL用完整SHA-256；原Supervisor短URL hash不改写，经过原URL核对后桥接。

`activeScope`控制可派发阶段，不只是报告标签。ASR属于`english_ready_for_translation`，L2属于`layer2_machine_candidate`，配音属于`audio_screened`；媒体验收不会顺带启动模型。原始8秒同步门槛、24GiB reserve、固定声音/batch/seed身份均保留。

付费/source/audio/delivery阶段要求manifest的`consumerCapabilities` binding指向[冻结能力配置](unified-consumer-capabilities.zh.md)，与原source、locale和政策逐项匹配。媒体阶段允许locale/policy留空，不代表完整交付减少语言。

未来产物尚不存在时，先冻结当期可执行阶段、全消费者能力配置和受限 [continuation recipe](unified-continuation.zh.md)；owner 从不可变输出与已验证证据物化下一 revision 的具体输入，并在同一账本下 CAS 切换。缺证据时等待，不需要在聊天中手改未来 manifest。不能用虚构的未来文件SHA通过准入，也不能把能力检查称为产物有效。

## Producer与审核

| adapter | 输出与门禁 |
|---|---|
| `media.verify` | ffprobe及完整音频解码，核对媒体SHA和窗口 |
| `source.prepare` | ≤180秒分块ASR、MFA、anchors、独立judge；只产生待人工审核的English Source候选 |
| `canonical.inspect` | 原四层验证器，并核对manifest原媒体、URL、窗口、locale与政策身份 |
| `canonical.layer2` | 原durable controller的固定locale入口；共享预算账本、每run一个active locale，unknown继续占位 |
| `canonical.audio` | 冻结嵌套输入、固定合成配方、稀疏缓存复用、assembly-only、正式音频候选和输出闭包；待机器筛查/人听审 |
| `study.produce` | v1 冻结显式提供文本；[v2 独立模型生成](unified-study-generation.zh.md)按完整翻译组生成大纲/默想，带独立预算、缓存、未知结果阻断；仍须人审 |
| `app.delivery` | [四产物公开资源](layer4-four-product-public-delivery.zh.md)、Web/原生读取、元数据/路由、授权发布及端点读回；缺端保持partial |
| `review.gate` | 仅消费当前 hash/source/locale 及所选英文修订包绑定的人审收据 |
| `fixture.replay` | 固定离线返回；不能创建批准或生产资格 |

consumer capabilities v2 使用 release-package-v3；v1 仍可检查旧消费者，但不能给新四产物发布授予能力资格。下游生成、审核和 canonical inspection 均比较所选英文源包的 JSON SHA；同媒体、同窗口的另一文本修订不能替代。

Source、音频与交付的配置参见[Source adapter](unified-source-preparation.zh.md)、[音频 adapter](unified-audio-adapter.zh.md)。L2预算和零API迁移参见[预算与迁移](canonical-layer2-budget-and-migration.zh.md)。

模型预算授权绑定配置、代码、请求上限与固定账本根。总额度在派发前保守预留，每次真实调用再次检查硬上限；未知结果不退款、不自动重试。软件的价格上界不表示账单已核销。

```bash
.venv/bin/python scripts/sermon.py review ingest --run-id <run-key> \
  --job-id <stage-job-id> --receipt /absolute/review.json \
  --expected-revision <stateRevision> --json
```

续跑配方中的证据槽通过同一审核入口导入；此动作只存入证据，不将已有审核 gate 标为批准：

```bash
.venv/bin/python scripts/sermon.py review ingest --run-id <run-key> \
  --binding <frozen-recipe-slot> --receipt /absolute/evidence.json \
  --expected-revision <stateRevision> --json
```

预算授权、审后包与内容收据分别验证；内容审核 gate 仍用 `--job-id`。recipe 的 `activeScope` 必须保持当前 manifest 已授权的 canary/final 范围，最终范围不完整时不会报告成功。

大纲和默想使用独立`sermon-study-review-v1`，不借用音轨收据。翻译、听审和学习产物批准互不替代。机器通过、整体听审、逐项疑点裁定、同步例外分别保留。状态完成要求每个locale覆盖其应有端点，中文读回不能覆盖韩文和西文。

## 修订、停止和未知结果

```bash
.venv/bin/python scripts/sermon.py worker drain --run-id <run-key> \
  --expected-revision <stateRevision> --json
.venv/bin/python scripts/sermon.py run submit --manifest /absolute/revision-2.json \
  --plan-hash <new-plan-hash> --expected-revision <drained-stateRevision> --json
.venv/bin/python scripts/sermon.py job reconcile --run-id <run-key> \
  --job-id <stage-job-id> --expected-revision <stateRevision> --json
```

新revision必须递增1，并已drain、旧owner停止且无在途/unknown。旧状态先归档；只复用成功、输入/代码不变且原response/产物仍有效的节点，其依赖变化会传到下游。连续修订保留最初response来源。预算预留不因revision清零。端点读回不直接跨revision晋升；用新`verify`动作重读。

派发前intent与预算持久化；返回response先落盘，随后更新状态。owner消失时遗留running转`waiting_reconciliation`。`reconcile/cache-recover`只消费原绑定已保留返回，不另发API；缺返回保持unknown。取消只关闭后续派发，保留真实在途结果。CAS冲突要求重新读取当前revision，不覆盖另一个操作者的状态。

## 计量与实验

owner在人工等待期间持续观察持久stateRevision，新的审核证据触发同一程序继续，无需聊天轮询。owner事件记录ready、enqueued、started、finished/approved；UTC与同进程monotonic分开。跨进程恢复缺失的monotonic耗时保持未知。现有provider/job accounting通过dispatch span和持久job context接入，模型token、缓存、预算估计、账单与Codex上下文分别记录。关键路径缺边不补零；没有同工作负载标定时不猜ETA。

`sermon_unified_observability.bounded_packet`提供显式字节上限的诊断包，带遗漏数量，不携带全文，也不授予执行或批准权限。

```bash
.venv/bin/python -m scripts.sermon_workflow_experiment \
  --protocol /absolute/protocol.json --receipt /absolute/cold-a.json
.venv/bin/python -m scripts.verify_sermon_unified_cli --out /absolute/new-empty-fixture-dir
```

fixture使用真正CLI和脱离聊天的owner，固定100次转移、零API，要求交接p95≤2秒。它不证明模型速度、内容质量、设备播放或15小时完整交付。容量和STE A/B工具只在固定质量/声音/输入及相应授权下执行；真实实验收据仍须另外取得。

## Temporal可选接入

继续使用现有独立SDK环境；SDK worker通过项目Python调用同一pump和账本。默认不注册统一生产activity。

```bash
.venv/bin/python scripts/sermon.py worker transfer --run-id <run-key> \
  --scheduler temporal --expected-revision <drained-stateRevision> --json
artifacts/temporal/runtime/venv/bin/python -m scripts.sermon_temporal worker \
  --profile production --allow-production-execute --enable-unified
artifacts/temporal/runtime/venv/bin/python -m scripts.sermon_temporal client unified-submit \
  --state-root /absolute/unified-store --run-key <run-key> --plan-hash <plan-hash>
```

迁移前必须drain并无unknown；canonical和Temporal共用pump锁，未转交的scheduler拒绝运行。SDK activity不自动重试；workflow在审核/unknown门禁等待显式证据signal，CLI ingest/resume唤醒后仍重验原收据。取消等待同一在途工作收尾。回退同样先drain，再转`canonical`。这是单机执行接线，不是高可用部署。
