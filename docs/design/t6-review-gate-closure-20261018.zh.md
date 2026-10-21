# T6 review gate 迁移：冻结实验闭包核查（2026-10-18）

状态：只读核查；[代码候选 PR #1036](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/1036) 为草稿，**尚未合并**。本记录只保留身份与运行状态，不复制忽略目录中的计划、媒体或响应内容。

## 绑定到旧实现的证据

| 本地冻结证据 | 核对结果 |
|---|---|
| `artifacts/dev-full-rerun-20261001/run-plan.json` 与 `execution-inputs.json` | `executionIdentity.loadedProjectCodeSha256` 共 94 项，包含 `scripts/sermon_review_gate.py` = `6ccc5d279217e697186731fe45cdb55b011d73594de4fb45068acc30528a7709`。该轮 `final-result.json.status=incomplete`。 |
| `artifacts/next-concurrency-605s-20261005-r8-final/code-stage-manifest.json` 与 `stage-descriptor.json` | 代码文件 539 项、全文件 580 项；均包含相同 gate 哈希。`snapshotSha256=7056eb324fa04326b5a2a7035e9a9b4028d095d171754051b1058a3e6a4f43a0`。 |
| 同轮 `validated-command-preparation.json`、`comparison-ready/latest-run.json` | 前者为 `ready_for_new_exclusive_session`，后者为 `blocked`；准备完成不等于实验完成。 |

旧 gate 哈希与本次审计时 `origin/dev` 的 `scripts/sermon_review_gate.py` 原文件相同。旧计划属于旧实现：不得用新门面或包文件的哈希补写旧收据。静态路径也不能据文件名排除 Prefect：[`sermon_business_prefect_flow.py`](../../packages/production/src/tongxing_production/workflows/diagnostic/business_prefect_flow.py) 导入 [`sermon_strict_gate_admission.py`](../../packages/production/src/tongxing_production/text/strict/gate_admission.py)，后者导入旧 gate。

## 新候选的身份边界

#1036 把 gate 实现移至 `tongxing_production.text`，保留同模块的 `scripts/` 导入门面。当前 [`text/controller.py`](../../packages/production/src/tongxing_production/text/controller.py) 的 `code_identity()` 哈希全部 `scripts/**/*.py` 和 `packages/production/src/**/*.py`：移动必生成新的 Layer 2 代码身份。审计时另一个正式三语 Layer 2 任务仍在运行，因此本 PR 不得热替换其冻结 checkout 或沿用旧身份续跑。

候选没有新增 `path_aliases.py` 映射：当前没有对 `scripts/sermon_review_gate.py` 逻辑键的 resolver 消费者；增加无关映射仍会改变 G1 质检物理闭包所包含的 resolver 字节。删去映射后的本地 W 为 `df299eca0e9f11689e7a88654b7b2616df1e10bd8cd60a9847e3561d5db41b10`，与 [G1 实施代记录](../reports/20261017-g1-implementation-generation.zh.md)相同，见[定向报告 #1045](https://github.com/JonathanJing/sermon-video-zh-subtitles/pull/1045)。未来如确需给 gate 的版本化逻辑键新增别名，应单独评审新旧实施代及机器质检收据影响。

## 历史实验恢复决定

用户于 2026-10-17（PDT，UTC 为 10-18）在本次迁移讨论中选择：**保留旧快照；今后重启另建新计划**。因此上述旧 revision、run-plan 和 stage snapshot 保持只读，绑定旧 gate 哈希；#1036 合并后不在新 checkout 上续用它们。未来若重启实验，须另建计划、冻结新的实施身份并独立取得届时所需的资源与预算授权。此决定不改变当前正式三语 Layer 2 的运行边界，也不把旧实验标为完成。

## 合并前的证据

1. 正式三语 Layer 2 运行达到终态并正常关闭；核对预算结算、未知结果、候选/返修 intent，以及运行时 checkout 未被热替换。技术终态不代表人工内容批准。
2. 保留上述历史实验的旧 revision、plan 与 stage snapshot，以旧 gate 哈希只读复验；若要重新派发实验，须建立新的计划与实现身份，不能把旧 `ready` 或 `blocked` 收据当作新实现通过。
3. 对 #1036 的精确提交取得 CI 与代码/安全审查收据，再与最新 `dev` 比较改动。旧 `scripts/` 导入、schema 宿主绑定和准入行为的本地验证分别记录在 #1035、#1037、#1045。

本记录不授权付费重试、Spark 独占会话、真实音频生成或实验重新派发。
