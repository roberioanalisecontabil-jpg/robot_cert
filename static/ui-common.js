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
