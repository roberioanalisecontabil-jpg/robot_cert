/**
 * Funções partilhadas entre o painel (/) e a configuração (/configuracao).
 * O token JWT fica no localStorage do browser.
 */
(function() {
  const currentTheme = localStorage.getItem("cert_robot_theme");
  if (currentTheme) {
    document.documentElement.setAttribute("data-theme", currentTheme);
  }
})();

const KEY_STORAGE = "cert_robot_api_key"; // Agora armazena o Token JWT
const FONT_STORAGE = "cert_robot_data_fonte";
const SIDEBAR_COLLAPSED_STORAGE = "analise_certidigital_sidebar_collapsed";

function getDataFonte() {
  return localStorage.getItem(FONT_STORAGE) || "auto";
}

function setDataFonte(v) {
  if (v) localStorage.setItem(FONT_STORAGE, v);
  else localStorage.removeItem(FONT_STORAGE);
}

function getToken() {
  return localStorage.getItem(KEY_STORAGE) || "";
}

function getHeaders(json = false) {
  const h = {};
  if (json) h["Content-Type"] = "application/json";
  const token = getToken();
  if (token) {
    h["Authorization"] = `Bearer ${token}`;
  }
  return h;
}

function logout() {
  localStorage.removeItem(KEY_STORAGE);
  localStorage.removeItem('user_role');
  localStorage.removeItem('user_email');
  window.location.href = '/login';
}

document.addEventListener('click', function(e) {
  const logoutBtn = e.target.closest('[data-action="logout"]');
  if (logoutBtn) {
    e.preventDefault();
    logout();
  }
});

async function mensagemCorpoErro(r) {
  const raw = await r.text();
  try {
    const j = JSON.parse(raw);
    if (j.detail !== undefined) {
      if (Array.isArray(j.detail)) {
        return j.detail.map((x) => (x.msg != null ? x.msg : String(x))).join("; ");
      }
      return String(j.detail);
    }
    return raw.slice(0, 500);
  } catch (_e) {
    return raw.slice(0, 500);
  }
}

async function health() {
  const r = await fetch("/api/health");
  return r.json();
}

function applySidebarState() {
  const collapsed = localStorage.getItem(SIDEBAR_COLLAPSED_STORAGE) === "1";
  document.body.classList.toggle("sidebar-collapsed", collapsed);
}

function toggleSidebar() {
  const collapsed = document.body.classList.toggle("sidebar-collapsed");
  localStorage.setItem(SIDEBAR_COLLAPSED_STORAGE, collapsed ? "1" : "0");
}

function initSidebarToggle() {
  const sidebar = document.querySelector(".sidebar");
  const main = document.querySelector(".main-content");
  if (!sidebar || !main) return;
  if (document.getElementById("btn-sidebar-toggle")) return;

  applySidebarState();

  const btn = document.createElement("button");
  btn.id = "btn-sidebar-toggle";
  btn.type = "button";
  btn.className = "sidebar-toggle-btn";
  btn.title = "Recolher/expandir menu";
  btn.setAttribute("aria-label", "Recolher/expandir menu lateral");
  btn.innerHTML = "&#9776;";
  btn.addEventListener("click", toggleSidebar);
  main.prepend(btn);
}

function ensureGlobalLoadingOverlay() {
  let overlay = document.getElementById("global-loading-overlay");
  if (overlay) return overlay;
  overlay = document.createElement("div");
  overlay.id = "global-loading-overlay";
  overlay.className = "global-loading-overlay";
  overlay.innerHTML = `
    <div class="global-loading-card" role="status" aria-live="polite">
      <div class="global-loading-spinner" aria-hidden="true"></div>
      <div class="global-loading-text" id="global-loading-text">Carregando...</div>
    </div>
  `;
  document.body.appendChild(overlay);
  return overlay;
}

function setGlobalLoading(show, text = "Carregando...") {
  const overlay = ensureGlobalLoadingOverlay();
  const textEl = document.getElementById("global-loading-text");
  if (textEl) textEl.textContent = text;
  overlay.classList.toggle("is-visible", !!show);
}

/**
 * Loading inline – cobre apenas o container indicado (ex.: .table-container).
 * O container recebe position:relative para que o overlay absoluto fique sobre ele.
 * @param {string|HTMLElement} container  id ou elemento do container
 * @param {boolean} show
 * @param {string} [text]
 */
function setTableLoading(container, show, text = "Carregando...") {
  const el = typeof container === "string" ? document.getElementById(container) : container;
  if (!el) return;

  // Garante que o container seja "anchor" para o overlay absoluto
  if (!el.classList.contains("table-loading-anchor")) {
    el.classList.add("table-loading-anchor");
  }

  let overlay = el.querySelector(".table-loading-overlay");
  if (!overlay) {
    overlay = document.createElement("div");
    overlay.className = "table-loading-overlay";
    overlay.innerHTML = `
      <div class="global-loading-card" role="status" aria-live="polite">
        <div class="global-loading-spinner" aria-hidden="true"></div>
        <div class="global-loading-text">Carregando...</div>
      </div>
    `;
    el.appendChild(overlay);
  }

  const textEl = overlay.querySelector(".global-loading-text");
  if (textEl) textEl.textContent = text;
  overlay.classList.toggle("is-visible", !!show);
}

/** Lista de página (janela de até `maxBotões`) igual ao modelo Histórico/Dashboard/Vencidos. */
function cgWindowPaginas(totalPaginas, paginaAtual, maxBotões) {
  const mb = typeof maxBotões === "number" ? maxBotões : 5;
  const total = Math.max(1, Number(totalPaginas) || 1);
  let atual = Number(paginaAtual) || 1;
  atual = Math.min(Math.max(1, atual), total);
  if (total <= mb) {
    const a = [];
    for (let i = 1; i <= total; i++) a.push(i);
    return a;
  }
  let start = atual - Math.floor(mb / 2);
  start = Math.max(1, Math.min(start, total - mb + 1));
  const out = [];
  for (let j = 0; j < mb; j++) out.push(start + j);
  return out;
}

function _cgResolveEl(sel) {
  return typeof sel === "string" ? document.getElementById(sel) : sel;
}

/** Esconde barra cg-page-nav (sem números, ex.: sem dados). */
function cgPageNavHide(bar, ul, metaOptional) {
  const b = _cgResolveEl(bar);
  const u = _cgResolveEl(ul);
  const m = metaOptional != null ? _cgResolveEl(metaOptional) : null;
  if (b) b.classList.remove("is-visible");
  if (u) u.querySelectorAll("li[data-cg-page-num]").forEach((node) => node.remove());
  if (m) m.textContent = "";
}

/**
 * Atualiza navegação .cg-page-nav (texto meta, botões numerados, estado Anterior/Seguinte).
 * Manténha handlers em btn prev/next definidos pela página (só atualiza disabled).
 *
 * opts.pg — { pagina, total_paginas, total_itens }; se null/`total_paginas` omitido → esconde.
 */
function cgPageNavRefresh(opts) {
  const bar = _cgResolveEl(opts.bar);
  const metaEl = _cgResolveEl(opts.meta);
  const ul = _cgResolveEl(opts.ul);
  const liNext = _cgResolveEl(opts.liNext);
  const btnPrev = _cgResolveEl(opts.prev);
  const btnNext = _cgResolveEl(opts.next);
  if (!bar || !metaEl || !ul || !liNext || !btnPrev || !btnNext) return;

  const pgRaw = opts.pg;
  if (!pgRaw || pgRaw.total_paginas == null) {
    bar.classList.remove("is-visible");
    ul.querySelectorAll("li[data-cg-page-num]").forEach((n) => n.remove());
    metaEl.textContent = "";
    return;
  }

  let totalPaginas = Math.max(1, Number(pgRaw.total_paginas) || 1);
  let pagina = Number(pgRaw.pagina) || 1;
  pagina = Math.min(Math.max(1, pagina), totalPaginas);
  const totalItens = pgRaw.total_itens != null ? Number(pgRaw.total_itens) : 0;
  const synthetic = { pagina, total_paginas: totalPaginas, total_itens: totalItens };

  const hideSingle = opts.hideWhenSingle !== false;
  if (hideSingle && totalPaginas <= 1) {
    bar.classList.remove("is-visible");
    ul.querySelectorAll("li[data-cg-page-num]").forEach((n) => n.remove());
    metaEl.textContent = "";
    btnPrev.disabled = true;
    btnNext.disabled = true;
    return;
  }

  bar.classList.add("is-visible");

  metaEl.textContent =
    typeof opts.metaFormatter === "function"
      ? opts.metaFormatter(synthetic)
      : `Página ${synthetic.pagina} de ${synthetic.total_paginas} · ${synthetic.total_itens} registo(s)`;

  ul.querySelectorAll("li[data-cg-page-num]").forEach((node) => node.remove());

  const mb = opts.maxButtons != null ? opts.maxButtons : 5;
  const go = typeof opts.goToPage === "function" ? opts.goToPage : null;

  cgWindowPaginas(totalPaginas, pagina, mb).forEach((pnum) => {
    const li = document.createElement("li");
    li.setAttribute("data-cg-page-num", "1");
    const btn = document.createElement("button");
    btn.type = "button";
    btn.textContent = String(pnum);
    const cur = pnum === synthetic.pagina;
    btn.className = "cg-page-link cg-page-link--square" + (cur ? " cg-page-link--current" : "");
    if (cur) {
      btn.setAttribute("aria-current", "page");
      btn.disabled = true;
    } else if (go) {
      btn.addEventListener("click", () => go(pnum));
    }
    li.appendChild(btn);
    ul.insertBefore(li, liNext);
  });

  btnPrev.disabled = synthetic.pagina <= 1;
  btnNext.disabled = synthetic.pagina >= synthetic.total_paginas;
}

// Interceptar todas as requisições para verificar 401
const originalFetch = window.fetch;
window.fetch = async (...args) => {
    const response = await originalFetch(...args);
    if (response.status === 401 && !window.location.pathname.includes('/login')) {
        logout();
    }
    return response;
};

function applyTheme(theme) {
  const btn = document.getElementById("btn-theme-toggle");
  const sunIcon = `<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" style="width:1.25rem;height:1.25rem;"><path stroke-linecap="round" stroke-linejoin="round" d="M12 3v2.25m6.364.386l-1.591 1.591M21 12h-2.25m-.386 6.364l-1.591-1.591M12 18.75V21m-4.773-4.227l-1.591 1.591M5.25 12H3m4.227-4.773L5.636 5.636M15.75 12a3.75 3.75 0 11-7.5 0 3.75 3.75 0 017.5 0z" /></svg>`;
  const moonIcon = `<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" style="width:1.25rem;height:1.25rem;"><path stroke-linecap="round" stroke-linejoin="round" d="M21.752 15.002A9.718 9.718 0 0118 15.75c-5.385 0-9.75-4.365-9.75-9.75 0-1.33.266-2.597.748-3.752A9.753 9.753 0 003 11.25C3 16.635 7.365 21 12.75 21a9.753 9.753 0 009.002-5.998z" /></svg>`;
  
  if (theme === "dark") {
    document.documentElement.setAttribute("data-theme", "dark");
    if (btn) {
      btn.innerHTML = sunIcon;
      btn.title = "Ativar modo claro";
    }
  } else {
    document.documentElement.setAttribute("data-theme", "light");
    if (btn) {
      btn.innerHTML = moonIcon;
      btn.title = "Ativar modo escuro";
    }
  }
}

function initThemeToggle() {
  const sidebarHeader = document.querySelector(".sidebar-header");
  if (!sidebarHeader) return;
  if (document.getElementById("btn-theme-toggle")) return;

  const btn = document.createElement("button");
  btn.id = "btn-theme-toggle";
  btn.type = "button";
  btn.style.background = "transparent";
  btn.style.border = "none";
  btn.style.cursor = "pointer";
  btn.style.padding = "0.4rem";
  btn.style.marginLeft = "auto";
  btn.style.color = "var(--sidebar-text)";
  btn.style.display = "flex";
  btn.style.alignItems = "center";
  btn.style.justifyContent = "center";
  btn.style.borderRadius = "var(--radius-sm)";
  btn.style.transition = "all var(--duration-fast) var(--ease-out)";
  
  btn.addEventListener("mouseenter", () => {
    btn.style.backgroundColor = "var(--sidebar-hover)";
    btn.style.color = "var(--sidebar-text-active)";
  });
  btn.addEventListener("mouseleave", () => {
    btn.style.backgroundColor = "transparent";
    btn.style.color = "var(--sidebar-text)";
  });

  btn.addEventListener("click", () => {
    let current = localStorage.getItem("cert_robot_theme");
    if (!current) {
      const isDarkSystem = window.matchMedia("(prefers-color-scheme: dark)").matches;
      current = isDarkSystem ? "dark" : "light";
    }
    const nextTheme = current === "dark" ? "light" : "dark";
    localStorage.setItem("cert_robot_theme", nextTheme);
    applyTheme(nextTheme);
  });

  sidebarHeader.appendChild(btn);
  applyTheme(localStorage.getItem("cert_robot_theme"));
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", () => {
    initSidebarToggle();
    initThemeToggle();
  });
} else {
  initSidebarToggle();
  initThemeToggle();
}

// ─── Paginador reutilizável ───────────────────────────────────────────────────
/**
 * Uso:
 *   const pag = new Paginator({
 *     containerId : "pagination",   // id do <div> onde os botões aparecem
 *     infoId      : "pg-info",      // id do <p> com "Exibindo X–Y de Z"
 *     pageSize    : 20,
 *     scrollTarget: ".table-container", // seletor para scroll no topo ao mudar página
 *     onRender    : (fatia) => { /* renderiza só a fatia *\/ }
 *   });
 *   pag.set(todosOsItens);          // carrega/atualiza a lista
 *   pag.goto(1);                    // força ir para página 1
 */
class Paginator {
  constructor({ containerId, infoId, pageSize = 20, scrollTarget, onRender }) {
    this._cId    = containerId;
    this._iId    = infoId;
    this._size   = pageSize;
    this._scroll = scrollTarget;
    this._cb     = onRender;
    this._items  = [];
    this._page   = 1;
  }

  set(items) {
    this._items = items || [];
    this._page  = 1;
    this._render();
  }

  goto(pg) {
    const total = Math.max(1, Math.ceil(this._items.length / this._size));
    this._page  = Math.min(Math.max(1, pg), total);
    this._render();
    if (this._scroll) {
      const el = document.querySelector(this._scroll);
      if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }

  /** Retorna todos os itens (para exportação). */
  all() { return this._items; }

  _render() {
    const total   = this._items.length;
    const totalPg = Math.max(1, Math.ceil(total / this._size));
    if (this._page > totalPg) this._page = totalPg;

    const start = (this._page - 1) * this._size;
    const end   = Math.min(start + this._size, total);
    const slice = this._items.slice(start, end);

    // Chama o callback de renderização
    if (this._cb) this._cb(slice);

    // Info de registros
    const infoEl = document.getElementById(this._iId);
    if (infoEl) {
      infoEl.textContent = total === 0
        ? "Nenhum registro encontrado."
        : `Exibindo ${start + 1}–${end} de ${total} registro(s)`;
    }

    // Botões de navegação
    const cEl = document.getElementById(this._cId);
    if (!cEl) return;
    if (totalPg <= 1) { cEl.innerHTML = ""; return; }

    const W = 2;
    let pStart = Math.max(1, this._page - W);
    let pEnd   = Math.min(totalPg, this._page + W);
    if (pEnd - pStart < W * 2) {
      if (pStart === 1) pEnd = Math.min(totalPg, pStart + W * 2);
      else pStart = Math.max(1, pEnd - W * 2);
    }

    const p = this._page;
    let h = `<button data-pg="${p - 1}" ${p === 1 ? "disabled" : ""}>‹ Anterior</button>`;
    if (pStart > 1) {
      h += `<button data-pg="1">1</button>`;
      if (pStart > 2) h += `<button disabled>…</button>`;
    }
    for (let i = pStart; i <= pEnd; i++) {
      h += `<button data-pg="${i}" class="${i === p ? "active" : ""}">${i}</button>`;
    }
    if (pEnd < totalPg) {
      if (pEnd < totalPg - 1) h += `<button disabled>…</button>`;
      h += `<button data-pg="${totalPg}">${totalPg}</button>`;
    }
    h += `<button data-pg="${p + 1}" ${p === totalPg ? "disabled" : ""}>Próxima ›</button>`;
    cEl.innerHTML = h;

    // Delegação de eventos (um único listener)
    cEl.onclick = (ev) => {
      const btn = ev.target.closest("button[data-pg]");
      if (!btn || btn.disabled) return;
      this.goto(Number(btn.dataset.pg));
    };
  }
}

