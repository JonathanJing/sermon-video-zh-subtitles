// Isolated Dev label for the shared v3 reader. Interface and content languages
// remain independent; this label follows the interface picker.
const copy = {
  zh: ["DEV 测试站 · 此页用于核验已审核的多语言内容；公开发布请以正式站点为准。", "六句实验页", "每周演练页"],
  en: ["Dev test site · Reviewed multilingual content is shown here for verification. Check the public site for the released version.", "Six-unit experiment", "Weekly dry run"],
  ko: ["DEV 테스트 사이트 · 검토된 다국어 콘텐츠를 확인하는 페이지입니다. 공식 게시 여부는 공식 사이트에서 확인하세요.", "여섯 문장 실험", "주간 사전 점검"],
  es: ["Sitio de pruebas DEV · Aquí se verifica contenido multilingüe revisado. Consulta el sitio público para la versión publicada.", "Prueba de seis unidades", "Ensayo semanal"],
};

function render() {
  const locale = document.getElementById("interface-language")?.value || "zh";
  const [message, link, dryRun] = copy[locale] || copy.zh;
  document.getElementById("devPreviewMessage").textContent = message;
  document.getElementById("devPocLink").textContent = link;
  const dryRunLink = document.getElementById("devDryRunLink");
  if (dryRunLink) dryRunLink.textContent = dryRun;
}

document.getElementById("interface-language")?.addEventListener("change", render);
document.getElementById("language-toggle")?.addEventListener("click", () => queueMicrotask(render));
render();

if (location.pathname.startsWith("/dry-run/")) {
  const edition = document.getElementById("edition-label");
  const title = document.querySelector("title");
  const markPreview = () => {
    if (edition && edition.textContent !== "DRY RUN · 测试页") edition.textContent = "DRY RUN · 测试页";
    if (title && !title.textContent.startsWith("DRY RUN · ")) title.textContent = `DRY RUN · ${title.textContent}`;
  };
  if (edition) new MutationObserver(markPreview).observe(edition, { childList: true, characterData: true, subtree: true });
  if (title) new MutationObserver(markPreview).observe(title, { childList: true, characterData: true, subtree: true });
  markPreview();
}
