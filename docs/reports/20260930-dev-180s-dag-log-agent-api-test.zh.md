# 2026-09-30 Dev 三分钟真实流程诊断

本次使用 `dev` 的 `63c0a18040b7f7744b334cebdb31778de228b064`，执行新的真实 ASR、英文源检查及三语翻译请求，并把实际结果和阻断状态发布到 Dev App。**完整三语文本、配音与四层发布未通过；当前 DAG、日志和 Agents 诊断入口尚不足以支持这条端到端流程。**

- [Dev App 测试周次](https://ai-for-god-sermon-audio-dev.web.app/?week=dryrun-20260930-real-180s)
- [三分钟原片、英文 ASR 与问题清单](https://ai-for-god-sermon-audio-dev.web.app/diagnostic-180s/dryrun-20260930-real-180s/index.html)
- [脱敏诊断报告 JSON](https://ai-for-god-sermon-audio-dev.web.app/diagnostic-180s/dryrun-20260930-real-180s/report.json)

## 执行范围与结果

用户授权：从开头跑三分钟测试到 Dev App，遇到问题先记录再继续，人工审核在本次测试默认通过。测试以 `user_authorized_default_pass_for_test` 单独记录；原始包的真实人工审批仍为 pending，`productionEligible=false`。默认通过人工环节不产生缺失的机器候选，也不替代机器生成和结构校验。

输入为已有、经用户授权的 2026-09-27 来源片段，原时间线 60–240 秒，文件实际容器时长 180.013167 秒。复用下载文件，重新完整解码校验；没有重新下载全视频。

| 阶段 | 实际执行 | 结果和限制 |
|---|---|---|
| 媒体 | 哈希、时长、完整解码 | 通过；片段 SHA-256 `79bada8f2e960adb470a146f183449db433308b53c20d03ea9c7e2e0a66e906b` |
| ASR | 新的 gpt-transcribe 请求 1 次 | 返回成功；英文属于机器结果，未逐字人审 |
| 英文源检查 | 新的 Astra 请求 1 次 | 返回成功；真实人审仅在测试上下文默认通过 |
| 锚点 | 重建 Source/Anchor 包，39 units、每语 13 groups | 新转写、音频、片段、窗口和旧对齐证据一致后复用 MFA；未重新执行 MFA 推理 |
| 三语翻译 | zh-Hans、ko、es，各 13 次 Astra 生成请求 | 全部 HTTP 400，三语均 `strict_locale_group_not_passed`，候选输出为空 |
| 独立机器审查 | 0 次 Sol 请求 | 上游生成失败，无文本可审查 |
| 配音 | 0 次真实 TTS 推理 | 三语 `machine_candidate_missing`；已记录下游阻断，不能据此判断 TTS 引擎故障或性能 |
| Dev 交付 | 独立诊断桥接脚本 + Firebase Hosting | 发布真实原片、英文 ASR、问题清单和三语阻断状态；没有伪造 Audio/Release Package |

旧 bounded run 的 5,400 秒期限已经失效。本次保留旧运行、旧账本与期限，建立独立新测试，不重置旧账本。新运行 ID 为 `9734563c3a3f13447afae6b37b9e99949c4d7a3977755ee321fae32edeb9b771`。

## DAG、日志与 Agents API

调用实际的 [bounded driver](../../scripts/run_bounded_diagnostic.py)、[strict locale producer](../../scripts/sermon_strict_locale.py) 和 [HTTP provider](../../scripts/sermon_provider_http.py)。由于当前真实诊断 Prefect 入口只到只读交付，本次用隔离驱动串接阶段，再用 Dev 桥接脚本发布；**没有执行一条统一的 fresh ASR → Dev publish live Prefect DAG**。桥接脚本位于 ignored artifacts，属于测试准备，并非已合入产品的发布实现。前端沿用已核验的完整 Dev Hosting 基线，只增补本次诊断入口；没有宣称整个前端重新从最新 dev 构建。

- 41 个 provider 请求均有终态收据：2 returned、39 rejected，unknown/reserved 状态均为 0。HTTP 400 不重复付费重试，也未擅自更换模型。
- 合并输出 323 条 accounting events、9 个 trace，导出 84 个 span；事件完整性检查通过，没有未闭合 span。
- 周报/关键路径整体为 partial；9 个 trace 中 7 个为 partial，其中 6 个缺少可识别依赖或 executor，1 个缺少或存在 container dependency。只有 2 个可投影，不能据此计算完整生产关键路径。事件数量齐全不等于 DAG 依赖与队列证据齐全。
- 真实 Agents API 读取自己的已有会话通过：retrieve session、list turns、list items，读取到 1 turn / 7 items。没有新建 Agent 会话或执行付费 Agent 模型调用。
- [诊断 adapter](../../scripts/sermon_agent_diagnostics.py) 对 live client 明确返回 `live_diagnostic_not_authorized`。已有 Supervisor 的 dual-PDF 角色也不等于本次四层诊断入口；本次没有验证 Agent 自动分析或修复这次真实故障。
- Prefect SDK + fixture/mock 的三个定向测试模块共 68 tests 通过，37.710 秒。这验证适配逻辑，不证明真实生产 DAG、真实 TTS 或新 Agent 推理通过。

预算收据中最坏情况保留为 10,302,911 microusd（约 $10.302911），不是实际花费。两个成功返回请求的已知估算合计为 88,675 microusd（约 $0.088675）；39 个 rejected 请求的 usage/billing 未知，未核对供应商账单。完整网络调用总数也没有从局部计数推定。

## 问题记录与建议验证

| ID | 观察到的问题 | 下一步可执行验证 |
|---|---|---|
| F01 | 三语全部 39 个 Astra 生成请求 HTTP 400 | 使用相同冻结输入做单组最小请求；取得安全错误 code/param 后再定位参数兼容性。现有证据不能确定具体原因 |
| F02 | HTTP 收据丢弃响应错误 code、param 等，只有状态码 | 增加脱敏、限长的结构化错误摘要；故障注入确认既能定位错误又不会泄露正文或凭据 |
| F03 | 同一种系统性 400 仍派发全部 39 组 | 检验系统性请求错误短路及可恢复终态，避免继续累积无效派发和预算保留 |
| F04 | Agents 会话读 API 可用，live 诊断 adapter 不可用 | 补齐有授权、有预算和脱敏输入的 live 诊断路径，再让 Agent 分析本次真实 trace |
| F05 | 最新 dev 缺少 fresh ASR 到 Dev 发布的统一真实 DAG | 接通执行、依赖、恢复状态与 Dev publish 节点；用新短片跑统一入口验证 |
| F06 | 原运行的绝对期限阻止暂停后的续跑 | 保留守卫；设计显式续期或新 attempt 的恢复协议，不能静默重置期限与账本 |
| F07 | 机器候选缺失阻止 TTS | 先恢复有效候选和机器审查，再运行真实三语 TTS；人工 default-pass 不能补出内容 |
| F08 | 7/9 trace 关键路径 partial | 补齐生产 executor、dependency、ready/queued 事件及跨阶段绑定，然后再计算整条关键路径 |
| F09 | App 明确显示失败，但通用文案仍为“配音准备中”“本周大纲已经就绪” | 区分 failed、pending、ready 展示，避免用户把失败当作仍在运行。本次仅记录，未修改产品 UI |

测试准备问题单独记录：H01 首次准备脚本误用语言插件单文件哈希，已改为 producer 要求的复合实现哈希，保留首次失败及 v2 输入；H02 新阶段导入模块扩展执行身份，使原 exact identity 预检失败，验证原模块集合和哈希后单独保存扩展身份；H03 首次 deploy 误用 Caption Dev project，CLI 因无对应 site 拒绝、未发布，核实项目后改用 Audio Dev。H01/H03 是测试驱动错误，不归因于产品故障。诊断桥接页面的配音说明也已修正为“本次没有生成配音”，重新部署并校验。

## 发布和验收证据

实际 Firebase project/site 均为 `ai-for-god-sermon-audio-dev`。发布前对完整基线 289 个文件做 GET/SHA 校验，并在部署前再次检查线上 ETag。发布后完整核验 295 个文件：保留 287 个原文件，更新 `app.mjs` 与 `published-weeks.mjs`，新增 6 个诊断文件。新增及修改文件使用 GET/SHA；保留文件用先前完整 GET/SHA 收据、当前本地 SHA 和线上 ETag 复核。说明文案修正后的 2 个文件再次 GET/SHA，其余 293 个再次 HEAD/ETag，最终全站检查通过。

- 原有 11 个周次保留，新增诊断周次后共 12 个；正式默认项和 `multilingual-v3.json` 保持原值。
- 原片 Range 请求返回 HTTP 206，读取 1,024 bytes，与本地对应字节一致。
- 浏览器核对三语切换均显示 `machine_candidate_missing`、无可播放配音，播放按钮禁用。
- 原片浏览器 readyState=4、时长 180.013167 秒、无 media error；点击播放后观察 currentTime 从 0 增至 31.776309 秒，再暂停。未验证浏览器完整三分钟播放、实体设备、场地或配音同步。
- 状态为 `published_http_verified`；device/venue acceptance 均 `not_run`，workflow scope 为 `isolated_real_diagnostic_partial`。这不是完整 `four_layer_release`。

## 本地证据与定向检查

原始日志、媒体、账本和恢复资料保留在本工作树 ignored 的 `artifacts/dev-three-minute-20260930/`，不提交 Git。关键文件：

- `authorization.json`、`run-plan.json`、`run/`、`inputs-v2/`：用户测试授权、预算边界、真实调用及冻结包。
- `l2.log`、`l2-v2.log`、`test-evidence.json`、`curated-issues.json`：首次准备失败、39 次真实拒绝、汇总问题。
- `combined-logs/events.jsonl`、`pipeline-report/`、`trace.json`、`trace-diagnostics.json`、`safe-export/`：323 事件、关键路径与脱敏导出。
- `agents-live-read-probe.json`、`adapter-checks.log`：已有会话只读测试与 68 tests；会话标识仅留本地。
- `dev-baseline-preflight.json`、`dev-http-verification.json`、`dev-video-range.json`、`deployment-receipt.json`：完整基线、最终 295 文件和 Range 验证。
- `browser-verification.json`、`dev-app-diagnostic.jpg`：浏览器观察与截图。

日志导出使用 [weekly report](../../scripts/weekly_pipeline_report.py)、[safe observability export](../../scripts/export_observability_trace.py)、[trace export](../../scripts/export_sermon_trace.py)。线上文件验证使用 [complete Dev snapshot preflight](../../scripts/preflight_firebase_dev_snapshot.py)。

```sh
SERMON_TEST_PREFECT=1 "$PREFECT_PYTHON" -m unittest \
  tests.test_sermon_diagnostic_prefect_flow \
  tests.test_sermon_agent_diagnostics \
  tests.test_sermon_business_prefect_flow

git diff --check
```

`PREFECT_PYTHON` 指向已有 Prefect pilot 环境；未安装新运行时。源码只提交本报告，未在这次测试中修复上述产品问题。后续真实三语音频、统一 DAG 及 Agent 自动诊断验收仍待 F01/F02/F04/F05 等修复后重新执行。
