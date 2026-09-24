// Dev-only copy. The shared Production reader owns the language setting.
const copy = {
  "zh-Hans": ["DEV 测试站 · 此页用于核验已审核的多语言内容；公开发布请以正式站点为准。", "六句实验页"],
  en: ["Dev test site · Reviewed multilingual content is shown here for verification. Check the public site for the released version.", "Six-unit experiment"],
  ko: ["DEV 테스트 사이트 · 검토된 다국어 콘텐츠를 확인하는 페이지입니다. 공식 게시 여부는 공식 사이트에서 확인하세요.", "여섯 문장 실험"],
  es: ["Sitio de pruebas DEV · Aquí se verifica contenido multilingüe revisado. Consulta el sitio público para la versión publicada.", "Prueba de seis unidades"],
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
