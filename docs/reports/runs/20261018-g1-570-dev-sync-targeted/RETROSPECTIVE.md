# 复盘：20261018-g1-570-dev-sync-targeted

证据：同目录 `INDEX.md`、`manifest.json`、`outcome.json` 和 `summary.json`。

## 结论先行

交付类型：测试。#570 A3 分支同步 #569 后的定向测试通过：74 passed、97 subtests passed。仅为隔离工作树代码验证，没有生产输入或音频交付验收。

## 总时间

pytest 墙钟 37.92 秒；未调用外部模型或服务。与此前不同范围的 A3 测试不作速度比较。

## 各层模型、耗时与速度

| 层／阶段 | 状态 | 模型、调用、耗时、速度、费用 | 证据 |
|---|---|---|---|
| L1 来源 ASR、MFA、机器评审 | not_run | 无 | outcome.json |
| L2 初译、独立审核、文本质检 | not_run | 无 | outcome.json |
| L3 配音、回转写、音频质检 | not_run | 无；仅本地合成测试 | outcome.json |
| L4 构建与发布 | not_run | 无 | outcome.json |
| 本地 Python 定向测试 | passed | 无模型；37.92 秒；不适用 token／音频速度及费用 | outcome.json、summary.json |

## 错误

无测试错误。一次身份探针误用新模块名，改用 `audio.screening` 后别名检查通过；该探针未发起模型或生产请求。

## 可以改进的地方

预检：按 `path_aliases.py` 查找移动后模块名，避免猜测。依据：身份探针的 import 错误；负责人：G1 集成；跟踪：PR #570。

## 实际覆盖范围

验证筛查旧名别名、工作树可编辑包来源、23/23 W 冻结键、W/T 哈希、加载代码身份及五个受影响测试文件。L1–L4 真实运行均 not_run。

## 遗留状态

旧冻结运行的未知结果及预留未触碰；无新 job hold、Dev 构建号或待发布产物。本地测试文件位于 Git 忽略的 `artifacts/`。

## 外部可见的变化

无 Dev 发布、TestFlight、设备播放或场地验收；均为 not_run。
