# 机器质检豁免与 TTS 前时长预算

## 决定

2026-10-06，Jony 在项目线程里确定了以下规则：

- 中文、韩语、西语都改为**机器质检通过后自动发布**。人工改为发布后抽查，发现问题再发修订版。证道起止时间仍由人输入。
- “每句最多落后 8 秒”是同传听感的目标，保留。时长控制前移到 TTS 之前，不再依靠事后批例外（例如 10/4 的 62 秒）。
- 翻译和复核可以用同一个模型，前提是有可测量的质量证据。
- 修复按**单句**计数：先修 2 次，不行再修 2 次，每句最多 4 次。5% 也按句子（英文 source unit）计算，一个含多句的组按它的句数计入。
  - 音频仍不过关：这一句只显示字幕，不配音。
  - 文字仍不过关：这一句改为显示英文原文。
  - 不配音的句子超过全篇 5%：整个语言改为只发文字（`audio_unavailable`）。
  - 失去译文的句子超过全篇 5%：该语言暂停发布。

机器质检豁免**不是**人工批准。豁免收据里 `humanApproval` 保持 `false`，`reviewKind` 写为 `machine_quality_waiver`，页面必须显示 `disclosure` 文案。

## 组件

| 环节 | 入口 | 作用 |
|---|---|---|
| L2 逐组确定性检查 | `language_review_plugins/ko_weekly_auto.py`、`es_weekly_auto.py`（共享 `auto_qc_text_common.py`） | 每周通用，不写死任何一篇讲道。检查目标文字脚本与占位符（西语须以拉丁字母为主；中文须为简体，假名、谚文或繁体字都会失败）、未翻译的英文、语域（西语不得用 vosotros，包括省略主语的 decís、sois）、术语表人名、经文出处（英文说了就必须有，没说不能加；带书卷名的引用要对上同一卷书，66 卷的中韩西名称在 `_BIBLE_BOOKS`）、数字（数字或目标语言读法；含小数和 “nineteen ninety-nine” 这类年份读法） |
| L2 整篇检查 | `scripts/target_text_auto_qc.py` | 长度离群：与本篇中位数比较。**回译比对**：第一次调用只给目标语言文字，翻回英文；第二次调用对比冻结英文和回译，判断有没有漏译、增译、否定、数字、人名、经文、意思偏移。模型调用由调用方注入，没有回译结果的组不能判为通过 |
| L3 单句检查 | `scripts/target_audio_auto_qc.py` | TTS 之后马上检查：时长异常（与本篇语速中位数比较，以及与原声时长之比）、截断、近乎无声、静音过多、长停顿、削波、句首句尾静音过长。回转写两级：小 ASR 标出的疑点由强 ASR 复核（必须是另一个模型），两边都不一致才判失败。每个 ASR 结果都绑定所听音频和预期文字的哈希以及模型；音频重合成后沿用旧分数无效，这一句停在 `pending_primary_asr`，不能只凭声学指标通过 |
| 8 秒预算 | `scripts/target_audio_predicted_schedule.py` | 用已测音频拟合各语言语速，再用正式排程公式按**预测时长**排一次。超窗的组给出 `maxSpeechUnits`，供口播修订一次改到位。语速绑定 speech job 的合成身份（adapter、配置、模型版本、音色、说话人、conditioning、语言参数、文本规范化）和所测音频的哈希；身份不同就拒绝预算，需要重新拟合 |
| 注错校准 | `scripts/auto_qc_seeded_errors.py` | 在干净成品里注入已知错误，统计每类检出率和干净样例的误报率。只有出现干净版本没有的新问题才算检出（错句配音必须由 ASR 判出），不会把原有误报算成检出。文字类含换书卷（wrong_book），音频类含换成别句的配音（wrong_sentence，需要注入 ASR transport） |
| 豁免收据 | `scripts/machine_quality_waiver.py` | 汇总最终 QC 结果，按上面的 5% 规则决定这个语言是自动发布、只发文字还是暂停。先核对 QC 收据确实检查的是这份候选（每组译文哈希）和这份音频包（候选哈希、每句音频哈希），对不上就报错 |
| 门禁收据 | `scripts/machine_quality_release_basis.py` | 生成并校验两种绑定到具体产物的收据：**译文豁免**（`sermon-target-language-machine-text-waiver-v1`，绑定一个 L2 候选）和**试听豁免**（`sermon-target-language-machine-audio-waiver-v1`，绑定一个 L3 音频包、它的 ASR 筛查和口播稿的译文豁免） |

## 校准门槛

只有满足以下全部条件，才允许豁免：

- 校准收据的 `implementationSha256` 与当前 QC 代码一致。代码一改，必须重新校准。
- 校准时回译检查实际参与了（`semanticChecksIncluded=true`）。
- 本次 QC 用的回译运行身份（`semanticIdentity`：后端、模型和设置）和 ASR 模型，必须与校准时一致。换成别的模型或后端，必须重新校准。
- 总检出率 ≥ 95%，每类 ≥ 90%。每一类注错都必须实际试过（`trials > 0`）；缺一类或某类零样本都算校准不足。要发配音时，校准还必须包含音频各类；只发文字时，音频类的结果不影响放行。
- 干净样例误报率 ≤ 10%。

只做离线确定性检查时，“删掉半句”这类错误只能检出约 58% 到 75%（见测试样例）。这正是必须加入回译检查的原因。

## 命令

```bash
# 用已有正式音频拟合语速（rows: [{text, audioSeconds, audioSha256}]，--speech-job 为这些音频的 job）
python scripts/target_audio_predicted_schedule.py fit --input rate-input.json --speech-job measured-job.json --out rate.json
# TTS 前预测排程（groups: [{gid, sourceStart, sourceEnd, text}]，时间相对 clip；--speech-job 为本次要合成的 job）
python scripts/target_audio_predicted_schedule.py budget --input groups.json --rate rate.json --speech-job job.json --out budget.json
# 单句音频 QC（units: [{groupId, text, sourceSeconds, wavPath, asr: {primary, secondary?}, priorFailedAttempts?}]，
# 每个 ASR 结果为 {similarity, audioSha256, textSha256, model, modelRevision?}）
python scripts/target_audio_auto_qc.py --input units.json --out audio-qc.json
# 离线注错校准（不含回译和 ASR transport，因此不能单独解锁豁免）
python scripts/auto_qc_seeded_errors.py --input calibration-input.json --out calibration.json
# 豁免决定
python scripts/machine_quality_waiver.py --locale ko --candidate candidate.json \
  --text-qc text-qc.json --audio-qc audio-qc.json --audio-package audio-package.json \
  --calibration calibration.json --out waiver.json
# 译文豁免收据（代替人工译文审核收据）
python scripts/machine_quality_release_basis.py text --source source.json --anchor anchor.json \
  --candidate candidate.json --text-qc text-qc.json --calibration calibration.json --out text-waiver.json
# 用译文豁免进入第 3 层：写出 speech job v3
python scripts/prepare_target_language_speech_job.py ... --text-release-basis text-waiver.json --out speech-job
# 试听豁免收据（代替人工试听收据）；ASR 标出的句子必须有强 ASR 复核
python scripts/machine_quality_release_basis.py audio --package audio-package.json --screening screening.json \
  --audio-qc audio-qc.json --text-waiver spoken-text-waiver.json --calibration calibration.json \
  --secondary-asr-model gpt-transcribe --out audio-waiver.json
```

## 当前接线范围

**已接上：**

- **L2 → L3：** `prepare_target_language_speech_job.py` 接受译文豁免收据（`--text-release-basis`）。这时候选保持 `machine_review_pass_human_review_pending`、`humanReview.translation=pending`，写出的 speech job 是 v3：`inputs.textReleaseBasis` 绑定豁免收据，`textPolicy` 为 `exact_machine_waived_target_text`。人工收据仍写出原来的 v2，已有的 job 身份不变。所有读取 speech job 的生产者（音频包构建、单句完整性、严格链 L3 准备、恢复计划、ASR 筛查）都接受 v2 和 v3。
- **L3：** 音频包仍按构建结果保持 `machine_screened`（ASR 全过）或 `candidate`（ASR 标出疑点），`humanApproval=false`。试听豁免收据可以代替人工试听收据，通过 `validate_audio_screening_review`、`inspect_canonical_audio`（配置项 `machineWaiver`）和 `sermon_unified` 的 `audio` 审核。ASR 标出的每一句都必须有强 ASR 复核通过。
- **sermon_unified：** `ingest_review` 接收两种豁免收据，把该步记为 `review=waived`、事件 `review.waived`，不写 `approvedAt`。`translation_approved` 和 `listen_approved` 两个范围接受 `waived`；大纲与默想仍要求人工 `approved`。

第 1 版豁免只放行**每一句都通过**的语言：有句子要只显字幕或改显英文时，收据不会生成，这个语言仍走人工路径。

**还没有接上：**

1. 第 4 层：`build_full_video_app_release.py` 与 `sermon_unified_delivery` 仍要求人工译文收据和 `human_reviewed` 音频包；发布包、目录和网页/iOS 客户端还没有“机器质检”状态和披露文案。目录里一旦出现新状态，旧版 iOS 会拒绝整个目录，所以需要新目录版本，并先发新版客户端。
2. 回译检查的真实模型 transport（沿用 L2 的后端身份与缓存规则），以及首次真实校准。
3. 冻结 policy 时，为韩/西选择 `ko-weekly-auto-v1` / `es-weekly-auto-v1` 插件，并把 `requiredChecks` 设为 `auto_qc_text_common.REQUIRED`。
4. 只显字幕的句子、改显英文的句子和只发文字的语言（`audio_unavailable`）。
5. 口播修订 prompt 读取 `maxSpeechUnits`。
6. 英文转写审核、页面信息、大纲与默想的机器检查，以及每周发布授权改为长期授权。
