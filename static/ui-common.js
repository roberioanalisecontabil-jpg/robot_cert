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
  if (window.innerWidth > 768) {
    const collapsed = localStorage.getItem(SIDEBAR_COLLAPSED_STORAGE) === "1";
    document.body.classList.toggle("sidebar-collapsed", collapsed);
  }
}

function toggleSidebar() {
  if (window.innerWidth <= 768) {
    const isOpen = document.body.classList.toggle("sidebar-open");
    let backdrop = document.getElementById("sidebar-backdrop");
    if (!backdrop) {
      backdrop = document.createElement("div");
      backdrop.id = "sidebar-backdrop";
      backdrop.className = "sidebar-backdrop";
      document.body.appendChild(backdrop);
      backdrop.addEventListener("click", () => {
        document.body.classList.remove("sidebar-open");
      });
    }
  } else {
    const collapsed = document.body.classList.toggle("sidebar-collapsed");
    localStorage.setItem(SIDEBAR_COLLAPSED_STORAGE, collapsed ? "1" : "0");
  }
}

function initSidebarToggle() {
  const sidebar = document.querySelector(".sidebar");
  const main = document.querySelector(".main-content");
  if (!sidebar || !main) return;
  if (document.getElementById("btn-sidebar-toggle")) return;

  applySidebarState();

  // Wrapper para os botões do topo (menu + tema)
  let bar = document.getElementById("topbar-actions");
  if (!bar) {
    bar = document.createElement("div");
    bar.id = "topbar-actions";
    bar.className = "topbar-actions";
    main.prepend(bar);
  }

  const btn = document.createElement("button");
  btn.id = "btn-sidebar-toggle";
  btn.type = "button";
  btn.className = "sidebar-toggle-btn";
  btn.title = "Recolher/expandir menu";
  btn.setAttribute("aria-label", "Recolher/expandir menu lateral");
  btn.innerHTML = "&#9776;";
  btn.addEventListener("click", toggleSidebar);
  bar.appendChild(btn);
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
  let el = typeof container === "string" ? document.getElementById(container) : container;
  if (!el) return;

  // Se o elemento contiver um wrapper de tabela (com overflow-x) ou uma tabela direta,
  // vamos ancorar o loading nele para evitar cobrir a barra de ferramentas (toolbar) com o campo de busca.
  const tableWrapper = el.querySelector('div[style*="overflow-x"]');
  if (tableWrapper) {
    el = tableWrapper;
  } else {
    const tableEl = el.querySelector('table');
    if (tableEl && tableEl.parentElement) {
      el = tableEl.parentElement;
    }
  }

  // Garante que o elemento seja "anchor" para o overlay absoluto
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

/**
 * Exibe uma notificação flutuante (Toast) não bloqueante (WCAG 2.2 AA).
 * @param {string} message - Texto da notificação
 * @param {'success'|'error'|'warning'|'info'} [type='info'] - Tipo do toast
 * @param {number} [duration=4000] - Duração em ms antes do auto-dismiss
 */
function showToast(message, type = 'info', duration = 4000) {
  let container = document.getElementById('toast-container');
  if (!container) {
    container = document.createElement('div');
    container.id = 'toast-container';
    container.className = 'toast-container';
    container.setAttribute('aria-live', 'polite');
    container.setAttribute('aria-atomic', 'true');
    document.body.appendChild(container);
  }

  const toast = document.createElement('div');
  toast.className = `toast-item toast-${type}`;
  
  const icons = {
    success: '&#10003;',
    error: '&#9888;',
    warning: '&#9888;',
    info: '&#8505;'
  };

  toast.innerHTML = `
    <span class="toast-icon">${icons[type] || icons.info}</span>
    <span class="toast-message">${message}</span>
    <button type="button" class="toast-close" aria-label="Fechar notificação">&times;</button>
  `;

  const closeBtn = toast.querySelector('.toast-close');
  closeBtn.addEventListener('click', () => removeToast(toast));

  container.appendChild(toast);
  requestAnimationFrame(() => toast.classList.add('is-visible'));

  if (duration > 0) {
    setTimeout(() => removeToast(toast), duration);
  }
}

function removeToast(toast) {
  if (!toast || !toast.parentNode) return;
  toast.classList.remove('is-visible');
  toast.addEventListener('transitionend', () => {
    if (toast.parentNode) toast.parentNode.removeChild(toast);
  }, { once: true });
}

/**
 * Renderiza um estado vazio ilustrado e acionável em tabelas ou containers.
 * @param {HTMLElement|string} target - Container alvo
 * @param {Object} options - Configurações do empty state
 */
function renderEmptyState(target, { title = "Nenhum registro encontrado", description = "Não há dados para exibir no momento.", icon = "&#128269;", actionText = null, onAction = null }) {
  const container = typeof target === 'string' ? document.getElementById(target) : target;
  if (!container) return;

  const html = `
    <div class="empty-state-card">
      <div class="empty-state-icon">${icon}</div>
      <h3 class="empty-state-title">${title}</h3>
      <p class="empty-state-desc">${description}</p>
      ${actionText ? `<button type="button" class="primary empty-state-btn">${actionText}</button>` : ''}
    </div>
  `;
  container.innerHTML = html;

  if (actionText && typeof onAction === 'function') {
    const btn = container.querySelector('.empty-state-btn');
    if (btn) btn.addEventListener('click', onAction);
  }
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
  if (document.getElementById("btn-theme-toggle")) return;

  // Coloca o botão de tema ao lado do botão sanduíche no topbar
  let bar = document.getElementById("topbar-actions");
  if (!bar) {
    // Se initSidebarToggle ainda não rodou, cria o wrapper
    const main = document.querySelector(".main-content");
    if (!main) return;
    bar = document.createElement("div");
    bar.id = "topbar-actions";
    bar.className = "topbar-actions";
    main.prepend(bar);
  }

  const btn = document.createElement("button");
  btn.id = "btn-theme-toggle";
  btn.type = "button";
  btn.className = "sidebar-toggle-btn theme-toggle-btn";

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

  bar.appendChild(btn);
  applyTheme(localStorage.getItem("cert_robot_theme"));
}

async function fetchNotifications() {
  const token = getToken();
  if (!token) return;
  const badge = document.getElementById("notification-badge");
  const body = document.getElementById("notifications-body");
  if (!body) return;
  
  try {
    const r = await fetch("/api/colaborador/notificacoes", {
      headers: getHeaders()
    });
    if (!r.ok) {
      if (r.status === 401) {
        logout();
      }
      return;
    }
    const data = await r.json();
    const items = data.itens || [];
    
    // Update badge
    if (items.length > 0) {
      badge.textContent = items.length;
      badge.style.display = "flex";
    } else {
      badge.style.display = "none";
    }
    
    // Build items
    if (items.length === 0) {
      body.innerHTML = '<div class="notif-empty">Tudo em dia! Sem alertas.</div>';
    } else {
      body.innerHTML = items.map(it => {
        const typeClass = it.tipo === "expired" ? "notif-expired" : "notif-expiring";
        const typeLabel = it.tipo === "expired" ? "Vencido" : "Expirando";
        const dateFmt = new Date(it.vencimento).toLocaleDateString('pt-BR');
        return `
          <div class="notification-item ${typeClass}">
            <div class="notif-item-header">
              <span class="notif-badge-type">${typeLabel}</span>
              <span class="notif-date">${dateFmt}</span>
            </div>
            <div class="notif-message">${it.mensagem}</div>
            <div class="notif-doc">Doc: ${it.documento}</div>
          </div>
        `;
      }).join('');
    }
  } catch (e) {
    console.error("Erro ao carregar notificações", e);
    body.innerHTML = '<div class="notif-error">Erro ao carregar alertas.</div>';
  }
}

function initNotifications() {
  if (document.getElementById("notifications-container")) return;
  const token = getToken();
  if (!token) return;

  let bar = document.getElementById("topbar-actions");
  if (!bar) {
    const main = document.querySelector(".main-content");
    if (!main) return;
    bar = document.createElement("div");
    bar.id = "topbar-actions";
    bar.className = "topbar-actions";
    main.prepend(bar);
  }

  const container = document.createElement("div");
  container.id = "notifications-container";
  container.className = "notifications-container";
  container.innerHTML = `
    <button id="btn-notifications-toggle" type="button" class="sidebar-toggle-btn notifications-bell-btn" title="Atualização Automática de Alertas" aria-label="Alertas e Notificações">
      <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" style="width:1.25rem;height:1.25rem;">
        <path stroke-linecap="round" stroke-linejoin="round" d="M14.857 17.082a23.848 23.848 0 005.454-1.31A8.967 8.967 0 0118 9.75v-.7V9A6 6 0 006 9v.75a8.967 8.967 0 01-2.312 6.022c1.733.64 3.56 1.085 5.455 1.31m5.714 0a24.255 24.255 0 01-5.714 0m5.714 0a3 3 0 11-5.714 0" />
      </svg>
      <span class="notification-badge" id="notification-badge" style="display: none;">0</span>
    </button>
    <div class="notifications-dropdown" id="notifications-dropdown" style="display: none;">
      <div class="notifications-header">
        <h3>Notificações</h3>
        <span class="notif-sync-mode" title="Verificação em segundo plano">Atualização Automática</span>
      </div>
      <div class="notifications-body" id="notifications-body">
        <div class="notif-loading">Carregando...</div>
      </div>
    </div>
  `;

  const themeBtn = document.getElementById("btn-theme-toggle");
  if (themeBtn) {
    bar.insertBefore(container, themeBtn);
  } else {
    bar.appendChild(container);
  }

  const toggleBtn = document.getElementById("btn-notifications-toggle");
  const dropdown = document.getElementById("notifications-dropdown");

  toggleBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    const isVisible = dropdown.style.display === "block";
    dropdown.style.display = isVisible ? "none" : "block";
    if (!isVisible) {
      fetchNotifications();
    }
  });

  document.addEventListener("click", (e) => {
    if (!e.target.closest("#notifications-container")) {
      dropdown.style.display = "none";
    }
  });

  fetchNotifications();
  // Atualização Automática a cada 60s
  setInterval(fetchNotifications, 60000);
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", () => {
    initSidebarToggle();
    initThemeToggle();
    initNotifications();
  });
} else {
  initSidebarToggle();
  initThemeToggle();
  initNotifications();
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

/* --- ATALHOS DE TECLADO E ACESSIBILIDADE (WCAG 2.2 AA) --- */
document.addEventListener('keydown', function(e) {
  // Atalho '/' para focar na caixa de busca rápida
  if (e.key === '/' && !['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement.tagName)) {
    const searchInput = document.getElementById('busca-cert') || document.querySelector('input[type="search"]');
    if (searchInput) {
      e.preventDefault();
      searchInput.focus();
    }
  }

  // Tecla 'Escape' para fechar modais ou dropdowns ativos
  if (e.key === 'Escape') {
    document.querySelectorAll('.modal, [role="dialog"]').forEach(modal => {
      if (modal.style.display !== 'none' && modal.classList.contains('active')) {
        modal.style.display = 'none';
        modal.classList.remove('active');
      }
    });
    const notifDropdown = document.getElementById('notifications-dropdown');
    if (notifDropdown && notifDropdown.style.display !== 'none') {
      notifDropdown.style.display = 'none';
    }
  }
});

