# Review Pack Player

逐句审核页：打开一个审核包，听、看、标问题，最后复制一行口令回传。

它是[跨太平洋无人值守生产](../../docs/design/unattended-cross-pacific-production.zh.md) §6–§7 的审核面：**纯静态、没有 API**。页面不发任何请求，所以审核人不需要 VPN、不需要服务端、不需要会话；决定用一行文字回到飞书，再由生产机按 `message_id` 落盘。

## 为什么是静态包

审核人常在中国，生产机在美国。把审核页做成静态目录之后：

- 只有一次 HTTP GET 和 Range 请求，网络差也打得开；
- 音频和文字都在包里，不依赖生产机在线；
- 没有服务端，就没有要运维的进程、域名和证书。

代价写在设计稿里，不隐藏：**收据是 `selfReported`**，页面无法向服务端证明"真的听了哪几句"。这是刻意的降级，不是遗漏。

## 包的结构

```text
<out>/
  index.html  app.js  styles.css   本目录的文件（`review_pack.py build` 会复制）
  pack.json                        sentence-first-review-pack-v1
  audio/review.mp3                 整轨（`--checkpoint audio` 才有）
  audio/clip-<id>.mp3              只切疑点句，来自 run 的 tts/<id>.wav
```

`pack.json` 每句同时给两种时钟：`start`/`end` 是原片窗口内的时间（对原声 A/B 用），`dubStart`/`dubSeconds` 是配音轨里的位置（播放用）。`flags` 是这句被标出的原因：

| flag | 含义 | 默认进「重点听」 |
|---|---|---|
| `revised` | 译文被修订过（含同步精简） | 否 |
| `note` | `review.json` 里有备注 | 否 |
| `spoken` | 口播稿与字幕不同 | 否 |
| `speaker` | 讲员归属存疑 | **是** |
| `digits` | 口播稿里还有阿拉伯数字 | **是** |
| `lag` | 落后超过 0.8 s | **是** |
| `doubt` | `--doubt` 传入的源句疑问 | **是** |

「重点听」是默认视图：11-08 那期 460 句里 208 句带 flag，但只有 40 句是真疑点；不分开的话 45% 的句子都要点一遍。

## 构建

```bash
python3 tools/ops/review_pack.py build \
  --run artifacts/sentence-first-agent/20261108-jesus-is-just-zh \
  --locale zh-Hans --checkpoint audio \
  --out artifacts/review-pack/20261108-zh
```

- `--checkpoint text`：不带任何音频，整包约 230 KB，网络最差时也能用。
- `--clips N`：疑点句切片上限，默认 120；切片来自 `tts/<id>.wav`，需要本机 `ffmpeg`。
- `--code XXXX`：指定口令码；不指定时按 `productionId + locale` 从 `ABCDEFGHJKLMNPQRSTUVWXYZ23456789` 里取 4 位，同一期同一语言恒定。

`--out` 必须放在被忽略的路径（`artifacts/` 或 `/tmp`），包里含未发布音轨。

## 口令协议

页面右下角「复制口令」给出唯一一行，粘到飞书即可：

| 口令 | 含义 |
|---|---|
| `CBZY audio PASS played=52` | 检查点通过，实际听过 52 句 |
| `CBZY audio FIX s0013 s0088` | 只改这几句 |

每行都有「问题或改法」输入框；**填了字就自动把这句标成问题**，并按 `s0013: 具体改法` 追加在口令下面：

```text
CBZY audio FIX s0006 s0012
s0006: 「分堂」应为「会堂」
s0012: 读法：삼천 → 삼 천
```

第一行是命令，其余 `^s\d{4}: ` 行是逐句说明。`CBZY` 是本期口令码，`audio`/`text` 是检查点。生产侧只接受白名单用户与群，按 `message_id` 去重（设计稿 §6.5）。

## 部署到阿里云 OSS 香港

本机没有 `ossutil`（Homebrew 也没有这个 formula），所以发布用的是同一个工具的 OSS REST 调用，**只依赖标准库**。凭据放在 ossutil 兼容的配置文件里，将来装了 `ossutil` 也能共用：

```bash
cat > ~/.ossutilconfig <<'EOF'
[Credentials]
endpoint=oss-cn-hongkong.aliyuncs.com
accessKeyID=<你的 AccessKey ID>
accessKeySecret=<你的 AccessKey Secret>
EOF
chmod 600 ~/.ossutilconfig
```

也可以改用环境变量 `ALIYUN_OSS_ACCESS_KEY_ID` / `ALIYUN_OSS_ACCESS_KEY_SECRET`。

```bash
# 1. 每次一个新随机前缀（32 位十六进制），路径就是权限
TOKEN=$(python3 -c "import secrets;print(secrets.token_hex(16))")

# 2. 先看计划，不上传
python3 tools/ops/review_pack.py publish \
  --pack artifacts/review-pack/20261108-zh \
  --bucket tongxing-review-hk --prefix review/$TOKEN

# 3. 确认后上传（对象带 x-oss-object-acl: public-read）
python3 tools/ops/review_pack.py publish \
  --pack artifacts/review-pack/20261108-zh \
  --bucket tongxing-review-hk --prefix review/$TOKEN --execute

# 4. 看完就删
python3 tools/ops/review_pack.py remove \
  --pack artifacts/review-pack/20261108-zh \
  --bucket tongxing-review-hk --prefix review/$TOKEN --execute
```

要点：

- **路径就是权限**：`$TOKEN` 用 32 位随机十六进制，不要用 pageId 或日期。
- 每个对象单独设 `public-read`，bucket 本身可以保持私有；删掉前缀即收回访问。
- 音频靠 OSS 原生 Range 播放，不需要转码或分片。
- 对象直连的 URL 够用；要目录式地址就在 bucket 上开静态网站托管，首页文档设 `index.html`。
- AccessKey 只留在 `~/.ossutilconfig` 或环境变量里，不进仓库、不进日志、不进通知正文。

## 交互

| 操作 | 键盘 | 手机 |
|---|---|---|
| 播放/暂停 | 空格 | 底部圆形按钮 |
| 上一句/下一句 | K / J（或方向键） | 卡片右上「上一句 / 下一句」 |
| 通过 | Enter | 「通过」 |
| 标问题 | X | 「标问题」或直接在输入框写改法 |
| 下一疑点 | F | — |

播完一句自动接下一句（同一筛选内的顺序）；按空格暂停就停在那一句。听过的句子计入 `played=N`。

`localStorage` 按 `productionId` 保存判定与已听记录，换设备靠导出——这是纯静态包的取舍，见设计稿 §7.3。

## 已知限制

1. **收据是自述**：页面无法上报，生产侧只能记 `selfReported: true`。
2. **没有原声 A/B**：包里只有配音轨；原声片段要另切（当前 `pack.json` 已带 `start`/`end`，接口留着）。
3. **没有服务端续审**：两台设备之间不同步。
4. **纯文字包不播放音频**：`--checkpoint text` 时播放键禁用。
