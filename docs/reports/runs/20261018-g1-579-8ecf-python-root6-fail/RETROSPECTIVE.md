# 复盘：20261018-g1-579-8ecf-python-root6-fail

证据：同目录 `INDEX.md`、`manifest.json`、`outcome.json`、`summary.json`；[GitHub Actions run 39087751408](https://github.com/JonathanJing/sermon-video-zh-subtitles/actions/runs/39087751408)。

## 结论先行

交付类型：Python CI。#579 `8ecf7493` 的 root-6 完成 739 项、4 skipped、1 failure：`test_review_leaves.test_waiver_identity_reads_the_moved_ledger` 仍用运行时 alias 字典 patch 期待 W 变化，与新的物理字节闭包不符。其余未完成 root 分组主动取消，运行终态 `cancelled`；不能作为全量通过证据。修订测试后的新 head 是 `b6507b5d`。

## 总时间

GitHub 起止时间见 `outcome.json`；取消运行不与完整通过耗时比较。

## 各层模型、耗时与速度

| 层／阶段 | 状态 | 模型、调用、耗时、速度、费用 | 证据 |
|---|---|---|---|
| L1 来源 ASR、MFA、机器评审 | not_run | 无 | `summary.json` |
| L2 初译、独立审核、文本质检 | not_run | 无 | `summary.json` |
| L3 配音、回转写、音频质检 | not_run | 无 | `summary.json` |
| L4 构建与发布 | not_run | 无 | `summary.json` |
| Python CI | cancelled after failure | 无模型；root-6 一项测试失败，其余部分结果见明细 | `outcome.json`、`summary.json` |

## 错误

`tests/test_review_leaves.py:45` 断言 W 会因 `patch.dict(PATH_ALIASES)` 变化，实际 W 现在读固定的 facade、目标与解析器物理文件字节。新测试通过临时仓库根复制完整 49 文件、变异 ledger 目标、恢复原字节来检验当前契约；没有改真实 checkout 的生产文件。

## 可以改进的地方

身份读取方式变化时，同步审查历史身份测试的变异方法；依据：root-6 本次单项失败；负责人：G1 集成；跟踪：PR #579。

## 实际覆盖范围

`changes` 与 root-0、root-1、root-3 成功，root-6 失败，其余取消，Native/shared 跳过；无完整全量结果。L1–L4 真实生产未运行。

## 遗留状态

等待新 head `b6507b5d` 的完整 CI 与审查。旧冻结运行未知结果及请求预留未触碰。

## 外部可见的变化

只有 CI 失败与取消收据；无 Dev 发布、TestFlight、设备播放或场地验收。
