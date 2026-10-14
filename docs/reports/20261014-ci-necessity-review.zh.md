# CI 抓到了什么，以及 CI 还值不值得跑（2026-10-14）

数据范围：仓库从 2026-08-03 第一次 CI 到 2026-10-13 的全部 GitHub Actions 运行（3289 次，其中 Python tests 1588 次、Tongxing iOS 1342 次、Local Prefect pilot 272 次），394 个 PR（已合并 284 个）。253 个失败 job 的日志全部读过，提取了失败测试名和报错。分类是我按报错和后续提交判断的，个别条目（尤其 iOS UI 测试日志没打印断言的）属于推断。

## 一句话结论

Python 全量测试值得保留：在合并前拦住了约 18 起跨模块回归，几乎都是 agent 改了 A 模块、本地只跑了 A 的测试、结果把 B 模块弄坏。真正需要动的是噪声：约 1/3 的失败是 flaky 测试和文档行尾空格，iOS UI 测试在 macOS 上又慢又不稳，dev 上的 push 全量重跑两个月没抓到过一个真问题。

## 1. 失败都是什么

151 次失败的运行（不含被新 push 取消的 559 次）：

| 类别 | 次数 | 占比 | 说明 |
|---|---|---|---|
| 真实失败（代码或测试确实不一致） | 88 | 58% | 归并为 48 起事件，见下 |
| 已知 flaky 测试 | 28 | 19% | 同一测试在 3 个以上无关分支上随机失败 |
| 同一提交重跑就过 | 9 | 6% | 7 次是 iOS UI 测试 |
| 文档 `git diff --check`（行尾空格） | 24 | 16% | docs_change_gate，约 17 个分支 |
| Runner 环境（缺 ffmpeg/ffprobe） | 2 | 1% | |

**合计约 41% 的红灯与代码正确性无关。**

### 1.1 真实失败的 48 起事件

| 类型 | 事件数 | 例子 |
|---|---|---|
| 跨模块回归（不修会在运行时坏） | ~18 | #184 `sermon_run_progress.py` 里 `NameError: seen`；#91 新加 ko/es/vi 后界面语言表缺键；#180 accounting 字段改名后 `KeyError: reportGenerationNetworkCalls`；#242/#248 统一运行时和模型后 benchmark、迁移、Prefect strict policy 一起坏；#335 Layer 1 改动后 `tailOverrunSeconds` 缺失导致 Layer 3 导出 34 个测试挂；#362 韩语数字改动打断 machine QC clip 测试 `synthesisIdentity`；#380/#383 API 阶段改动后 `api_cli_outcome_directory_required_before_dispatch`；#382 预算规划器让术语表测试报 `unsupported_bounded_provider_model`；#343 解包错误；#19/#29 iOS 编译错误（`allowBluetoothHFP`、Swift 类型检查超时） |
| 批量合并/集成时的语义冲突 | 4（含在上面） | #205「批量合入八个 PR」、#332「Merge non-report PRs into dev」、#383、#91，单个 PR 各自是绿的，合到一起才红 |
| 测试锁死常量或快照，需要同步更新 | ~14 | #46 模型名 `gpt-6-sol != gpt-6-astra`；#232/#235/#241 iOS 版本号和 build 号 pin；#287 测试 fake 缺新属性；#181/#198/#218 状态值/快照变化 |
| CI 自检（新测试没登记到 workflow） | 3 | #256/#276/#322 `test_ci_change_scope` 要求新原生测试写进 native_contracts 列表 |
| iOS UI 测试失败、日志无断言 | 7 | #32/#41/#45/#46/#48/#49/#195，大多在下一个提交或重跑后通过，无法确认是否真实 |
| 其他（时间相关断言等） | 2 | #120/#130 `published-weeks.test.mjs` 要求 500ms 内加载，实际 689ms（该断言后来已删除） |

第二类（锁常量）是这个仓库的测试风格造成的：大量测试把模型名、版本号、hash、快照写死，作用是"改了就必须有意识地同步"。它们确实拦住了无意的漂移，但也让每次有意的改动都要多一轮。

### 1.2 Flaky 测试（按影响排序）

| 测试 | 影响分支 | 时间 | 状态 |
|---|---|---|---|
| `test_lease_fencing ... test_real_timeline_child_completes_after_multiple_original_ttls` | 11 | 9/20–10/2 | 10/2 之后没再出现，似乎已修 |
| `test_sermon_app_delivery_workflow ... test_two_actual_supervisor_cli_processes_admit_one_fixed_bundle` | 5 | 10/7–10/12 | 10/12 已修（8e89806a：准入后新建的 queued 作业视为等待） |
| `test_run_spark_diagnostic_audio ... test_readonly_gateway_...`（BrokenPipe） | 3 | 10/7–10/12 | 10/12 已修（4bf72e64：被拒连接不再写入），dev push 上红过 2 次 |
| `test_sermon_pilot_evidence ... test_engine_then_readonly_report_replay_and_failure` | 3 | 10/8–10/13 | 仍在；本地含并发负载跑 10 次未复现，失败时只打印了 Prefect 日志，看不到哪个节点失败 |
| `test_canonical_layer2_auto_repair ... test_groups_run_concurrently_in_the_worker`（1 != 2） | 2 | 10/13 | 仍在：靠 50 ms sleep 期望两组重叠，慢 runner 上第一组先跑完 |
| iOS `testPublishedLanguagePageIsVerifiedAndNativePlayerRemains`、`testForegroundAlignmentIslandSyntheticFeedbackScreenshots`、`testTranscriptAutomaticallyFollowsNextCaption` 等 | 多个 | 9/23–10/7 | island 测试是 #269 用 admin bypass 的原因；10/7 21:10 之后 main/dev 上的 ios-validation 全部通过 |

### 1.3 基线本来就红

dev/main 的 push 运行共红过 11 次：9 次是上面的 flaky 测试，2 次是 iOS island UI 测试。**dev push 全量运行（288 次）没有抓到过任何真实回归**，它抓到的都是 PR 上已经暴露过的 flaky。

### 1.4 带红合并

284 个已合并 PR 里，239 个 Python CI 一次没红过，45 个至少红过一次，修好后合并。最后一次检查仍红就合并的有 4 个：#380（API-only 阶段，Python 红）、#285（Decision API 试验）、#267（iOS 1.26.16 发布）、#269（W41 推广，iOS island 测试）。

## 2. 成本

- 仓库是公开的，GitHub 托管 runner 分钟数免费，目前没有现金成本。若转私有，按近 3.5 周用量（Linux 约 48,400 分钟、macOS 约 3,060 分钟）粗估每月 $600–800（推断，按当前公开价位估算）。
- 真正的成本是等待：Python 全量测试成功运行的中位时长 W40 约 7 分钟，W41 约 16 分钟，W42 约 16 分钟（测试数增长抵消了 8 分片的收益）。每次 push 要等一轮，agent 修一轮 flaky 或行尾空格也要再等一轮。
- 1588 次 Python 运行中 380 次被新 push 取消，说明 agent 经常连续 push，取消机制在起作用。
- iOS：macOS job 1342 次运行里，contract-validation 跑了 503 次（约 780 分钟），native-client/ios-validation 约 2,280 分钟，后者失败里 UI flaky 占多数。

## 3. Codex 审查和 CI 的分工

这次没有系统统计 Codex 评论，只按已知情况对比：CI 抓的是"能执行出错"的问题（缺键、改名、跨模块契约、编译错误）；Codex 抓的是边界条件和设计问题（例如 #260 的 15 轮语言边界情况），这些测试里本来没有覆盖。两者几乎不重叠，不能互相替代。

## 4. 建议

按收益排序：

1. **保留 PR → dev 的 Python 全量测试作为必需检查。** 它是唯一能拦住跨模块回归的环节，这两个月拦了约 18 起。在多个 agent 并行改同一个仓库、本地只跑相关测试的工作方式下，这一层不能去掉。
2. **修掉仍在出现的 flaky 测试。** 上表第 2、3 行和 Node 500ms 断言已在 dev 上修好，iOS island 测试 10/7 后也已转绿；剩下 Layer 2 并发计时和 Prefect pilot 回放。这能去掉约 1/4 的红灯，也是 #269 那类 admin bypass 的根源。修法是去掉真实计时/真实 socket 依赖，不是跳过。
3. **行尾空格不要再靠 CI 发现。** 24 次失败、约 17 个分支；全部来自 `run-report/*` 分支：拷贝的日志（torch 警告、xcodebuild 输出）带行尾空格，INDEX.md 或复盘 Markdown 末尾多空行；另有 1 次是断链。让 `export_run_digest.py`/`publish_run_report.sh` 写文件时去掉行尾空格，或在 AGENTS.md 里要求 push 前跑 `git diff --check`（AGENTS.md 已写了 docs-only 要跑，但生成报告的路径漏了）。
4. **dev 上的 push 全量运行改成每日一次定时运行。** 两个月 288 次没有抓到真实问题，只重复暴露 flaky。保留一次夜间全量，用来发现合并顺序造成的语义冲突（#205/#332 这类）。代价是这类冲突最晚次日才发现；如果想当场发现，可以改用 merge queue，这是另一个更大的改动。
5. **iOS UI 测试（ios-validation）只在推广到 main 和手动触发时跑，并且先修 island 测试。** 现在已经基本是这样配置的（dev 上跑 contract，main 上跑模拟器），要做的是修测试，而不是继续用 admin bypass。iOS 编译错误（#19/#29）是 contract/编译检查抓到的，保留。
6. **锁常量类测试保持现状。** 它们是在给"有意改动"收过路费，但这正是四层契约要求的身份绑定。可以考虑的改进是报错时直接提示"要更新哪个常量"，减少 agent 多一轮的猜测。
7. Local Prefect pilot 保留（按路径触发，10 次失败里 7 次是真实契约破坏）。Tracker contracts 和 Branch promotion 很便宜，保留。

做了 2–4 之后，预计红灯里的噪声从约 41% 降到 10% 以下，dev 上的 CI 运行次数少约 18%，每次 PR 等待时间不变（约 16 分钟）。如果还想压等待时间，下一步是"Install audio verification tools"缓存，或者按改动范围只跑受影响模块再加夜间全量，但后者会放走一部分跨模块回归，不建议先做。

## 附：方法

- 运行和 job 明细来自 GitHub Actions API；失败 job 日志用 GitHub MCP 读取并提取 FAIL/ERROR 行。
- "flaky" 的判定：同一测试在 3 个以上无关分支失败，或同一提交重跑后通过。
- "真实失败" 按分支归并成事件，再按报错人工归类；iOS UI 测试日志多数没有断言内容，归类是推断。

## 5. 实施（2026-10-14，同一 PR）

- `test_groups_run_concurrently_in_the_worker`：第一个调用等第二个调用到达（最多 5 秒），不再赌 50 ms sleep；串行实现仍会以 peak=1 失败。
- `test_engine_then_readonly_report_replay_and_failure`：没能复现，先让断言同时打印 stdout（每个节点的 executionStatus/reason），下次失败能看到原因。
- `export_run_digest.py` 新增 `--tidy-whitespace`，导出时自动执行；`publish_run_report.sh` 在提交前再整理一次，并用 `git diff --cached --check` 拦住剩余问题，不再推到 CI 才发现。
- Python tests：去掉 push 到 dev 的触发，新增每日 UTC 10:17 定时运行（检出 dev，全量）和手动触发。定时任务读取 main 上的 workflow 文件，下次推广到 main 后生效；失败时 GitHub 通知最后修改 cron 的人。
- iOS UI 测试已经只在推广到 main 和手动触发时运行，不需要改。
