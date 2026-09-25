# Resi 直播已播内容下载

适用场景：直播尚未结束，但需要保存播放器当前保留的已播内容。以下方法于 2026-09-19 在 [Mariners Weekend Live](https://www.marinerschurch.org/weekendlive/) 实际成功；接口与播放器结构属于当时观察，后续可能变化。

这是一条媒体获取路径，不自动启动转写、翻译或发布。公开播放清单完整下载，不等于整场直播完整，也不等于完整证道已经人工确认。进入预制生产仍需按[四层合同](multilingual-production-interfaces.zh.md)绑定媒体哈希、时间轴和证道范围。

## 1. 准备与定位当前场次

需要 `python3`、`curl`、`ffmpeg`、`ffprobe`。在仓库根目录运行；为每次抓取创建新目录，保留失败产物，避免覆盖已验证媒体：

```bash
mkdir -p artifacts
RESI_DIR="$(mktemp -d "$PWD/artifacts/resi-capture-XXXXXX")"
export RESI_DIR
curl -fLsS --max-time 30 'https://www.marinerschurch.org/weekendlive/' \
  -o "$RESI_DIR/page.html"
rg 'data-embed-id|webplayer/loader' "$RESI_DIR/page.html"
```

首次使用前确认 `artifacts/` 存在且被 Git 忽略；若不存在，先运行 `mkdir -p artifacts`。页面当时包含 `data-embed-id="fc7c04d4-80b9-4c8a-ac1c-fc7f808a6f55"`，以及 `https://control.resi.io/webplayer/loader.min.js`。不要把这个播放器 ID 当作每周场次 ID。

当时播放器通过以下公开接口解析最新场次：

```text
https://webevents.resi.io/api/v1/eventprofiles/latest/<data-embed-id>
```

返回的 `uuid` 才是场次 ID；`cloud.hlsUrl` 为 HLS 主清单，`cloud.dashUrl` 为 DASH 清单。每次先核对场次名称与实际画面，不复用旧周 URL。如果接口变化，从页面实际加载的 loader/bundle 或浏览器 Network 查看真实请求，不猜测私有接口。仅使用公开或已授权媒体；遇到认证或 DRM，不绕过限制。

以下命令从刚下载的页面解析 ID，并仅保存必要字段，避免落盘统计地址和客户端标识：

```bash
python3 - <<'PY'
import json, os, pathlib, re, urllib.request
p = pathlib.Path(os.environ['RESI_DIR'])
match = re.search(r'data-embed-id=["\x27]([^"\x27]+)', (p/'page.html').read_text())
if not match:
    raise SystemExit('未找到 embed ID；检查实际播放器')
url = 'https://webevents.resi.io/api/v1/eventprofiles/latest/' + match[1]
with urllib.request.urlopen(url, timeout=30) as r:
    d = json.load(r)
keep = {k: d.get(k) for k in ('uuid', 'name', 'cloud', 'segmentOffset', 'simLive')}
(p/'source.json').write_text(json.dumps(keep, indent=2) + '\n')
with urllib.request.urlopen(d['cloud']['hlsUrl'], timeout=30) as r:
    master = r.read().decode()
(p/'master.m3u8').write_text(master)
print('场次:', keep['uuid'], keep['name'])
print('主清单已保存到本地 master.m3u8；查看后选择音视频 URI，不把完整 URL 粘贴到共享日志。')
PY
```

## 2. 选择画质并冻结清单

从主清单的 `RESOLUTION` 选择视频子清单，再按它的 `AUDIO` 分组找到 `EXT-X-MEDIA` 中的音频 URI。当次 1080p 为 `Manifest_0_0.m3u8`，英语双声道为 `Manifest_1_1.m3u8`；文件名不是通用约定，必须以本次主清单为准。

直播清单会增长。直接把动态清单交给 FFmpeg 可能持续录到直播结束；本方法保存一次子清单，把相对 URI 转成绝对 URI，并在**本地副本**追加 `EXT-X-ENDLIST`，固定下载范围。不会修改服务器，也不能恢复清单中已移除的历史片段。

根据本次清单填写下面两个值，再执行：

```bash
export RESI_VIDEO_PLAYLIST='Manifest_0_0.m3u8'
export RESI_AUDIO_PLAYLIST='Manifest_1_1.m3u8'
python3 - <<'PY'
import datetime, json, os, pathlib, re, urllib.parse, urllib.request
p = pathlib.Path(os.environ['RESI_DIR'])
base = json.loads((p/'source.json').read_text())['cloud']['hlsUrl']
receipt = {'captured_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'tracks': {}}
for track, env in [('video', 'RESI_VIDEO_PLAYLIST'), ('audio', 'RESI_AUDIO_PLAYLIST')]:
    url = urllib.parse.urljoin(base, os.environ[env])
    with urllib.request.urlopen(url, timeout=30) as r:
        s = r.read().decode()
    if not s.startswith('#EXTM3U') or '#EXTINF:' not in s:
        raise SystemExit('子清单无有效媒体片段')
    if '#EXT-X-KEY:' in s:
        raise SystemExit('存在加密声明；停止本公开无加密下载路径')
    (p/f'{track}-original.m3u8').write_text(s)
    lines = []
    for line in s.splitlines():
        if line and not line.startswith('#'):
            line = urllib.parse.urljoin(url, line)
        else:
            line = re.sub(r'URI="([^"]+)"', lambda m: 'URI="' + urllib.parse.urljoin(url, m[1]) + '"', line)
        lines.append(line)
    if '#EXT-X-ENDLIST' not in s:
        lines.append('#EXT-X-ENDLIST')
    (p/f'{track}-snapshot.m3u8').write_text('\n'.join(lines) + '\n')
    durations = [float(l.split(':', 1)[1].split(',')[0]) for l in s.splitlines() if l.startswith('#EXTINF:')]
    receipt['tracks'][track] = {'segments': len(durations), 'duration_seconds': sum(durations)}
(p/'snapshot.json').write_text(json.dumps(receipt, indent=2) + '\n')
print(json.dumps(receipt, indent=2))
PY
```

两个请求并非原子操作，可能跨过清单更新点。合并前比较原始子清单的 `EXT-X-MEDIA-SEQUENCE`、首尾片段编号与时间信息，确认音视频覆盖同一时间范围；片段数或总时长接近本身不证明起点一致。有差异时保留这次快照，重新获取一组匹配清单或明确处理共同范围，不静默裁切或宣称完整。`segmentOffset` 和底层流时间戳不能直接当作下载文件中的证道起点。

## 3. 下载并合并

```bash
ffmpeg -nostdin -n -hide_banner -loglevel warning \
  -protocol_whitelist file,http,https,tcp,tls,crypto \
  -i "$RESI_DIR/video-snapshot.m3u8" \
  -protocol_whitelist file,http,https,tcp,tls,crypto \
  -i "$RESI_DIR/audio-snapshot.m3u8" \
  -map 0:v:0 -map 1:a:0 -c copy -movflags +faststart \
  "$RESI_DIR/service.mp4" > "$RESI_DIR/download.log" 2>&1
RESI_DOWNLOAD_EXIT=$?
printf '%s\n' "$RESI_DOWNLOAD_EXIT" > "$RESI_DIR/download-exit.txt"
```

`-c copy` 直接合并原始编码，不重新压缩；`-n` 拒绝覆盖。立即保存退出状态并检查日志，非零不得标记完成：FFmpeg 有时遇到片段缺失仍能产出文件，因此“文件存在”或“退出 0”不能单独证明完整。HTTP 204、403、404、空片段或跳片需要调查；不要靠猜片段编号补齐。如果中断，保留快照、日志及不完整文件，以新输出文件名重试；此 FFmpeg 命令不提供可靠的断点续传。清单仍在也不保证旧媒体片段仍可取得。

## 4. 验证与来源记录

```bash
ffprobe -v error \
  -show_entries format=duration,size:stream=index,codec_name,width,height,sample_rate,channels,duration \
  -of json "$RESI_DIR/service.mp4" > "$RESI_DIR/probe.json"
cat "$RESI_DIR/probe.json"
ffmpeg -nostdin -v error -ss 30 -i "$RESI_DIR/service.mp4" -t 8 -f null -
ffmpeg -nostdin -v error -sseof -10 -i "$RESI_DIR/service.mp4" -f null -
shasum -a 256 "$RESI_DIR/service.mp4" > "$RESI_DIR/service.sha256"
```

比较输出音视频时长与各自冻结清单之和，并检查下载日志。首尾抽样解码仅验证抽样位置；重要制作需要时可执行全文件解码 `ffmpeg -nostdin -v error -i "$RESI_DIR/service.mp4" -f null -`。人工播放确认所需证道开头与结尾，批准范围必须绑定该文件哈希与本地时间轴。

保留观看页 URL、场次 ID/名称、抓取 UTC 时间、原始/冻结清单、片段数与时长、文件大小、SHA-256、下载退出状态及验证结果。不要注入 cookie 或私有凭据。清单及 FFmpeg 原始错误日志可能包含媒体 URL 或签名参数，只留在本地受控目录，分享前必须脱敏，不得进入 Git 或共享日志；本目录不能直接作为可公开发布包。结束时分别报告“清单范围下载完成”和“证道范围是否已审核”。

## 已验证案例：2026-09-19

以下来自当次本地下载产物，不表示链接如今仍可下载：

| 项目 | 观察结果 |
|---|---|
| 场次 | Saturday 4:00pm Live Service |
| 场次 ID | `7c193fd4-bc90-4f3b-aa00-37dfe8423aa0` |
| 冻结范围 | 视频、音频各 1538 个片段，约 4567.296 秒（76 分 07 秒） |
| 输出 | H.264 1920×1080；AAC 48 kHz 双声道；2,488,322,798 字节 |
| SHA-256 | `728f864e92ea08dbce249249369016e0fee47950ec4e6dcb60cd6d83185e8caf` |
| 验证 | 下载退出 0，音视频时长匹配清单，首尾抽样解码通过 |
| 当次交付边界 | 未人工确认证道起止；未执行全篇解码或全篇听审 |

原始本地产物位于当时主工作区的 `artifacts/resi-live-20260919/`，包括 `download-manifest.json`、`probe.json`、清单和 MP4；这些忽略文件不会随分支或新 worktree 复制。上述命令是对当次步骤的通用化整理，本次文档更新不重新下载历史媒体。
