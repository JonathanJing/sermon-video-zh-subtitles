# dsh-production-progress

DSH 的逐句优先生产进度 dock。它把 `run_status.py` 写的快照显示在输入框上方的
`conversation.input.dock`：一行当前阶段、进度、心跳和 attention；点击展开阶段表。

它是**只读观察器**：不写 run、不改变门禁、不调用 Python、不碰 keychain。

## 数据源

```text
<statusRoot>/.status-index.json
<statusRoot>/<run>/status/status.json
```

`statusRoot` 解析顺序：

1. 插件配置 `statusRoot`；
2. 环境变量 `SFA_STATUS_ROOT`；
3. 个人 checkout 默认路径：
   `~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/artifacts/sentence-first-agent`；
4. `<cwd>/artifacts/sentence-first-agent`。

`run_status.py` 的 `register`/`mark` 现在写完事件后会刷新 `status.json`，所以 dock
是低延迟的；没有新事件时它会显示快照 age，超过 120 秒标为可能过期。

## 安装（desktop profile，本地包）

桌面 profile 由 App 管理，CLI 不一定接受 `--profile desktop`。把源码复制到稳定的
用户目录（不要直接 link 到临时 worktree），再让 profile link 它：

```bash
mkdir -p ~/.dsh/plugins
cp -R tools/ops/dsh-production-progress ~/.dsh/plugins/dsh-production-progress
cd ~/.dsh/profiles/desktop
pnpm add --ignore-scripts link:$HOME/.dsh/plugins/dsh-production-progress
```

然后把包名加进 `~/.dsh/profiles/desktop/package.json` 的
`dsh.profile.bundles`（放在 `dsh-working-activity` 之后即可）：

```json
"dsh-production-progress"
```

重启 DSH 后生效。`cordis.patch.yml` 会挂载 host 半；`dsh.client` 会由
client module scanner 服务到 `/plugins/dsh-production-progress/client.js`。

> 这是本地开发包（`private: true`，`link:` 安装）。更新时重新复制到
> `~/.dsh/plugins/dsh-production-progress` 并重启；卸载用
> `pnpm remove dsh-production-progress` 并从 `bundles` 删除。安装前备份
> `package.json` 与 `pnpm-lock.yaml`。

## 配置

默认路径可用时不需要配置。仓库移动或换机器时，在
`~/.dsh/profiles/desktop/cordis.patch.yml` 的用户层按 id 覆盖（不要插第二行）：

```yaml
- id: production-progress
  name: dsh-production-progress
  config:
    statusRoot: /path/to/artifacts/sentence-first-agent
```

## 界面

- 一行：状态点、语言、当前阶段、`done/total`、心跳/等待、`预计 HH:MM`、`⚠ n`。
- 待审听（`human_review` waiting）且存在 `sessionId` 时，行尾出现“打开对话 ↗”：
  - `run_status.py handoff` 默认把 `DSH_SESSION_ID` 写进 waiting；也支持 `--session-id` 覆盖。
  - 点击调用客户端的 `sessions.open(id)`（旧版回退 `uiWorkspace.openSession(id)`），切到发起审听的会话。
  - 没有 `DSH_SESSION_ID` 或不在 DSH 内运行时不会显示按钮。
- 点击行展开：run 标题、阶段表（最多 12 条）、第一条 attention、缺步骤、快照 age。
- 没有 run 时 dock 不渲染；完成超过 6 小时的 run 也会隐藏。
- 颜色：蓝=进行中，琥珀=等待/需处理，红=失败/停滞，绿=完成。

## 测试

```bash
cd tools/ops/dsh-production-progress
npm test
```

7 个 Node 测试覆盖 host 的 index/snapshot 合并、目录回退、路由注册、GET/405，
以及 client bundle 的 `__ModuleLoader__` 形状和 `conversation.input.dock` 注册。

## 限制

- 全局显示最近一个生产 run，不按 session/workspace 过滤；多生产并行时只显示
  优先级最高（attention > active > planned > completed）的一个。
- 4 秒轮询，不是 WebSocket；快照本身由生产脚本刷新。
- 只覆盖 DSH 0.2.x 的 `conversation.input.dock`；DSH 升级后需用真实槽位复核。
- `status.json` 不公开：dock 只在本地 GUI 读它，不要把该路由暴露到公网。
- “打开对话”依赖 host 半透传 `sessionId`；首次安装/更新 host 后需要重启 DSH，client 半可单独 HMR。
