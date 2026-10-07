# 机器质检豁免与 TTS 前时长预算

## 决定

2026-10-06，Jony 在项目线程里确定了以下规则：

- 中文、韩语、西语都改为**机器质检通过后自动发布**。人工改为发布后抽查，发现问题再发修订版。证道起止时间仍由人输入。
- “每句最多落后 8 秒”是同传听感的目标，保留。时长控制前移到 TTS 之前，不再依靠事后批例外（例如 10/4 的 62 秒）。
- 翻译和复核可以用同一个模型，前提是有可测量的质量证据。
- 修复按**单句**计数：先修 2 次，不行再修 2 次，每句最多 4 次。
  - 音频仍不过关：这一句只显示字幕，不配音。
  - 文字仍不过关：这一句改为显示英文原文。
  - 不配音的句子超过全篇 5%：整个语言改为只发文字（`audio_unavailable`）。
  - 失去译文的句子超过全篇 5%：该语言暂停发布。

机器质检豁免**不是**人工批准。豁免收据里 `humanApproval` 保持 `false`，`reviewKind` 写为 `machine_quality_waiver`，页面必须显示 `disclosure` 文案。

## 组件

| 环节 | 入口 | 作用 |
|---|---|---|
| L2 逐组确定性检查 | `language_review_plugins/ko_weekly_auto.py`、`es_weekly_auto.py`（共享 `auto_qc_text_common.py`） | 每周通用，不写死任何一篇讲道。检查目标文字脚本与占位符、未翻译的英文、语域、术语表人名、经文出处（英文说了就必须有，没说不能加）、数字（数字或目标语言读法） |
| L2 整篇检查 | `scripts/target_text_auto_qc.py` | 长度离群：与本篇中位数比较。**回译比对**：第一次调用只给目标语言文字，翻回英文；第二次调用对比冻结英文和回译，判断有没有漏译、增译、否定、数字、人名、经文、意思偏移。模型调用由调用方注入，没有回译结果的组不能判为通过 |
| L3 单句检查 | `scripts/target_audio_auto_qc.py` | TTS 之后马上检查：时长异常（与本篇语速中位数比较，以及与原声时长之比）、截断、近乎无声、静音过多、长停顿、削波。回转写两级：小 ASR 标出的疑点由强 ASR 复核，两边都不一致才判失败 |
| 8 秒预算 | `scripts/target_audio_predicted_schedule.py` | 用已测音频拟合各语言语速，再用正式排程公式按**预测时长**排一次。超窗的组给出 `maxSpeechUnits`，供口播修订一次改到位 |
| 注错校准 | `scripts/auto_qc_seeded_errors.py` | 在干净成品里注入已知错误，统计每类检出率和干净样例的误报率 |
| 豁免收据 | `scripts/machine_quality_waiver.py` | 汇总最终 QC 结果，按上面的 5% 规则决定这个语言是自动发布、只发文字还是暂停 |

## 校准门槛

只有满足以下全部条件，才允许豁免：

- 校准收据的 `implementationSha256` 与当前 QC 代码一致。代码一改，必须重新校准。
- 校准时回译检查实际参与了（`semanticChecksIncluded=true`）。
- 总检出率 ≥ 95%，每类 ≥ 90%。
- 干净样例误报率 ≤ 10%。

只做离线确定性检查时，“删掉半句”这类错误只能检出约 58% 到 75%（见测试样例）。这正是必须加入回译检查的原因。

## 命令

```bash
# 用已有正式音频拟合语速（rows: [{text, audioSeconds}]）
python scripts/target_audio_predicted_schedule.py fit --input rate-input.json --out rate.json
# TTS 前预测排程（groups: [{gid, sourceStart, sourceEnd, text}]，时间相对 clip）
python scripts/target_audio_predicted_schedule.py budget --input groups.json --rate rate.json --out budget.json
# 单句音频 QC（units: [{groupId, text, sourceSeconds, wavPath, asrPrimary?, asrSecondary?, priorFailedAttempts?}]）
python scripts/target_audio_auto_qc.py --input units.json --out audio-qc.json
# 离线注错校准（不含回译，因此不能单独解锁豁免）
python scripts/auto_qc_seeded_errors.py --input calibration-input.json --out calibration.json
# 豁免决定
python scripts/machine_quality_waiver.py --locale ko --candidate candidate.json \
  --text-qc text-qc.json --audio-qc audio-qc.json --calibration calibration.json --out waiver.json
```

## 当前接线范围

本次提交包含检查、校准、预测排程和豁免收据，以及离线测试，不调用模型、不改音频或文字。以下还没有接上，需要后续变更：

1. 回译检查的真实模型 transport（沿用 L2 的 API/CLI 后端身份与缓存规则），以及首次真实校准。
2. 现有准入仍要求人工批准：L2 → L3 的 `human_translation_approved`、L3 Audio Package 的 `human_reviewed`、Release Package 的门禁。需要在这些 schema 和 `sermon_unified` 审核门中，把 `machine_quality_waiver` 收据作为一种正式但非人工的放行依据，并在页面上显示披露文案。
3. 冻结 policy 时，为韩/西选择 `ko-weekly-auto-v1` / `es-weekly-auto-v1` 插件，并把 `requiredChecks` 设为 `auto_qc_text_common.REQUIRED`。
4. 口播修订 prompt 读取 `maxSpeechUnits`；失败句只显字幕的播放器展示。
