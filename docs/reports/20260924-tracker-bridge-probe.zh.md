# Tracker Firebase → Mac 通信探针（2026-09-24）

## 范围

在 Dev 项目 `ai-for-god-sermon-audio-dev` 的命名 Firestore 数据库 `sermon-tracker`，用私有集合 `trackerBridgeMockCommands` 测试一条 `mock_ping` 指令。本机通过 Admin SDK 监听和 15 秒查询对账，事务领取后原子写入忽略 Git 的 JSON 收件箱，再把收件状态和 JSON SHA-256 写回同一指令。它不执行审核、账本变更或 producer。

公开页面另有 `?bridgeMock=1` 交互示意：可查看模拟证据清单、模拟排队与本机领取。按钮不会向云端发指令。页面上的真实测试收据是一次历史结果，不能证明领取器持续在线。

## 实测结果

| 检查点 | 结果 |
|---|---|
| 云端创建 | 2026-09-24 21:20:30.138 UTC，私有指令 `mock_ping`，状态 `queued` |
| 本机领取 | 2026-09-24 21:20:31.361 UTC，本机 JSON 写入并回写 `received`，两端记录相差约 1.223 秒 |
| 本地收件 | `artifacts/tracker-bridge-mock/inbox/<commandId>.json`，权限 `0600`；动作、页面、步骤及 `mockOnly=true` 正确 |
| 完整性 | 本地 JSON SHA-256 与 Firestore 回执一致 |
| 未登录浏览器写入 | 对私有集合返回 `permission-denied`；未创建测试文档 |

这证明本次运行期间 Dev Firestore → 这台 Mac 的私有指令传输及回执成立。1.223 秒是单次观测，不能当服务等级承诺；Mac 休眠或领取器停止后不会立即收件，排队指令需恢复后对账。

## 复现

在 `experiments/sermon-dubbing-poc/tracker-admin` 安装依赖，并确保本机 ADC 有 Dev 项目相应数据库访问权。在两个终端依次运行：

```bash
node bridge-mock.mjs receive --page-id 2026-09-20-laodicea-clip \
  --inbox ../../../artifacts/tracker-bridge-mock/inbox --timeout-seconds 60
node bridge-mock.mjs send --page-id 2026-09-20-laodicea-clip \
  --step-id L3-05@zh-Hans
node bridge-mock.mjs inspect --id <send 输出的 commandId>
```

`receive` 是一次性探针，不是常驻服务。代码将项目、数据库、集合和动作限制在 Dev 测试环境；不要把 CLI 参数扩展为任意批准或执行指令。正式链路设计见[远程审核通信设计](../tracker-remote-review-bridge.zh.md)。

## 尚未接通

- 浏览器登录、审核者身份和私有证据展示／上传。
- 浏览器真正提交指令、后端验证审核裁决和生成可追溯收据。
- 常驻本机领取器、心跳、故障重试、正式工作账本状态转换及 Agent 安全续跑。

因此 Dev 页面上的演示不能被视为正式远程审核入口。
