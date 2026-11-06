// Spike v2: equivale a trocar static/ui-common.js:214 por
//   const salvo = localStorage.getItem(SIDEBAR_COLLAPSED_STORAGE);
//   const collapsed = salvo === null ? window.innerWidth < 1600 : salvo === "1";
// Sem preferencia salva e com janela < 1600px, o menu comeca recolhido.
(() => {
  let salvo = null;
  try { salvo = localStorage.getItem("analise_certidigital_sidebar_collapsed"); } catch (e) {}
  if (salvo === null && innerWidth > 768 && innerWidth < 1600) document.body.classList.add("sidebar-collapsed");
})();
