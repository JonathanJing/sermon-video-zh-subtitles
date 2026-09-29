// Dev-only copy. The shared Production reader owns the language setting.
const copy = {
  "zh-Hans": ["DEV 测试站 · 正式周次与模拟演练同处 App 目录；演练片段不代表正式审核或发布。", "六句实验页"],
  en: ["Dev test site · Formal weeks and simulations appear in the App catalog; a simulation is not a formal review or release.", "Six-unit experiment"],
  ko: ["DEV 테스트 사이트 · 정식 주차와 모의 연습은 앱 목록에 함께 표시됩니다. 모의 연습은 정식 검토나 게시가 아닙니다.", "여섯 문장 실험"],
  es: ["Sitio de pruebas DEV · Las semanas formales y las simulaciones aparecen en el catálogo de la app; una simulación no es una revisión ni publicación formal.", "Prueba de seis unidades"],
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
