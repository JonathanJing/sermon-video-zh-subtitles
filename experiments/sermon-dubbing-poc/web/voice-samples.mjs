// Optional Korean and Spanish voice auditions. These are independent of weekly releases.
const CATALOG_URL = "/voice-demos/2026-09-21-v2/production-ko-es.json";
const PREFIX = "/voice-demos/2026-09-21-v2/";
const COPY = {
  zh: { intro: "以下韩语和西班牙语音色为 AI 合成试听样音，使用示例文稿，并非本周证道配音；仍待人工听审。", ko: "03  韩语 AI 样音", es: "04  西班牙语 AI 样音", script: "查看样音文稿", pending: "待人工听审", priority: "机器筛查建议优先复听" },
  en: { intro: "The Korean and Spanish voices below are AI-generated auditions using sample scripts, not this week's sermon audio. Human listening review is pending.", ko: "03  Korean AI sample", es: "04  Spanish AI sample", script: "View sample script", pending: "Awaiting human listening review", priority: "Machine screen: listen again first" },
  ko: { intro: "아래 한국어와 스페인어 음성은 예문으로 만든 AI 합성 샘플입니다. 이번 주 설교 음성이 아니며 사람의 청취 검토를 기다리고 있습니다.", ko: "03  한국어 AI 샘플", es: "04  스페인어 AI 샘플", script: "샘플 원고 보기", pending: "청취 검토 대기 중", priority: "기계 검사: 우선 재청취" },
  es: { intro: "Las voces coreana y española son muestras de IA con textos de prueba; no son el audio del sermón de esta semana. Esperan revisión auditiva humana.", ko: "03  Muestra de IA en coreano", es: "04  Muestra de IA en español", script: "Ver texto de muestra", pending: "Pendiente de revisión auditiva humana", priority: "Revisión automática: escuchar de nuevo" },
};

export function validateVoiceSamples(catalog, speakerNames) {
  if (catalog?.schemaVersion !== "sermon-production-voice-auditions-v1"
      || catalog.status !== "audition_demo" || catalog.humanListeningStatus !== "pending"
      || !Array.isArray(catalog.speakers) || catalog.speakers.length !== speakerNames.size) {
    throw new Error("Invalid voice audition catalog");
  }
  const seen = new Set();
  for (const speaker of catalog.speakers) {
    if (!/^[a-z0-9_]+$/.test(speaker.speakerId) || !speakerNames.has(speaker.displayName)
        || seen.has(speaker.displayName) || !Array.isArray(speaker.samples)
        || speaker.samples.length !== 2) throw new Error("Invalid voice audition speaker");
    seen.add(speaker.displayName);
    if (new Set(speaker.samples.map(sample => sample.locale)).size !== 2
        || !speaker.samples.some(sample => sample.locale === "ko")
        || !speaker.samples.some(sample => sample.locale === "es")) {
      throw new Error("Incomplete voice audition locales");
    }
    for (const sample of speaker.samples) {
      if (sample.path !== `${PREFIX}${speaker.speakerId}/${sample.locale}.mp3`
          || !/^[a-f0-9]{64}$/.test(sample.sha256) || !(sample.bytes > 0)
          || sample.humanListeningStatus !== "pending" || typeof sample.reviewPriority !== "boolean"
          || typeof sample.text !== "string" || !sample.text.trim()) {
        throw new Error("Invalid voice audition sample");
      }
    }
  }
  return catalog;
}

export function mountVoiceSamples(grid, catalog, doc = document) {
  const cards = new Map([...grid.querySelectorAll(".voice-card")]
    .map(card => [card.querySelector("h3")?.textContent, card]));
  validateVoiceSamples(catalog, new Set(cards.keys()));
  if (grid.querySelector("[data-voice-demo-locale]")) return;
  const note = doc.createElement("p");
  note.className = "description voice-demo-intro";
  grid.before(note);
  const localized = [];
  for (const speaker of catalog.speakers) {
    const card = cards.get(speaker.displayName);
    for (const locale of ["ko", "es"]) {
      const sample = speaker.samples.find(item => item.locale === locale);
      const section = doc.createElement("section");
      section.className = "voice-demo-sample";
      section.dataset.voiceDemoLocale = locale;
      const label = doc.createElement("p");
      label.className = "sample-label";
      const audio = doc.createElement("audio");
      audio.controls = true;
      audio.preload = "none";
      audio.src = sample.path;
      audio.addEventListener("play", () => {
        for (const other of doc.querySelectorAll("audio")) if (other !== audio) other.pause();
      });
      const transcript = doc.createElement("details");
      transcript.className = "voice-demo-text";
      const summary = doc.createElement("summary");
      const script = doc.createElement("p");
      script.lang = locale;
      script.textContent = sample.text;
      transcript.append(summary, script);
      const status = doc.createElement("p");
      status.className = "voice-demo-status";
      section.append(label, audio, transcript, status);
      if (sample.reviewPriority) {
        const priority = doc.createElement("p");
        priority.className = "voice-demo-priority";
        section.append(priority);
        localized.push(copy => { priority.textContent = copy.priority; });
      }
      localized.push(copy => {
        label.textContent = copy[locale];
        audio.setAttribute("aria-label", `${speaker.displayName} · ${copy[locale]}`);
        summary.textContent = copy.script;
        status.textContent = copy.pending;
      });
      card.append(section);
    }
  }
  const refresh = () => {
    const language = doc.documentElement.lang.toLowerCase().split("-")[0];
    const copy = COPY[language] || COPY.zh;
    note.textContent = copy.intro;
    localized.forEach(update => update(copy));
  };
  refresh();
  new MutationObserver(refresh).observe(doc.documentElement, { attributes: true, attributeFilter: ["lang"] });
}

if (globalThis.document?.getElementById("voice-grid")) {
  const grid = document.getElementById("voice-grid");
  fetch(CATALOG_URL, { cache: "no-store" }).then(async response => {
    if (!response.ok) return;
    const catalog = await response.json();
    const mount = () => {
      if (grid.querySelectorAll(".voice-card").length !== catalog.speakers?.length) return false;
      mountVoiceSamples(grid, catalog);
      return true;
    };
    if (mount()) return;
    const observer = new MutationObserver(() => { if (mount()) observer.disconnect(); });
    observer.observe(grid, { childList: true });
  }).catch(error => console.warn("Voice auditions unavailable", error));
}
