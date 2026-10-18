# 复盘：20261018-g1-579-transport-physical-fixture

证据：同目录 `INDEX.md`、`manifest.json`、`outcome.json`、`summary.json`；PR #579。

## 结论先行

交付类型：本地定向代码测试。root-7 的旧 transport 身份测试仍用运行时 alias 字典 patch 期待 T 变化，与物理字节闭包不符。测试现复制完整 T 物理文件清单至临时根、变异并恢复 transcription request 目标文件；`unittest` 4 个测试通过。生产代码未改。

## 总时间

定向 unittest 0.054 秒；未跑完整 CI。

## 各层模型、耗时与速度

| 层／阶段 | 状态 | 模型、调用、耗时、速度、费用 | 证据 |
|---|---|---|---|
| L1 来源 ASR、MFA、机器评审 | not_run | 无 | `summary.json` |
| L2 初译、独立审核、文本质检 | not_run | 无 | `summary.json` |
| L3 配音、回转写、音频质检 | not_run | 无 | `summary.json` |
| L4 构建与发布 | not_run | 无 | `summary.json` |
| compute-leaf 定向测试 | pass | 无模型；4 测试 | `outcome.json`、`summary.json` |

## 错误

旧测试 patch `path_aliases.PATH_ALIASES` 并期待 T 改变；新 T 对固定物理文件清单读取字节。patch 字典不会改变实际文件。修订后临时根复制完整 T 清单，只变异目标文件，随后恢复。

## 可以改进的地方

物理闭包引入时一并搜索历史 alias-patch 身份测试；依据：root-7 单项失败；负责人：G1 集成；跟踪：PR #579。

## 实际覆盖范围

只验证 compute-leaf 文件及 T 身份测试语义；真实 checkout 的生产文件未修改。完整 Python、iOS CI 将在新 head 重跑。

## 遗留状态

等待新 exact-head CI 与审查。旧冻结运行未知结果和请求预留未触碰。

## 外部可见的变化

仅代码测试收据；无 Dev 发布、TestFlight、设备或场地验收。
