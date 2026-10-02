# 2026-09-30 Dev 三分钟诊断续跑与交付

三语有效机器候选、39 段真实配音、Dev HTTP 回读及 App 内三语短时播放均已完成。最终交付为隔离的 `preview_only` 诊断周次；**完整 live DAG、Agents 自动诊断和原生 TTS worker 尚未通过，正式四层发布未完成。** 产品源码未修改，遇到的问题与验收条件已登记在 [统一 backlog 的 DEV-DIAG-001—014](../backlog.zh.md#dev-180s-diagnostic-followup)。

- [Dev App 测试周次](https://ai-for-god-sermon-audio-dev.web.app/?week=dryrun-20260930-real-180s)
- [原片、英文 ASR 与三语试听](https://ai-for-god-sermon-audio-dev.web.app/diagnostic-180s/dryrun-20260930-real-180s/index.html)
- [公开脱敏结果 JSON](https://ai-for-god-sermon-audio-dev.web.app/diagnostic-180s/dryrun-20260930-real-180s/report.json)
- [首次阻断时的历史报告](20260930-dev-180s-dag-log-agent-api-test.zh.md)：保留原 39 次 HTTP 400、TTS=0、295 文件和 323 events / 84 spans；其线上链接现已显示续跑结果。

## 来源、授权与执行身份

运行代码冻结在 `dev@63c0a18040b7f7744b334cebdb31778de228b064`；工作分支此前的两个提交只增加报告和 backlog，不改变生产代码。Dev App 使用已核验的完整 Hosting 基线增补诊断资产，没有把整个前端宣称为从该提交重新构建。

用户决定先继续暴露问题，再集中修复，并明确授权“允许额度放宽，跑完全程即可”。人工审核按用户要求在本次测试默认通过，记录为 `user_authorized_default_pass_for_test`；真实包人审仍 pending，`productionEligible=false`。机器与插件检查仍实际执行，没有把模型审核改标成人工批准。

输入沿用经授权的 2026-09-27 原时间线 60–240 秒片段，容器时长 180.013167 秒，片段 SHA-256 为 `79bada8f2e960adb470a146f183449db433308b53c20d03ea9c7e2e0a66e906b`。首次运行新执行 ASR 1 次、Astra 英文源检查 1 次；后续复用这些已绑定收据，没有重复 ASR。Source/Anchor 含 39 units，每语分为 13 groups；新转写、音频、窗口和原对齐证据一致后复用 MFA，没有重新执行 MFA 推理。

Source 规范化 hash 为 `fd3741f1c8b5da9ad8ac295214930260a81b15da4abcfe610b87b2afc2fe3124`，Anchor 为 `5cedc9209b8bc52ed3741de49a7ebf44833613d442437d249425f96e96a9a826e`。ASR 是机器结果，未进行逐字人工核对。

## 续跑、预算与机器候选

保留原 A 的配置、store、clock、期限和账本，B/C 分别冻结新的 attempt，并记录父／祖先输入与收据 hash。累计上限为 320 请求／$80；C 独立上限为 110 请求／$40／5,400 秒。没有退款、清空保留额或把旧失败当成未调用。v7 的零调用准备失败留存，不计成额外付费 attempt。

| attempt | provider 请求 | returned / rejected | 最坏情况预算保留 | returned usage 已知估算 |
|---|---:|---:|---:|---:|
| A：原 run，含输入修订探针 | 124 | 85 / 39 | $23.461904 | $1.618319 |
| B：linked-v8 | 86 | 86 / 0 | $14.376520 | $1.827184 |
| C：linked-v9 | 83 | 83 / 0 | $13.743839 | $1.694824 |
| 合计 | 293 | 254 / 39 | $51.582263 | $5.140327 |

三个 provider 终态均无 `reserved` 或 `outcome_unknown`。$5.140327 是已返回 usage 乘冻结费率的估算，**不是供应商账单**；39 次 rejected 的 usage/billing 未知。最坏情况预算保留也不等于实际花费。本地 TTS 不产生 provider 计费，本地计算成本未测量。provider 请求数不代表全部网络请求数。

为继续测试，私有输入显式声明 JSON、有序 coverage、四项 verifier requiredChecks 与合法 reason 枚举，并处理未使用 pending 术语的输入合同冲突。这些输入版本、失败响应和检查回执均保留，没有修改产品 prompt、schema、术语表或语言插件。

B 有四次真实内容 repair：zh-Hans g012 的 `meaning_omission`，ko g003/g007 和 es g005 的 `language_rule_failed`，均创建新 revision 并重新生成、独立审核，增加八次请求。随后插件发现本次政策把实际使用的 World War 目标表面设成英文，和正常三语表达冲突。H04 属测试输入错误；C 独立声明 pending 的中文、韩语、西语目标表面，不倒填已审核译名。

三语 policy hash 随之改变，旧组不能继续按新政策 admission。C 对每语全部 13 组真实重新生成、Sol 审核及插件核验，没有跨政策拼贴旧通过组。最终三份候选共 39 组机器及插件通过，locale 状态为 `waiting_human`；只有隔离测试授权允许下游 preview。

| locale | 最终候选规范化 hash | 机器／插件 |
|---|---|---|
| zh-Hans | `78eabf394e2bef66e4ac31f1f305dfc6824d889cb387a5fe8c0ff87697768a3c` | 13/13 通过 |
| ko | `eeee2ab623f51b581a0ce6cd04ae7798f60f7d4b4c085fdf15281807c5b2586f` | 13/13 通过 |
| es | `67c7cf9eff26881b29d016baf4d945e491fa26547b08edd820614b6fa96af123` | 13/13 通过 |

## 真实配音与原生 worker 故障

三语原生 preview worker 均在模型加载前失败：`qwen_tts` 导入 `sox` 时执行 `os.popen('sox -h')`，被 subprocess guard 以 `diagnostic_preview_subprocess_forbidden` 拒绝。三个进程均有已知非零退出与原始日志，合成 WAV=0；guard 未放宽，未伪造原生 worker 成功收据。该实际故障登记为 `DEV-DIAG-014`。

之后用 checked-in [独立 preview renderer](../../scripts/render_speculative_target_language_speech.py) 完成真实推理。它继续核验候选、policy、Source/Anchor、注册 voice/consent/checkpoint、预算、helper hash 和 **原 C 绝对 deadline**；父进程设置有界超时，离线加载既有模型，输出到全新的 recovery-2 目录。自定义 standalone 收据明确 `nativeWorkerSucceeded=false`，不代替原 worker 的收据或正式 Audio Package。

实际使用既有 Qwen TTS checkpoint，MPS / float32 / sdpa / seed=42；依赖冻结为 Python 3.13、torch 2.14.0、qwen-tts 0.1.1、transformers 4.57.3、sox 1.5.0、jsonschema 4.26.0。没有另行下载模型或安装依赖。H05 helper 冻结次序错误在 renderer/model 启动前终止，0 WAV；保留失败后重新准备，不列为产品缺陷。

| locale | 新合成并完整解码 WAV | 音轨时长 | locale attempt 墙钟时间 | 浏览器播放位置 |
|---|---:|---:|---:|---:|
| zh-Hans | 13 | 189.92 秒 | 417.605 秒 | 25.763278 秒 |
| ko | 13 | 215.92 秒 | 463.815 秒 | 21.801196 秒 |
| es | 13 | 195.76 秒 | 427.461 秒 | 20.559598 秒 |

39 个单元均为新推理，没有采用旧音频缓存。每个 WAV、推理回执及 sound identity 绑定对应候选、来源、术语政策、voice/checkpoint；合并为 mono 24 kHz / 64 kbps MP3 后也完整解码通过。

音轨比原片分别长约 9.91、35.91、15.75 秒。当前 cue 使用各自配音轨的时间偏移，**原视频同步未验证**；没有进行转写回查、完整人工听审或正式 Layer 3/4 包验收。单元推理、解码和短时可播不能推断这些验收通过。

## Dev 发布与实际 App 验证

目标 project/site 均为 `ai-for-god-sermon-audio-dev`。部署前重新核验 295 文件基线，候选保留全部旧路径：292 文件不变，改变三个诊断 JSON/HTML，新增三条按 hash 命名的 MP3，最终共 298 文件。原 11 个周次及正式默认周次不变，目录仍为原周次加本次诊断共 12 项。未发布到 Production。

| 新音轨 | MP3 SHA-256 |
|---|---|
| zh-Hans | `d49f0474ff81942a85ab9231dbab0a42ea48e4c97d55a338ecbd4c3061599439` |
| ko | `8b35adc38864fdee17859bba6c34fd6f589fd3b9c193ce2fc86fd77197864f90` |
| es | `f32e5fa243e40c724937a3b7dc4f0e435a31c53bda6986548aa7d6c7f4ae0921` |

HTTP 核验覆盖 298 文件：六个新增／改变文件重新 GET 并比对 SHA，292 个保留文件以当前 HEAD/ETag、既有完整 GET SHA 和本地 SHA 交叉核验。三条 MP3 与来源视频的 Range 均返回 206，1,024 字节内容匹配，Content-Range 正确。

在 Dev App 内实际点击内容语言切换和播放按钮，中文界面保持不变，分别播放中文、韩语、西语新音轨超过 20 秒；三条均 `paused=false`、`readyState=4`、`error=null`，然后通过 UI 暂停。不是脚本直接调用 media.play()。最后停在中文 0:00，截图保存在私有证据目录。浏览器结果仅为短时播放，没有连续播完三条音轨；iOS 真机和现场均 `not_run`。

## DAG、日志与 Agents API 的结论

合并 13 份原始日志来源并绑定快照来源 hash，得到 3,409 events / 26 traces / 963 spans。重复事件、损坏事件、冲突回执及未闭合 span 均为 0：26 run、32 workflow、905 stage 启停配对完整。

但有 295 条 `api_attempt_started`、293 条终态。旧 A 的两次派发在 124 请求额度用满后、进入网络前被拒绝，未写入 provider 账本；stage 已 failed/闭合，不能误称付费在途或 unknown provider outcome。缺的是 `dispatched=false` 的明确 API 终态，登记在 `DEV-DIAG-013/008`，不能靠退款或猜测补账。

局部 DAG 缺口出现在 19 个 trace：15 个有 `legacy_dependency_or_executor_unknown`，6 个有 `cross_clock_parent_timing_unknown`，1 个有 `missing_or_container_dependency`，其中存在重叠。跨时钟缺口包括三次原生失败 worker 和三次实际独立 renderer。其余 7 个没有局部缺口，但周报把全局两条 missing model finish 传播到全部 26 个 trace，关键路径仍为 `partial` / null。导出退出码 1 表达这一诊断状态，文件已经产出；不能据 span 总数估计完整 critical path 或 ETA。

各段真实 generation/review、音频和 delivery 有观测证据，原跨 run 关联按实际 lineage 保留，没有合成一条不存在的全程 DAG。**本次仍未执行统一 fresh ASR→Dev publish live Prefect DAG**；独立恢复和发布桥接暴露了产品接线不足，不能关闭 `DEV-DIAG-005/008`。

真实 Agents API 读取自己的已有会话在首次测试通过，读到 1 turn / 7 items；本次没有追加付费 Agent inference。当前 [诊断入口](../../scripts/sermon_agent_diagnostics.py) 仍要求 offline，live client 返回 `live_diagnostic_not_authorized`。用户放宽额度不等于适配器已经接通，`DEV-DIAG-004` 保持 pending。

## 问题登记与后续验收

新增四项均未实施产品修复：

| ID | 实际问题 | 修复后的关键验收 |
|---|---|---|
| `DEV-DIAG-011` | prompt 未明确 JSON、有序 coverage、四项 requiredChecks 和合法 reason 枚举，和 API/schema 不一致 | 原生输入无需私有补丁即可完成真实 Astra→Sol，错误响应保留 |
| `DEV-DIAG-012` | 全表 coverage 要求包含未使用系列，但插件在查 source 命中前拒绝 pending target=None | 明确未使用／确实使用项规则，术语来源和有效约束不退化 |
| `DEV-DIAG-013` | returned 无效产物、插件失败和派发前预算拒绝缺少具体持久化终态，controller 泛化为 unknown | call/revision/artifact 与具体失败关联，保守预算、恢复和成功 locale 均保留 |
| `DEV-DIAG-014` | 原生 worker 的依赖 import-time shell 和 subprocess guard 冲突 | 受控探测／导入，真实三语原生 worker 推理、解码和原期限收据；不全面开放 shell |

首次 39 次 HTTP 400 的精确错误 body 未保存，不能追补供应商原 error code；最小 JSON 请求成功和代码观察支持 `011` 的定位，但不证明历史所有 400 的唯一根因。私有 v6 driver 漏写异常 locale、过长 registerRules 被上限拒绝、H01/H03/H04/H05 属测试准备问题，和产品缺陷分别记录。

`DEV-DIAG-007` 从上游 blocked 更新为 `waiting_evidence`：独立真实三语音频和 Dev 可播已测得，原生 worker、正式同步/听审/包、设备/现场仍缺证据。其余问题不因 preview 成功关闭。接下来可按 backlog 修 prompt/术语与失败持久化，再修原生 worker 和统一 DAG，最后验收 live Agent；本次登记不自动启动下一批修复或生产发布。

## 私有证据索引与文档核验

完整原始证据位于 ignored `artifacts/dev-three-minute-20260930/`，不提交媒体、模型文本、stderr、凭据或私人绝对路径。

- 来源与机器链：`run-plan.json`、`results-v9.json`、`result-input-bindings-v9.json`、`continuation-discoveries-v3.json`、`findings-continuation.json`。
- 预算：`budget-attempt-{a,b,c}-final.json`、`cumulative-final-provider-budget.json`；旧账本独立保留。
- 原生失败：`run-linked-v9/native-worker-known-failures.json`、`run-linked-v9/linked-real-preview-results/`；真实独立音频：`run-linked-v9/standalone-real-previews/attempt-recovery-2/`、`run-linked-v9/final-audio-summary.json`。
- 发布：`standalone-prepublish-bindings-v9.json`、`dev-delta-v9/delta-receipt.json`、`deployment-receipt-v9.json`、`dev-http-verification-v9.json`、`dev-video-range-v9.json`。
- 浏览器：`browser-verification-v9.json`、`browser-summary-v9.json`、`dev-app-diagnostic-continuation-context.png`。
- 日志：`continued-logs/`、`continued-pipeline-report/`、`continued-safe-export/`、`continued-trace.json`、`continued-trace-diagnostics.json`。
- 最终边界：`final-acceptance-v9.json` 绑定部署、HTTP、浏览器、日志和预算收据 hash，保留原各阶段收据不改写。

本轮提交只更新文档；核验 diff whitespace、受影响本地链接、稳定 ID 唯一性、证据 hash 和收据数字。实际推理、完整解码、部署读回及浏览器验收如上；没有把文档检查或旧组件测试写成本次产品修复通过。
