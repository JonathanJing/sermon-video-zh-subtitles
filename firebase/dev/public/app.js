import {
  fetchVerified, validateDemoCatalog, validateDemoContent, validateDemoRelease
} from "./dev-integrity.mjs";
import {
  formalReleaseView, loadOptionalFormalCatalog, validateFormalCaptions,
  validateFormalContent, validateFormalRelease
} from "./formal-dev-adapter.mjs";
import { PlaybackMemory } from "./playback-memory.mjs";

const languageNames = {
  en: { native: "English", code: "EN", detail: "英文原文" },
  "zh-Hans": { native: "简体中文", code: "ZH", detail: "中文（简体）" },
  ko: { native: "한국어", code: "KO", detail: "韩语" },
  es: { native: "Español", code: "ES", detail: "西班牙语" },
  vi: { native: "Tiếng Việt", code: "VI", detail: "越南语" }
};

const interfaceCopy = {
  zh: {
    banner: "9 月 20 日证道片段 POC；可切换英文原文和四种目标语言对照。", brand: "多语言证道", languageCard: "证道语言",
    mockTitle: "真实 Layer 2 + Layer 3 POC", mockBody: "六个英文源句分别翻译并经 GPT 语义裁判；Eric 克隆音色仅供 Dev App 测试。",
    sourceTitle: "Layer 1 英文原文", sourceBody: "使用同一来源窗口的英文 anchor 和 Eric 原始录音，作为四种译文与克隆音频的对照。",
    tabs: ["收听", "字幕全文", "大纲"], now: "正在讲述", transcript: "字幕全文", outline: "证道大纲",
    playerNote: "机器生成的讲员克隆音色；非原始录音、非正式配音，人工听审待完成。", sourcePlayerNote: "讲员原始英文录音片段；英文 anchor 仍保留其 Layer 1 机器边界审核状态。", release: "发布包状态", text: "文字", audio: "音频",
    mock: "机器审核通过 · 待人工", tone: "克隆音频 · 待听审", dialogTitle: "选择证道语言", dialogHint: "界面语言、内容语言和音频语言分别管理。",
    dialogFoot: "英文是 Layer 1 来源对照；四种目标语言均为开发 POC。越南语 ASR 筛查低于门线。",
    footer: "独立个人开发项目，与 Mariners Church 无隶属或背书关系。", switchInterface: "切换界面为英文",
    themeDark: "深色", themeLight: "浅色", audioVariant: "校对音频版本", capabilities: "机器译文 · 估算字幕 · 克隆音频", sourceCapabilities: "英文原文 · 原始录音 · 来源时间轴", loadError: "Dev 内容暂时无法载入"
  },
  en: {
    banner: "September 20 sermon-fragment POC; switch between the English source and four target languages.", brand: "Multilingual Sermons", languageCard: "Sermon language",
    mockTitle: "Real Layer 2 + Layer 3 POC", mockBody: "Six English source units were translated and GPT-judged; Eric's cloned voice is for Dev App testing only.",
    sourceTitle: "Layer 1 English source", sourceBody: "The aligned English anchors and Eric's original recording provide the reference for all four translations and cloned voices.",
    tabs: ["Listen", "Transcript", "Outline"], now: "Now speaking", transcript: "Full transcript", outline: "Sermon outline",
    playerNote: "Machine-generated speaker clone; not the original recording or production dubbing. Human listening is pending.", sourcePlayerNote: "Original English speaker audio; the English anchors retain their Layer 1 machine-boundary review state.", release: "Release package status", text: "Text", audio: "Audio",
    mock: "Machine pass · human pending", tone: "Cloned audio · listening pending", dialogTitle: "Choose sermon language", dialogHint: "Interface, content, and audio languages are managed separately.",
    dialogFoot: "English is the Layer 1 source reference. All four target languages are development POCs; Vietnamese remains below the ASR threshold.",
    footer: "Independent personal development project; not affiliated with or endorsed by Mariners Church.", switchInterface: "Switch interface to Chinese",
    themeDark: "Dark", themeLight: "Light", audioVariant: "Review audio version", capabilities: "Machine text · Estimated captions · Cloned audio", sourceCapabilities: "English source · Original audio · Source timeline", loadError: "Dev content is temporarily unavailable"
  }
};

// Interface language controls labels only. It supplies the default content
// locale when opening a sermon without an explicit content choice; changing
// the interface never interrupts the current sermon or audio.
const interfaceLocales = {
  zh: { native: "简体中文", code: "中", htmlLang: "zh-Hans" },
  en: { native: "English", code: "EN", htmlLang: "en" },
  ko: { native: "한국어", code: "KO", htmlLang: "ko" },
  es: { native: "Español", code: "ES", htmlLang: "es" },
  vi: { native: "Tiếng Việt", code: "VI", htmlLang: "vi" }
};
const extraCopy = {
  zh: { brandName: "同行", brandDetail: "证道中文听译", edition: "DEV · 机器 POC", week: "本期与往期", weekHint: "选择日期，收听往期证道", more: "更多", sourceToggle: "英文原文", sourceReference: "英文原文参考", transcriptHint: "点时间跳转", showTranscript: "查看全文", captionNote: "字幕随当前音频更新 · Dev POC", footerBrand: "同行 · 证道中文听译", footerMotto: "一起听懂，一路同行。", interfaceLabel: "选择界面语言", close: "关闭", ready: "音频已就绪", loading: "音频准备中", playing: "正在播放", paused: "已暂停", play: "开始播放", pause: "暂停播放", backHint: "向前调整", back: "后退 5 秒", forwardHint: "向后调整", forward: "前进 5 秒", current: "回到当前句", precision: "定位 / 精调", alignment: "此 POC 未发布现场自动对齐资料", progress: "播放进度", sourceMedia: "英文原文 · 原始音频", targetMedia: "机器译文 · 克隆音频", sourceStatus: "来源参考", screened: "机器筛查", needsReview: "需人工复核" },
  en: { brandName: "Tongxing", brandDetail: "Sermon listening", edition: "DEV · MACHINE POC", week: "Current & past", weekHint: "Choose a sermon date", more: "More", sourceToggle: "English source", sourceReference: "English source reference", transcriptHint: "Tap a time to jump", showTranscript: "Full transcript", captionNote: "Captions follow audio · Dev POC", footerBrand: "Tongxing · Sermon listening", footerMotto: "Listen and understand together.", interfaceLabel: "Choose app language", close: "Close", ready: "Audio ready", loading: "Preparing audio", playing: "Playing", paused: "Paused", play: "Play", pause: "Pause", backHint: "Adjust back", back: "Back 5 seconds", forwardHint: "Adjust forward", forward: "Forward 5 seconds", current: "Current sentence", precision: "Seek / fine tune", alignment: "Live auto alignment is unavailable in this POC", progress: "Playback progress", sourceMedia: "English source · original audio", targetMedia: "Machine text · cloned audio", sourceStatus: "Source reference", screened: "Machine screened", needsReview: "Human review needed" },
  ko: { brandName: "동행", brandDetail: "설교 듣기", edition: "DEV · 기계 POC", week: "이번 주와 지난 설교", weekHint: "설교 날짜 선택", more: "더보기", sourceToggle: "영어 원문", sourceReference: "영어 원문 참고", transcriptHint: "시간을 눌러 이동", showTranscript: "전체 자막", captionNote: "오디오에 맞춰 자막 표시 · Dev POC", footerBrand: "동행 · 설교 듣기", footerMotto: "함께 듣고 이해해요.", interfaceLabel: "앱 언어 선택", close: "닫기", ready: "오디오 준비됨", loading: "오디오 준비 중", playing: "재생 중", paused: "일시 정지", play: "재생", pause: "일시 정지", backHint: "뒤로 조정", back: "5초 뒤로", forwardHint: "앞으로 조정", forward: "5초 앞으로", current: "현재 문장", precision: "위치 / 세부 조정", alignment: "이 POC에는 현장 자동 정렬 자료가 없습니다", progress: "재생 진행률", sourceMedia: "영어 원문 · 원본 오디오", targetMedia: "기계 번역 · 복제 음성", sourceStatus: "원문 참고", screened: "기계 검토", needsReview: "사람 검토 필요" },
  es: { brandName: "Tongxing", brandDetail: "Escuchar sermones", edition: "DEV · POC AUTOMÁTICA", week: "Actuales y anteriores", weekHint: "Elige una fecha", more: "Más", sourceToggle: "Original en inglés", sourceReference: "Referencia en inglés", transcriptHint: "Toca una hora para ir", showTranscript: "Transcripción completa", captionNote: "Subtítulos con el audio · Dev POC", footerBrand: "Tongxing · Escuchar sermones", footerMotto: "Escuchemos y comprendamos juntos.", interfaceLabel: "Elegir idioma de la app", close: "Cerrar", ready: "Audio listo", loading: "Preparando audio", playing: "Reproduciendo", paused: "En pausa", play: "Reproducir", pause: "Pausar", backHint: "Ajustar atrás", back: "Retroceder 5 segundos", forwardHint: "Ajustar adelante", forward: "Avanzar 5 segundos", current: "Frase actual", precision: "Buscar / ajustar", alignment: "Esta POC no incluye alineación automática en vivo", progress: "Progreso de reproducción", sourceMedia: "Original inglés · audio original", targetMedia: "Traducción automática · voz clonada", sourceStatus: "Fuente de referencia", screened: "Revisión automática", needsReview: "Revisión humana pendiente" },
  vi: { brandName: "Đồng Hành", brandDetail: "Nghe bài giảng", edition: "DEV · POC TỰ ĐỘNG", week: "Tuần này và trước đây", weekHint: "Chọn ngày bài giảng", more: "Thêm", sourceToggle: "Bản gốc tiếng Anh", sourceReference: "Tham khảo bản gốc tiếng Anh", transcriptHint: "Chạm mốc thời gian để chuyển", showTranscript: "Toàn bộ phụ đề", captionNote: "Phụ đề theo âm thanh · Dev POC", footerBrand: "Đồng Hành · Nghe bài giảng", footerMotto: "Cùng lắng nghe và thấu hiểu.", interfaceLabel: "Chọn ngôn ngữ ứng dụng", close: "Đóng", ready: "Âm thanh đã sẵn sàng", loading: "Đang chuẩn bị âm thanh", playing: "Đang phát", paused: "Đã tạm dừng", play: "Phát", pause: "Tạm dừng", backHint: "Chỉnh lùi", back: "Lùi 5 giây", forwardHint: "Chỉnh tới", forward: "Tới 5 giây", current: "Câu hiện tại", precision: "Tìm / chỉnh vị trí", alignment: "POC này chưa có dữ liệu căn chỉnh tự động tại chỗ", progress: "Tiến trình phát", sourceMedia: "Bản gốc tiếng Anh · âm thanh gốc", targetMedia: "Bản dịch máy · giọng nhân bản", sourceStatus: "Bản gốc tham khảo", screened: "Máy đã kiểm tra", needsReview: "Cần người kiểm tra" }
};
const statusCopy = {
  zh: { sourceText: "英文来源 · 边界待复核", sourceAudio: "讲员原始音频", passText: "机器审核通过 · 待人工", passAudio: "机器筛查 · 待听审", pending: "机器复筛待完成 · 待听审", review: "ASR 筛查未达门线 · 需复核", unverified: "机器筛查未通过或状态未知 · 需复核", textPending: "文字状态待核实 · 不可发布", themeLight: "浅色", themeDark: "深色", oneWeek: "当前只有一个 Dev POC 片段" },
  en: { sourceText: "English source · boundary review pending", sourceAudio: "Original speaker audio", passText: "Machine pass · human review pending", passAudio: "Machine screened · listening pending", pending: "Machine screening pending · listening pending", review: "ASR below threshold · review required", unverified: "Screening failed or unknown · review required", textPending: "Text status unverified · not publishable", themeLight: "Light", themeDark: "Dark", oneWeek: "One Dev POC fragment is available" },
  ko: { sourceText: "영어 원문 · 경계 검토 대기", sourceAudio: "설교자 원본 오디오", passText: "기계 검토 통과 · 사람 검토 대기", passAudio: "기계 검사 · 청취 검토 대기", pending: "기계 재검사 대기 · 청취 검토 대기", review: "ASR 기준 미달 · 재검토 필요", unverified: "검사 실패 또는 상태 불명 · 검토 필요", textPending: "텍스트 상태 미확인 · 게시 불가", themeLight: "밝게", themeDark: "어둡게", oneWeek: "현재 Dev POC 설교 한 편만 제공됩니다" },
  es: { sourceText: "Fuente inglesa · límites pendientes", sourceAudio: "Audio original del predicador", passText: "Revisión automática · revisión humana pendiente", passAudio: "Audio revisado por máquina · escucha pendiente", pending: "Revisión automática pendiente · escucha pendiente", review: "ASR bajo el umbral · requiere revisión", unverified: "Revisión fallida o desconocida · comprobar", textPending: "Estado del texto sin verificar · no publicable", themeLight: "Claro", themeDark: "Oscuro", oneWeek: "Hay un solo fragmento Dev POC" },
  vi: { sourceText: "Bản gốc tiếng Anh · chờ kiểm tra mốc", sourceAudio: "Âm thanh gốc của người giảng", passText: "Máy đã kiểm tra · chờ người duyệt", passAudio: "Máy đã kiểm tra · chờ nghe duyệt", pending: "Chờ máy kiểm tra lại · chờ nghe duyệt", review: "ASR dưới ngưỡng · cần kiểm tra", unverified: "Kiểm tra thất bại hoặc không rõ · cần xem lại", textPending: "Trạng thái văn bản chưa xác minh · chưa thể phát hành", themeLight: "Sáng", themeDark: "Tối", oneWeek: "Hiện chỉ có một bài giảng Dev POC" }
};
const textOnlyCopy = {
  zh: "仅文字 · 无此语言音频", en: "Text only · no audio in this language",
  ko: "텍스트만 제공 · 이 언어의 음성 없음", es: "Solo texto · sin audio en este idioma",
  vi: "Chỉ có văn bản · không có âm thanh ngôn ngữ này"
};
const textOnlyCaptionCopy = {
  zh: "阅读译文 · 此语言暂无音频", en: "Read the text · audio is unavailable in this language",
  ko: "번역문 읽기 · 이 언어의 음성 없음", es: "Leer la traducción · audio no disponible en este idioma",
  vi: "Đọc bản dịch · không có âm thanh ngôn ngữ này"
};
const utilityCopy = {
  zh: { error: "Dev 内容加载失败；当前内容和播放未改变。", retry: "重试", resumeAt: "上次听到", resume: "恢复位置", restart: "从头开始", download: "下载当前音频", seekTo: "跳转到", brandHome: "同行 Dev 首页", sermonInfo: "证道信息", moreOptions: "更多选项", resumeRegion: "恢复收听" },
  en: { error: "Dev content could not load. Your current sermon and playback are unchanged.", retry: "Retry", resumeAt: "Last listened at", resume: "Resume", restart: "Start over", download: "Download current audio", seekTo: "Jump to", brandHome: "Tongxing Dev home", sermonInfo: "Sermon details", moreOptions: "More options", resumeRegion: "Resume listening" },
  ko: { error: "Dev 콘텐츠를 불러오지 못했습니다. 현재 설교와 재생은 그대로 유지됩니다.", retry: "다시 시도", resumeAt: "마지막으로 들은 위치", resume: "이어서 듣기", restart: "처음부터", download: "현재 오디오 다운로드", seekTo: "이동", brandHome: "동행 Dev 홈", sermonInfo: "설교 정보", moreOptions: "더보기 옵션", resumeRegion: "이어서 듣기" },
  es: { error: "No se pudo cargar el contenido Dev. Se mantiene la reproducción actual.", retry: "Reintentar", resumeAt: "Última posición", resume: "Continuar", restart: "Empezar de nuevo", download: "Descargar audio actual", seekTo: "Ir a", brandHome: "Inicio de Tongxing Dev", sermonInfo: "Detalles del sermón", moreOptions: "Más opciones", resumeRegion: "Continuar escuchando" },
  vi: { error: "Không tải được nội dung Dev. Bài giảng và âm thanh hiện tại vẫn giữ nguyên.", retry: "Thử lại", resumeAt: "Đã nghe đến", resume: "Nghe tiếp", restart: "Bắt đầu lại", download: "Tải âm thanh hiện tại", seekTo: "Chuyển đến", brandHome: "Trang chủ Đồng Hành Dev", sermonInfo: "Thông tin bài giảng", moreOptions: "Tùy chọn khác", resumeRegion: "Nghe tiếp" }
};
const formalCopy = {
  zh: { edition: "DEV · 四层审核片段", title: "三语审核片段", body: "译文、音频和同步已有独立人工审核收据；发布验收状态单独显示。", player: "目标语言配音 · 已完成全文听审与原视频 1 倍速同步审核。", content: "人工审核通过", audio: "全文听审通过", httpPending: "待 HTTP 验证", httpPass: "HTTP 已验证", language: "译文 · 已审核配音", foot: "此页面提供中文、韩语和西班牙语的审核片段。", caption: "字幕与已审核音频同步 · Dev" },
  en: { edition: "DEV · FOUR-LAYER REVIEWED", title: "Reviewed three-language clip", body: "The text, audio, and synchronization have independent human review receipts; publication checks are shown separately.", player: "Target-language dubbing reviewed end to end and against the source video at 1×.", content: "Human reviewed", audio: "Full playback reviewed", httpPending: "HTTP check pending", httpPass: "HTTP verified", language: "Reviewed text and dubbing", foot: "This page provides a reviewed Chinese, Korean, and Spanish clip.", caption: "Captions follow reviewed audio · Dev" },
  ko: { edition: "DEV · 4단계 검토", title: "3개 언어 검토 영상", body: "번역문, 오디오, 동기화의 독립적인 사람 검토 기록이 있습니다. 게시 검증 상태는 별도로 표시됩니다.", player: "전체 청취 및 원본 영상 1배속 동기화 검토를 마친 더빙입니다.", content: "사람 검토 완료", audio: "전체 청취 검토 완료", httpPending: "HTTP 검증 대기", httpPass: "HTTP 검증 완료", language: "검토된 번역과 더빙", foot: "중국어, 한국어, 스페인어 검토 영상을 제공합니다.", caption: "검토된 오디오와 동기화된 자막 · Dev" },
  es: { edition: "DEV · CUATRO CAPAS REVISADAS", title: "Fragmento revisado en tres idiomas", body: "El texto, el audio y la sincronización tienen revisión humana independiente. La verificación de publicación se muestra aparte.", player: "Doblaje revisado completo y sincronizado con el video original a velocidad 1×.", content: "Revisión humana completa", audio: "Audio escuchado completo", httpPending: "Verificación HTTP pendiente", httpPass: "HTTP verificado", language: "Texto y doblaje revisados", foot: "Esta página ofrece el fragmento revisado en chino, coreano y español.", caption: "Subtítulos sincronizados con audio revisado · Dev" },
  vi: { edition: "DEV · FOUR-LAYER REVIEWED", title: "Reviewed three-language clip", body: "Text, audio, and synchronization have independent human review receipts.", player: "Target-language dubbing reviewed end to end and against source video at 1×.", content: "Human reviewed", audio: "Full playback reviewed", httpPending: "HTTP check pending", httpPass: "HTTP verified", language: "Reviewed text and dubbing", foot: "Chinese, Korean, and Spanish reviewed clip.", caption: "Captions follow reviewed audio · Dev" }
};
Object.assign(interfaceCopy, {
  ko: { ...interfaceCopy.en, brand: "다국어 설교", languageCard: "설교 언어", mockTitle: "Layer 2 + Layer 3 POC", mockBody: "기계 번역과 복제 음성은 개발용이며 사람의 검토가 필요합니다.", sourceTitle: "Layer 1 영어 원문", sourceBody: "영어 원문과 원본 오디오는 번역과 복제 음성의 참고 자료입니다.", tabs: ["듣기", "전체 자막", "개요"], now: "현재 문장", transcript: "전체 자막", outline: "설교 개요", playerNote: "기계 생성 음성입니다. 공식 더빙이 아니며 청취 검토가 필요합니다.", sourcePlayerNote: "원본 영어 오디오입니다. 원문 구간은 아직 기계 검토 상태입니다.", release: "릴리스 패키지 상태", text: "텍스트", audio: "오디오", dialogTitle: "설교 언어 선택", dialogHint: "앱 언어, 설교 언어, 오디오 언어는 별도로 관리됩니다.", dialogFoot: "영어는 원문 참고입니다. 네 가지 번역은 개발 POC이며 베트남어 ASR은 기준 미달입니다.", footer: "Mariners Church와 무관한 개인 개발 프로젝트입니다.", audioVariant: "검토용 오디오 버전", capabilities: "기계 번역 · 예상 자막 · 복제 음성", sourceCapabilities: "영어 원문 · 원본 오디오", loadError: "Dev 콘텐츠를 불러올 수 없습니다" },
  es: { ...interfaceCopy.en, brand: "Sermones multilingües", languageCard: "Idioma del sermón", mockTitle: "POC de las capas 2 y 3", mockBody: "La traducción automática y la voz clonada son solo para desarrollo y requieren revisión humana.", sourceTitle: "Fuente inglesa de la capa 1", sourceBody: "El texto y audio originales en inglés sirven de referencia para las traducciones.", tabs: ["Escuchar", "Transcripción", "Esquema"], now: "Ahora", transcript: "Transcripción completa", outline: "Esquema del sermón", playerNote: "Voz generada por máquina; no es doblaje oficial. Falta revisión auditiva.", sourcePlayerNote: "Audio original en inglés; los límites de segmentos aún tienen revisión automática.", release: "Estado del paquete", text: "Texto", audio: "Audio", dialogTitle: "Elegir idioma del sermón", dialogHint: "El idioma de la app, del contenido y del audio se gestionan por separado.", dialogFoot: "El inglés es la fuente. Los otros idiomas son POC de desarrollo; el ASR vietnamita está bajo el umbral.", footer: "Proyecto personal independiente, sin afiliación ni respaldo de Mariners Church.", audioVariant: "Versión de audio para revisión", capabilities: "Traducción automática · subtítulos estimados · voz clonada", sourceCapabilities: "Original inglés · audio original", loadError: "No se puede cargar el contenido Dev" },
  vi: { ...interfaceCopy.en, brand: "Bài giảng đa ngôn ngữ", languageCard: "Ngôn ngữ bài giảng", mockTitle: "POC lớp 2 + lớp 3", mockBody: "Bản dịch máy và giọng nhân bản chỉ dành cho phát triển, cần được người kiểm tra.", sourceTitle: "Bản gốc tiếng Anh lớp 1", sourceBody: "Văn bản và âm thanh tiếng Anh gốc là tài liệu tham khảo cho các bản dịch.", tabs: ["Nghe", "Toàn bộ phụ đề", "Dàn ý"], now: "Đang nói", transcript: "Toàn bộ phụ đề", outline: "Dàn ý bài giảng", playerNote: "Giọng do máy tạo, không phải bản lồng tiếng chính thức. Chưa được nghe kiểm tra.", sourcePlayerNote: "Âm thanh tiếng Anh gốc; mốc câu vẫn ở trạng thái máy kiểm tra.", release: "Trạng thái gói phát hành", text: "Văn bản", audio: "Âm thanh", dialogTitle: "Chọn ngôn ngữ bài giảng", dialogHint: "Ngôn ngữ ứng dụng, nội dung và âm thanh được quản lý riêng.", dialogFoot: "Tiếng Anh là bản gốc. Bốn bản dịch là POC; ASR tiếng Việt dưới ngưỡng yêu cầu.", footer: "Dự án cá nhân độc lập, không liên kết hoặc được Mariners Church bảo trợ.", audioVariant: "Phiên bản âm thanh để kiểm tra", capabilities: "Bản dịch máy · phụ đề ước tính · giọng nhân bản", sourceCapabilities: "Bản gốc tiếng Anh · âm thanh gốc", loadError: "Không tải được nội dung Dev" }
});

const state = {
  catalog: null, page: null, locale: null, release: null, content: null, audioVariant: null,
  ui: interfaceLocales[localStorage.getItem("tongxing-dev-ui")] ? localStorage.getItem("tongxing-dev-ui") : "zh",
  activeTab: "listen", showSource: false, audioObjectURL: null, selectionToken: 0,
  selectionController: null, variantController: null, pendingPageId: null, pendingLocale: null, pendingVariantId: null, pendingResume: null,
  lastSavedAt: 0, switchingAudio: false, lastCueIndex: null, captionRevealScheduled: false
};
const $ = (id) => document.getElementById(id);
const audio = $("audio");
const playbackMemory = new PlaybackMemory({ storage: localStorage });

async function loadJSON(path) {
  const response = await fetch(path, { cache: "no-store" });
  if (!response.ok) throw new Error(`${path}: HTTP ${response.status}`);
  return response.json();
}

function availableAudioVariants(release = state.release, content = state.content, locale = state.locale) {
  if (release?.audioVariants?.length) return release.audioVariants;
  return release?.audioUrl ? [{
    id: "default",
    label: languageNames[locale]?.native || "Audio",
    labelEn: languageNames[locale]?.native || "Audio",
    description: "",
    descriptionEn: "",
    audioUrl: release.audioUrl,
    audioSha256: release.audioSha256,
    durationSeconds: content?.durationSeconds
  }] : [];
}

function activeCues() {
  return state.audioVariant?.cues?.length ? state.audioVariant.cues : (state.content?.cues || []);
}

function effectiveDuration() {
  if (Number.isFinite(audio.duration)) return audio.duration;
  return state.audioVariant?.durationSeconds || state.content?.durationSeconds || 24;
}

function loadAudioVariant(variant, objectURL, { remember = true } = {}) {
  const previousURL = state.audioObjectURL;
  state.switchingAudio = true;
  audio.pause();
  state.audioVariant = variant;
  state.audioObjectURL = objectURL || null;
  state.pendingResume = null;
  state.lastCueIndex = null;
  if (variant) audio.src = objectURL;
  else audio.removeAttribute("src");
  audio.load();
  state.switchingAudio = false;
  if (previousURL) URL.revokeObjectURL(previousURL);
  if (variant && remember) localStorage.setItem(`tongxing-dev-audio-${state.page.id}-${state.locale}`, variant.id);
}

async function verifiedAudioURL(variant, signal) {
  const bytes = await fetchVerified(variant.audioUrl, variant.audioSha256, { signal });
  const type = variant.audioUrl.endsWith(".wav") ? "audio/wav" : "audio/mpeg";
  return URL.createObjectURL(new Blob([bytes], { type }));
}

function playbackSource() {
  if (!state.page || !state.audioVariant || !state.locale) return null;
  return {
    week: state.page.date,
    trackId: `${state.page.id}:${state.locale}:${state.audioVariant.id}`,
    audioSha256: state.audioVariant.audioSha256
  };
}

function saveProgress(force = false) {
  if (state.switchingAudio || state.pendingResume || !audio.currentTime || !audio.duration) return;
  if (!force && Date.now() - state.lastSavedAt < 4000) return;
  playbackMemory.save(playbackSource(), {
    positionSeconds: audio.currentTime, fineOffset: 0, durationSeconds: audio.duration
  });
  state.lastSavedAt = Date.now();
}

function renderResume() {
  const saved = state.pendingResume;
  $("resumeCard").hidden = !saved;
  if (saved) $("resumeMessage").textContent = `${utilityCopy[state.ui].resumeAt} ${formatTime(saved.positionSeconds)}`;
}

function seekTo(time) {
  audio.currentTime = Math.max(0, Math.min(effectiveDuration(), time));
  state.pendingResume = null;
  renderResume();
  syncPlayer();
  saveProgress(true);
}

async function switchAudioVariant(variant) {
  if (!variant || variant.id === state.audioVariant?.id) return;
  state.pendingVariantId = null;
  state.variantController?.abort();
  const controller = new AbortController();
  state.variantController = controller;
  const token = state.selectionToken;
  const locale = state.locale;
  try {
    const objectURL = await verifiedAudioURL(variant, controller.signal);
    if (controller.signal.aborted || token !== state.selectionToken || locale !== state.locale) {
      URL.revokeObjectURL(objectURL);
      return;
    }
    saveProgress(true);
    loadAudioVariant(variant, objectURL);
    $("loadError").hidden = true;
    render();
  } catch (error) {
    if (!controller.signal.aborted && token === state.selectionToken) {
      state.pendingVariantId = variant.id;
      renderAudioVariantPicker();
      showError(error);
    }
  }
}

function routeSelection() {
  const match = location.pathname.match(/^\/pages\/([A-Za-z0-9][A-Za-z0-9._-]{0,127})\/(en|zh-Hans|ko|es|vi)\/?$/);
  const query = new URLSearchParams(location.search);
  return { pageId: match?.[1] || query.get("week"), locale: match?.[2] || query.get("lang") };
}

async function selectLocale(locale, { navigate = true, manual = false, page = state.page } = {}) {
  const target = page?.targets[locale];
  if (!target) return;
  state.selectionController?.abort();
  state.variantController?.abort();
  const controller = new AbortController();
  const token = ++state.selectionToken;
  state.selectionController = controller;
  state.pendingPageId = page.id;
  state.pendingLocale = locale;
  state.pendingVariantId = null;
  try {
  const releaseBytes = await fetchVerified(target.releasePackageUrl, target.releasePackageJsonSha256,
    { signal: controller.signal, maxBytes: 1024 * 1024 });
  const parsedRelease = JSON.parse(new TextDecoder().decode(releaseBytes));
  const formal = page.catalogKind === "formal";
  const release = formal
    ? formalReleaseView(validateFormalRelease(parsedRelease, page, locale), page, locale)
    : validateDemoRelease(parsedRelease, page, locale);
  const contentBytes = await fetchVerified(release.contentUrl, release.contentSha256,
    { signal: controller.signal, maxBytes: 4 * 1024 * 1024 });
  const content = formal
    ? validateFormalContent(JSON.parse(new TextDecoder().decode(contentBytes)), parsedRelease, page, locale)
    : validateDemoContent(JSON.parse(new TextDecoder().decode(contentBytes)), release, locale);
  if (formal) {
    const captionBytes = await fetchVerified(release.captionsUrl, release.captionsSha256,
      { signal: controller.signal, maxBytes: 4 * 1024 * 1024 });
    validateFormalCaptions(JSON.parse(new TextDecoder().decode(captionBytes)), content);
  }
  const variants = availableAudioVariants(release, content, locale);
  const savedVariant = localStorage.getItem(`tongxing-dev-audio-${page.id}-${locale}`);
  const saved = variants.find(item => item.id === savedVariant);
  const variant = (saved?.supersededBy && variants.find(item => item.id === saved.supersededBy))
    || saved
    || variants.find(item => item.id === release.defaultAudioVariantId)
    || variants[0];
  const objectURL = variant ? await verifiedAudioURL(variant, controller.signal) : null;
  if (token !== state.selectionToken || controller.signal.aborted) {
    if (objectURL) URL.revokeObjectURL(objectURL);
    return;
  }
  saveProgress(true);
  state.page = page;
  state.locale = locale;
  state.release = release;
  state.content = content;
  state.pendingPageId = null;
  state.pendingLocale = null;
  state.pendingResume = null;
  loadAudioVariant(variant, objectURL, { remember: false });
  if (manual) {
    localStorage.setItem(`tongxing-dev-content-override-${page.id}`, locale);
  }
  if (navigate) history.pushState({ locale }, "", release.pageUrl);
  $("loadError").hidden = true;
  render();
  if ($("languageDialog").open) $("languageDialog").close();
  } catch (error) {
    if (controller.signal.aborted || token !== state.selectionToken) return;
    throw error;
  }
}

function render() {
  const content = state.content;
  document.documentElement.lang = interfaceLocales[state.ui].htmlLang;
  document.title = `${content.title} · ${extraCopy[state.ui].brandName} Dev`;
  $("seriesLabel").textContent = content.series;
  $("sermonTitle").textContent = content.title;
  $("seriesLabel").lang = state.locale;
  $("sermonTitle").lang = state.locale;
  $("sermonSummary").lang = state.locale;
  $("currentCaption").lang = state.locale;
  $("nextCaption").lang = state.locale;
  $("outlineList").lang = state.locale;
  $("sermonMeta").replaceChildren(...[content.speaker, content.scripture, content.date].map(value => {
    const span = document.createElement("span");
    span.textContent = value;
    return span;
  }));
  $("sermonSummary").textContent = content.summary;
  $("moreSummary").textContent = content.summary;
  $("languageName").textContent = languageNames[state.locale].native;
  const weekSelect = $("weekSelect");
  weekSelect.replaceChildren(...state.catalog.pages.map(page => {
    const option = document.createElement("option");
    option.value = page.id;
    option.textContent = `${page.date} · ${page.catalogKind === "formal" ? "四层审核片段" : "Dev POC"}`;
    option.selected = page.id === state.page.id;
    return option;
  }));
  weekSelect.value = state.page.id;
  $("fieldControls").hidden = !state.audioVariant;
  renderTranscript();
  renderOutline();
  renderLanguageList();
  renderInterfaceCopy();
  const download = $("downloadAudio");
  download.hidden = !state.audioObjectURL;
  if (state.audioObjectURL) {
    download.href = state.audioObjectURL;
    download.download = `${state.page.id}-${state.locale}-${state.audioVariant.id}.mp3`;
  } else {
    download.removeAttribute("href");
  }
  syncPlayer();
  revealCurrentCaption();
}

function renderAudioVariantPicker() {
  const variants = availableAudioVariants();
  const picker = $("audioVariantPicker");
  picker.hidden = variants.length < 2;
  if (picker.hidden) return;
  const select = $("audioVariantSelect");
  select.replaceChildren(...variants.map(variant => {
    const option = document.createElement("option");
    option.value = variant.id;
    option.textContent = state.ui === "zh" ? variant.label : (variant.labelEn || variant.label);
    option.selected = variant.id === state.audioVariant?.id;
    return option;
  }));
  $("audioVariantDescription").textContent = state.ui === "zh"
    ? (state.audioVariant?.description || "")
    : (state.audioVariant?.descriptionEn || state.audioVariant?.description || "");
}

function renderInterfaceCopy() {
  const copy = interfaceCopy[state.ui];
  const extra = extraCopy[state.ui];
  const utility = utilityCopy[state.ui];
  document.documentElement.lang = interfaceLocales[state.ui].htmlLang;
  $("brandName").textContent = extra.brandName;
  $("brandSubtitle").textContent = extra.brandDetail;
  $("editionLabel").textContent = state.page?.catalogKind === "formal" ? formalCopy[state.ui].edition : extra.edition;
  $("weekLabel").textContent = extra.week;
  $("weekHint").textContent = state.catalog?.pages.length === 1 ? statusCopy[state.ui].oneWeek : extra.weekHint;
  $("weekSelect").title = $("weekHint").textContent;
  $("languageButton").setAttribute("aria-label", `${copy.languageCard}: ${languageNames[state.locale]?.native || ""}`);
  document.querySelector(".week-browser").setAttribute("aria-label", extra.week);
  document.querySelector(".brand").setAttribute("aria-label", utility.brandHome);
  document.querySelector(".sermon-banner").setAttribute("aria-label", utility.sermonInfo);
  $("moreOptions").setAttribute("aria-label", utility.moreOptions);
  $("resumeCard").setAttribute("aria-label", utility.resumeRegion);
  $("fieldControls").setAttribute("aria-label", extra.brandDetail);
  document.querySelector('.tabs').setAttribute("aria-label", extra.brandDetail);
  $("languageCardLabel").textContent = copy.languageCard;
  $("mockNoticeTitle").textContent = state.locale === "en" ? copy.sourceTitle : copy.mockTitle;
  $("mockNoticeBody").textContent = state.locale === "en" ? copy.sourceBody : copy.mockBody;
  [$("listenTab"), $("transcriptTab"), $("outlineTab")].forEach((node, index) => node.textContent = copy.tabs[index]);
  $("moreToggle").textContent = extra.more;
  $("nowHeading").textContent = copy.now;
  $("sourceToggle").textContent = extra.sourceToggle;
  $("sourceReferenceLabel").textContent = extra.sourceReference;
  $("transcriptHint").textContent = extra.transcriptHint;
  $("showTranscript").textContent = extra.showTranscript;
  $("captionNote").textContent = state.audioVariant ? extra.captionNote : textOnlyCaptionCopy[state.ui];
  $("transcriptHeading").textContent = copy.transcript;
  $("outlineHeading").textContent = copy.outline;
  $("outlineBadge").textContent = state.page?.catalogKind === "formal" ? "DEV · REVIEWED" : "DEV POC";
  $("playerNote").textContent = !state.audioVariant ? textOnlyCopy[state.ui]
    : state.locale === "en" ? copy.sourcePlayerNote : copy.playerNote;
  $("releaseTitle").textContent = copy.release;
  $("contentStatusLabel").textContent = copy.text;
  $("audioStatusLabel").textContent = copy.audio;
  const statuses = statusCopy[state.ui];
  const screening = state.audioVariant?.machineScreeningStatus || state.release?.machineScreening?.status;
  $("contentStatus").textContent = state.locale === "en" ? statuses.sourceText
    : state.release?.contentStatus === "machine_review_pass_human_review_pending" ? statuses.passText : statuses.textPending;
  $("audioStatus").textContent = state.release?.audioStatus === "unavailable" ? textOnlyCopy[state.ui]
    : state.locale === "en" ? statuses.sourceAudio
    : screening === "pass" ? statuses.passAudio
    : screening === "requires_review" ? statuses.review
    : ["pending_for_default_audio_variant", "pending_for_this_audio_variant"].includes(screening) ? statuses.pending : statuses.unverified;
  if (state.page?.catalogKind === "formal") {
    const formal = formalCopy[state.ui];
    $("mockNoticeTitle").textContent = formal.title;
    $("mockNoticeBody").textContent = formal.body;
    $("playerNote").textContent = formal.player;
    $("captionNote").textContent = formal.caption;
    $("contentStatus").textContent = formal.content;
    $("audioStatus").textContent = formal.audio;
    $("httpStatus").textContent = state.release?.status === "published_http_verified"
      ? formal.httpPass : formal.httpPending;
    $("languageDialogFoot").textContent = formal.foot;
    $("sourceToggle").hidden = true;
    $("sourceBlock").hidden = true;
    $("alignmentNotice").hidden = true;
    $("alignmentDetail").hidden = true;
  } else {
    $("httpStatus").textContent = "Firebase Dev POC";
    $("sourceToggle").hidden = false;
    $("alignmentNotice").hidden = false;
    $("alignmentDetail").hidden = false;
  }
  $("languageDialogTitle").textContent = copy.dialogTitle;
  $("languageDialogHint").textContent = copy.dialogHint;
  if (state.page?.catalogKind !== "formal") $("languageDialogFoot").textContent = copy.dialogFoot;
  $("closeLanguageDialog").setAttribute("aria-label", extra.close);
  $("footerBrand").textContent = extra.footerBrand;
  $("footerMotto").textContent = extra.footerMotto;
  $("footerText").textContent = copy.footer;
  $("retryLoad").textContent = utility.retry;
  $("resumePosition").textContent = utility.resume;
  $("restartPosition").textContent = utility.restart;
  $("downloadAudio").textContent = utility.download;
  if (!$("loadError").hidden) $("loadErrorMessage").textContent = utility.error;
  $("interfaceLanguageCode").textContent = interfaceLocales[state.ui].code;
  $("interfaceLanguage").setAttribute("aria-label", extra.interfaceLabel);
  $("interfaceLanguageMenu").setAttribute("aria-label", extra.interfaceLabel);
  $("themeLabel").textContent = document.documentElement.dataset.theme === "dark" ? statuses.themeLight : statuses.themeDark;
  $("themeToggle").setAttribute("aria-label", $("themeLabel").textContent);
  $("audioVariantLabel").textContent = copy.audioVariant;
  $("backHint").textContent = extra.backHint;
  $("backLabel").textContent = extra.back;
  $("forwardHint").textContent = extra.forwardHint;
  $("forwardLabel").textContent = extra.forward;
  $("transcriptCurrent").textContent = extra.current;
  $("precisionOpen").textContent = extra.precision;
  $("alignmentNotice").textContent = extra.alignment;
  $("alignmentDetail").textContent = extra.alignment;
  $("progressTrack").setAttribute("aria-label", extra.progress);
  document.querySelector('[data-skip="-5"]').setAttribute("aria-label", extra.back);
  document.querySelector('[data-skip="5"]').setAttribute("aria-label", extra.forward);
  $("playIcon").textContent = audio.paused ? "▶" : "❚❚";
  $("playLabel").textContent = audio.paused ? extra.play : extra.pause;
  $("playButton").setAttribute("aria-label", $("playLabel").textContent);
  $("playerStatus").textContent = audio.paused ? (audio.readyState ? extra.paused : extra.loading) : extra.playing;
  renderInterfaceLanguageMenu();
  renderAudioVariantPicker();
  renderResume();
}

function renderInterfaceLanguageMenu() {
  $("interfaceLanguageMenu").replaceChildren(...Object.entries(interfaceLocales).map(([locale, info]) => {
    const button = document.createElement("button");
    button.type = "button";
    button.setAttribute("role", "menuitemradio");
    button.setAttribute("aria-checked", String(locale === state.ui));
    button.lang = info.htmlLang;
    const code = document.createElement("span"); code.className = "locale-code"; code.textContent = info.code;
    const name = document.createElement("span"); name.textContent = info.native;
    const check = document.createElement("span"); check.className = "locale-check"; check.textContent = locale === state.ui ? "✓" : "";
    button.append(code, name, check);
    button.addEventListener("click", () => {
      state.ui = locale;
      localStorage.setItem("tongxing-dev-ui", locale);
      $("interfaceLanguageMenu").hidden = true;
      $("interfaceLanguage").setAttribute("aria-expanded", "false");
      if (state.content) render(); else renderInterfaceCopy();
      $("interfaceLanguage").focus();
    });
    return button;
  }));
}

function renderLanguageList() {
  $("languageList").replaceChildren(...Object.keys(state.page.targets).map(locale => {
    const info = languageNames[locale];
    const button = document.createElement("button");
    button.type = "button";
    button.className = `language-option${locale === state.locale ? " is-selected" : ""}`;
    const target = state.page.targets[locale];
    const extra = extraCopy[state.ui];
    const status = state.page.catalogKind === "formal" ? formalCopy[state.ui].content
      : locale === "en" ? extra.sourceStatus : target.machineScreening === "requires_review" ? extra.needsReview : extra.screened;
    const media = state.page.catalogKind === "formal" ? formalCopy[state.ui].language
      : target.audioStatus === "unavailable" ? textOnlyCopy[state.ui]
      : locale === "en" ? extra.sourceMedia : extra.targetMedia;
    const displayName = new Intl.DisplayNames([interfaceLocales[state.ui].htmlLang], { type: "language" }).of(locale);
    button.innerHTML = `<span class="language-option-name"><span class="language-code">${info.code}</span><span><strong lang="${locale}">${info.native}</strong><small>${escapeHTML(displayName)}</small></span></span><span class="language-option-caps">${media}<br>${status}</span>`;
    button.addEventListener("click", () => selectLocale(locale, { manual: true }).catch(showError));
    return button;
  }));
}

function renderTranscript() {
  $("transcriptList").replaceChildren(...activeCues().map((cue, index) => {
    const row = document.createElement("div");
    const button = document.createElement("button");
    const copy = document.createElement("div");
    button.type = "button";
    row.className = `transcript-item${currentCueIndex() === index ? " is-current" : ""}`;
    button.className = "transcript-time";
    button.textContent = formatTime(cue.start);
    button.setAttribute("aria-label", `${utilityCopy[state.ui].seekTo} ${formatTime(cue.start)}`);
    copy.className = "transcript-copy";
    const source = state.locale === "en" || !cue.source || cue.source === cue.text ? "" : `<span lang="en">${escapeHTML(cue.source)}</span>`;
    copy.innerHTML = `<strong lang="${state.locale}">${escapeHTML(cue.text)}</strong>${source}`;
    button.disabled = !state.audioVariant;
    button.addEventListener("click", () => seekTo(cue.start));
    row.append(button, copy);
    return row;
  }));
}

function renderOutline() {
  $("outlineList").replaceChildren(...state.content.outline.map(item => {
    const section = document.createElement("section");
    section.className = "outline-item";
    const title = document.createElement("h3"); title.textContent = item.title;
    const body = document.createElement("p"); body.textContent = item.body;
    section.append(title, body);
    return section;
  }));
}

function currentCueIndex() {
  if (!state.content) return 0;
  const cues = activeCues();
  const active = cues.findIndex(cue => audio.currentTime >= cue.start && audio.currentTime < cue.end);
  if (active >= 0) return active;
  let latest = 0;
  cues.forEach((cue, index) => { if (audio.currentTime >= cue.start) latest = index; });
  return latest;
}

function currentCue() { return activeCues()[currentCueIndex()]; }

function revealCurrentCaption() {
  if (!state.content || !state.audioVariant || state.activeTab !== "listen" || state.captionRevealScheduled || !$("moreOptions").hidden) return;
  state.captionRevealScheduled = true;
  requestAnimationFrame(() => {
    state.captionRevealScheduled = false;
    if (state.activeTab !== "listen" || !$("moreOptions").hidden) return;
    const caption = $("currentCaption").getBoundingClientRect();
    const dock = $("fieldControls").getBoundingClientRect();
    const overlap = caption.bottom - dock.top + 16;
    if (overlap > 0) window.scrollBy({ top: overlap, behavior: "auto" });
  });
}

function syncPlayer() {
  if (!state.content) return;
  const cue = currentCue();
  const index = currentCueIndex();
  if (index !== state.lastCueIndex) {
    state.lastCueIndex = index;
    revealCurrentCaption();
  }
  $("currentCaption").textContent = cue?.text || "";
  $("nextCaption").textContent = activeCues()[index + 1]?.text || "";
  $("sourceCaption").textContent = state.locale === "en" ? "" : cue?.source || "";
  $("sourceBlock").hidden = state.page?.catalogKind === "formal" || state.locale === "en" || !state.showSource || !cue?.source;
  $("sourceToggle").hidden = state.page?.catalogKind === "formal" || state.locale === "en";
  $("sourceToggle").setAttribute("aria-pressed", String(state.showSource));
  $("cueCounter").textContent = `${currentCueIndex() + 1} / ${activeCues().length}`;
  const duration = effectiveDuration();
  const percent = Math.min(100, Math.max(0, audio.currentTime / duration * 100));
  $("progressFill").style.width = `${percent}%`;
  $("progressTrack").setAttribute("aria-valuenow", String(Math.round(percent)));
  $("elapsed").textContent = formatTime(audio.currentTime);
  $("duration").textContent = formatTime(duration);
  const extra = extraCopy[state.ui];
  $("playIcon").textContent = audio.paused ? "▶" : "❚❚";
  $("playLabel").textContent = audio.paused ? extra.play : extra.pause;
  $("playButton").setAttribute("aria-label", $("playLabel").textContent);
  $("playButton").disabled = !state.audioVariant;
  $("playerStatus").textContent = state.audioVariant
    ? (audio.paused ? (audio.readyState ? extra.paused : extra.loading) : extra.playing)
    : textOnlyCopy[state.ui];
  document.querySelectorAll(".transcript-item").forEach((item, index) => item.classList.toggle("is-current", index === currentCueIndex()));
}

function switchTab(name) {
  state.activeTab = name;
  document.querySelectorAll("[data-tab]").forEach(button => {
    const active = button.dataset.tab === name;
    button.classList.toggle("is-active", active);
    if (button.getAttribute("role") === "tab") {
      button.setAttribute("aria-selected", String(active));
      button.tabIndex = active ? 0 : -1;
    }
    else button.setAttribute("aria-pressed", String(active));
  });
  document.querySelectorAll(".panel").forEach(panel => {
    const active = panel.id === `panel-${name}`;
    panel.hidden = !active;
    panel.classList.toggle("is-active", active);
  });
  if (name === "listen") revealCurrentCaption();
}

function formatTime(value) {
  const seconds = Math.max(0, Math.floor(value || 0));
  return `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
}

function escapeHTML(value) {
  const span = document.createElement("span");
  span.textContent = value;
  return span.innerHTML;
}

function showError(error) {
  if (error?.name === "AbortError") return;
  console.error(error);
  $("loadErrorMessage").textContent = utilityCopy[state.ui].error;
  $("loadError").hidden = false;
  if (!state.content) $("sermonTitle").textContent = interfaceCopy[state.ui].loadError;
}

function bindEvents() {
  $("weekSelect").addEventListener("change", event => openPage(event.target.value).catch(showError));
  $("languageButton").addEventListener("click", () => $("languageDialog").showModal());
  $("closeLanguageDialog").addEventListener("click", () => $("languageDialog").close());
  $("languageDialog").addEventListener("click", event => { if (event.target === $("languageDialog")) $("languageDialog").close(); });
  $("audioVariantSelect").addEventListener("change", event => {
    const variant = availableAudioVariants().find(item => item.id === event.target.value);
    void switchAudioVariant(variant);
  });
  document.querySelectorAll("[data-tab]").forEach(button => button.addEventListener("click", () => switchTab(button.dataset.tab)));
  const tabs = [...document.querySelectorAll('[role="tab"]')];
  tabs.forEach((tab, index) => tab.addEventListener("keydown", event => {
    const next = event.key === "ArrowRight" ? (index + 1) % tabs.length
      : event.key === "ArrowLeft" ? (index + tabs.length - 1) % tabs.length
      : event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1 : -1;
    if (next >= 0) {
      event.preventDefault();
      switchTab(tabs[next].dataset.tab);
      tabs[next].focus();
    }
  }));
  $("showTranscript").addEventListener("click", () => switchTab("transcript"));
  $("sourceToggle").addEventListener("click", () => { state.showSource = !state.showSource; syncPlayer(); });
  $("moreToggle").addEventListener("click", () => {
    $("moreOptions").hidden = !$("moreOptions").hidden;
    $("moreToggle").setAttribute("aria-expanded", String(!$("moreOptions").hidden));
  });
  $("transcriptCurrent").addEventListener("click", () => { switchTab("listen"); $("currentCaption").scrollIntoView({ block: "center" }); });
  $("resumePosition").addEventListener("click", () => {
    if (state.pendingResume) seekTo(state.pendingResume.positionSeconds);
  });
  $("restartPosition").addEventListener("click", () => {
    playbackMemory.clear(playbackSource());
    seekTo(0);
  });
  $("retryLoad").addEventListener("click", () => {
    if (state.pendingVariantId) {
      void switchAudioVariant(availableAudioVariants().find(item => item.id === state.pendingVariantId));
    } else if (state.pendingPageId) openPage(state.pendingPageId,
      { requestedLocale: state.pendingLocale }).catch(showError);
    else if (state.page) selectLocale(state.locale || state.page.defaultTargetLocale).catch(showError);
    else loadInitialCatalog().catch(showError);
  });
  $("precisionOpen").addEventListener("click", () => $("progressTrack").focus());
  $("playButton").addEventListener("click", () => {
    if (!audio.paused) { audio.pause(); return; }
    if (state.pendingResume) seekTo(state.pendingResume.positionSeconds);
    audio.play().catch(showError);
  });
  document.querySelectorAll("[data-skip]").forEach(button => button.addEventListener("click", () => {
      seekTo(audio.currentTime + Number(button.dataset.skip));
  }));
  $("progressTrack").addEventListener("click", event => {
    const rect = event.currentTarget.getBoundingClientRect();
    seekTo(effectiveDuration() * (event.clientX - rect.left) / rect.width);
  });
  $("progressTrack").addEventListener("keydown", event => {
    if (["ArrowLeft", "ArrowRight"].includes(event.key)) {
      event.preventDefault();
      seekTo(audio.currentTime + (event.key === "ArrowRight" ? 1 : -1));
    }
  });
  audio.addEventListener("timeupdate", () => { syncPlayer(); saveProgress(); });
  audio.addEventListener("loadedmetadata", () => {
    state.pendingResume = playbackMemory.read(playbackSource(), audio.duration);
    renderResume();
    syncPlayer();
  });
  audio.addEventListener("play", syncPlayer);
  audio.addEventListener("pause", () => { syncPlayer(); saveProgress(true); });
  audio.addEventListener("ended", syncPlayer);
  audio.addEventListener("error", () => { if (audio.error) showError(new Error("Dev audio failed")); });
  window.addEventListener("pagehide", () => saveProgress(true));
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") saveProgress(true);
  });
  $("interfaceLanguage").addEventListener("click", () => {
    const menu = $("interfaceLanguageMenu");
    menu.hidden = !menu.hidden;
    $("interfaceLanguage").setAttribute("aria-expanded", String(!menu.hidden));
    if (!menu.hidden) menu.querySelector('[aria-checked="true"]').focus();
  });
  document.addEventListener("click", event => {
    if (!event.target.closest(".interface-language-control")) {
      $("interfaceLanguageMenu").hidden = true;
      $("interfaceLanguage").setAttribute("aria-expanded", "false");
    }
  });
  $("interfaceLanguageMenu").addEventListener("keydown", event => {
    if (event.key === "Escape") {
      event.preventDefault();
      $("interfaceLanguageMenu").hidden = true;
      $("interfaceLanguage").setAttribute("aria-expanded", "false");
      $("interfaceLanguage").focus();
    } else if (["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) {
      event.preventDefault();
      const buttons = [...$("interfaceLanguageMenu").querySelectorAll("button")];
      const current = buttons.indexOf(document.activeElement);
      const next = event.key === "Home" ? 0 : event.key === "End" ? buttons.length - 1
        : (current + (event.key === "ArrowDown" ? 1 : -1) + buttons.length) % buttons.length;
      buttons[next].focus();
    }
  });
  $("themeToggle").addEventListener("click", () => {
    const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    localStorage.setItem("tongxing-dev-theme", next);
    renderInterfaceCopy();
  });
  window.addEventListener("popstate", () => {
    const route = routeSelection();
    openPage(route.pageId || state.catalog.defaultPageId,
      { navigate: false, requestedLocale: route.locale }).catch(showError);
  });
}

async function openPage(pageId, { navigate = true, requestedLocale = null } = {}) {
  const page = state.catalog.pages.find(item => item.id === pageId);
  if (!page) throw new Error(`Unknown Dev page: ${pageId}`);
  const saved = localStorage.getItem(`tongxing-dev-content-override-${page.id}`);
  const preferred = state.ui === "zh" ? "zh-Hans" : state.ui;
  const locale = page.targets[requestedLocale] ? requestedLocale
    : page.targets[saved] ? saved
    : page.targets[preferred] ? preferred : page.defaultTargetLocale;
  try {
    await selectLocale(locale, { navigate, page });
  } catch (error) {
    if (state.page) $("weekSelect").value = state.page.id;
    throw error;
  }
}

async function loadInitialCatalog() {
  const demo = validateDemoCatalog(await loadJSON("/multilingual.json"));
  const formal = await loadOptionalFormalCatalog(fetch, demo.pages.map(page => page.id));
  const pages = [
    ...(formal?.pages || []).map(page => ({ ...page, catalogKind: "formal" })),
    ...demo.pages.map(page => ({ ...page, catalogKind: "poc" }))
  ];
  state.catalog = { pages, defaultPageId: formal?.defaultPageId || demo.defaultPageId };
  const route = routeSelection();
  await openPage(route.pageId || state.catalog.defaultPageId,
    { navigate: location.pathname !== "/", requestedLocale: route.locale });
}

async function init() {
  document.documentElement.dataset.theme = localStorage.getItem("tongxing-dev-theme") === "light" ? "light" : "dark";
  bindEvents();
  switchTab("listen");
  renderInterfaceCopy();
  try { await loadInitialCatalog(); }
  catch (error) { showError(error); }
}

init();
