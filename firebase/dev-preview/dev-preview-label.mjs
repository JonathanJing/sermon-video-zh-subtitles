// Dev-only copy. The shared Production reader owns the language setting.
const copy = {
  "zh-Hans": ["DEV 预演 · 9 月 20 日三语审核样片。本周新整篇尚未发布。", "六句实验页"],
  en: ["DEV preview · Reviewed September 20 trilingual clip. This week's full sermon is not published yet.", "Six-unit experiment"],
  ko: ["DEV 미리보기 · 9월 20일 검토된 3개 언어 설교 부분입니다. 이번 주 전체 설교는 아직 게시되지 않았습니다.", "여섯 문장 실험"],
  es: ["Vista previa DEV · Fragmento trilingüe revisado del 20 de septiembre. El sermón completo de esta semana aún no está publicado.", "Prueba de seis unidades"],
};

function render() {
  const [message, link] = copy[document.documentElement.lang] || copy.en;
  document.getElementById("devPreviewMessage").textContent = message;
  document.getElementById("devPocLink").textContent = link;
}

new MutationObserver(render).observe(document.documentElement, {
  attributes: true, attributeFilter: ["lang"]
});
render();
