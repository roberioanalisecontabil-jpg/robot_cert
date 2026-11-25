/* Wiki do CertGuard (25/11/2026): índice lateral, imagem em tela cheia e
   botão de copiar nos blocos de código. Sem JS a página continua legível:
   o índice some, a imagem abre em outra aba pelo link e o código se copia
   à mão. */
(function () {
  "use strict";
  const artigo = document.querySelector(".wiki-artigo");
  if (!artigo) return;

  // ── Índice "Nesta página": h2 e h3 do artigo ─────────────────────────
  const lista = document.getElementById("wiki-toc-lista");
  const toc = document.querySelector(".wiki-toc");
  const titulos = Array.from(artigo.querySelectorAll("h2, h3"));
  const usados = new Set();
  function slug(texto) {
    const base = texto.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase()
      .replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "secao";
    let s = base, n = 2;
    while (usados.has(s) || document.getElementById(s)) s = base + "-" + n++;
    usados.add(s);
    return s;
  }
  const links = new Map();
  titulos.forEach((t) => {
    if (!t.id) t.id = slug(t.textContent.trim());
    else usados.add(t.id);
    if (!lista) return;
    const li = document.createElement("li");
    li.className = "wiki-toc__item wiki-toc__item--" + t.tagName.toLowerCase();
    const a = document.createElement("a");
    a.href = "#" + t.id;
    a.textContent = t.textContent.trim();
    li.appendChild(a);
    lista.appendChild(li);
    links.set(t, a);
  });
  if (toc && titulos.length >= 2) toc.hidden = false;

  // Marca no índice o título que está no topo da leitura.
  if (links.size && "IntersectionObserver" in window) {
    const visiveis = new Set();
    const io = new IntersectionObserver((entradas) => {
      entradas.forEach((e) => (e.isIntersecting ? visiveis.add(e.target) : visiveis.delete(e.target)));
      const atual = titulos.find((t) => visiveis.has(t));
      if (!atual) return;
      links.forEach((a, t) => {
        if (t === atual) a.setAttribute("aria-current", "location");
        else a.removeAttribute("aria-current");
      });
    }, { rootMargin: "0px 0px -70% 0px" });
    titulos.forEach((t) => io.observe(t));
  }

  // ── Imagem em tela cheia ────────────────────────────────────────────
  const zoom = document.getElementById("wiki-zoom");
  const zoomImg = zoom && zoom.querySelector("img");
  if (zoom && zoomImg && typeof zoom.showModal === "function") {
    artigo.addEventListener("click", (ev) => {
      const link = ev.target.closest(".wiki-print a");
      if (!link || ev.ctrlKey || ev.metaKey || ev.shiftKey) return;
      ev.preventDefault();
      const img = link.querySelector("img");
      zoomImg.src = link.href;
      zoomImg.alt = img ? img.alt : "";
      zoom.showModal();
    });
    // Qualquer clique fecha: fora da imagem (no fundo) ou nela.
    zoom.addEventListener("click", () => zoom.close());
    zoom.addEventListener("close", () => { zoomImg.removeAttribute("src"); });
  }

  // ── Copiar código ───────────────────────────────────────────────────
  const ICONE_COPIAR = '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>';
  const ICONE_OK = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 6 9 17l-5-5"/></svg>';
  artigo.querySelectorAll("pre").forEach((pre) => {
    const caixa = document.createElement("div");
    caixa.className = "wiki-codigo";
    pre.parentNode.insertBefore(caixa, pre);
    caixa.appendChild(pre);
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "wiki-copiar";
    btn.innerHTML = ICONE_COPIAR + '<span class="wiki-copiar__texto">Copiar</span>';
    btn.setAttribute("aria-label", "Copiar o código");
    caixa.appendChild(btn);
    let volta = 0;
    btn.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(pre.innerText.replace(/\n$/, ""));
      } catch (_e) {
        // Sem a API (contexto sem HTTPS): seleciona para o Ctrl+C.
        const r = document.createRange();
        r.selectNodeContents(pre);
        const s = getSelection();
        s.removeAllRanges();
        s.addRange(r);
        return;
      }
      btn.innerHTML = ICONE_OK + '<span class="wiki-copiar__texto">Copiado</span>';
      btn.classList.add("is-ok");
      clearTimeout(volta);
      volta = setTimeout(() => {
        btn.innerHTML = ICONE_COPIAR + '<span class="wiki-copiar__texto">Copiar</span>';
        btn.classList.remove("is-ok");
      }, 1600);
    });
  });
})();
