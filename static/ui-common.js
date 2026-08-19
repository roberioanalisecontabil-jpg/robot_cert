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

function initSidebarPorPapel() {
  // A sidebar virou partial em 15/08, mas a revelação dos itens restritos
  // ficou copiada em cada tela — e as cópias envelheceram em ritmos
  // diferentes: 8 telas só conheciam os itens de admin antigos, então um
  // admin no Início não via Dashboard nem Carteiras; eles só apareciam para
  // quem já estava NELES. A lista de quem vê o quê mora aqui, uma vez.
  // O servidor confere de novo em cada API: isto é conveniência, não barreira.
  const role = localStorage.getItem("user_role");
  const porPapel = {
    admin: ["nav-users", "nav-config", "nav-installer", "nav-dashboard", "nav-carteiras"],
    gestor: ["nav-carteiras"],
  };
  (porPapel[role] || []).forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.style.display = "flex";
  });
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
  // Heroicons `bars-3`, mesmo traco 1.5 dos irmaos desta barra. Era
  // `&#9776;` (U+2630, TRIGRAM FOR HEAVEN): um caractere de texto fazendo
  // papel de icone, dimensionado por `font-size` e desenhado pela fonte do
  // sistema — sem relacao de peso nem de tamanho com os SVGs ao lado.
  btn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" d="M3.75 6.75h16.5M3.75 12h16.5m-16.5 5.25h16.5" /></svg>';
  btn.addEventListener("click", toggleSidebar);
  bar.appendChild(btn);
}

/**
 * Uma área rolável precisa ser alcançável por teclado (WCAG 2.1.1) — mas só
 * enquanto de fato rolar. Com 10 linhas por página a tabela cabe inteira, e um
 * `tabindex="0"` fixo criaria uma parada de tabulação que não faz nada, além de
 * poluir a lista de regiões do leitor de tela. Aqui o foco é ligado/desligado
 * conforme a tabela realmente transborde.
 */
function atualizarRegioesRolaveis(raiz) {
  const escopo = raiz || document;
  escopo.querySelectorAll(".table-scroll").forEach((el) => {
    // Abaixo de 768px o container vira `overflow: visible` (layout de cards).
    // Sem esta checagem, `scrollHeight > clientHeight` continuaria verdadeiro
    // num elemento que não rola, criando uma parada de tabulação fantasma.
    const est = window.getComputedStyle(el);
    const podeRolar = /(auto|scroll)/.test(est.overflowY + " " + est.overflowX);
    const rola =
      podeRolar &&
      (el.scrollHeight > el.clientHeight + 1 || el.scrollWidth > el.clientWidth + 1);
    if (rola) {
      el.setAttribute("tabindex", "0");
      el.setAttribute("role", "region");
    } else {
      el.removeAttribute("tabindex");
      el.removeAttribute("role");
    }
  });
}

/** Observa mudanças de tamanho das áreas roláveis (troca de página, filtro, resize). */
function initRegioesRolaveis() {
  atualizarRegioesRolaveis();
  const alvos = document.querySelectorAll(".table-scroll");
  if (!alvos.length) return;

  if (typeof ResizeObserver === "function") {
    const ro = new ResizeObserver(() => atualizarRegioesRolaveis());
    alvos.forEach((el) => {
      ro.observe(el);
      const t = el.querySelector("table");
      if (t) ro.observe(t); // o conteúdo muda a cada render da tabela
    });
  } else {
    window.addEventListener("resize", () => atualizarRegioesRolaveis());
  }
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

  // Ancoramos o loading na área da tabela (não no container inteiro) para não
  // cobrir a toolbar com o campo de busca enquanto os dados carregam.
  // A âncora precisa ser um elemento que NÃO rola: dentro de `.table-scroll` o
  // overlay `inset: 0` resolveria contra a altura total do conteúdo e o spinner
  // ficaria fora da área visível em tabelas longas.
  const anchor = el.querySelector(".table-scroll-anchor");
  if (anchor) {
    el = anchor;
  } else {
    const tableWrapper = el.querySelector('div[style*="overflow-x"]');
    if (tableWrapper) {
      el = tableWrapper;
    } else {
      const tableEl = el.querySelector("table");
      if (tableEl && tableEl.parentElement) {
        el = tableEl.parentElement;
      }
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

const TOAST_MAX_EMPILHADOS = 3;
const TOAST_PENDENTE_STORAGE = "cg_toast_pendente";

/**
 * Duração proporcional ao tamanho da mensagem, mínimo 4s (`07 §15`).
 * Base de ~55ms por caractere ≈ velocidade de leitura confortável.
 */
function _toastDuracao(message) {
  return Math.min(12000, Math.max(4000, String(message || "").length * 55));
}

/**
 * Exibe uma notificação flutuante (Toast) não bloqueante (WCAG 2.2 AA).
 * Substitui `alert()`: não bloqueia a página nem exige clique para prosseguir.
 * @param {string} message - Texto da notificação (inserido como texto, nunca como HTML)
 * @param {'success'|'error'|'warning'|'info'} [type='info'] - Tipo do toast
 * @param {number} [duration] - ms antes do auto-dismiss; 0 = não fecha sozinho.
 *                              Omitido = calculado pelo tamanho da mensagem.
 */
/**
 * Escapa texto para interpolação segura em HTML.
 *
 * Mora aqui, e não em cada página, por dois motivos que se confirmaram na
 * prática em 16/08/2026:
 *
 * 1. Estava duplicada em SEIS templates, e três páginas mais novas
 *    (dashboard, carteiras e os painéis novos do instalador) a **usavam sem
 *    definir** — `ReferenceError` em todo caminho de render. Não quebrou nos
 *    testes porque eles leem o HTML de origem, não executam o JavaScript.
 * 2. Os dados vêm do CN do certificado, controlado por quem gera o `.pfx`.
 *    A CSP com nonce bloqueia script inline, mas markup injetado ainda
 *    desfigura a tela — e depender só da CSP é ter uma camada de defesa.
 *
 * `textContent` + `innerHTML` faz o navegador escapar: mais curto que uma
 * cadeia de `.replace()` e sem risco de esquecer um caractere.
 */
/**
 * Estado de um certificado -> como ele aparece na tabela.
 *
 * Mora aqui porque o mesmo mapeamento estava escrito DUAS vezes, em
 * `index.html` e `colaborador_certificados.html`. Duas cópias da mesma regra
 * divergem — foi assim que os textos de UI acabaram misturando pt-BR e pt-PT,
 * uma tela por vez, sem nada acusando.
 *
 * O `glifo` é o A2 da auditoria de UI/UX. O texto já bastava para o WCAG 1.4.1
 * (cor não é o único meio: "Ativo"/"Vencido" estão escritos), então isto não é
 * conformidade — é leitura à distância. Numa tabela de centenas de linhas,
 * forma se reconhece antes de palavra, e com deuteranopia (~8% dos homens) o
 * verde e o laranja convergem, deixando só a leitura como saída.
 *
 * Também desfaz uma ambiguidade: `erro` e `fora_do_padrao` dividem a classe
 * `badge-bad`, então eram visualmente idênticos. Agora `!` e `?` os separam.
 */
const BADGE_STATUS = {
  ativo:          { classe: "badge-ok",      texto: "Ativo",               glifo: "✓" },
  expirando:      { classe: "badge-warning", texto: "Expirando",           glifo: "⚠" },
  vencido:        { classe: "badge-expired", texto: "Vencido",             glifo: "✕" },
  erro:           { classe: "badge-bad",     texto: "Erro",                glifo: "!" },
  fora_do_padrao: { classe: "badge-bad",     texto: "Falha (sem padrão)", glifo: "?" },
  nao_encontrado: { classe: "badge-bad",     texto: "Não encontrado", glifo: "?" },
};

/**
 * HTML do badge de status. `chave` é uma das de `BADGE_STATUS`.
 *
 * Chave desconhecida vira um badge neutro com o próprio valor escapado — o
 * comportamento que as duas cópias já tinham, e que existe porque `status` vem
 * do servidor e pode ganhar valores novos antes de a tela saber deles.
 *
 * O glifo leva `aria-hidden="true"`: o leitor de tela já lê o texto ao lado, e
 * sem isso anunciaria "marca de seleção Ativo".
 */
/**
 * Badge de AVISO, para o que não é estado de certificado.
 *
 * Existe porque a etiqueta "sem líder" de um departamento tem a mesma forma
 * visual de um badge, mas não pertence a `BADGE_STATUS` — e montar a string
 * `class="badge badge-bad"` à mão no template é justamente o que
 * `test_status_de_certificado_nao_e_montado_a_mao_no_template` proíbe, para a
 * terceira cópia do mapeamento de status não nascer.
 */
function badgeAviso(texto) {
  return (
    '<span class="badge badge-bad">' +
    '<span class="badge-glifo" aria-hidden="true">!</span>' +
    esc(texto) +
    "</span>"
  );
}

function badgeStatus(chave) {
  const d = BADGE_STATUS[chave];
  if (!d) {
    return '<span class="badge badge-bad">' + esc(chave) + "</span>";
  }
  return (
    '<span class="badge ' + d.classe + '">' +
    '<span class="badge-glifo" aria-hidden="true">' + d.glifo + "</span>" +
    esc(d.texto) +
    "</span>"
  );
}

function esc(v) {
  const d = document.createElement("div");
  d.textContent = v == null ? "" : String(v);
  return d.innerHTML;
}

function showToast(message, type = "info", duration) {
  let container = document.getElementById("toast-container");
  if (!container) {
    container = document.createElement("div");
    container.id = "toast-container";
    container.className = "toast-container";
    // Erros interrompem a leitura; sucesso/info esperam uma pausa natural.
    container.setAttribute("aria-live", "polite");
    container.setAttribute("aria-atomic", "false");
    document.body.appendChild(container);
  }

  // Máximo de 3 simultâneos, substituindo os mais antigos (`07 §15`).
  const existentes = container.querySelectorAll(".toast-item");
  for (let i = 0; i <= existentes.length - TOAST_MAX_EMPILHADOS; i++) {
    removeToast(existentes[i]);
  }

  const icons = { success: "✓", error: "⚠", warning: "⚠", info: "ℹ" };

  const toast = document.createElement("div");
  toast.className = `toast-item toast-${type}`;
  if (type === "error") toast.setAttribute("role", "alert");

  const spanIcon = document.createElement("span");
  spanIcon.className = "toast-icon";
  spanIcon.setAttribute("aria-hidden", "true");
  spanIcon.textContent = icons[type] || icons.info;

  // textContent, não innerHTML: mensagens carregam dados de certificado
  // (nome/CN do titular), que são conteúdo controlado por terceiros.
  const spanMsg = document.createElement("span");
  spanMsg.className = "toast-message";
  spanMsg.textContent = String(message == null ? "" : message);

  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "toast-close";
  btn.setAttribute("aria-label", "Fechar notificação");
  btn.textContent = "×";
  btn.addEventListener("click", () => removeToast(toast));

  toast.append(spanIcon, spanMsg, btn);
  container.appendChild(toast);
  requestAnimationFrame(() => toast.classList.add("is-visible"));

  const ms = duration === undefined ? _toastDuracao(message) : duration;
  if (ms > 0) setTimeout(() => removeToast(toast), ms);
  return toast;
}

function removeToast(toast) {
  if (!toast || !toast.parentNode) return;
  toast.classList.remove("is-visible");
  // Rede de segurança: se a transição não disparar (aba oculta, reduced-motion),
  // o nó seria mantido no DOM indefinidamente.
  const remover = () => {
    if (toast.parentNode) toast.parentNode.removeChild(toast);
  };
  toast.addEventListener("transitionend", remover, { once: true });
  setTimeout(remover, 600);
}

/**
 * Guarda um toast para ser exibido DEPOIS de uma navegação.
 * Usado onde antes havia `alert()` seguido de `window.location.href`: um toast
 * comum apareceria e sumiria junto com a página, sem chance de leitura.
 */
function showToastAfterRedirect(message, type = "info") {
  try {
    sessionStorage.setItem(TOAST_PENDENTE_STORAGE, JSON.stringify({ message, type }));
  } catch (_e) {
    /* sessionStorage indisponível (modo privado antigo): apenas ignora */
  }
}

function _consumirToastPendente() {
  let raw = null;
  try {
    raw = sessionStorage.getItem(TOAST_PENDENTE_STORAGE);
    if (raw) sessionStorage.removeItem(TOAST_PENDENTE_STORAGE);
  } catch (_e) {
    return;
  }
  if (!raw) return;
  try {
    const { message, type } = JSON.parse(raw);
    if (message) showToast(message, type || "info");
  } catch (_e) {
    /* payload corrompido: ignora */
  }
}

/**
 * Estado vazio DENTRO de uma tabela, como linha única com colspan.
 * `renderEmptyState()` substitui o innerHTML do container — em uma tabela isso
 * destruiria o <thead>. Aqui o cabeçalho é preservado, então o usuário continua
 * vendo quais colunas existem.
 */
function renderEmptyRow(tbody, colspan, options = {}) {
  const el = typeof tbody === "string" ? document.getElementById(tbody) : tbody;
  if (!el) return;

  const {
    title = "Nenhum registro encontrado",
    description = "Não há dados para exibir com os filtros atuais.",
    icon = "🔍",
    actionText = null,
    onAction = null,
  } = options;

  el.innerHTML = "";

  const tr = document.createElement("tr");
  // Marcada como linha de estado: o layout de cards no mobile a ignora,
  // senão o estado vazio viraria um "card" com rótulo de coluna.
  tr.className = "cg-state-row";
  const td = document.createElement("td");
  td.colSpan = colspan || 1;
  td.style.padding = "0";
  td.style.border = "0";

  const card = document.createElement("div");
  card.className = "empty-state-card";
  card.style.margin = "0";
  card.style.border = "0";

  const divIcon = document.createElement("div");
  divIcon.className = "empty-state-icon";
  divIcon.setAttribute("aria-hidden", "true");
  divIcon.textContent = icon;

  const h3 = document.createElement("p");
  h3.className = "empty-state-title";
  h3.textContent = title;

  const p = document.createElement("p");
  p.className = "empty-state-desc";
  p.textContent = description;

  card.append(divIcon, h3, p);

  if (actionText && typeof onAction === "function") {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "primary";
    btn.textContent = actionText;
    btn.addEventListener("click", onAction);
    card.appendChild(btn);
  }

  td.appendChild(card);
  tr.appendChild(td);
  el.appendChild(tr);
}

/**
 * Linhas "fantasma" durante o primeiro carregamento (`07 §3`).
 * Preferível ao overlay quando ainda não há dado nenhum na tela: o usuário vê
 * a forma da tabela se montando em vez de um retângulo vazio, e o layout não
 * dá salto quando os dados chegam (CLS).
 */
function renderSkeletonRows(tbody, linhas = 6, colunas = 5) {
  const el = typeof tbody === "string" ? document.getElementById(tbody) : tbody;
  if (!el) return;
  el.setAttribute("aria-busy", "true");
  el.innerHTML = "";
  for (let i = 0; i < linhas; i++) {
    const tr = document.createElement("tr");
    tr.className = "cg-state-row cg-skeleton-row";
    tr.setAttribute("aria-hidden", "true");
    for (let c = 0; c < colunas; c++) {
      const td = document.createElement("td");
      const div = document.createElement("div");
      div.className = "skeleton-cell";
      // Larguras irregulares parecem texto real, não uma grade de blocos.
      div.style.width = [92, 70, 84, 60, 78][(i + c) % 5] + "%";
      td.appendChild(div);
      tr.appendChild(td);
    }
    el.appendChild(tr);
  }
}

function limparSkeleton(tbody) {
  const el = typeof tbody === "string" ? document.getElementById(tbody) : tbody;
  if (el) el.removeAttribute("aria-busy");
}

/**
 * Banner persistente de aviso no topo de um `.table-container` (`07 §16`).
 * Diferente do toast: fica visível até a condição deixar de valer, porque é
 * informação que o usuário precisa consultar no momento em que decide exportar.
 * Passar `mensagem` vazia remove o banner.
 */
function setBannerAviso(container, mensagem, tipo = "warning") {
  const el = typeof container === "string" ? document.getElementById(container) : container;
  if (!el) return;

  let banner = el.querySelector(".cg-banner");

  if (!mensagem) {
    if (banner) banner.remove();
    return;
  }

  if (!banner) {
    banner = document.createElement("div");
    banner.className = "cg-banner";
    banner.setAttribute("role", "status");

    const span = document.createElement("span");
    span.className = "cg-banner__icon";
    span.setAttribute("aria-hidden", "true");
    span.textContent = "⚠";

    const txt = document.createElement("span");
    txt.className = "cg-banner__text";

    banner.append(span, txt);

    // Logo acima da área da tabela, depois da toolbar — onde o olho já está
    // quando o usuário procura o botão de exportar.
    const alvo = el.querySelector(".table-scroll-anchor");
    if (alvo) el.insertBefore(banner, alvo);
    else el.appendChild(banner);
  }

  banner.className = "cg-banner cg-banner--" + tipo;
  banner.querySelector(".cg-banner__text").textContent = mensagem;
}

/** Mensagem padrão de limite de exportação, ou null se não há truncamento. */
function mensagemLimiteExportacao(pg) {
  if (!pg) return null;
  const max = Number(pg.export_max) || 0;
  const total = Number(pg.total_itens) || 0;
  if (!max || total <= max) return null;
  return (
    "Este filtro tem " +
    total.toLocaleString("pt-BR") +
    " registros, mas a exportação envia no máximo " +
    max.toLocaleString("pt-BR") +
    ". Refine os filtros para exportar tudo."
  );
}

/**
 * Renderiza um estado vazio ilustrado e acionável em tabelas ou containers.
 * @param {HTMLElement|string} target - Container alvo
 * @param {Object} options - Configurações do empty state
 */
function renderEmptyState(target, { title = "Nenhum registro encontrado", description = "Não há dados para exibir no momento.", icon = "&#128269;", actionText = null, onAction = null }) {
  const container = typeof target === 'string' ? document.getElementById(target) : target;
  if (!container) return;

  // `icon` fica sem escape de propósito: é entidade HTML vinda do código
  // (&#128269;), não dado de usuário. O resto passa por `esc` -- título e
  // descrição chegam a carregar nome de titular em algumas telas.
  const html = `
    <div class="empty-state-card">
      <div class="empty-state-icon">${icon}</div>
      <h3 class="empty-state-title">${esc(title)}</h3>
      <p class="empty-state-desc">${esc(description)}</p>
      ${actionText ? `<button type="button" class="primary empty-state-btn">${esc(actionText)}</button>` : ''}
    </div>
  `;
  container.innerHTML = html;

  if (actionText && typeof onAction === 'function') {
    const btn = container.querySelector('.empty-state-btn');
    if (btn) btn.addEventListener('click', onAction);
  }
}

/** Lista de página (janela de até `maxBotões`) igual ao modelo Histórico/Início/Vencidos. */
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
      : `Página ${synthetic.pagina} de ${synthetic.total_paginas} · ${synthetic.total_itens} registro(s)`;

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

/* ══════════════════════════════════════════════════════════════════════════
   Troca de senha obrigatória

   Vive aqui, e não numa tela, porque precisa existir em TODAS: a pessoa entra
   e cai onde estava antes, ou digita uma URL direto. Amarrar isto ao login
   deixaria qualquer outra porta aberta.

   Quem manda é o servidor. `require_auth` responde 403 com o cabeçalho
   `X-Senha-Provisoria` em qualquer rota que não seja a da troca, e o
   interceptor abaixo reage. A tela não decide nada — só reage ao que já foi
   recusado. Um modal que a própria página decidisse mostrar seria contornável
   fechando o modal.
   ══════════════════════════════════════════════════════════════════════════ */

let _senhaModalAberto = false;

function _fecharSessaoPorSenhaTrocada() {
  // Trocar a senha carimba `senha_alterada_em`, e o token atual passa a ser
  // anterior a isso — ele morre na requisição seguinte. Levar ao login é o
  // desfecho honesto, e não um efeito colateral a esconder.
  showToastAfterRedirect("Senha alterada. Entre com a nova senha.", "success");
  logout();
}

function abrirTrocaDeSenhaObrigatoria() {
  if (_senhaModalAberto) return;
  _senhaModalAberto = true;

  const dlg = document.createElement("dialog");
  dlg.className = "modal";
  dlg.id = "modal-senha-obrigatoria";
  dlg.innerHTML = `
    <form class="modal__form" id="form-senha-obrigatoria">
      <div class="modal__head">
        <h2>Defina sua senha</h2>
        <p class="modal__sub">
          A senha atual foi definida por outra pessoa. Escolha uma que só você
          saiba para continuar usando o portal.
        </p>
      </div>
      <div class="modal__body">
        <div class="modal__erro" id="so-erro" role="alert"></div>
        <div class="modal__campo">
          <label for="so-atual">Senha atual</label>
          <input type="password" id="so-atual" required autocomplete="current-password">
        </div>
        <div class="modal__campo">
          <label for="so-nova">Nova senha</label>
          <div class="campo-senha">
            <input type="password" id="so-nova" required minlength="6"
                   autocomplete="new-password" placeholder="mínimo 6 caracteres">
            <button type="button" class="btn-olho" id="so-olho"
                    aria-controls="so-nova" aria-pressed="false"
                    aria-label="Mostrar senha">&#128065;</button>
          </div>
        </div>
        <div class="modal__campo">
          <label for="so-conf">Repita a nova senha</label>
          <input type="password" id="so-conf" required minlength="6" autocomplete="new-password">
        </div>
      </div>
      <div class="modal__foot">
        <button type="button" class="btn-action" id="so-sair">Sair</button>
        <button type="submit" class="primary" id="so-salvar">Definir senha</button>
      </div>
    </form>`;
  document.body.appendChild(dlg);

  const erro = (t) => {
    const el = dlg.querySelector("#so-erro");
    el.textContent = t || "";
    el.setAttribute("data-visivel", t ? "1" : "0");
  };

  // NÃO há botão de fechar, e o Esc é bloqueado: a alternativa a definir a
  // senha é sair, não é ficar. Deixar fechar devolveria a pessoa a um portal
  // em que nada responde — todas as rotas recusam com 403 — e o sintoma seria
  // "o sistema não carrega nada", sem dizer por quê.
  dlg.addEventListener("cancel", (e) => e.preventDefault());
  dlg.querySelector("#so-sair").addEventListener("click", () => logout());

  dlg.querySelector("#so-olho").addEventListener("click", () => {
    const campo = dlg.querySelector("#so-nova");
    const btn = dlg.querySelector("#so-olho");
    const revelado = campo.type === "text";
    campo.type = revelado ? "password" : "text";
    btn.setAttribute("aria-pressed", String(!revelado));
    btn.setAttribute("aria-label", revelado ? "Mostrar senha" : "Ocultar senha");
    campo.focus();
  });

  dlg.querySelector("#form-senha-obrigatoria").addEventListener("submit", async (e) => {
    e.preventDefault();
    const atual = dlg.querySelector("#so-atual").value;
    const nova = dlg.querySelector("#so-nova").value;
    const conf = dlg.querySelector("#so-conf").value;
    if (nova !== conf) {
      erro("As duas senhas não são iguais.");
      dlg.querySelector("#so-conf").focus();
      return;
    }
    const btn = dlg.querySelector("#so-salvar");
    btn.disabled = true;
    btn.textContent = "Salvando...";
    erro("");
    try {
      // `originalFetch`, e não `fetch`: o interceptor abaixo reabriria este
      // mesmo modal ao ver o 403 de uma senha atual errada.
      const r = await originalFetch("/api/senha/trocar", {
        method: "POST",
        headers: getHeaders(true),
        body: JSON.stringify({ senha_atual: atual, nova_senha: nova }),
      });
      if (!r.ok) {
        let d = {};
        try { d = await r.json(); } catch (_) {}
        erro(d.detail || "Não foi possível trocar a senha.");
        return;
      }
      dlg.close();
      dlg.remove();
      _fecharSessaoPorSenhaTrocada();
    } catch (_) {
      erro("Erro de conexão com o servidor.");
    } finally {
      btn.disabled = false;
      btn.textContent = "Definir senha";
    }
  });

  dlg.showModal();
  dlg.querySelector("#so-atual").focus();
}

// Interceptar todas as requisições para verificar 401 e senha provisória
const originalFetch = window.fetch;
window.fetch = async (...args) => {
    const response = await originalFetch(...args);
    if (response.status === 401 && !window.location.pathname.includes('/login')) {
        logout();
    }
    // Cabeçalho, e não o texto da mensagem: casar por string quebraria assim
    // que alguém reescrevesse a frase, e o modal simplesmente pararia de
    // aparecer — sem erro, com a pessoa vendo um portal que não responde.
    if (response.status === 403 && response.headers.get("X-Senha-Provisoria")) {
        abrirTrocaDeSenhaObrigatoria();
    }
    return response;
};

/** Tema em vigor quando o usuário nunca escolheu manualmente: o do sistema. */
function temaDoSistema() {
  return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches
    ? "dark"
    : "light";
}

/**
 * Aplica o tema.
 * `theme` nulo/ausente = "seguir o sistema": o atributo data-theme é REMOVIDO.
 * Setar data-theme="light" nesse caso (comportamento anterior) anulava o bloco
 * `@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) }`,
 * de modo que todo usuário com sistema escuro recebia a interface clara.
 */
function applyTheme(theme) {
  const btn = document.getElementById("btn-theme-toggle");
  const sunIcon = `<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" d="M12 3v2.25m6.364.386l-1.591 1.591M21 12h-2.25m-.386 6.364l-1.591-1.591M12 18.75V21m-4.773-4.227l-1.591 1.591M5.25 12H3m4.227-4.773L5.636 5.636M15.75 12a3.75 3.75 0 11-7.5 0 3.75 3.75 0 017.5 0z" /></svg>`;
  const moonIcon = `<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" d="M21.752 15.002A9.718 9.718 0 0118 15.75c-5.385 0-9.75-4.365-9.75-9.75 0-1.33.266-2.597.748-3.752A9.753 9.753 0 003 11.25C3 16.635 7.365 21 12.75 21a9.753 9.753 0 009.002-5.998z" /></svg>`;

  if (theme === "dark" || theme === "light") {
    document.documentElement.setAttribute("data-theme", theme);
  } else {
    document.documentElement.removeAttribute("data-theme");
  }

  if (!btn) return;

  // O ícone precisa refletir o tema EM VIGOR, não o preferido — senão, no modo
  // "seguir o sistema" com SO escuro, o botão ofereceria "ativar modo escuro".
  const emVigor = theme === "dark" || theme === "light" ? theme : temaDoSistema();
  const seguindoSistema = theme !== "dark" && theme !== "light";
  const sufixo = seguindoSistema ? " (seguindo o sistema)" : "";

  if (emVigor === "dark") {
    btn.innerHTML = sunIcon;
    btn.title = "Ativar modo claro" + sufixo;
    btn.setAttribute("aria-label", "Ativar modo claro" + sufixo);
  } else {
    btn.innerHTML = moonIcon;
    btn.title = "Ativar modo escuro" + sufixo;
    btn.setAttribute("aria-label", "Ativar modo escuro" + sufixo);
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
    const armazenado = localStorage.getItem("cert_robot_theme");
    const emVigor = armazenado === "dark" || armazenado === "light" ? armazenado : temaDoSistema();
    const proximo = emVigor === "dark" ? "light" : "dark";

    if (proximo === temaDoSistema()) {
      // Voltou a coincidir com o SO: devolvemos o controle ao sistema em vez de
      // congelar a escolha, para que o usuário acompanhe o modo noturno automático.
      localStorage.removeItem("cert_robot_theme");
      applyTheme(null);
    } else {
      localStorage.setItem("cert_robot_theme", proximo);
      applyTheme(proximo);
    }
  });

  bar.appendChild(btn);
  applyTheme(localStorage.getItem("cert_robot_theme"));

  // Enquanto o usuário estiver seguindo o sistema, acompanhar a troca em tempo real
  // (ex.: modo noturno automático do Windows/macOS virando ao anoitecer).
  if (window.matchMedia) {
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const aoMudarSistema = () => {
      if (!localStorage.getItem("cert_robot_theme")) applyTheme(null);
    };
    if (mq.addEventListener) mq.addEventListener("change", aoMudarSistema);
    else if (mq.addListener) mq.addListener(aoMudarSistema);
  }
}

/** Atualiza o badge e o nome acessível do sino a partir dos totais. */
function _aplicarBadgeNotificacoes(dados) {
  const badge = document.getElementById("notification-badge");
  const btn = document.getElementById("btn-notifications-toggle");
  if (!badge) return;

  // Contamos só o que está dentro da janela de ação. Antes o badge exibia o
  // total (519), que incluía centenas de certificados vencidos há 1 a 2 anos —
  // um número que nunca baixava e por isso deixava de ser sinal.
  const n = Number(dados && dados.total_acionavel) || 0;

  if (n > 0) {
    badge.textContent = n > 99 ? "99+" : String(n);
    badge.style.display = "flex";
  } else {
    badge.style.display = "none";
  }

  if (btn) {
    // A contagem precisa chegar ao leitor de tela: o aria-label era fixo.
    btn.setAttribute(
      "aria-label",
      n > 0
        ? `Alertas e notificações: ${n} exigem atenção`
        : "Alertas e notificações: nenhum item exige atenção"
    );
  }
}

/** Um item da lista, montado no DOM (nunca innerHTML: `nome` vem do CN do certificado). */
function _criarItemNotificacao(it) {
  const div = document.createElement("div");
  div.className = "notification-item " + (it.tipo === "expired" ? "notif-expired" : "notif-expiring");

  const header = document.createElement("div");
  header.className = "notif-item-header";

  const tipo = document.createElement("span");
  tipo.className = "notif-badge-type";
  const dias = Number(it.dias_restantes);
  if (it.tipo === "expired") {
    tipo.textContent = dias === 0 ? "Venceu hoje" : `Venceu há ${Math.abs(dias)}d`;
  } else {
    tipo.textContent = dias === 0 ? "Vence hoje" : `Vence em ${dias}d`;
  }

  const data = document.createElement("span");
  data.className = "notif-date";
  const d = new Date(it.vencimento);
  data.textContent = isNaN(d.getTime()) ? "—" : d.toLocaleDateString("pt-BR");

  header.append(tipo, data);

  const nome = document.createElement("div");
  nome.className = "notif-message";
  nome.textContent = it.nome || "Certificado sem nome";

  const doc = document.createElement("div");
  doc.className = "notif-doc";
  doc.textContent = "Doc: " + (it.documento || "—");

  div.append(header, nome, doc);

  // Duplicidade não é escondida: o mesmo certificado em N arquivos vira uma
  // linha só, mas a contagem fica visível.
  const oc = Number(it.ocorrencias) || 1;
  if (oc > 1) {
    const dup = document.createElement("div");
    dup.className = "notif-doc";
    dup.textContent = `Encontrado em ${oc} arquivos`;
    div.appendChild(dup);
  }

  return div;
}

function _criarSecaoNotificacoes(titulo, total, itens) {
  const frag = document.createDocumentFragment();

  const h = document.createElement("p");
  h.className = "notif-section-title";
  h.textContent = total > itens.length ? `${titulo} (${itens.length} de ${total})` : `${titulo} (${total})`;
  frag.appendChild(h);

  itens.forEach((it) => frag.appendChild(_criarItemNotificacao(it)));
  return frag;
}

async function fetchNotifications() {
  const token = getToken();
  if (!token) return;
  const body = document.getElementById("notifications-body");
  if (!body) return;

  try {
    const r = await fetch("/api/colaborador/notificacoes", { headers: getHeaders() });
    if (!r.ok) {
      if (r.status === 401) logout();
      // Sem isto, o badge mantinha a contagem antiga após uma falha.
      _aplicarBadgeNotificacoes(null);
      body.innerHTML = "";
      body.appendChild(
        Object.assign(document.createElement("div"), {
          className: "notif-error",
          textContent: "Não foi possível carregar os alertas.",
        })
      );
      return;
    }

    const data = await r.json();
    const items = data.itens || [];
    _aplicarBadgeNotificacoes(data);

    body.innerHTML = "";

    if (!items.length) {
      body.appendChild(
        Object.assign(document.createElement("div"), {
          className: "notif-empty",
          textContent: "Tudo em dia! Nenhum certificado vencido ou a vencer.",
        })
      );
      return;
    }

    // Duas seções: primeiro o que ainda dá para evitar, depois o passivo.
    const expirando = items.filter((x) => x.tipo === "expiring");
    const vencidos = items.filter((x) => x.tipo === "expired");

    if (expirando.length) {
      body.appendChild(
        _criarSecaoNotificacoes("Expirando", Number(data.total_expirando) || expirando.length, expirando)
      );
    }
    if (vencidos.length) {
      body.appendChild(
        _criarSecaoNotificacoes("Vencidos", Number(data.total_vencidos) || vencidos.length, vencidos)
      );
    }

    // Rodapé: o que não coube continua alcançável, em vez de sumir.
    if (data.truncado) {
      const rodape = document.createElement("div");
      rodape.className = "notif-footer";

      const txt = document.createElement("span");
      txt.textContent = `Mostrando ${data.exibidos} de ${data.total}`;

      const link = document.createElement("a");
      link.href = "/vencidos";
      link.className = "notif-footer__link";
      link.textContent = "Ver lista completa";

      rodape.append(txt, link);
      body.appendChild(rodape);
    }
  } catch (e) {
    console.error("Erro ao carregar notificações", e);
    _aplicarBadgeNotificacoes(null);
    body.innerHTML = "";
    body.appendChild(
      Object.assign(document.createElement("div"), {
        className: "notif-error",
        textContent: "Falha de conexão ao carregar os alertas.",
      })
    );
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
    <button id="btn-notifications-toggle" type="button" class="sidebar-toggle-btn notifications-bell-btn" title="Alertas e notificações" aria-label="Alertas e notificações" aria-expanded="false" aria-haspopup="true" aria-controls="notifications-dropdown">
      <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
        <path stroke-linecap="round" stroke-linejoin="round" d="M14.857 17.082a23.848 23.848 0 005.454-1.31A8.967 8.967 0 0118 9.75v-.7V9A6 6 0 006 9v.75a8.967 8.967 0 01-2.312 6.022c1.733.64 3.56 1.085 5.455 1.31m5.714 0a24.255 24.255 0 01-5.714 0m5.714 0a3 3 0 11-5.714 0" />
      </svg>
      <span class="notification-badge" id="notification-badge" style="display: none;">0</span>
    </button>
    <div class="notifications-dropdown" id="notifications-dropdown" style="display: none;">
      <div class="notifications-header">
        <h3>Notificações</h3>
        <span class="notif-sync-mode" title="A lista é atualizada automaticamente enquanto esta aba está aberta">Automático</span>
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

  /** Fonte única de verdade para abrir/fechar: mantém aria-expanded em sincronia. */
  function definirDropdownAberto(aberto, devolverFoco) {
    dropdown.style.display = aberto ? "block" : "none";
    toggleBtn.setAttribute("aria-expanded", String(aberto));
    if (aberto) {
      fetchNotifications();
    } else if (devolverFoco) {
      // Devolve o foco a quem abriu (04 §4) — sem isso, ao fechar com Esc o
      // foco ficaria no <body> e a navegação por teclado recomeçaria do topo.
      toggleBtn.focus();
    }
  }

  toggleBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    definirDropdownAberto(dropdown.style.display !== "block", false);
  });

  document.addEventListener("click", (e) => {
    if (!e.target.closest("#notifications-container") && dropdown.style.display === "block") {
      definirDropdownAberto(false, false);
    }
  });

  // Esc fecha e devolve o foco. Registrado aqui (e não no handler global de
  // teclado) porque só este escopo conhece o botão que abriu o painel.
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && dropdown.style.display === "block") {
      definirDropdownAberto(false, true);
    }
  });

  fetchNotifications();

  // Atualização automática a cada 60s, PAUSADA com a aba em segundo plano.
  // Antes o timer rodava para sempre: uma aba deixada aberta o dia inteiro
  // gerava ~480 requisições autenticadas que ninguém veria (08 §6).
  const INTERVALO_NOTIF = 60000;
  let timerNotif = setInterval(fetchNotifications, INTERVALO_NOTIF);

  document.addEventListener("visibilitychange", () => {
    clearInterval(timerNotif);
    if (document.visibilityState === "visible") {
      // Busca imediata ao voltar: o dado pode estar 1h desatualizado.
      fetchNotifications();
      timerNotif = setInterval(fetchNotifications, INTERVALO_NOTIF);
    }
  });
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", () => {
    initSidebarPorPapel();
    initSidebarToggle();
    initThemeToggle();
    initNotifications();
    initRegioesRolaveis();
    _consumirToastPendente();
  });
} else {
  initSidebarPorPapel();
  initSidebarToggle();
  initThemeToggle();
  initNotifications();
  initRegioesRolaveis();
  _consumirToastPendente();
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

  // Tecla 'Escape' fecha modais ativos.
  // O painel de notificações NÃO é tratado aqui: initNotifications() registra o
  // próprio handler, que além de fechar devolve o foco ao botão que o abriu.
  if (e.key === 'Escape') {
    document.querySelectorAll('.modal, [role="dialog"]').forEach(modal => {
      if (modal.style.display !== 'none' && modal.classList.contains('active')) {
        modal.style.display = 'none';
        modal.classList.remove('active');
      }
    });
  }
});


/* ══════════════════════════════════════════════════════════════════════════
   Diálogos
   ══════════════════════════════════════════════════════════════════════════ */

/**
 * Substituto de `confirm()`, em `<dialog>` nativo.
 *
 * O `confirm()` do navegador trava a aba inteira, não aceita estilo, não diz
 * QUAL item está sendo afetado sem repetir tudo na mensagem, e em algumas
 * configurações o usuário pode marcar "não mostrar mais" e perder a pergunta.
 *
 * Devolve uma Promise<boolean>. Fechar no Esc ou no backdrop resolve `false` —
 * o padrão seguro: cancelar nunca deve ser mais difícil que confirmar.
 *
 * @param {{titulo:string, mensagem:string, textoConfirmar?:string,
 *          textoCancelar?:string, perigo?:boolean}} opcoes
 */
function confirmarAcao(opcoes) {
  const o = opcoes || {};
  return new Promise((resolve) => {
    const dlg = document.createElement("dialog");
    dlg.className = "modal";

    const head = document.createElement("div");
    head.className = "modal__head";
    const h2 = document.createElement("h2");
    // `textContent`, nunca innerHTML: o título costuma carregar nome ou e-mail
    // vindos do servidor, que derivam do CN do certificado.
    h2.textContent = o.titulo || "Confirmar";
    head.appendChild(h2);

    const body = document.createElement("div");
    body.className = "modal__body";
    const p = document.createElement("p");
    p.style.margin = "0";
    p.textContent = o.mensagem || "";
    body.appendChild(p);

    const foot = document.createElement("div");
    foot.className = "modal__foot";
    const btnNao = document.createElement("button");
    btnNao.type = "button";
    btnNao.className = "btn-action";
    btnNao.textContent = o.textoCancelar || "Cancelar";
    const btnSim = document.createElement("button");
    btnSim.type = "button";
    btnSim.className = o.perigo ? "btn-action btn-danger" : "primary";
    btnSim.textContent = o.textoConfirmar || "Confirmar";
    foot.appendChild(btnNao);
    foot.appendChild(btnSim);

    dlg.appendChild(head);
    dlg.appendChild(body);
    dlg.appendChild(foot);
    document.body.appendChild(dlg);

    let resposta = false;
    btnSim.addEventListener("click", () => { resposta = true; dlg.close(); });
    btnNao.addEventListener("click", () => dlg.close());
    // Clique no backdrop: o alvo é o próprio <dialog> só quando o clique cai
    // fora do conteúdo, porque os filhos capturam o resto.
    dlg.addEventListener("click", (e) => { if (e.target === dlg) dlg.close(); });
    dlg.addEventListener("close", () => {
      dlg.remove();
      resolve(resposta);
    });

    dlg.showModal();
    // Foco no cancelar, e não no confirmar: com o foco no botão de ação, um
    // Enter reflexo — de quem estava digitando — executaria a operação.
    btnNao.focus();
  });
}

/**
 * Abre um `<dialog class="modal">` que já existe no HTML da página.
 *
 * Existe para centralizar duas coisas que é fácil esquecer: fechar no clique
 * do backdrop (o `<dialog>` nativo NÃO faz isso sozinho) e devolver o foco a
 * quem abriu quando fecha — sem isso o foco volta para o começo da página e
 * quem navega por teclado se perde depois de cada edição.
 */
function abrirModal(id) {
  const dlg = document.getElementById(id);
  if (!dlg || typeof dlg.showModal !== "function") return null;
  const origem = document.activeElement;

  if (!dlg.dataset.ligado) {
    dlg.dataset.ligado = "1";
    dlg.addEventListener("click", (e) => { if (e.target === dlg) dlg.close(); });
  }
  dlg.addEventListener("close", function devolveFoco() {
    dlg.removeEventListener("close", devolveFoco);
    if (origem && typeof origem.focus === "function") origem.focus();
  });

  dlg.showModal();
  return dlg;
}
