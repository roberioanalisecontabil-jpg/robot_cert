/**
 * Funções partilhadas entre o painel (/) e a configuração (/configuracao).
 * O token JWT fica no localStorage do browser.
 */
const KEY_STORAGE = "cert_robot_api_key"; // Agora armazena o Token JWT
const FONT_STORAGE = "cert_robot_data_fonte";
const SIDEBAR_COLLAPSED_STORAGE = "certguard_sidebar_collapsed";

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

// Interceptar todas as requisições para verificar 401
const originalFetch = window.fetch;
window.fetch = async (...args) => {
    const response = await originalFetch(...args);
    if (response.status === 401 && !window.location.pathname.includes('/login')) {
        logout();
    }
    return response;
};

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initSidebarToggle);
} else {
  initSidebarToggle();
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

