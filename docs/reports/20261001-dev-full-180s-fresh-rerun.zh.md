# 2026-10-01 最新 Dev 三分钟完整重跑

本轮使用 `dev@7e534bb6eaf2a414def5bbd99167d6898a07b5b5`，同一片段重新执行 ASR、英文检查、本地 MFA、三语 Astra→Sol→插件/admission、原生 TTS、Firebase Dev 发布、完整浏览器播放及真实只读 Agents API。流程已跑到最后；**业务终态为 `incomplete`，交付只读汇合被 Fresh MFA 身份检查阻断；Dev 发布与播放成功分别成立。** 没有把失败回填为通过，没有在本轮修改产品代码消除原证据。

[Dev App](https://ai-for-god-sermon-audio-dev.web.app/?week=dryrun-20261001-dev-full-180s&tab=production) · [Backlog](../backlog.zh.md#dev-full-fresh-rerun-20261001)

## 输入与运行边界

- 代码：八个 PR 经 [#205](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/205) 整合后的上述 Dev SHA；执行前 fetch 并冻结代码、工具、输入、runtime、checkpoint 和预算。
- 视频：2026-09-27 素材的 `60–240s` 窗口，实际长度 `180.013167s`，大小 `113,034,700 bytes`，SHA-256 `79bada8f2e960adb470a146f183449db433308b53c20d03ea9c7e2e0a66e906b`；与上一轮相同。复用已核验媒体，未重新下载；当前 fixture 的 source URL hash 为 null，不能据此声称已验证链接 intake。
- Run ID：`1a4c7ad2b6cb87617bc8d61384fbd754cdf179fb573ea13b1eb5a8c6362df160`；独立 page ID：`dryrun-20261001-dev-full-180s`。
- 新 ASR、新英文源检查、新 `fresh_local_mfa`、新三语文字与新 39 个原生 WAV；未复用历史 Source/L2/audio。模型、授权音色 checkpoint、环境和既有媒体可以复用。
- 用户此前的 default-pass 仅用于隔离 Dev 测试继续推进；实际 source/translation/listening approval 保持 pending，`productionEligible=false`。机器审核失败仍须真实修复和复核。
- 本轮为 Mac 本地 MFA 与 Mac MPS 原生诊断路径。Spark SSH、模型及 MFA 已观察可用，但现有诊断 runtime 固定 Python 3.13/同主机执行，尚未接通 Spark Python 3.12 NGC 的远程 adapter；不能将本次称作默认 Spark 路径或正式 TTS batch/back-ASR 性能验收。

## 结果与实际覆盖

| 环节 | 本轮事实 | 限制／终态 |
|---|---|---|
| ASR／英文源／锚点 | 新 ASR、新 source check、新本地 MFA，39 英文单元，下游可用 | 英文逐字/窗口正式人审 pending；未补出 URL provenance |
| 三语文字 | 每语 13 组，最终 Astra→Sol→完整插件/admission 通过 | 正式译文/术语人审 pending |
| 中文局部返工 | `fresh-g012` 原 Sol execution succeeded、verdict needs_rework、reason meaning_addition；新 revision 由 Astra 重译、Sol pass，最终插件/admission 绑定新产物 | 两次新增请求；旧失败和修复链均保留，无关组未重付；该内容问题已在本轮处理 |
| 原生音频 | 三语各 13 个新 WAV，3 次模型加载，MPS float32/sdpa，39 个单元完整解码；当前 runtime/checkpoint/四事实收据核验通过 | preview_only；无历史音频 seed/cache；正式回转写、同步、听审、Audio/Release 未验 |
| Delivery readonly | 三语 ready 后实际检查失败：`fresh_delivery_source_mfa_changed` / ContractError | processed=false、readyForDownstream=false；原 final 保持 incomplete |
| Dev 发布 | 显式 Dev 诊断授权下继续发布；344 用户文件 HTTP/SHA，源视频 Range 206；独立线上完整 346 文件 gzip hash map 与配置核验通过 | 335 条旧用户路径全部保留；13 处允许的 UI/weeks 更新，9 新路径；正式 catalog 未变 |
| Chrome | 三语整轨及原片段自然 1×、0→ended，无 seek/加速/media error；18 UI 和诊断数据公网 SHA、三语切换、旧周 5 秒回归通过 | headless Chrome 154；源视频为核验 App 链接后的新未播放 video 元素。无真人听审、物理 iOS 或视频同步验收 |
| DAG／log | 业务 2469 events / 479 spans / 1 trace；无冲突、重复或未闭合阶段；3 组 native 四事实、12 条已记录跨进程边通过 | Fresh Source 依赖缺口导致 report/trace partial、criticalPath=null；UTC wall/resource queue/ETA 不确定 |
| Agents API | 一个真实 session/root turn completed，6 次只读工具提交，final 合同通过，diagnosisStatus=needs_more_evidence | 指出身份比较阻断，缺比较操作数、接纳关系与真实时序，未定位 MFA 具体根因；无业务写入/生成/重试/发布权限 |

Chrome 验收时间为 `2026-10-01T22:32:41.606Z–22:36:30.404Z`。音频实际时长：中文 `191.60s`、韩语 `215.20s`、西语 `194.08s`；视频 `180.013167s`。这些时长不等于语言质量或时间轴同步通过。

## 暴露的问题与修复验收

### Fresh MFA 身份误判：DEV-DIAG-016 / P0

`scripts/sermon_fresh_source_evidence.py` 的 fresh_local_mfa 分支把新 `mfa/backend.json.runtime` 与历史 runtime seed 做整体相等比较。实际只差 `adapterSha256` 和 `executionHost`：新 adapter SHA 正好等于本次冻结的最新 `scripts/mfa_alignment.py`；执行主机名称变化是新的执行 provenance。依赖 files/nativeKalpy/condaRecords/version/executionPlatform 元数据深比较一致，不是已观察依赖漂移。当前守卫在后续逐文件健康复验前就拒绝，因此元数据一致也不能冒充独立依赖文件健康证明。

修复应分别校验稳定依赖、当前冻结 producer 和本次执行 provenance，并在付费前检查 recipe/consumer 兼容。实际新 MFA 与缓存分支都须验收；未知依赖、篡改、过期来源及非冻结 adapter 仍要拒绝。不得简单删除 runtime 守卫。原失败证据保留。

### Fresh Source 因果边漏连：DEV-DIAG-008 / P0，重新打开

`diagnostic.transcription` 与 `diagnostic.source_model` 两个实际 provider execution leaf 缺 `dependsOn`；alignment 依赖 `diagnostic.fresh_source_check` container 而非实际 source_model leaf。既有 v8 缓存路径的依赖通过不覆盖这条新执行分支。需传递 typed completion span 并接通实际叶子因果关系；不能拿父容器/猜测时序补造依赖。完整 CP 未建立，资源/provider queue 与 UTC wall 缺测照实保留。确定性收尾观测仍归既有 `015`。

### 交付阻断未在 App 展示：DEV-DIAG-020 / P1

页面保留机器文字完成、DEV 试听待审、人工/正式资格待完成的真实状态，但没有展示后端 `delivery.readonly blocked` 及具体原因。需绑定同一 run/版本的整体状态和安全原因，独立展示「音轨可播」「交付检查阻断」「HTTP 已验证」，不能让 ready 音轨掩盖整体 incomplete，也不能把人审改为通过。

### Agent 证据不足以定位根因：DEV-DIAG-021 / P1

本轮真实 observer 约 `60.36s`，29 steps，66 次 transport returned（create_session 1、retrieve_session 29、list_turns 29、submit_tool_result 6、list_items 1）；工具为 packet 1、evidence 3、version_diff 2。通信、工具绑定、只读权限和最终诊断合同有效；**自动根因定位能力尚不足**。

当前安全包只提供通用 `identity_mismatch`、code/package 变更及 receipt hash/status；未提供实际字段比较和接纳关系，所有证据 observedAt 都等于 snapshot cutoff，无法推断先后。应以版本化白名单提供脱敏字段名、预期/实测 hash、匹配语义、原事件时间/monotonic 绑定、收据接纳及确定性复现证据；私密主机名/路径/正文/key 不进入 API。以本次失败和依赖漂移负例测试诊断，证据不足仍返回 needs_more_evidence，不授予修复执行权限。

### 可重复入口、计算 profile、完整基线：DEV-DIAG-017–019 / P1

本次实际功能调用成功，但仍依赖 ignored 私有 driver/input/bootstrap、线上基线重构与 observer/browser 桥接；现有 bounded CLI 不提供整个测试的一条可重复入口。需公开规范化预检/冻结/执行/断点/闭父/发布核验流程，提前验证硬额度、runtime/checkpoint 和最新 Source consumer，并保留 URL/媒体/窗口绑定；复用有效模型/媒体而不复用要重测的产物。

Spark 远程诊断需版本化 Linux/NGC/Python 环境、命令白名单、依赖/进程/时钟收据和 host adapter。当前诊断 renderer 为 scalar；正式 TTS batch=2/back-ASR=4 需要真实路径合同与门禁，不能靠伪造批准进入。此项归既有 DEV-SPD-003/DEV-L3-001。

发布前完整基线为 335 用户文件、约 2.05GB。旧 301 文件快照会遗漏近期 speaker-clips-v2；本次从完整实时 map 重构并验证，保留两个 Firebase 管理路径的独立合同。两次发布前 GET 证明当时基线未变，**不是原子并发保护**。规范发布器应验证完整基线/配置/管理资源并检查 stale，评估目标 lease 或服务端可用的原子条件机制，不能先声称 CAS 已支持。本次最终版本 `c44625ed9684c597`，release `1790893711594000`，344 用户文件共 `2,172,471,665 bytes`。

## 额度、工具准备和诚实未知

本次业务硬额度冻结为 124 requests / 5400s / 40,000,000 microUSD。实际 82 请求全部 returned（预计 80 + 中文局部返工 2），reserved/unknown/rejected 为 0；保守预留 `14,202,634 microUSD`，**不是实际费用或账单**。ASR token usage 缺测，完整 combined token total 保持未知。父运行已经永久关闭，newDispatchAllowed=false；observer 不修改业务账本。

Agents 独立观察预留 `2,000,000 microUSD` 保留，不退款；actual model、usage、cost 无返回，保持 unknown。observer-stop 为本地预算/次数/期限控制，不能描述成服务端硬额度。旧业务/Agents/D5 账本保持原样，历史未结项不补结算。

准备阶段先尝试 160 requests/10800s，被现有 hard cap 在 0 provider 调用时正确拒绝；随后才冻结合法额度。历史 checkpoint manifest 绑定旧绝对 validator 路径，被正确拒绝后按当前代码重建相同模型树声明。私有监督工具曾混入 attempt marker 计数、混淆 collector/business run ID、漏取 node.reason；各原版本保留，修正工具并以实际 typed 收据复核。observer-v4 执行前 16 个零 API 测试通过，v1–v3 未执行新 API。这些为准备/监督工具问题，不新建未修复产品缺陷。

## 证据与复查

原始媒体、provider response、日志、账本、浏览器截图与 API 回包只在 ignored `artifacts/dev-full-rerun-20261001/`；不将私密材料写入 Git。

| 证据 | 相对上述 root 的位置／SHA |
|---|---|
| 冻结计划及原业务终态 | `run-plan.json`、`final-result.json`（终态文件 SHA `1e6a96bec2d08ab8db68101082f96cb1559d25af65e5acebdbc1cd5515056d74`） |
| 原业务审计与返工链 | `audit-tools/terminal-audit-summary.json`；`audit-tools/snapshots/1909ac72c78f92ee59d43ca3ba7c95ee041824ed96b2cc850dc25b08ee5ec152/` |
| 含 observer 的独立终态审计 | `audit-tools/final-observer-audit.json`；`audit-tools/snapshots/ce6576c2262e0fb3ccf731601afceb282712de9877cf7d1c9d89ce1a92635e73/`：2483 events / 483 spans / 2 traces，仍 partial；plan/final/providerState/closed 与原业务快照相同，原业务日志字节 SHA 不变 |
| MFA 比较失败 | `audit-tools/fresh-mfa-inspector-failure.json`（SHA `6cb144a49925c330c56cc976f65b553b7b6dce3d71c3102f8eddfccd15804f57`） |
| 发布 HTTP 与独立线上审计 | `dev-candidate/http-receipt.json`；`delivery-audit/summary.json`、`postpublish-version-audit-2026-10-01T22-32-19-628Z.json` |
| 完整浏览器播放 | `browser-tools/final-browser-audit.json`、`chrome-complete-attempt-1/acceptance-receipt.json`（原收据 SHA `c9d0e667e065260a520475722b57aefa690eeec816a13c54deb29e27288794c2`） |
| 真实只读 Agent | `audit-tools/observer-prepared/99684b0011b5bd7ed766d0bb16cc4581de5822035f96f1146d5d4616e9c740c4/result-summary.json`；auth SHA `1fb721859cabf1d336cfb75cc423eb33dbfabfe3c03f75065d3bb05d4dc443a3` |

复查导出使用现有 `weekly_pipeline_report`、`export_observability_trace`、`export_sermon_trace`，参数和独立新输出目录见各 audit snapshot 的 `reproduce-commands.json`。含 observer 的终态快照独立生成，不覆盖原业务快照。新测试证明真实生成、原生执行、Dev HTTP 和浏览器完整播放；未证明正式人审、回转写、同步、正式四层发布、iOS 真机、会场或整篇性能。
