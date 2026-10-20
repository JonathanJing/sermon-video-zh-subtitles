# 复盘：20261018-g1-579-b650-python-root7-fail

证据：同目录 `INDEX.md`、`manifest.json`、`outcome.json`、`summary.json`；[GitHub Actions run 39088555417](https://github.com/JonathanJing/sermon-video-zh-subtitles/actions/runs/39088555417)。

## 结论先行

交付类型：Python CI。#579 `b6507b5d` 的 root-7 完成 741 项、6 skipped、1 failure：`test_infrastructure_compute_leaves.test_transport_identity_reads_the_moved_request_builder` 仍用运行时 alias 字典 patch 期待 T 变化，与物理字节闭包不符。root-3 未完成后主动取消，运行终态 `cancelled`；不能作为全量通过证据。修订测试后的新 head 为 `da2f6ffc`。

## 总时间

GitHub 起止时间见 `outcome.json`；取消运行不与完整通过耗时比较。

## 各层模型、耗时与速度

| 层／阶段 | 状态 | 模型、调用、耗时、速度、费用 | 证据 |
|---|---|---|---|
| L1 来源 ASR、MFA、机器评审 | not_run | 无 | `summary.json` |
| L2 初译、独立审核、文本质检 | not_run | 无 | `summary.json` |
| L3 配音、回转写、音频质检 | not_run | 无 | `summary.json` |
| L4 构建与发布 | not_run | 无 | `summary.json` |
| Python CI | cancelled after failure | 无模型；root-7 一项测试失败，其余部分结果见明细 | `outcome.json`、`summary.json` |

## 错误

`tests/test_infrastructure_compute_leaves.py:43` patch `PATH_ALIASES` 后期待 T 变化；新 T 读取固定物理路径，未改文件字节。新测试通过临时根复制完整 T 清单、变异目标、恢复原字节来检验当前契约。

## 可以改进的地方

引入物理闭包时一起搜索旧 alias-patch 身份测试；依据：root-7 单项失败；负责人：G1 集成；跟踪：PR #579。

## 实际覆盖范围

`changes` 与 root-0、root-1、root-2、root-4、root-5、root-6 成功；root-7 失败，root-3 取消，Native/shared 跳过；无完整全量结果。L1–L4 生产未运行。

## 遗留状态

等待新 head `da2f6ffc` 完整 CI 与审查。旧冻结运行未知结果及请求预留未触碰。

## 外部可见的变化

只有 CI 失败及取消收据；无 Dev 发布、TestFlight、设备播放或场地验收。
