/**
 * Funções partilhadas entre o painel (/) e a configuração (/configuracao).
 * A chave API fica no localStorage do browser (não no servidor).
 */
const KEY_STORAGE = "cert_robot_jwt";
const ROLE_STORAGE = "cert_robot_role";
const FONT_STORAGE = "cert_robot_data_fonte";

function getDataFonte() {
  return localStorage.getItem(FONT_STORAGE) || "auto";
}

function setDataFonte(v) {
  if (v) localStorage.setItem(FONT_STORAGE, v);
  else localStorage.removeItem(FONT_STORAGE);
}

function getJwtToken() {
  return localStorage.getItem(KEY_STORAGE) || "";
}

function setJwtToken(token) {
  if (token) localStorage.setItem(KEY_STORAGE, token);
  else localStorage.removeItem(KEY_STORAGE);
}

function getUserRole() {
  return localStorage.getItem(ROLE_STORAGE) || "user";
}

function logout() {
  localStorage.removeItem(KEY_STORAGE);
  localStorage.removeItem(ROLE_STORAGE);
  window.location.href = "/login";
}

function getHeaders(json) {
  const h = {};
  if (json) h["Content-Type"] = "application/json";
  const t = getJwtToken();
  if (t) {
    h["Authorization"] = "Bearer " + t;
  }
  return h;
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
