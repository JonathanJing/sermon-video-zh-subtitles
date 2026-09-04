export function createCaptionState({ segmentId = "", en = "", zh = "", phase = "idle" } = {}) {
  return {
    previousFinal: null,
    active: { segmentId, en, zh, phase },
  };
}

function completedCaption(active) {
  if (active?.phase !== "final" || !active.en || !active.zh) return null;
  return {
    segmentId: active.segmentId,
    en: active.en,
    zh: active.zh,
  };
}

export function applyCaptionEvent(state, event) {
  const current = state || createCaptionState();
  const active = current.active || createCaptionState().active;

  if (event.type === "stream.ready") {
    return createCaptionState({
      en: "Listening for English speech…",
      zh: "请开始讲话。",
      phase: "listening",
    });
  }

  if (event.type === "asr.final") {
    return {
      previousFinal: completedCaption(active) || current.previousFinal,
      active: {
        segmentId: event.segmentId || "",
        en: event.sourceTextEn || "",
        zh: "",
        phase: "requesting",
      },
    };
  }

  if (["translation.partial", "translation.final", "translation.failed", "translation.skipped"].includes(event.type)) {
    if (event.segmentId && active.segmentId && event.segmentId !== active.segmentId) return current;
    const fallback = event.type === "translation.failed"
      ? "翻译暂时不可用，请查看英文原文。"
      : event.type === "translation.skipped"
        ? "翻译积压，暂时显示英文原文。"
        : event.type === "translation.final"
          ? "翻译结果为空。"
          : active.zh;
    return {
      ...current,
      active: {
        segmentId: event.segmentId || active.segmentId,
        en: event.sourceTextEn ?? active.en,
        zh: event.targetTextZh || fallback,
        phase: event.type === "translation.partial"
          ? "streaming"
          : event.type === "translation.final"
            ? "final"
            : "error",
      },
    };
  }

  return current;
}
