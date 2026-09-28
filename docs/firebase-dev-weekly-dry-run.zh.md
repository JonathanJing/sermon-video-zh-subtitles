# 每周正式制作前的 Firebase Dev 演练

目标是在新一周 Layer 1 开始前，先用**上一期已审核、已发布的固定样本**检验 Layer 4 的组装、App 内加载和 Dev 发布链路。演练不产生新一周的英文源稿、翻译、配音或人工批准收据，也不改变 Production。

## 环境边界

- Dev Hosting 固定为 `ai-for-god-sermon-audio-dev`；页面可见 `DEV 测试站`，`engagement.json.enabled=false`，无 Production `/api/**` 转发，并设置 `noindex`。
- 演练样本使用已经批准的 2026-09-27 完整 31:31 页面。其 `multilingual-v3.json`、三语 Release v2、全文与口播字幕、英文对照、现场定位索引、视频和音频必须逐项绑定到原有哈希。演练不把复制动作记录为新的 Layer 1–3 审核。
- 保留 Dev 现有 `multilingual-v2.json`、旧样片、`/dev-poc.html` 和所有仍被目录引用的文件。候选从**完整线上 Dev 快照**组装，不从 `firebase/dev/public` 这个不完整源码目录直接部署。

## 首次对齐与预演

`scripts/align_firebase_dev_v3.py` 是 9/27 的一次性迁移入口。它拒绝错误的 Firebase 站点、未审核的三语 Release、意料之外的同名文件覆盖，以及已经是 v3 的 Dev 基线。构建报告、预检和 HTTP 收据保存在 Git 忽略的 `artifacts/` 中。

```bash
PY=/absolute/path/to/repo/.venv/bin/python
TOOL=/absolute/path/to/weekly-worktree/scripts/align_firebase_dev_v3.py
BASE=/absolute/path/to/complete-current-dev-candidate
PROD=/absolute/path/to/complete-reviewed-production-snapshot
OUT=/absolute/path/to/ignored/dev-dry-run

"$PY" "$TOOL" build --dev-base-candidate "$BASE" \
  --production-public "$PROD/public" --production-config "$PROD/firebase.json" \
  --out "$OUT/candidate"
"$PY" "$TOOL" preflight --candidate "$OUT/candidate" \
  --dev-base-candidate "$BASE" --out "$OUT/preflight.json"
"$PY" "$TOOL" deploy --candidate "$OUT/candidate" \
  --preflight "$OUT/preflight.json" --out "$OUT/deployment.json"
"$PY" "$TOOL" verify --candidate "$OUT/candidate" --out "$OUT/http.json"
```

发布前预检逐文件 GET 当前线上 Dev，并比较大小和 SHA-256；部署仅接受 30 分钟内、绑定到同一候选的预检。发布后逐文件复核 200、大小和 SHA-256，再查三语音轨 `Range: bytes=0-0`、三语实际文稿 HTML（不能把 `/pages/**` 重写后的首页 200 当作页面）以及 App 首页的 v3 默认页。浏览器分别切换中文、韩语、西语，确认页面标题、31:31 音轨、英文对照和声音定位入口；旧周及实验页仍可打开。HTTP、浏览器、iOS 设备和现场接收分别记录。

## 之后每周的顺序

1. **正式制作前**：在 Dev 重放最近一次已批准页面及一份只用于结构检查的合成下一周 fixture。验证目录 schema、哈希拒绝、旧周保留、三语切换、页面深链、音频 Range、英文对照和定位数据。fixture 标 `preview_only`，不得进入正式目录或声称人工审核。
2. **真实 Layer 1–3 完成后**：用该周真实审核收据组装 Layer 4 候选；按 Dev 当前完整快照追加新周，禁止覆盖已有 `pageId` 或删除旧资产。记录每个输入哈希、构建开始/完成时间和文件差异。
3. **Dev 发布**：重新预检线上完整基线，部署 Dev，逐文件 HTTP 核验，再在浏览器打开 App 内本周页面并做三语短时播放。失败时恢复上一版 Dev Hosting release；不把 Dev 通过等同于 Production、iOS 设备或现场通过。
4. **Production 决策**：使用真实 Layer 4 包和独立 Production 目标完成相同检查。Dev 的演练收据只证明发布链路，不代替该周内容审核。

通用 v3 `next-week build-update` 仍需接入 Dev 发布器；当前旧 `multilingual_dev_preview.py build-update` 只接受 v2 目录，不能用于下一周正式 v3 页面。对应开发项见 `docs/backlog.zh.md` 的 `DEV-L4-005`。
