# 复盘：20261018-g1-579-proxy-review-ci-cancelled

证据：同目录 `INDEX.md`、`manifest.json`、`outcome.json` 和 `summary.json`；GitHub Actions run 39084686553。

## 结论先行

交付类型：CI 测试。#579 head `6013fb16000e701a9102821084faee8aeb989f08` 的 Python workflow 因 #570 三项新的代码审查发现主动取消，终态 `cancelled`。`changes` 与 root-2、root-4、root-7 成功，其余五个 root 组取消；`unittest` 聚合在取消期间报 failure。不能把这次运行当作全量通过；修复级联后的新 head 需要另行验证。

## 总时间

GitHub 起止时间见 outcome.json；取消前运行时间不能与完整测试比较。

## 各层模型、耗时与速度

| 层／阶段 | 状态 | 模型、调用、耗时、速度、费用 | 证据 |
|---|---|---|---|
| L1 来源 ASR、MFA、机器评审 | not_run | 无 | summary.json |
| L2 初译、独立审核、文本质检 | not_run | 无 | summary.json |
| L3 配音、回转写、音频质检 | not_run | 无 | summary.json |
| L4 构建与发布 | not_run | 无 | summary.json |
| Python CI | cancelled | 无模型；三组 root 成功，其余不完整 | outcome.json、summary.json |

## 错误

#570 新审查指出 diagnostic replay 对 renderer 门面哈希、E05 来源定位仍指旧门面、`audio/hosted.py` 等执行绑定未进入 W／计分／语速身份闭包。旧 head 的 CI 已失去合并判断意义，主动取消；聚合 failure 来自取消时的不完整分组。

## 可以改进的地方

预检：搬迁审查时对仓库内所有旧路径引用做身份与来源定位扫描；依据：本次三项发现；负责人：G1 集成；跟踪：PR #570/#579。

## 实际覆盖范围

仅 `changes` 与 root-2、root-4、root-7 完成成功；五组 root 无完整结果，Native/shared 按路径跳过。L1–L4 真实运行均 not_run。

## 遗留状态

修复在 #570 并级联 #579 后重算 W、T、计分、语速及逐键哈希；旧冻结运行的未知结果与预留未触碰。

## 外部可见的变化

只有 GitHub Actions 取消收据；无 Dev 发布、TestFlight、设备播放或场地验收。
