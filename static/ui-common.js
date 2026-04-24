/**
 * Funções partilhadas entre o painel (/) e a configuração (/configuracao).
 * A chave API fica no localStorage do browser (não no servidor).
 */
const KEY_STORAGE = "cert_robot_api_key";
const FONT_STORAGE = "cert_robot_data_fonte";

function getDataFonte() {
  return localStorage.getItem(FONT_STORAGE) || "auto";
}

function setDataFonte(v) {
  if (v) localStorage.setItem(FONT_STORAGE, v);
  else localStorage.removeItem(FONT_STORAGE);
}

function getApiKey() {
  const el = document.getElementById("api-key");
  const typed = el ? el.value.trim() : "";
  if (typed) return typed;
  return localStorage.getItem(KEY_STORAGE) || "";
}

function getHeaders(json) {
  const h = {};
  if (json) h["Content-Type"] = "application/json";
  const k = getApiKey();
  if (k) h["X-API-Key"] = k;
  return h;
}

function guardarChaveNoStorage() {
  const el = document.getElementById("api-key");
  const t = el ? el.value.trim() : "";
  if (t) localStorage.setItem(KEY_STORAGE, t);
  else localStorage.removeItem(KEY_STORAGE);
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
