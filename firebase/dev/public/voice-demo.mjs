// Optional, demo-only voice comparison in the Dev reader's More panel.
// This sidecar never changes the sermon catalog or the main player selection.
const CATALOG = "/voice-demos/2026-09-21-v2/catalog.json";
const PREFIX = "/voice-demos/2026-09-21-v2/";
const LANGUAGES = {
  "zh-Hans": "中文", ko: "한국어", es: "Español", vi: "Tiếng Việt"
};
const COPY = {
  zh: {
    title: "多语种音色试听 · Demo", intro: "按讲员展开，先听原始英文片段，再比较四种 AI 合成语言。样音使用统一示例文稿，并非本周证道配音。",
    original: "讲员原始英文片段", generated: "AI 合成样音", transcript: "查看英文机器转写参考", script: "查看样音文稿",
    pending: "本组样音待人工听审", priority: "机器筛查建议优先复听", source: "原声来源", unavailable: "暂时无法读取试听资料，请稍后重试。",
    disclosure: "独立个人项目；讲员及教会未背书这些 AI 合成样音。音色登记不代表每种语言或每篇证道已获正式听审。"
  },
  en: {
    title: "Multilingual voice demos", intro: "Expand a speaker to hear the original English clip, then compare four AI generated languages. These shared sample scripts are not this week's sermon audio.",
    original: "Original English clip", generated: "AI generated sample", transcript: "View machine transcript", script: "View sample script",
    pending: "This sample set awaits human listening review", priority: "Machine screen: listen again first", source: "Original source", unavailable: "Voice demos are unavailable. Please try again later.",
    disclosure: "Independent personal project. These AI samples are not endorsed by the speakers or church. A selected voice does not certify every language or sermon recording."
  },
  ko: {
    title: "다국어 음색 데모", intro: "설교자를 펼쳐 영어 원음을 먼저 듣고 네 가지 AI 합성 언어를 비교하세요. 공통 예문이며 이번 주 설교 음성이 아닙니다.",
    original: "영어 원음", generated: "AI 합성 샘플", transcript: "기계 전사 참고 보기", script: "샘플 원고 보기",
    pending: "이 샘플은 사람의 청취 검토 대기 중", priority: "기계 검사: 우선 재청취", source: "원음 출처", unavailable: "음색 데모를 불러올 수 없습니다. 나중에 다시 시도하세요.",
    disclosure: "독립적인 개인 프로젝트입니다. AI 샘플은 설교자나 교회의 보증이 아닙니다. 음색 선택은 모든 언어나 설교 음성의 승인을 뜻하지 않습니다."
  },
  es: {
    title: "Demos de voces multilingües", intro: "Despliega un orador, escucha primero su voz original en inglés y compara cuatro idiomas generados por IA. Son textos de prueba, no el audio del sermón de esta semana.",
    original: "Voz original en inglés", generated: "Muestra generada por IA", transcript: "Ver transcripción automática", script: "Ver texto de muestra",
    pending: "Estas muestras esperan revisión auditiva humana", priority: "Revisión automática: escuchar de nuevo", source: "Fuente original", unavailable: "No se pudieron cargar las demos. Inténtalo más tarde.",
    disclosure: "Proyecto personal independiente. Ni los oradores ni la iglesia respaldan estas muestras de IA. Elegir una voz no aprueba todos los idiomas ni las grabaciones."
  },
  vi: {
    title: "Bản nghe thử giọng đa ngôn ngữ", intro: "Mở từng diễn giả để nghe giọng tiếng Anh gốc trước, rồi so sánh bốn ngôn ngữ do AI tạo. Đây là văn bản mẫu, không phải âm thanh bài giảng tuần này.",
    original: "Giọng tiếng Anh gốc", generated: "Mẫu giọng AI", transcript: "Xem bản chép máy", script: "Xem văn bản mẫu",
    pending: "Các mẫu này đang chờ người nghe kiểm duyệt", priority: "Kiểm tra máy: nên nghe lại trước", source: "Nguồn bản gốc", unavailable: "Không thể tải bản nghe thử. Vui lòng thử lại sau.",
    disclosure: "Dự án cá nhân độc lập. Các mẫu AI không được diễn giả hoặc nhà thờ bảo trợ. Việc chọn giọng không xác nhận mọi ngôn ngữ hay bài giảng."
  }
};

const locale = () => {
  const code = document.documentElement.lang.toLowerCase();
  return code.startsWith("ko") ? "ko" : code.startsWith("es") ? "es"
    : code.startsWith("vi") ? "vi" : code.startsWith("en") ? "en" : "zh";
};
const copy = key => COPY[locale()][key];
const element = (tag, className, text) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
};
const localize = root => {
  for (const node of root.querySelectorAll("[data-voice-copy]")) {
    node.textContent = copy(node.dataset.voiceCopy);
  }
};
const label = (key, tag = "span", className = "") => {
  const node = element(tag, className, copy(key));
  node.dataset.voiceCopy = key;
  return node;
};
const validPath = value => typeof value === "string" && value.startsWith(PREFIX)
  && !value.includes("..") && !value.includes("?") && !value.includes("#");

function createAudio(asset, name, labelText) {
  if (!validPath(asset.path)) throw new Error("Invalid demo audio path");
  const audio = element("audio");
  audio.controls = true;
  audio.preload = "none";
  audio.src = asset.path;
  audio.setAttribute("aria-label", `${name} · ${labelText}`);
  audio.addEventListener("play", () => {
    document.getElementById("audio")?.pause();
    for (const other of document.querySelectorAll("#voiceDemoDetails audio")) {
      if (other !== audio) other.pause();
    }
  });
  return audio;
}

function renderSpeaker(speaker) {
  if (!speaker || typeof speaker.displayName !== "string" || !speaker.original
      || !Array.isArray(speaker.samples) || speaker.samples.length !== 4) {
    throw new Error("Invalid demo speaker");
  }
  const details = element("details", "voice-demo-speaker");
  details.append(element("summary", "", speaker.displayName));
  details.addEventListener("toggle", () => {
    if (!details.open) {
      for (const audio of details.querySelectorAll("audio")) audio.pause();
      return;
    }
    if (details.dataset.loaded) return;
    details.dataset.loaded = "true";
    const original = element("section", "voice-demo-track");
    original.append(label("original", "h4"), createAudio(speaker.original, speaker.displayName, copy("original")));
    const transcript = element("details", "voice-demo-text");
    transcript.append(label("transcript", "summary"));
    const sourceText = element("p", "", speaker.original.text);
    sourceText.lang = "en";
    transcript.append(sourceText);
    original.append(transcript);
    if (speaker.original.sourceUrl?.startsWith("https://")) {
      const link = element("a", "voice-demo-source");
      link.href = speaker.original.sourceUrl;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.append(label("source"));
      original.append(link);
    }
    details.append(original);
    for (const sample of speaker.samples) {
      if (!LANGUAGES[sample.locale]) throw new Error("Invalid demo locale");
      const row = element("section", "voice-demo-track");
      const heading = element("h4", "", `${LANGUAGES[sample.locale]} · ${copy("generated")}`);
      heading.dataset.voiceGeneratedLocale = sample.locale;
      row.append(heading, createAudio(sample, speaker.displayName, LANGUAGES[sample.locale]));
      const text = element("details", "voice-demo-text");
      text.append(label("script", "summary"));
      const paragraph = element("p", "", sample.text);
      paragraph.lang = sample.locale;
      text.append(paragraph);
      row.append(text);
      if (sample.reviewPriority) row.append(label("priority", "p", "voice-demo-caution"));
      details.append(row);
    }
    details.append(label("pending", "p", "voice-demo-pending"));
  });
  return details;
}

const more = document.getElementById("moreOptions");
if (more) {
  const panel = element("details", "voice-demo-panel");
  panel.id = "voiceDemoDetails";
  panel.append(label("title", "summary"));
  const body = element("div", "voice-demo-body");
  body.append(label("intro", "p", "voice-demo-intro"));
  const list = element("div", "voice-demo-list");
  body.append(list, label("disclosure", "p", "voice-demo-disclosure"));
  panel.append(body);
  more.append(panel);
  let loaded = false;
  panel.addEventListener("toggle", async () => {
    if (!panel.open) {
      for (const audio of panel.querySelectorAll("audio")) audio.pause();
      return;
    }
    if (loaded) return;
    try {
      const response = await fetch(CATALOG, { cache: "no-store" });
      if (!response.ok) throw new Error(`Demo catalog HTTP ${response.status}`);
      const catalog = await response.json();
      if (catalog.schemaVersion !== "sermon-multilingual-voice-demo-public-v1"
          || catalog.status !== "audition_demo"
          || !Array.isArray(catalog.speakers) || catalog.speakers.length !== 6) {
        throw new Error("Invalid demo catalog");
      }
      list.replaceChildren(...catalog.speakers.map(renderSpeaker));
      loaded = true;
    } catch (error) {
      console.warn("Voice demo unavailable", error);
      list.replaceChildren(label("unavailable", "p", "voice-demo-error"));
    }
  });
  document.getElementById("audio")?.addEventListener("play", () => {
    for (const audio of panel.querySelectorAll("audio")) audio.pause();
  });
  new MutationObserver(() => {
    localize(panel);
    for (const heading of panel.querySelectorAll("[data-voice-generated-locale]")) {
      heading.textContent = `${LANGUAGES[heading.dataset.voiceGeneratedLocale]} · ${copy("generated")}`;
    }
  }).observe(document.documentElement, { attributes: true, attributeFilter: ["lang"] });
}
