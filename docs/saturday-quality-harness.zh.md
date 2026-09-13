# 周六质量回归 Harness

已接入本地 **Promptfoo 0.122.2**，并冻结一组真实证道模型审核样本。运行器读取已保存的文本、口读输入、ASR 收据和媒体，不调用收费模型，也不授予人工验收或发布资格。

## 安装与运行

依赖独立放在 [quality-promptfoo](../experiments/sermon-dubbing-poc/quality-promptfoo/package.json)，不全局安装、不修改播放器或已有服务。使用锁文件重装已实际验证：

```sh
PROMPTFOO_DISABLE_TELEMETRY=1 PROMPTFOO_DISABLE_UPDATE=1 \
  npm ci --prefix experiments/sermon-dubbing-poc/quality-promptfoo \
  --ignore-scripts --no-audit --no-fund
```

要求 Node.js ≥ 22.22；本次使用 26.7.0。Node 依赖较大，留在已被 Git 忽略的 `node_modules/`；提交范围只有 manifest、锁文件、适配器和小样本。真实媒体检查另需项目 `.venv`、`ffmpeg`、`ffprobe`。

运行真实 v3 基线及完整现有媒体检查：

```sh
.venv/bin/python experiments/sermon-dubbing-poc/quality-promptfoo/run_eval.py \
  --suite experiments/sermon-dubbing-poc/quality-baselines/2026-09-06-l8ucqF9uA9A/suite.json \
  --baseline experiments/sermon-dubbing-poc/quality-baselines/2026-09-06-l8ucqF9uA9A/baseline-v3.json \
  --candidate experiments/sermon-dubbing-poc/quality-baselines/2026-09-06-l8ucqF9uA9A/baseline-v3.json \
  --media-work artifacts/sermon-dubbing/2026-09-06-live-fallback-v3-numbers
```

省略 `--out-dir` 时会建立新的 `artifacts/saturday-quality/runs/<时间和随机ID>/`，保留每次结果。指定目录必须新建或为空。输出包含 `comparison.json`、实际 `promptfoo-results.json`、日志、配置、锁文件哈希和 `run-receipt.json`；传入 `--media-work` 时另有 `media-check.json`。媒体 job 哈希必须与 candidate 绑定，不能用另一个任务的媒体为此候选背书。

运行真实历史负例时，将 `--candidate` 改为同目录的 `known-issue-v2.json`，并省略 `--media-work`。它应失败：Promptfoo 退出码为 `100`，统一运行器返回 **1**。检查通过返回 **0**；输入或执行故障返回 **2**。baseline 与 candidate 任一失败都不能判为通过，沿用坏 baseline 不会抹平现有问题。

## 已完成的实际验证

| 检查 | 2026-09-06 观察结果 |
|---|---|
| 合成 fixture 正例 / 缺段与数字负例 | Promptfoo 实际 1 pass / 1 fail，均无执行错误 |
| 真实 v3 的 8 个固定样本 | Promptfoo 实际 1 pass；模型审核身份保留 |
| 真实 v2 历史数字问题 | Promptfoo 实际 1 fail；拦住 4 项数字口读/识别约束 |
| v3 自然 WAV、自然 MP3、英文源片段、同步 MP3 | 全部重新完整解码，实际哈希和时长匹配绑定报告 |
| v3 全文同步 | 58 块按现有声学锚点与 placement 重新计算，无预算失败 |

自然中文时长为 **1711.05 秒**，源片段和同步 MP3 均为 **1967 秒**。已有 ASR 报告仍有 **38 条 review candidates**；本轮没有将这些条目改为人耳通过，没有重新调用 ASR，也没有清除待审状态。

本轮原始观察报告位于：

- `artifacts/saturday-quality/promptfoo-synthetic-pass-20260906/`
- `artifacts/saturday-quality/promptfoo-synthetic-regression-20260906/`
- `artifacts/saturday-quality/promptfoo-real-v3-20260906/`
- `artifacts/saturday-quality/promptfoo-real-v2-knownissue-20260906/`

这些是本次运行证据，不代表未来重新运行结果或线上健康状态。

## 真实基线与审核身份

真实样本来自公开证道 [l8ucqF9uA9A](https://www.youtube.com/watch?v=l8ucqF9uA9A) 已保存的 v3 job，覆盖 blocks **1、2、9、10、17、38、42、53**。选择包含地名、数字、专名、否定、神学术语、经文和疑惑/信心表达。原始 58 块审核是 `gpt-6-astra` 模型审核；音色认可不等于逐句 human Gold。v2/v3 的整篇音频人工审核仍 pending。

[冻结目录](../experiments/sermon-dubbing-poc/quality-baselines/2026-09-06-l8ucqF9uA9A/suite.json) 和 [构建器](../experiments/sermon-dubbing-poc/quality-baselines/freeze_reviewed_baseline.py) 保存所选原文、已审核中文、实际 TTS 输入、实际 ASR 识别以及收据/音频哈希。构建器只读原任务，写入一个新的空目录；不会覆盖既有快照。

真实数据使用显式 **v2 schema**，与合成 v1 fixture 分开：

| 契约 | 说明 |
|---|---|
| `saturday-quality-suite-v1` / `output-v1` | 原有合成 fixture 和明确的人工审核字段契约，保持兼容 |
| `saturday-quality-suite-v2` | 仅 `model_reviewed` 真实样本；`modelReviewEvidence` 绑定生产 job；每块绑定英文和参考中文哈希，保留 `humanApproval: false` |
| `saturday-quality-output-v2` | `jobEvidence` 绑定各自实际生产版本；所有样本的 `unitEvidence` 完整覆盖其实际单位，逐项绑定原 WAV 和 ASR 收据 |
| `saturday-quality-comparison-v1` | 固定 suite 哈希、两组输出哈希、逐项 `regressions` / `resolved`、原 ASR 指标；`humanAcceptance: not_evaluated` |

v2 校验复用既有 `validate_frozen` / spoken-review 校验链，核对父 job、模型审核、原输入、正文修改和证据哈希。原始本地 artifacts 必须仍可用；缺失或改变时失败，不能只重填 hash 来让旧输出通过。v2 不允许改标为 `human_reviewed`。

## 为什么旧 ASR 满分仍必须失败

真实 v2 的 block 2 包含源英文 **5,300** 与 **3,000**。旧规则把 TTS 输入变成“`五,三百`”和“`三,零`”；保存的 ASR 分别识别成“`五三百`”和“`三零`”。当时两个 unit 的 `similarity` 都是 **1.0**，`differences` 都为空，因为错误也存在于比较用的 expected 中。

新 v2 数字规则绑定源英文 token 与整数值，再用项目现有 `cardinal()` 导出规范口读，分别检查：

1. 中文显示保留正确数值，允许源数字或等值中文数词。
2. 实际保存的 TTS 输入出现“五千三百”和“三千”。
3. 实际保存的 ASR 识别仍包含相同数值。

因此旧 v2 即使自洽仍失败四项；v3 已保存 unit 5 的“五千三百 / 三千”通过。本检查不会把 ASR 对上文字当成人耳验收；匹配只表示没有触发这两条确定性数字回归。

其他检查包括完整样本 ID 覆盖、英文保真、中文为空、重复完整段落/句子、显式术语和禁用片段、版本化口读输入。它们不证明所有语义都正确；8 个样本也不代表全文逐句质量验收。含刻意重复修辞的新样本需先定义例外规则并测试，不能直接放宽通用检查。

## 现有媒体的真实复查

[media_check.py](../experiments/sermon-dubbing-poc/quality-promptfoo/media_check.py) 可单独执行：

```sh
.venv/bin/python experiments/sermon-dubbing-poc/quality-promptfoo/media_check.py \
  --work artifacts/sermon-dubbing/2026-09-06-live-fallback-v3-numbers \
  --out artifacts/saturday-quality/new-media-check.json
```

输出文件必须新建且位于原 job 外。检查执行 FFmpeg 完整解码及 ffprobe 时长探测，核验前后媒体哈希、job/render/ASR/assembly 的关联，复用 `load_anchors`、`load_placements` 和 `budgets` 重算现有时间证据。它不合成、不改速、不重写音频、不调用模型、不模拟人工试听。原有完整发布验收仍须执行。

纯 v1 文本检查仍可用 [quality_harness.py](../experiments/sermon-dubbing-poc/quality_harness.py) 的 `--suite --baseline --candidate --out` CLI。其可选六项 `evidence`（job、naturalAudio、asrScreening、timing、syncedAssembly、syncedAudio）是保存报告复核；需要真正重新解码时使用上述媒体 CLI。

## 本地执行与网络约束

Promptfoo [自定义 provider](https://www.promptfoo.dev/docs/providers/custom-api/) 只读刚生成且哈希锁定的比较报告；[JavaScript assertion](https://www.promptfoo.dev/docs/configuration/expected-outputs/javascript/) 实际判定结果。运行器检查 provider 和 assertion 确实执行，不能把空 eval 或启动失败当成通过。

根据[官方遥测说明](https://www.promptfoo.dev/docs/configuration/telemetry/)禁用 telemetry 和更新检查，并使用[官方 CLI](https://www.promptfoo.dev/docs/usage/command-line/) 的 `--no-share --no-write --no-cache`。不继承模型密钥或云配置，配置目录也独立放在本次 artifacts 中。运行器要求 macOS `sandbox-exec` 的 `deny network*`：不仅不配置联网 provider，操作系统也拒绝网络访问；测试已证明 loopback 连接返回 `EPERM`。安装依赖需要 npm registry，评估阶段不联网。

## 验证命令

```sh
.venv/bin/python -m unittest discover \
  -s experiments/sermon-dubbing-poc -p test_quality_harness.py -v
.venv/bin/python -m unittest discover \
  -s experiments/sermon-dubbing-poc/quality-promptfoo -p 'test_*.py' -v
```

第二组会实际运行已安装 Promptfoo 的正负例和网络拒绝测试；真实回归测试在原收据缺失时明确 skip，不能替代有原收据的实际运行。测试中的一秒静音 WAV 仅验证解码器错误门槛，真实媒体证据是上表列出的本周完整文件。
