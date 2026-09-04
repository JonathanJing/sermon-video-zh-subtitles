(function () {
  const shell = document.querySelector("#viewer-shell");
  const captionStage = document.querySelector(".caption-stage");
  const connection = document.querySelector(".connection");
  const connectionLabel = document.querySelector("#connection-label");
  const lastUpdate = document.querySelector("#last-update");
  const previous = document.querySelector("#previous");
  const divider = document.querySelector("#divider");
  const previousZh = document.querySelector("#previous-zh");
  const previousEn = document.querySelector("#previous-en");
  const activeZh = document.querySelector("#active-zh");
  const activeEn = document.querySelector("#active-en");
  const demoLabel = document.querySelector("#demo-label");
  let latestSequence = -1;
  let latestPublishedAt = 0;

  function setConnection(state, label, detail) {
    connection.dataset.state = state;
    connectionLabel.textContent = label;
    lastUpdate.textContent = detail;
  }

  function render(snapshot) {
    if (!snapshot || Number(snapshot.sequence) < latestSequence) return;
    latestSequence = Number(snapshot.sequence) || 0;
    latestPublishedAt = Number(snapshot.publishedAt) || Date.now();
    const old = snapshot.previousFinal;
    captionStage.classList.toggle("has-previous", Boolean(old));
    previous.hidden = !old;
    divider.hidden = !old;
    if (old) {
      previousZh.textContent = old.targetTextZh || "";
      previousEn.textContent = old.sourceTextEn || "";
    }
    const active = snapshot.active || {};
    activeZh.textContent = active.targetTextZh || (active.sourceTextEn ? "正在翻译…" : "等待现场字幕…");
    activeEn.textContent = active.sourceTextEn || "";
    if (snapshot.status === "ended") setConnection("ended", "本场已结束", "字幕保留至链接过期");
    else if (snapshot.status === "revoked") setConnection("error", "链接已失效", "请向现场人员索取新二维码");
    else setConnection("live", "直播中", "刚刚更新");
  }

  function tokenFromLocation() {
    const match = location.pathname.match(/^\/s\/([A-Za-z0-9_-]{24,})\/?$/);
    return match ? match[1] : new URLSearchParams(location.search).get("token") || "";
  }

  function startDemo() {
    demoLabel.hidden = false;
    render({
      status: "live",
      sequence: 42,
      publishedAt: Date.now(),
      previousFinal: {
        sourceTextEn: "We walk by faith, not by sight.",
        targetTextZh: "我们凭信心而行，不凭眼见。",
      },
      active: {
        sourceTextEn: "That changes how we face tomorrow.",
        targetTextZh: "这改变了我们面对明天的方式。",
        phase: "streaming",
      },
    });
  }

  function startFirebase() {
    const token = tokenFromLocation();
    if (!/^[A-Za-z0-9_-]{24,}$/.test(token)) {
      setConnection("error", "链接无效", "请重新扫描现场二维码");
      activeZh.textContent = "这个字幕链接无效。";
      return;
    }
    if (!window.firebase?.apps?.length) {
      setConnection("error", "服务未配置", "请联系现场人员");
      activeZh.textContent = "公网字幕服务尚未配置。";
      return;
    }
    const database = window.firebase.database();
    database.ref(".info/connected").on("value", (snapshot) => {
      if (!snapshot.val()) setConnection("stale", "正在重连", "保留最后一句字幕");
    });
    database.ref(`sessions/${token}`).on("value", (snapshot) => {
      if (!snapshot.exists()) {
        setConnection("error", "链接不可用", "可能尚未开始、已过期或已撤销");
        activeZh.textContent = "字幕尚未开始，或链接已经过期。";
        return;
      }
      render(snapshot.val());
    }, () => {
      setConnection("error", "无法读取字幕", "链接可能已过期或撤销");
    });
  }

  document.querySelectorAll("[data-layout]").forEach((button) => {
    button.addEventListener("click", () => {
      const layout = button.dataset.layout;
      if (layout === "auto") shell.removeAttribute("data-layout");
      else shell.dataset.layout = layout;
      sessionStorage.setItem("caption-layout", layout);
      document.querySelectorAll("[data-layout]").forEach((candidate) => {
        candidate.setAttribute("aria-pressed", String(candidate === button));
      });
    });
  });
  const savedLayout = sessionStorage.getItem("caption-layout");
  if (["portrait", "landscape"].includes(savedLayout)) {
    document.querySelector(`[data-layout="${savedLayout}"]`)?.click();
  }
  document.querySelector("#fullscreen").addEventListener("click", async () => {
    try {
      if (!document.fullscreenElement) await document.documentElement.requestFullscreen();
      else await document.exitFullscreen();
    } catch (_) {
      setConnection("stale", "浏览器不支持全屏", "字幕仍可正常显示");
    }
  });

  window.setInterval(() => {
    if (latestPublishedAt && Date.now() - latestPublishedAt > 10000 && connection.dataset.state === "live") {
      setConnection("stale", "字幕暂时停顿", "正在等待下一句");
    }
  }, 2000);

  if (new URLSearchParams(location.search).get("demo") === "1") startDemo();
  else startFirebase();
})();
