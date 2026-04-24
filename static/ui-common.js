/**
 * Funções partilhadas entre o painel (/) e a configuração (/configuracao).
 * O token JWT fica no localStorage do browser.
 */
const KEY_STORAGE = "cert_robot_api_key"; // Agora armazena o Token JWT
const FONT_STORAGE = "cert_robot_data_fonte";

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

// Interceptar todas as requisições para verificar 401
const originalFetch = window.fetch;
window.fetch = async (...args) => {
    const response = await originalFetch(...args);
    if (response.status === 401 && !window.location.pathname.includes('/login')) {
        logout();
    }
    return response;
};
