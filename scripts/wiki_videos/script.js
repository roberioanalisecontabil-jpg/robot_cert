/* =========================================================================
   Apresentação cinematográfica em HTML — motor genérico

   Estrutura deste arquivo
     1. CONFIG ............ marca, textos, números e ajustes fáceis de editar
     2. Utilidades ........ easing, interpolação, ícones
     3. Réplica da UI ..... markup das telas do SEU produto, com dados FICTÍCIOS
     4. Roteiro ........... as cenas (duração, câmera, cursor, ações, legendas)
     5. Motor de timeline . estado = função do tempo (pausa/seek nunca dessincronizam)
     6. Áudio ............. trilha (arquivo local ou sintetizada) e efeitos sutis
     7. Player ............ controles, teclado, tela cheia

   O conteúdo de exemplo (app fictício "Acme Flow") está nas seções 3 e 4: troque-o pelo do seu produto.
   O motor (a partir da seção 5) não precisa mudar.
   ========================================================================= */
'use strict';

/* ------------------------------------------------------------------ 1. CONFIG */
const CONFIG = {
  produto: 'CertGuard',                                  // nome grande da abertura e do encerramento
  sistema: 'Wiki do CertGuard',                          // linha pequena sob o nome
  slogan: 'Contabilidade e Gestão Inteligente',
  logo: 'assets/logos/certguard.png',                    // o C dourado da bandeja (ico/certguard.png)
  logoPortal: 'assets/logos/certificado.png',            // o A do portal (static/logo.png)
  inicial: 'C',                                          // fallback do logotipo
  usuario: { nome: 'Colaborador Demo', primeiro: 'Colaborador', iniciais: 'CD', email: 'colaborador.demo@exemplo.com' },
  audio: {
    // Vídeos da wiki não têm música. Sem o arquivo, o player sintetiza uma trilha só se alguém pedir som;
    // o MP4 é gravado com --sem-audio.
    arquivo: 'assets/audio/trilha.mp3',
    volumeInicial: 0.6,
    fadeInSeg: 3.5,
    fadeOutSeg: 5,
  },
  ritmo: { bpm: 100 },
  veuSeg: { entra: 0.5, segura: 0.18, sai: 0.9 },
  numeros: {},
};


/* --------------------------------------------------------------- 2. UTILIDADES */
/* --------------------------------------------------------------- 2. UTILIDADES */
const clamp = (v, a = 0, b = 1) => Math.min(b, Math.max(a, v));
const lerp = (a, b, p) => a + (b - a) * p;
const EASE = {
  linear: (p) => p,
  out: (p) => 1 - Math.pow(1 - p, 3),
  in: (p) => p * p * p,
  io: (p) => (p < 0.5 ? 4 * p * p * p : 1 - Math.pow(-2 * p + 2, 3) / 2),
  outBack: (p) => { const c1 = 1.70158, c3 = c1 + 1; return 1 + c3 * Math.pow(p - 1, 3) + c1 * Math.pow(p - 1, 2); },
  outExpo: (p) => (p >= 1 ? 1 : 1 - Math.pow(2, -10 * p)),
  soft: (p) => p * p * (3 - 2 * p),
};
const seg = (t, a, b, ease = 'io') => EASE[ease](clamp((t - a) / Math.max(1e-6, b - a)));
const fmtTempo = (s) => { s = Math.max(0, Math.floor(s)); return String(Math.floor(s / 60)).padStart(2, '0') + ':' + String(s % 60).padStart(2, '0'); };
const REAIS = new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' });
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

/* Ícones: traçado estilo Lucide (24×24). Só os nomes listados existem; nome inexistente renderiza vazio. */
const ICONS = {"check": "<path d=\"M20 6 9 17l-5-5\"/>", "check-circle": "<circle cx=\"12\" cy=\"12\" r=\"10\"/><path d=\"m9 12 2 2 4-4\"/>", "alert-triangle": "<path d=\"m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3\"/><path d=\"M12 9v4\"/><path d=\"M12 17h.01\"/>", "info": "<circle cx=\"12\" cy=\"12\" r=\"10\"/><path d=\"M12 16v-4\"/><path d=\"M12 8h.01\"/>", "x": "<path d=\"M18 6 6 18\"/><path d=\"m6 6 12 12\"/>", "chevron-down": "<path d=\"m6 9 6 6 6-6\"/>", "chevron-left": "<path d=\"m15 18-6-6 6-6\"/>", "chevron-right": "<path d=\"m9 18 6-6-6-6\"/>", "arrow-down": "<path d=\"M12 5v14\"/><path d=\"m19 12-7 7-7-7\"/>", "search": "<circle cx=\"11\" cy=\"11\" r=\"8\"/><path d=\"m21 21-4.3-4.3\"/>", "plus": "<path d=\"M5 12h14\"/><path d=\"M12 5v14\"/>", "pencil": "<path d=\"M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.497z\"/><path d=\"m15 5 4 4\"/>", "download": "<path d=\"M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4\"/><polyline points=\"7 10 12 15 17 10\"/><line x1=\"12\" x2=\"12\" y1=\"15\" y2=\"3\"/>", "upload": "<path d=\"M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4\"/><polyline points=\"17 8 12 3 7 8\"/><line x1=\"12\" x2=\"12\" y1=\"3\" y2=\"15\"/>", "file-down": "<path d=\"M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z\"/><path d=\"M14 2v4a2 2 0 0 0 2 2h4\"/><path d=\"M12 18v-6\"/><path d=\"m9 15 3 3 3-3\"/>", "layers": "<path d=\"m12.83 2.18a2 2 0 0 0-1.66 0L2.6 6.08a1 1 0 0 0 0 1.83l8.58 3.91a2 2 0 0 0 1.66 0l8.58-3.9a1 1 0 0 0 0-1.83z\"/><path d=\"M2 12a1 1 0 0 0 .58.91l8.6 3.91a2 2 0 0 0 1.65 0l8.58-3.9A1 1 0 0 0 22 12\"/><path d=\"M2 17a1 1 0 0 0 .58.91l8.6 3.91a2 2 0 0 0 1.65 0l8.58-3.9A1 1 0 0 0 22 17\"/>", "filter": "<polygon points=\"22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3\"/>", "list": "<path d=\"M3 5h.01\"/><path d=\"M3 12h.01\"/><path d=\"M3 19h.01\"/><path d=\"M8 5h13\"/><path d=\"M8 12h13\"/><path d=\"M8 19h13\"/>", "refresh-cw": "<path d=\"M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8\"/><path d=\"M21 3v5h-5\"/><path d=\"M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16\"/><path d=\"M8 16H3v5\"/>", "eye": "<path d=\"M2.062 12.348a1 1 0 0 1 0-.696 10.75 10.75 0 0 1 19.876 0 1 1 0 0 1 0 .696 10.75 10.75 0 0 1-19.876 0\"/><circle cx=\"12\" cy=\"12\" r=\"3\"/>", "file-text": "<path d=\"M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z\"/><path d=\"M14 2v4a2 2 0 0 0 2 2h4\"/><path d=\"M16 13H8\"/><path d=\"M16 17H8\"/><path d=\"M10 9H8\"/>", "paperclip": "<path d=\"M13.234 20.252 21 12.3\"/><path d=\"m16 6-8.414 8.586a2 2 0 0 0 0 2.828 2 2 0 0 0 2.828 0l8.414-8.586a4 4 0 0 0 0-5.656 4 4 0 0 0-5.656 0l-8.415 8.585a6 6 0 1 0 8.486 8.486\"/>", "image": "<rect width=\"18\" height=\"18\" x=\"3\" y=\"3\" rx=\"2\" ry=\"2\"/><circle cx=\"9\" cy=\"9\" r=\"2\"/><path d=\"m21 15-3.086-3.086a2 2 0 0 0-2.828 0L6 21\"/>", "user": "<path d=\"M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2\"/><circle cx=\"12\" cy=\"7\" r=\"4\"/>", "users": "<path d=\"M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2\"/><circle cx=\"9\" cy=\"7\" r=\"4\"/><path d=\"M22 21v-2a4 4 0 0 0-3-3.87\"/><path d=\"M16 3.13a4 4 0 0 1 0 7.75\"/>", "building": "<path d=\"M6 22V4a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v18Z\"/><path d=\"M6 12H4a2 2 0 0 0-2 2v6a2 2 0 0 0 2 2h2\"/><path d=\"M18 9h2a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2h-2\"/><path d=\"M10 6h4\"/><path d=\"M10 10h4\"/><path d=\"M10 14h4\"/><path d=\"M10 18h4\"/>", "calendar": "<path d=\"M8 2v4\"/><path d=\"M16 2v4\"/><rect width=\"18\" height=\"18\" x=\"3\" y=\"4\" rx=\"2\"/><path d=\"M3 10h18\"/>", "book-open": "<path d=\"M12 7v14\"/><path d=\"M3 18a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h5a4 4 0 0 1 4 4 4 4 0 0 1 4-4h5a1 1 0 0 1 1 1v13a1 1 0 0 1-1 1h-6a3 3 0 0 0-3 3 3 3 0 0 0-3-3z\"/>", "id-card": "<path d=\"M16 10h2\"/><path d=\"M16 14h2\"/><path d=\"M6.17 15a3 3 0 0 1 5.66 0\"/><circle cx=\"9\" cy=\"11\" r=\"2\"/><rect x=\"2\" y=\"5\" width=\"20\" height=\"14\" rx=\"2\"/>", "trash": "<path d=\"M3 6h18\"/><path d=\"M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6\"/><path d=\"M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2\"/><line x1=\"10\" x2=\"10\" y1=\"11\" y2=\"17\"/><line x1=\"14\" x2=\"14\" y1=\"11\" y2=\"17\"/>", "archive": "<rect width=\"20\" height=\"5\" x=\"2\" y=\"3\" rx=\"1\"/><path d=\"M4 8v11a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8\"/><path d=\"M10 12h4\"/>", "copy": "<rect width=\"14\" height=\"14\" x=\"8\" y=\"8\" rx=\"2\" ry=\"2\"/><path d=\"M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2\"/>", "phone": "<path d=\"M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6A19.79 19.79 0 0 1 2.12 4.18 2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72c.13.96.36 1.9.7 2.81a2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45c.9.34 1.85.57 2.81.7A2 2 0 0 1 22 16.92z\"/>", "message-circle": "<path d=\"M7.9 20A9 9 0 1 0 4 16.1L2 22Z\"/>", "video": "<path d=\"m16 13 5.223 3.482a.5.5 0 0 0 .777-.416V7.87a.5.5 0 0 0-.752-.432L16 10.5\"/><rect x=\"2\" y=\"6\" width=\"14\" height=\"12\" rx=\"2\"/>", "mail": "<rect width=\"20\" height=\"16\" x=\"2\" y=\"4\" rx=\"2\"/><path d=\"m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7\"/>", "flame": "<path d=\"M8.5 14.5A2.5 2.5 0 0 0 11 12c0-1.38-.5-2-1-3-1.072-2.143-.224-4.054 2-6 .5 2.5 2 4.9 4 6.5 2 1.6 3 3.5 3 5.5a7 7 0 1 1-14 0c0-1.153.433-2.294 1-3a2.5 2.5 0 0 0 2.5 2.5z\"/>", "cake": "<path d=\"M20 21v-8a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8\"/><path d=\"M4 16s.5-1 2-1 2.5 2 4 2 2.5-2 4-2 2.5 2 4 2 2-1 2-1\"/><path d=\"M2 21h20\"/><path d=\"M7 8v3\"/><path d=\"M12 8v3\"/><path d=\"M17 8v3\"/><path d=\"M7 4h.01\"/><path d=\"M12 4h.01\"/><path d=\"M17 4h.01\"/>", "gift": "<rect x=\"3\" y=\"8\" width=\"18\" height=\"4\" rx=\"1\"/><path d=\"M12 8v13\"/><path d=\"M19 12v7a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2v-7\"/><path d=\"M7.5 8a2.5 2.5 0 0 1 0-5A4.8 8 0 0 1 12 8a4.8 8 0 0 1 4.5-5 2.5 2.5 0 0 1 0 5\"/>", "briefcase": "<path d=\"M16 20V4a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16\"/><rect width=\"20\" height=\"14\" x=\"2\" y=\"6\" rx=\"2\"/>", "receipt": "<path d=\"M4 2v20l2-1 2 1 2-1 2 1 2-1 2 1 2-1 2 1V2l-2 1-2-1-2 1-2-1-2 1-2-1-2 1Z\"/><path d=\"M16 8h-6a2 2 0 1 0 0 4h4a2 2 0 1 1 0 4H8\"/><path d=\"M12 17.5v-11\"/>", "key": "<path d=\"m15.5 7.5 2.3 2.3a1 1 0 0 0 1.4 0l2.1-2.1a1 1 0 0 0 0-1.4L19 4\"/><path d=\"m21 2-9.6 9.6\"/><circle cx=\"7.5\" cy=\"15.5\" r=\"5.5\"/>", "lock": "<rect width=\"18\" height=\"11\" x=\"3\" y=\"11\" rx=\"2\" ry=\"2\"/><path d=\"M7 11V7a5 5 0 0 1 10 0v4\"/>", "star": "<path d=\"M11.525 2.295a.53.53 0 0 1 .95 0l2.31 4.679a2.123 2.123 0 0 0 1.595 1.16l5.166.756a.53.53 0 0 1 .294.904l-3.736 3.638a2.123 2.123 0 0 0-.611 1.878l.882 5.14a.53.53 0 0 1-.771.56l-4.618-2.428a2.122 2.122 0 0 0-1.973 0L6.396 21.01a.53.53 0 0 1-.77-.56l.881-5.139a2.122 2.122 0 0 0-.611-1.879L2.16 9.795a.53.53 0 0 1 .294-.906l5.165-.755a2.122 2.122 0 0 0 1.597-1.16z\"/>", "home": "<path d=\"M15 21v-8a1 1 0 0 0-1-1h-4a1 1 0 0 0-1 1v8\"/><path d=\"M3 10a2 2 0 0 1 .709-1.528l7-5.999a2 2 0 0 1 2.582 0l7 5.999A2 2 0 0 1 21 10v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z\"/>", "shield-check": "<path d=\"M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z\"/><path d=\"m9 12 2 2 4-4\"/>", "package": "<path d=\"m7.5 4.27 9 5.15\"/><path d=\"M21 8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z\"/><path d=\"m3.3 7 8.7 5 8.7-5\"/><path d=\"M12 22V12\"/>", "arrow-left-right": "<path d=\"M8 3 4 7l4 4\"/><path d=\"M4 7h16\"/><path d=\"m16 21 4-4-4-4\"/><path d=\"M20 17H4\"/>", "scale": "<path d=\"m16 16 3-8 3 8c-.87.65-1.92 1-3 1s-2.13-.35-3-1Z\"/><path d=\"m2 16 3-8 3 8c-.87.65-1.92 1-3 1s-2.13-.35-3-1Z\"/><path d=\"M7 21h10\"/><path d=\"M12 3v18\"/><path d=\"M3 7h2c2 0 5-1 7-2 2 1 5 2 7 2h2\"/>", "calculator": "<rect width=\"16\" height=\"20\" x=\"4\" y=\"2\" rx=\"2\"/><line x1=\"8\" x2=\"16\" y1=\"6\" y2=\"6\"/><line x1=\"16\" x2=\"16\" y1=\"14\" y2=\"18\"/><path d=\"M16 10h.01\"/><path d=\"M12 10h.01\"/><path d=\"M8 10h.01\"/><path d=\"M12 14h.01\"/><path d=\"M8 14h.01\"/><path d=\"M12 18h.01\"/><path d=\"M8 18h.01\"/>", "trending-down": "<path d=\"M16 17h6v-6\"/><path d=\"m22 17-8.5-8.5-5 5L2 7\"/>", "trending-up": "<path d=\"M16 7h6v6\"/><path d=\"m22 7-8.5 8.5-5-5L2 17\"/>", "table": "<path d=\"M12 3v18\"/><rect width=\"18\" height=\"18\" x=\"3\" y=\"3\" rx=\"2\"/><path d=\"M3 9h18\"/><path d=\"M3 15h18\"/>", "grid": "<rect width=\"7\" height=\"7\" x=\"3\" y=\"3\" rx=\"1\"/><rect width=\"7\" height=\"7\" x=\"14\" y=\"3\" rx=\"1\"/><rect width=\"7\" height=\"7\" x=\"14\" y=\"14\" rx=\"1\"/><rect width=\"7\" height=\"7\" x=\"3\" y=\"14\" rx=\"1\"/>", "log-out": "<path d=\"M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4\"/><polyline points=\"16 17 21 12 16 7\"/><line x1=\"21\" x2=\"9\" y1=\"12\" y2=\"12\"/>", "bell": "<path d=\"M10.268 21a2 2 0 0 0 3.464 0\"/><path d=\"M3.262 15.326A1 1 0 0 0 4 17h16a1 1 0 0 0 .74-1.673C19.41 13.956 18 12.499 18 8A6 6 0 0 0 6 8c0 4.499-1.411 5.956-2.738 7.326\"/>", "sun": "<circle cx=\"12\" cy=\"12\" r=\"4\"/><path d=\"M12 2v2\"/><path d=\"M12 20v2\"/><path d=\"m4.93 4.93 1.41 1.41\"/><path d=\"m17.66 17.66 1.41 1.41\"/><path d=\"M2 12h2\"/><path d=\"M20 12h2\"/><path d=\"m6.34 17.66-1.41 1.41\"/><path d=\"m19.07 4.93-1.41 1.41\"/>", "moon": "<path d=\"M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9\"/>"};
const ic = (name, size = 18, cls = '') =>
  `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="ag-icon ${cls}" aria-hidden="true">${ICONS[name] || ''}</svg>`;

/* ------------------------------------------------------- 3. RÉPLICA DA INTERFACE */
/*
  Réplicas do portal Analise Certificado e da bandeja CertGuard Análise, copiadas dos templates reais
  (templates/index.html, vencidos.html, colaborador_certificados.html, login.html, static/ui-common.js e
  estacao/bandeja.py). Rótulos e mensagens são os do produto; empresas, documentos e e-mails são FICTÍCIOS.
*/
Object.assign(ICONS, {
  clock: '<circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>',
  smartphone: '<rect width="14" height="20" x="5" y="2" rx="2" ry="2"/><path d="M12 18h.01"/>',
  shield: '<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/>',
  'list-checks': '<path d="m3 17 2 2 4-4"/><path d="m3 7 2 2 4-4"/><path d="M13 6h8"/><path d="M13 12h8"/><path d="M13 18h8"/>',
  'chart-line': '<path d="M3 3v16a2 2 0 0 0 2 2h16"/><path d="m19 9-5 5-4-4-3 3"/>',
  'chevron-up': '<path d="m18 15-6-6-6 6"/>',
  wifi: '<path d="M12 20h.01"/><path d="M2 8.82a15 15 0 0 1 20 0"/><path d="M5 12.859a10 10 0 0 1 14 0"/><path d="M8.5 16.429a5 5 0 0 1 7 0"/>',
  volume: '<path d="M11 4.702a.705.705 0 0 0-1.203-.498L6.413 7.587A1.4 1.4 0 0 1 5.416 8H3a1 1 0 0 0-1 1v6a1 1 0 0 0 1 1h2.416a1.4 1.4 0 0 1 .997.413l3.383 3.384A.705.705 0 0 0 11 19.298z"/><path d="M16 9a5 5 0 0 1 0 6"/>',
});

const EMAIL = CONFIG.usuario.email;
// Início: dados FICTÍCIOS (documentos inventados, sem dígito verificador real).
const CERTS = [
  { n: 1, st: 'Expirando', nome: 'Academia Movimento Livre Ltda', em: '02/11/2025', ve: '02/11/2026', doc: '10.000.001/0001-01' },
  { n: 2, st: 'Ativo',     nome: 'Cafeteria Bom Grão Ltda',       em: '15/01/2026', ve: '15/01/2027', doc: '10.000.002/0001-02' },
  { n: 3, st: 'Ativo',     nome: 'Clínica Sorriso Claro Ltda',    em: '20/03/2026', ve: '20/03/2027', doc: '10.000.003/0001-03', sieg: true, bloq: true },
  { n: 4, st: 'Expirando', nome: 'Distribuidora Rio Azul Ltda',   em: '10/11/2025', ve: '10/11/2026', doc: '10.000.004/0001-04' },
  { n: 5, st: 'Ativo',     nome: 'Escola Primeiros Passos Ltda',  em: '08/05/2026', ve: '08/05/2027', doc: '10.000.005/0001-05', bloq: true },
  { n: 6, st: 'Expirando', nome: 'Oficina Roda Firme Ltda',       em: '15/11/2025', ve: '15/11/2026', doc: '10.000.006/0001-06' },
  { n: 7, st: 'Ativo',     nome: 'Mercado Bairro Feliz Ltda',     em: '30/06/2026', ve: '30/06/2027', doc: '10.000.007/0001-07' },
];
const VENCIDOS = [
  { nome: 'PAPELARIA PONTO CERTO LTDA',   doc: '10.000.011/0001-11', ve: '18/10/2026', ha: 'há 5 dias' },
  { nome: 'PADARIA TRIGO DOURADO LTDA',   doc: '10.000.012/0001-12', ve: '30/09/2026', ha: 'há 23 dias' },
  { nome: 'TRANSPORTES ESTRADA BOA LTDA', doc: '10.000.013/0001-13', ve: '02/08/2026', ha: 'há 2 meses' },
];
const ALCANCE = [
  { n: 1, nome: 'ACADEMIA MOVIMENTO LIVRE LTDA', doc: '10.000.001/0001-01', ve: '02/11/2026', em: 'em 10 dias',  st: 'Expirando' },
  { n: 2, nome: 'CAFETERIA BOM GRÃO LTDA',       doc: '10.000.002/0001-02', ve: '15/01/2027', em: 'em 84 dias',  st: 'Ativo' },
  { n: 3, nome: 'DISTRIBUIDORA RIO AZUL LTDA',   doc: '10.000.004/0001-04', ve: '10/11/2026', em: 'em 18 dias',  st: 'Expirando' },
  { n: 4, nome: 'MERCADO BAIRRO FELIZ LTDA',     doc: '10.000.007/0001-07', ve: '30/06/2027', em: 'em 250 dias', st: 'Ativo' },
  { n: 5, nome: 'OFICINA RODA FIRME LTDA',       doc: '10.000.006/0001-06', ve: '15/11/2026', em: 'em 23 dias',  st: 'Expirando' },
  { n: 6, nome: 'PAPELARIA PONTO CERTO LTDA',    doc: '10.000.011/0001-11', ve: '18/10/2026', em: 'há 5 dias',   st: 'Vencido' },
];
const BADGE = { Ativo: ['success', 'check'], Expirando: ['warning', 'alert-triangle'], Vencido: ['danger', 'x'] };
const badge = (st) => `<span class="ag-badge ag-badge--${BADGE[st][0]}">${ic(BADGE[st][1], 13)} ${st}</span>`;
const chk = (id = '', cls = '') => `<span class="ag-checkbox ${cls}"${id ? ` id="${id}"` : ''}>${ic('check', 13)}</span>`;

const link = (id, icone, txt, extra = '') =>
  `<div class="sidebar-link" id="${id}">${ic(icone, 18)}<span>${txt}</span>${extra}</div>`;
const head = (eyebrow, titulo, lead, extra = '') =>
  `<div class="ag-page__head">${eyebrow ? `<div class="ag-page__eyebrow">${eyebrow}</div>` : ''}${extra}<h1 class="ag-page__title">${titulo}</h1>${lead ? `<p class="ag-page__lead">${lead}</p>` : ''}</div>`;
const campo = (label, id, ph, extra = '', cls = '') =>
  `<div><label class="ag-label">${label}</label><div class="ag-input ${cls}" id="${id}"><span class="ph">${ph}</span><span class="val"></span><span class="caret"></span></div>${extra}</div>`;
const selecao = (label, id, val, dd = '') =>
  `<div style="position:relative"><label class="ag-label">${label}</label><div class="ag-select" id="${id}"><span class="val">${val}</span>${ic('chevron-down', 16)}</div>${dd}</div>`;
const kpi = (rot, val, sub, icone, cls = '', id = '') =>
  `<div class="ag-kpi cg-kpi ${cls}"${id ? ` id="${id}"` : ''}><div><div class="ag-kpi__label">${rot}</div><div class="ag-kpi__value">${val}</div><div class="ag-kpi__delta">${sub}</div></div><span class="cg-kpi__icone">${ic(icone, 20)}</span></div>`;
const lgCampo = (label, id, ph, olho = false, cls = '') =>
  `<label class="lg-label">${label}</label><div class="lg-in ${cls}" id="${id}"><span class="ph">${ph}</span><span class="val"></span><span class="caret"></span>${olho ? `<span class="lg-olho">${ic('eye', 18)}</span>` : ''}</div>`;

/* O portal não tem barra superior: a marca fica no topo do menu lateral e o sino e o tema no canto da página. */
function htmlNavbar() {
  return `<div class="topo-acoes"><span class="topo-btn">${ic('bell', 20)}<i>2</i></span><span class="topo-btn">${ic('moon', 20)}</span></div>`;
}

function htmlSidebars() {
  return `
  <aside class="sidebar">
    <div class="sidebar-set" id="sb-portal">
      <div class="sb-marca"><img src="${CONFIG.logoPortal}" alt="" width="40" height="40"><div><b>Analise<br>Certificado</b><small>Monitor de Certificados</small></div></div>
      <div class="sb-recolher">${ic('list', 16)}</div>
      ${link('nav-inicio', 'home', 'Início')}
      ${link('nav-historico', 'clock', 'Histórico')}
      ${link('nav-vencidos', 'alert-triangle', 'Vencidos')}
      ${link('nav-duplicidades', 'copy', 'Duplicidades')}
      ${link('nav-acomp', 'chart-line', 'Acompanhamento')}
      ${link('nav-wiki', 'book-open', 'Wiki')}
      ${link('nav-app', 'smartphone', 'App autenticador')}
      <div class="sidebar-link sb-sair">${ic('log-out', 18)}<span>Sair</span></div>
    </div>
  </aside>`;
}

function htmlPaginas() {
  /* --- Bandeja: área de trabalho do Windows com o ícone perto do relógio e o menu do ícone --- */
  const desktop = `
  <section class="page cover dk" id="pg-desktop">
    <div class="dk-barra">
      <div class="dk-centro"><i class="dk-win"></i><i></i><i></i><i></i><i></i></div>
    </div>
    <div class="dk-canto" id="dk-canto">
      <div class="dk-menu" id="dk-menu" style="opacity:0;visibility:hidden">
        <div class="dk-m dk-m--off" id="dk-m-status">Certificados: ${EMAIL} — computador autorizado</div>
        <div class="dk-m"><b>Status e histórico</b></div>
        <div class="dk-m">Entrar no portal de certificados...</div>
        <div class="dk-m">Sair da conta de certificados</div>
        <div class="dk-m">Fechar</div>
      </div>
      <div class="dk-tray">
        <span>${ic('chevron-up', 16)}</span>
        <span class="dk-ico" id="dk-ico"><img src="${CONFIG.logo}" alt="" width="22" height="22"></span>
        <span>${ic('wifi', 16)}</span><span>${ic('volume', 16)}</span>
        <span class="dk-hora">09:12<br>23/10/2026</span>
      </div>
    </div>
  </section>`;

  /* --- Início (templates/index.html) --- */
  const linhas = CERTS.map((c) => `
    <tr id="in-row-${c.n}" class="${c.st === 'Expirando' ? '' : 'in-nexp'}">
      <td class="c-sel">${chk(`in-chk-${c.n}`, c.bloq ? 'is-dis' : '')}</td>
      <td>${badge(c.st)}${c.sieg ? ' <span class="ag-badge ag-badge--success">SIEG</span>' : ''}</td>
      <td>${c.nome}</td><td class="mono">${c.em}</td><td class="mono">${c.ve}</td>
      <td><span class="cg-tipo">CNPJ</span> <span class="mono">${c.doc}</span></td>
    </tr>`).join('');
  const ddStatus = `<div class="m-dd" id="dd-status"><div class="m-dd__it">Todos</div><div class="m-dd__it">Ativo</div><div class="m-dd__it" id="dd-st-exp">Expirando</div></div>`;
  const inicio = `
  <section class="page" id="pg-inicio">
    ${head('', 'Painel de Certificados', 'Veja os certificados dos seus clientes e instale-os na sua estação.')}
    <div class="cg-kpis" id="in-kpis">
      ${kpi('Total', '36', 'Certificados mapeados', 'shield')}
      ${kpi('Ativo', '29', 'Válidos e prontos para instalar', 'check-circle')}
      ${kpi('Expirando', '7', 'Vencem nos próximos 30 dias', 'clock', 'cg-kpi--exp', 'in-kpi-exp')}
    </div>
    <div class="ag-card cg-lista" id="in-card">
      <div class="cg-barra" id="in-acoes">
        ${selecao('Status', 'in-status', 'Todos', ddStatus)}
        ${selecao('SIEG', 'in-sieg', 'Todos')}
        ${campo('Buscar', 'in-busca', 'Nome, CNPJ ou CPF')}
        <span class="ag-btn ag-btn--outline" id="in-selecionar">${ic('list-checks', 16)}<span class="rot">Selecionar</span></span>
        <span class="ag-btn ag-btn--primary hide" id="in-instalar">${ic('download', 16)} Instalar selecionados (1)</span>
        <span class="ag-btn ag-btn--outline">${ic('file-down', 16)} Exportar ${ic('chevron-down', 14)}</span>
        <span class="ag-btn ag-btn--outline">${ic('refresh-cw', 16)} Atualizar tabela</span>
      </div>
      <p class="cg-meta">Atualizado em 23/10/2026, 09:12:00 · 3 vencidos não listados — <u>ver Vencidos</u></p>
      <p class="cg-nsel hide" id="in-n-sel">1 certificado selecionado</p>
      <div class="ag-table-wrap" id="in-tabwrap"><table class="ag-table" id="in-tab">
        <thead><tr><th class="c-sel">${chk()}</th><th>Status</th><th>Nome (titular)</th><th>Emissão</th><th>Vencimento</th><th>CNPJ / CPF</th></tr></thead>
        <tbody>${linhas}</tbody></table></div>
    </div>
    <div class="p-toast info" id="t-pedido" style="opacity:0;visibility:hidden">${ic('info', 18)}<span>Pedido enviado. Acompanhando a instalação…</span><i>×</i></div>
    <div class="p-toast ok" id="t-ok" style="opacity:0;visibility:hidden">${ic('check-circle', 18)}<span>Certificado instalado em PC-EXEMPLO-01.</span><i>×</i></div>
    <div class="w-toast" id="w-toast" style="opacity:0;visibility:hidden"><b>CertGuard Análise</b><span>1 certificado(s) instalado(s).</span></div>
    <div class="m-veu" id="ds-veu"></div>
    <div class="m-modal ds" id="ds-modal">
      <div class="ds-head"><h2>Defina sua senha</h2><p>A senha atual foi definida por outra pessoa. Escolha uma que só você saiba para continuar usando o portal.</p></div>
      <div class="ds-body">
        ${campo('Senha atual', 'ds-atual', '')}
        ${campo('Nova senha', 'ds-nova', 'mínimo 12 caracteres', '', 'ds-olho')}
        ${campo('Repita a nova senha', 'ds-conf', '')}
      </div>
      <div class="ds-foot"><span class="ag-btn ag-btn--outline">Sair</span><span class="ag-btn ds-escuro" id="ds-btn">Definir senha</span></div>
    </div>
  </section>`;

  /* --- Vencidos (templates/vencidos.html) --- */
  const vlinhas = VENCIDOS.map((v, i) => `
    <tr id="vc-row-${i + 1}"><td><span class="ag-cell-main">${v.nome}</span><span class="ag-cell-sub"><span class="cg-tipo">CNPJ</span> <span class="mono">${v.doc}</span></span></td>
    <td class="vc-dir"><span class="mono">${v.ve}</span><span class="ag-cell-sub">${v.ha}</span></td></tr>`).join('');
  const vencidos = `
  <section class="page" id="pg-vencidos">
    ${head('Monitor de certificados', 'Certificados vencidos', 'Clientes cujo certificado vigente já passou do vencimento. Filtre por período ou deixe as datas em branco para ver todos.')}
    <div class="cg-kpis cg-kpis--2" id="vc-kpis">
      ${kpi('Total de vencidos', '3', 'Em todo o período, sem filtro de datas', 'alert-triangle', 'cg-kpi--perigo', 'vc-total')}
      <div class="ag-kpi cg-kpi"><div style="flex:1"><div class="ag-kpi__label">Vencidos por ano</div>
        <div class="cg-ano"><span class="mono">2026</span><div class="ag-barchart__track"><div class="ag-barchart__fill" style="--barra:100%"></div></div><span class="mono">3</span></div>
        <div class="ag-kpi__delta">Um ano com vencidos</div></div></div>
    </div>
    <div class="ag-card cg-lista" id="vc-card">
      <div class="cg-barra cg-barra--vc">
        ${campo('Buscar', 'vc-busca', 'Nome, CNPJ/CPF ou data')}
        ${campo('Vencimento de', 'vc-de', 'dd/mm/yyyy')}
        ${campo('Até', 'vc-ate', 'dd/mm/yyyy')}
        <span class="ag-btn ag-btn--primary">${ic('filter', 16)} Filtrar</span>
        <span class="ag-btn ag-btn--outline">${ic('file-down', 16)} Exportar ${ic('chevron-down', 14)}</span>
      </div>
      <p class="cg-meta">3 vencidos · mostrando 1–3, do vencimento mais recente ao mais antigo &nbsp; Atualizado em 23/10/2026, 09:12:00</p>
      <div class="ag-table-wrap" id="vc-tab"><table class="ag-table"><thead><tr><th>Cliente</th><th class="vc-dir" style="color:var(--text-brand)">Vencimento ${ic('chevron-down', 12)}</th></tr></thead><tbody>${vlinhas}</tbody></table></div>
    </div>
  </section>`;

  /* --- Acompanhamento (templates/colaborador_certificados.html) --- */
  const alinhas = ALCANCE.map((a) => `
    <tr id="ac-row-${a.n}"><td class="c-sel">${chk(`ac-chk-${a.n}`)}</td>
      <td><span class="ag-cell-main">${a.nome}</span><span class="ag-cell-sub mono">${a.doc}</span></td>
      <td><span class="mono">${a.ve}</span><span class="ag-cell-sub">${a.em}</span></td><td>${badge(a.st)}</td></tr>`).join('');
  const acompanhados = ALCANCE.slice(0, 2).map((a) => `
    <tr><td><span class="ag-cell-main">${a.nome}</span><span class="ag-cell-sub mono">${a.doc}</span></td>
      <td><span class="mono">${a.ve}</span><span class="ag-cell-sub">${a.em}</span></td><td>${badge(a.st)}</td></tr>`).join('');
  const marcos = [30, 15, 7, 1].map((m) => `<span class="ac-marco" id="ac-marco-${m}">${chk('', 'is-on')} ${m} ${m === 1 ? 'dia' : 'dias'}</span>`).join('');
  const acomp = `
  <section class="page" id="pg-acomp">
    ${head('', 'Acompanhamento de certificados', 'Os certificados que você escolheu acompanhar, com os próximos vencimentos e o aviso por e-mail.')}
    <div class="cg-abas"><span class="cg-aba" id="ac-tab-acomp">Acompanhados <span class="n mono">(0)</span></span><span class="cg-aba" id="ac-tab-esc">Escolher certificados</span><span class="cg-aba">Avisos enviados</span></div>
    <div class="cg-paineis">
      <div class="ac-painel" id="ac-p-vazio" style="opacity:0;visibility:hidden">
        <div class="ac-vazio">${ic('chart-line', 28)}<b>Você ainda não acompanha nenhum certificado</b><span>Escolha os clientes da sua carteira para ver os vencimentos aqui.</span><span class="ag-btn ag-btn--primary">Escolher certificados</span></div>
      </div>
      <div class="ac-painel" id="ac-p-esc" style="opacity:0;visibility:hidden">
        <div class="ac-busca">${ic('search', 16)}<span>Nome ou CNPJ/CPF</span></div>
        <p class="cg-meta">6 clientes ao seu alcance</p>
        <div class="ag-table-wrap" id="ac-esc-tab"><table class="ag-table"><thead><tr><th class="c-sel"></th><th>Cliente</th><th>Vencimento</th><th>Status</th></tr></thead><tbody>${alinhas}</tbody></table></div>
      </div>
      <div class="ac-painel" id="ac-p-lista" style="opacity:0;visibility:hidden">
        <div class="cg-kpis cg-kpis--3p">
          ${kpi('Vencidos', '0', 'Já passaram do vencimento', 'alert-triangle')}
          ${kpi('A vencer em 30 dias', '1', 'Nos próximos 30 dias', 'clock')}
          ${kpi('Ativos', '1', 'Com mais de 30 dias de validade', 'check-circle')}
        </div>
        <div class="ac-aviso" id="ac-aviso-box">
          <div class="ac-aviso__linha" id="ac-aviso">${ic('mail', 18)}<span id="ac-aviso-txt">Aviso por e-mail</span><span class="ac-dest">para ${EMAIL}</span><span id="ac-aviso-estado"><span class="ag-badge ag-badge--neutral">Desligado</span></span><span class="ac-seta">${ic('chevron-down', 16)}</span></div>
          <div class="ac-aviso__corpo" id="ac-aviso-corpo">
            <div class="ac-quero" id="ac-quero">${chk('ac-quero-chk')} Quero receber aviso dos certificados que acompanho</div>
            <div class="ac-leg">Avisar quando faltarem</div>
            <div class="ac-marcos" id="ac-marcos">${marcos}</div>
            <p class="ac-dica">Desmarcar um prazo dispensa só o lembrete. O aviso de vencimento continua chegando.</p>
            <div class="ac-acoes"><span class="ag-btn ag-btn--outline is-off" id="ac-pref-salvar">Salvar preferência</span><span class="ac-msg" id="ac-pref-msg" style="opacity:0;visibility:hidden">Preferência salva.</span></div>
          </div>
        </div>
        <div class="ag-table-wrap"><table class="ag-table"><thead><tr><th>Cliente</th><th>Vencimento</th><th>Status</th></tr></thead><tbody>${acompanhados}</tbody></table></div>
      </div>
    </div>
    <div class="ac-barra" id="ac-barra" style="opacity:0;visibility:hidden"><span id="ac-barra-txt"><b>0</b> certificados marcados</span><span class="ag-btn ag-btn--ghost">Desfazer</span><span class="ag-btn ag-btn--primary" id="ac-salvar">Salvar seleção (0)</span></div>
    <div class="p-toast ok" id="ac-toast" style="opacity:0;visibility:hidden">${ic('check-circle', 18)}<span>2 certificados selecionados para acompanhamento.</span><i>×</i></div>
  </section>`;

  /* --- Login e segundo passo (templates/login.html) --- */
  const topoLogin = (sub) => `<img class="lg-logo" src="${CONFIG.logoPortal}" alt="" width="80" height="80"><h1>Analise Certificado</h1><p class="lg-sub">${sub}</p>`;
  const login = `
  <section class="page cover lg" id="pg-login">
    <div class="lg-card" id="lg-card">
      ${topoLogin('Faça login para acessar o monitor')}
      ${lgCampo('E-mail', 'lg-email', 'exemplo@email.com')}
      ${lgCampo('Senha', 'lg-senha', '••••••••', true)}
      <span class="lg-btn" id="lg-btn">Acessar o painel</span>
      <span class="lg-link">Esqueci minha senha</span>
    </div>
  </section>`;
  const codigo = `
  <section class="page cover lg" id="pg-codigo">
    <div class="lg-card" id="cd-card">
      ${topoLogin('Confirme que é você')}
      <p class="lg-dica" id="cd-dica">Enviamos um código para co••••••••••••••@exemplo.com. Ele vale por 15 minutos e permite 3 tentativas.</p>
      ${lgCampo('Código do e-mail', 'cd-codigo', '000000', false, 'lg-in--codigo')}
      <span class="lg-lembrar" id="cd-lembrar"><span class="lg-box" id="cd-box">${ic('check', 12)}</span> Lembrar deste navegador por 7 dias</span>
      <span class="lg-btn" id="cd-btn">Entrar</span>
      <span class="lg-link">Voltar e pedir outro código</span>
    </div>
  </section>`;

  return desktop + inicio + vencidos + acomp + login + codigo;
}

/* Metadados das páginas: qual menu lateral (area) aparece e qual item (nav) fica ativo. area: null = sem menu. */
const PAGINAS = {
  desktop:  { area: null,     nav: null },
  login:    { area: null,     nav: null },
  codigo:   { area: null,     nav: null },
  inicio:   { area: 'portal', nav: 'nav-inicio' },
  vencidos: { area: 'portal', nav: 'nav-vencidos' },
  acomp:    { area: 'portal', nav: 'nav-acomp' },
};

function htmlApp() {
  return `${htmlSidebars()}<main class="main">${htmlNavbar()}${htmlPaginas()}</main>`;
}

/* ------------------------------------------------------------------ 4. ROTEIRO */
/* Tempos em segundos do roteiro (o motor multiplica por RITMO = 0,6). Coordenadas do app: 1600×900. */
const A = {
  type: (sel, text, t, dur, o = {}) => ({ k: 'type', sel, text, t, dur, ...o }),
  cls: (sel, name, t, t2 = Infinity) => ({ k: 'cls', sel, name, t, t2 }),
  tw: (sel, t, dur, props, ease = 'out', o = {}) => ({ k: 'tw', sel, t, dur, props, ease, ...o }),
  txt: (sel, t, html, t2 = Infinity) => ({ k: 'txt', sel, t, html, t2 }),
  win: (sel, t, t2, o = {}) => ({ k: 'win', sel, t, t2, ...o }),
  bars: (sel, t, dur, stagger = 0.1) => ({ k: 'bars', sel, t, dur, stagger }),
  fn: (t, dur, f) => ({ k: 'fn', t, dur, f }),
};
const T_VEU = CONFIG.veuSeg;
const INF = 999;   // fim "para sempre" das ações; A.win não aceita Infinity (o fade de saída vira NaN)
const SENHA = '••••••••••••••';
// Estado do Início com o certificado já marcado (início da cena "Instalar").
const MARCADO = (t) => [
  A.cls('#in-tab', 'modo-sel', t), A.txt('#in-selecionar .rot', t, 'Cancelar'), A.cls('#in-selecionar', 'is-cancel', t),
  A.cls('#in-chk-2', 'is-on', t), A.cls('#in-row-2', 'is-sel', t), A.cls('#in-instalar', 'mostra', t), A.cls('#in-n-sel', 'mostra', t),
];
const EXPIRANDO = (t) => [A.txt('#in-status .val', t, 'Expirando'), A.cls('.in-nexp', 'is-oculta', t)];

const SCENES = [
  // vel: a abertura e o encerramento do motor foram pensados para vídeos longos; aqui correm mais depressa.
  { id: 'abertura', tipo: 'intro', nome: 'Abertura', dur: 14 / 1.5, vel: 1.5, cartela: false, paginas: [], legendas: [] },

  /* ============ 1. Instalar um certificado pela bandeja ============ */
  {
    id: 'b-antes', tipo: 'app', semChrome: true, nome: 'Antes de começar', eyebrow: 'Bandeja CertGuard Análise', dur: 14, cartela: true, cfx: 'zoom',
    paginas: [[0, 'desktop']],
    camera: [
      { t: 0, x: 800, y: 450, z: 1 },
      { t: 3.0, sel: '#dk-canto', z: 2.2 },
      { t: 12.6, sel: '#dk-canto', z: 2.2 },
      { t: 13.8, x: 800, y: 450, z: 1 },
    ],
    cursor: [
      { t: 2.6, x: 1100, y: 600 },
      { t: 4.6, to: '#dk-ico', click: true, mv: 1.2 },
      { t: 7.2, to: '#dk-m-status', anchor: [0.7, 0.5], mv: 0.9 },
    ],
    spots: [{ t: 7.4, t2: 12.2, sel: '#dk-m-status', label: 'Conectada e autorizada', pad: 6 }],
    legendas: [
      { t: 2.0, t2: 6.8, txt: 'Antes: a bandeja <b>CertGuard Análise</b> aberta, perto do relógio' },
      { t: 7.0, t2: 12.8, txt: 'No menu do ícone: <b>computador autorizado</b>' },
    ],
    fx: [A.win('#dk-menu', 4.8, 13.4, { fade: 0.2, y: 8 }), A.cls('#dk-ico', 'is-on', 4.7, 13.4)],
  },
  {
    id: 'b-selecionar', tipo: 'app', nome: 'Pedir no Início', eyebrow: 'Portal', dur: 16, cartela: true, cfx: 'slide',
    paginas: [[0, 'inicio']],
    camera: [
      { t: 0, x: 800, y: 450, z: 1 },
      { t: 2.8, sel: '#in-card', z: 1.3, dy: -60 },
      { t: 15, sel: '#in-card', z: 1.3, dy: -60 },
    ],
    cursor: [
      { t: 2.4, x: 900, y: 500 },
      { t: 4.0, to: '#in-selecionar', click: true, mv: 1.1 },
      { t: 7.0, to: '#in-chk-2', click: true, mv: 1.0 },
      { t: 10.0, to: '#in-n-sel', anchor: [0.6, 0.5], mv: 0.9 },
    ],
    spots: [{ t: 10.2, t2: 15, sel: '#in-instalar', label: 'Aparece quando há algo marcado', pad: 6 }],
    legendas: [
      { t: 2.6, t2: 6.6, txt: 'No <b>Início</b>, clique em <b>Selecionar</b>' },
      { t: 6.8, t2: 10.2, txt: 'Marque o certificado que vai instalar' },
      { t: 10.4, t2: 15.4, txt: 'Precisa da bandeja <b>pronta</b> neste computador' },
    ],
    fx: [
      A.cls('#in-tab', 'modo-sel', 4.1), A.txt('#in-selecionar .rot', 4.1, 'Cancelar'), A.cls('#in-selecionar', 'is-cancel', 4.1),
      A.cls('#in-chk-2', 'is-on', 7.1), A.cls('#in-row-2', 'is-sel', 7.1), A.cls('#in-instalar', 'mostra', 7.1), A.cls('#in-n-sel', 'mostra', 7.1),
    ],
  },
  {
    id: 'b-instalar', tipo: 'app', nome: 'Instalar', eyebrow: 'Portal', dur: 20, cartela: true,
    paginas: [[0, 'inicio']],
    camera: [
      { t: 0, x: 800, y: 450, z: 1 },
      { t: 1.2, sel: '#in-acoes', z: 1.3 },
      { t: 3.6, sel: '#in-acoes', z: 1.3 },
      { t: 4.8, x: 1250, y: 700, z: 1.35 },
      { t: 18.6, x: 1250, y: 700, z: 1.35 },
      { t: 19.8, x: 800, y: 450, z: 1 },
    ],
    cursor: [
      { t: 0.4, to: '#in-n-sel', anchor: [0.6, 0.5] },
      { t: 2.6, to: '#in-instalar', click: true, mv: 1.0 },
      { t: 5.6, x: 980, y: 520, mv: 1.2 },
    ],
    spots: [
      { t: 8.2, t2: 13.0, sel: '#w-toast', label: 'Aviso da bandeja, no canto da tela', pad: 8 },
    ],
    legendas: [
      { t: 1.0, t2: 4.6, txt: 'Clique em <b>Instalar selecionados</b>' },
      { t: 4.8, t2: 7.8, txt: 'O portal <b>acompanha</b> o pedido' },
      { t: 8.0, t2: 13.2, txt: 'A bandeja recebe e <b>instala sozinha</b>' },
      { t: 13.4, t2: 19.2, txt: 'Pronto: o certificado está no <b>seu Windows</b>' },
    ],
    fx: [
      ...MARCADO(0),
      A.cls('#in-instalar', 'is-hover', 2.7, 3.4),
      A.win('#t-pedido', 3.0, 7.6, { fade: 0.25, y: 14 }),
      A.win('#w-toast', 8.0, 13.4, { fade: 0.3, y: 24 }),
      A.win('#t-ok', 13.4, INF, { fade: 0.25, y: 14 }),
    ],
  },

  /* ============ 2. Acompanhar vencimentos ============ */
  {
    id: 'v-inicio', tipo: 'app', nome: 'Expirando', eyebrow: 'Início', dur: 18, cartela: true, cfx: 'slide',
    paginas: [[0, 'inicio']],
    camera: [
      { t: 0, x: 800, y: 450, z: 1 },
      { t: 2.8, sel: '#in-kpis', z: 1.3 },
      { t: 7.6, sel: '#in-kpis', z: 1.3 },
      { t: 8.6, sel: '#in-card', z: 1.3, dy: -60 },
      { t: 17, sel: '#in-card', z: 1.3, dy: -60 },
    ],
    cursor: [
      { t: 2.4, x: 900, y: 400 },
      { t: 3.8, to: '#in-kpi-exp', anchor: [0.4, 0.55], mv: 1.0 },
      { t: 9.2, to: '#in-status', click: true, mv: 1.2 },
      { t: 11.0, to: '#dd-st-exp', click: true, mv: 0.8 },
      { t: 13.4, to: '#in-row-4', anchor: [0.4, 0.5], mv: 1.0 },
    ],
    spots: [
      { t: 4.0, t2: 7.6, sel: '#in-kpi-exp', label: 'Vencem nos próximos 30 dias', pad: 6, baixo: true },
    ],
    legendas: [
      { t: 2.6, t2: 7.8, txt: 'No <b>Início</b>, o card <b>Expirando</b> conta o que vence em 30 dias' },
      { t: 8.2, t2: 11.4, txt: 'Em <b>Status</b>, escolha <b>Expirando</b>' },
      { t: 11.6, t2: 17.4, txt: 'A lista mostra <b>só os que vencem logo</b>' },
    ],
    fx: [
      A.win('#dd-status', 9.4, 11.3, { fade: 0.2, y: -8 }),
      A.cls('#in-status', 'is-focus', 9.3, 11.3),
      ...EXPIRANDO(11.2),
    ],
  },
  {
    id: 'v-vencidos', tipo: 'app', nome: 'Vencidos', eyebrow: 'Já venceram', dur: 14, cartela: true,
    paginas: [[0, 'inicio'], [2.2, 'vencidos']],
    camera: [
      { t: 0, x: 800, y: 450, z: 1 },
      { t: 3.0, x: 800, y: 450, z: 1 },
      { t: 4.0, sel: '#vc-kpis', z: 1.3 },
      { t: 8.6, sel: '#vc-kpis', z: 1.3 },
      { t: 9.6, sel: '#vc-tab', z: 1.3 },
      { t: 13.6, sel: '#vc-tab', z: 1.3 },
    ],
    cursor: [
      { t: 0.6, x: 700, y: 500 },
      { t: 2.0, to: '#nav-vencidos', click: true, mv: 1.2 },
      { t: 5.6, to: '#vc-total', anchor: [0.5, 0.55], mv: 1.2 },
      { t: 10.6, to: '#vc-row-1', anchor: [0.3, 0.5], mv: 1.0 },
    ],
    spots: [{ t: 4.6, t2: 8.6, sel: '#vc-total', label: 'Quem já venceu', pad: 6, baixo: true }],
    legendas: [
      { t: 0.6, t2: 3.6, txt: 'Clique em <b>Vencidos</b> no menu' },
      { t: 3.8, t2: 8.8, txt: 'Quem <b>já venceu</b>, para cobrar a renovação' },
      { t: 9.0, t2: 13.6, txt: 'Do vencimento <b>mais recente</b> para o mais antigo' },
    ],
    fx: [...EXPIRANDO(0)],
  },
  {
    id: 'v-escolher', tipo: 'app', nome: 'Acompanhamento', eyebrow: 'Escolher certificados', dur: 19, cartela: true,
    paginas: [[0, 'vencidos'], [2.2, 'acomp']],
    camera: [
      { t: 0, x: 800, y: 450, z: 1 },
      { t: 3.4, x: 800, y: 450, z: 1 },
      { t: 5.0, sel: '#ac-esc-tab', z: 1.25, dy: -40 },
      { t: 10.0, sel: '#ac-esc-tab', z: 1.25, dy: -40 },
      { t: 11.0, x: 1000, y: 560, z: 1.25 },
      { t: 18.6, x: 1000, y: 560, z: 1.25 },
    ],
    cursor: [
      { t: 0.6, x: 700, y: 500 },
      { t: 2.0, to: '#nav-acomp', click: true, mv: 1.2 },
      { t: 4.2, to: '#ac-tab-esc', click: true, mv: 1.0 },
      { t: 6.8, to: '#ac-chk-1', click: true, mv: 1.0 },
      { t: 8.6, to: '#ac-chk-3', click: true, mv: 0.8 },
      { t: 11.4, to: '#ac-salvar', click: true, mv: 1.1 },
    ],
    spots: [{ t: 12.0, t2: 17.0, sel: '#ac-toast', pad: 6, label: 'Seleção salva' }],
    legendas: [
      { t: 0.6, t2: 3.8, txt: 'Em <b>Acompanhamento</b>, escolha quem acompanhar' },
      { t: 4.0, t2: 6.6, txt: 'Abra a aba <b>Escolher certificados</b>' },
      { t: 6.8, t2: 11.0, txt: 'Marque os clientes' },
      { t: 11.2, t2: 18.4, txt: 'E clique em <b>Salvar seleção</b>' },
    ],
    fx: [
      A.win('#ac-p-vazio', 0, 4.4, { fade: 0.15 }),
      A.win('#ac-p-esc', 4.4, INF, { fade: 0.15 }),
      A.win('#ac-barra', 4.4, INF, { fade: 0.2, y: 20 }),
      A.cls('#ac-tab-acomp', 'is-on', 0, 4.4), A.cls('#ac-tab-esc', 'is-on', 4.4),
      A.cls('#ac-chk-1', 'is-on', 6.9), A.cls('#ac-chk-3', 'is-on', 8.7),
      A.cls('#ac-row-1', 'is-sel', 6.9), A.cls('#ac-row-3', 'is-sel', 8.7),
      A.txt('#ac-barra-txt', 6.9, '<b>1</b> certificado marcado <span class="pend">· alterações não salvas</span>', 8.7),
      A.txt('#ac-barra-txt', 8.7, '<b>2</b> certificados marcados <span class="pend">· alterações não salvas</span>', 11.6),
      A.txt('#ac-barra-txt', 11.6, '<b>2</b> certificados marcados'),
      A.txt('#ac-salvar', 6.9, 'Salvar seleção (1)', 8.7), A.txt('#ac-salvar', 8.7, 'Salvar seleção (2)'),
      A.cls('#ac-salvar', 'is-off', 0, 6.9), A.cls('#ac-salvar', 'is-off', 11.6),
      A.txt('#ac-tab-acomp .n', 11.6, '(2)'),
      A.win('#ac-toast', 11.8, INF, { fade: 0.25, y: 14 }),
    ],
  },
  {
    id: 'v-aviso', tipo: 'app', nome: 'Aviso por e-mail', eyebrow: 'Acompanhados', dur: 18, cartela: true,
    paginas: [[0, 'acomp']],
    camera: [
      { t: 0, x: 800, y: 450, z: 1 },
      { t: 2.4, x: 800, y: 450, z: 1 },
      { t: 3.4, sel: '#ac-aviso-box', z: 1.35 },
      { t: 17, sel: '#ac-aviso-box', z: 1.35 },
    ],
    cursor: [
      { t: 0.4, x: 900, y: 420 },
      { t: 1.4, to: '#ac-tab-acomp', click: true, mv: 0.9 },
      { t: 4.4, to: '#ac-aviso', anchor: [0.2, 0.5], click: true, mv: 1.1 },
      { t: 6.6, to: '#ac-quero-chk', click: true, mv: 0.9 },
      { t: 8.8, to: '#ac-marco-30', mv: 0.8 },
      { t: 11.0, to: '#ac-pref-salvar', click: true, mv: 0.9 },
    ],
    spots: [{ t: 7.0, t2: 10.6, sel: '#ac-aviso-estado', label: 'Ligado', pad: 4 }],
    legendas: [
      { t: 0.6, t2: 4.2, txt: 'Na aba <b>Acompanhados</b>, o resumo de quem você acompanha' },
      { t: 4.4, t2: 8.6, txt: 'Abra <b>Aviso por e-mail</b> e ligue o aviso' },
      { t: 8.8, t2: 10.8, txt: 'Escolha os prazos' },
      { t: 11.0, t2: 17.4, txt: 'Clique em <b>Salvar preferência</b>' },
    ],
    fx: [
      A.win('#ac-p-esc', 0, 1.5, { fade: 0.15 }), A.win('#ac-barra', 0, 1.5, { fade: 0.15 }),
      A.win('#ac-p-lista', 1.5, INF, { fade: 0.15 }),
      A.cls('#ac-tab-esc', 'is-on', 0, 1.5), A.cls('#ac-tab-acomp', 'is-on', 1.5),
      A.txt('#ac-tab-acomp .n', 0, '(2)'),
      A.cls('#ac-chk-1, #ac-chk-3', 'is-on', 0),
      A.cls('#ac-aviso-corpo', 'hide', 0, 4.5), A.cls('#ac-aviso-box', 'is-aberto', 4.5),
      A.cls('#ac-quero-chk', 'is-on', 6.7), A.cls('#ac-marcos', 'is-off', 0, 6.7),
      A.txt('#ac-aviso-txt', 6.7, 'Aviso por e-mail <strong>30, 15, 7 e 1 dias antes e quando vencer</strong>'),
      A.txt('#ac-aviso-estado', 6.7, '<span class="ag-badge ag-badge--success">Ligado</span>'),
      A.cls('#ac-pref-salvar', 'is-off', 0, 6.7), A.cls('#ac-pref-salvar', 'is-off', 11.2),
      A.win('#ac-pref-msg', 11.2, INF, { fade: 0.2 }),
    ],
  },

  /* ============ 3. Primeiro acesso com código ============ */
  {
    id: 'l-entrar', tipo: 'app', nome: 'Entrar', eyebrow: 'Primeiro acesso', dur: 14, cartela: true, cfx: 'zoom',
    paginas: [[0, 'login']],
    camera: [
      { t: 0, x: 800, y: 450, z: 1 },
      { t: 2.6, sel: '#lg-card', z: 1.4 },
      { t: 13.6, sel: '#lg-card', z: 1.4 },
    ],
    cursor: [
      { t: 2.4, x: 1100, y: 640 },
      { t: 3.8, to: '#lg-email', anchor: [0.3, 0.5], click: true, mv: 1.1 },
      { t: 6.0, to: '#lg-senha', anchor: [0.3, 0.5], click: true, mv: 0.9 },
      { t: 8.6, to: '#lg-btn', click: true, mv: 0.9 },
    ],
    legendas: [
      { t: 2.4, t2: 7.8, txt: 'Digite o <b>e-mail</b> e a <b>senha</b> que você recebeu' },
      { t: 8.0, t2: 13.6, txt: 'Clique em <b>Acessar o painel</b>' },
    ],
    fx: [
      A.type('#lg-email', EMAIL, 4.0, 0.4),
      A.type('#lg-senha', '••••••••••', 6.2, 0.4),
      A.cls('#lg-btn', 'is-hover', 8.7, 9.6),
    ],
  },
  {
    id: 'l-codigo', tipo: 'app', nome: 'Código do e-mail', eyebrow: 'Confirme que é você', dur: 20, cartela: true,
    paginas: [[0, 'login'], [0.6, 'codigo']],
    camera: [
      { t: 0, x: 800, y: 450, z: 1 },
      { t: 1.2, sel: '#cd-card', z: 1.4 },
      { t: 19.6, sel: '#cd-card', z: 1.4 },
    ],
    cursor: [
      { t: 1.0, to: '#lg-btn' },
      { t: 6.4, to: '#cd-codigo', anchor: [0.5, 0.5], click: true, mv: 1.1 },
      { t: 8.8, to: '#cd-box', click: true, mv: 0.9 },
      { t: 12.6, to: '#cd-btn', click: true, mv: 0.9 },
    ],
    pops: [{ t: 2.4, t2: 7.4, x: 1560, y: 300, ic: 'mail', txt: 'Código: 482915', sub: 'Chegou no seu e-mail', fx: 'drop' }],
    spots: [
      { t: 2.6, t2: 6.2, sel: '#cd-dica', label: 'Vale 15 minutos · 3 tentativas', pad: 6 },
      { t: 9.0, t2: 12.4, sel: '#cd-lembrar', label: 'Só no computador que é seu', pad: 6, baixo: true },
    ],
    legendas: [
      { t: 1.0, t2: 6.2, txt: 'O portal manda um <b>código de 6 dígitos</b> para o seu e-mail' },
      { t: 6.4, t2: 8.6, txt: 'Digite o código' },
      { t: 8.8, t2: 12.4, txt: 'Computador seu? Marque <b>Lembrar deste navegador</b>' },
      { t: 12.6, t2: 19.4, txt: 'Clique em <b>Entrar</b>' },
    ],
    fx: [
      A.type('#lg-email', EMAIL, 0, 0.01), A.type('#lg-senha', '••••••••••', 0, 0.01),
      A.type('#cd-codigo', '482915', 6.6, 0.4),
      A.cls('#cd-box', 'is-on', 8.9),
      A.cls('#cd-btn', 'is-hover', 12.7, 13.6),
    ],
  },
  {
    id: 'l-senha', tipo: 'app', nome: 'Defina sua senha', eyebrow: 'Senha provisória', dur: 22, cartela: true, cfx: 'drop',
    paginas: [[0, 'inicio'], [17.4, 'login']],
    camera: [
      { t: 0, x: 800, y: 450, z: 1 },
      { t: 2.4, sel: '#ds-modal', z: 1.3 },
      { t: 16, sel: '#ds-modal', z: 1.3 },
      { t: 17.2, x: 800, y: 450, z: 1 },
      { t: 18.6, sel: '#lg-card', z: 1.4 },
      { t: 21.6, sel: '#lg-card', z: 1.4 },
    ],
    cursor: [
      { t: 2.6, x: 900, y: 640 },
      { t: 4.2, to: '#ds-atual', anchor: [0.3, 0.5], click: true, mv: 1.0 },
      { t: 6.4, to: '#ds-nova', anchor: [0.3, 0.5], click: true, mv: 0.8 },
      { t: 8.6, to: '#ds-conf', anchor: [0.3, 0.5], click: true, mv: 0.8 },
      { t: 11.2, to: '#ds-btn', click: true, mv: 0.9 },
      { t: 19.2, to: '#lg-email', anchor: [0.3, 0.5], mv: 1.2 },
    ],
    legendas: [
      { t: 1.6, t2: 6.0, txt: 'Senha provisória? Abre a janela <b>Defina sua senha</b>' },
      { t: 6.2, t2: 10.8, txt: 'Nova senha com no mínimo <b>12 caracteres</b>' },
      { t: 11.0, t2: 17.0, txt: 'Clique em <b>Definir senha</b>' },
      { t: 17.6, t2: 21.6, txt: 'Depois, entre com a <b>nova senha</b>' },
    ],
    fx: [
      A.win('#ds-veu', 0.8, 17.4, { fade: 0.3 }),
      A.win('#ds-modal', 1.0, 17.4, { fade: 0.3, y: 24 }),
      A.type('#ds-atual', '••••••••••', 4.4, 0.4),
      A.type('#ds-nova', SENHA, 6.6, 0.4),
      A.type('#ds-conf', SENHA, 8.8, 0.4),
      A.cls('#ds-btn', 'is-hover', 11.3, 12.2),
    ],
  },

  { id: 'encerramento', tipo: 'closing', nome: 'Encerramento', eyebrow: 'Fim', dur: 22 / 1.6, vel: 1.6, cartela: false, paginas: [], legendas: [] },
];

// Cor e forma de transição de cada módulo. forma ∈ wipe | circle | diamond | blinds | push | band.
const MODULOS_COR = {
  portal:  { cor: '#B88157', escura: '#4a2f1b', clara: '#E4CC8F', forma: 'wipe' },
  bandeja: { cor: '#3d6a8a', escura: '#132433', clara: '#9cc0d8', forma: 'band' },
  login:   { cor: '#2a63b8', escura: '#0f2347', clara: '#8fb3ea', forma: 'diamond' },
  marca:   { cor: '#6b4a2b', escura: '#1a1410', clara: '#C9A06A', forma: 'circle' },
};
const MODULO_DA_CENA = {
  abertura: 'marca', encerramento: 'marca',
  'b-antes': 'bandeja', 'b-selecionar': 'portal', 'b-instalar': 'portal',
  'v-inicio': 'portal', 'v-vencidos': 'portal', 'v-escolher': 'portal', 'v-aviso': 'portal',
  'l-entrar': 'login', 'l-codigo': 'login', 'l-senha': 'portal',
};
const modDa = (sc) => MODULOS_COR[MODULO_DA_CENA[sc.id] || 'portal'];

/* ---- Três vídeos, um motor: cada um é um <body data-roteiro="nome"> num .html ---- */
const ROTEIROS = {
  bandeja: {
    titulo: 'Instalar pela bandeja', sub: 'Wiki do CertGuard', sistema: 'Wiki do CertGuard',
    frase: 'Instalar um certificado <b>pela bandeja</b>',
    desc: 'Do pedido no Início ao aviso do Windows: como um certificado chega ao seu computador. Dados fictícios.',
    cenas: ['abertura', 'b-antes', 'b-selecionar', 'b-instalar', 'encerramento'],
    resumo: [
      { ic: 'shield-check', tit: 'Bandeja pronta', p: 'Aberta, com você conectado e o computador autorizado.' },
      { ic: 'list-checks', tit: 'Selecionar', p: 'No Início, marque o certificado.' },
      { ic: 'download', tit: 'Instalar selecionados', p: 'A bandeja instala e avisa no canto da tela.' },
    ],
    fim: 'O certificado fica no seu usuário do Windows,<br><em>pronto para usar.</em>',
  },
  vencimentos: {
    titulo: 'Acompanhar vencimentos', sub: 'Wiki do CertGuard', sistema: 'Wiki do CertGuard',
    frase: 'Acompanhar os <b>vencimentos</b>',
    desc: 'Expirando no Início, a página Vencidos e o Acompanhamento com aviso por e-mail. Dados fictícios.',
    cenas: ['abertura', 'v-inicio', 'v-vencidos', 'v-escolher', 'v-aviso', 'encerramento'],
    resumo: [
      { ic: 'clock', tit: 'Expirando', p: 'No Início, o que vence nos próximos 30 dias.' },
      { ic: 'alert-triangle', tit: 'Vencidos', p: 'Quem já venceu, para cobrar a renovação.' },
      { ic: 'mail', tit: 'Acompanhamento', p: 'Escolha os clientes e receba o aviso por e-mail.' },
    ],
    fim: 'Nenhum vencimento<br><em>pega você de surpresa.</em>',
  },
  login: {
    titulo: 'Primeiro acesso com código', sub: 'Wiki do CertGuard', sistema: 'Wiki do CertGuard',
    frase: 'Primeiro acesso <b>com código</b>',
    desc: 'E-mail e senha, o código de 6 dígitos que chega por e-mail e a troca da senha provisória. Dados fictícios.',
    cenas: ['abertura', 'l-entrar', 'l-codigo', 'l-senha', 'encerramento'],
    resumo: [
      { ic: 'user', tit: 'E-mail e senha', p: 'Clique em Acessar o painel.' },
      { ic: 'mail', tit: 'Código do e-mail', p: '6 dígitos, vale 15 minutos e aceita 3 tentativas.' },
      { ic: 'key', tit: 'Defina sua senha', p: 'A provisória vira uma que só você sabe.' },
    ],
    fim: 'Pronto para usar o portal,<br><em>com segurança.</em>',
  },
};

const ROTEIRO = ROTEIROS[(document.body && document.body.dataset.roteiro) || 'bandeja'] || ROTEIROS.bandeja;
(function escolher() {
  const todas = SCENES.slice();
  SCENES.length = 0;
  ROTEIRO.cenas.forEach((id) => { const sc = todas.find((x) => x.id === id); if (sc) { if (ROTEIRO.eyebrows && ROTEIRO.eyebrows[id]) sc.eyebrow = ROTEIRO.eyebrows[id]; SCENES.push(sc); } });
  // Cenas seguidas do mesmo módulo (ferramentas de um setor, telas de uma área) não ganham cortina:
  // a anterior se dissolve na seguinte, sem zoom de entrada e com o título já no canto.
  SCENES.forEach((sc, i) => {
    const ant = SCENES[i - 1], m = MODULO_DA_CENA[sc.id];
    if (!ant || !m || m === 'marca' || MODULO_DA_CENA[ant.id] !== m || sc.tipo !== 'app' || ant.tipo !== 'app') return;
    sc.suave = true;
    if (sc.camera && sc.camera[0]) sc.camera[0] = { t: 0, x: 800, y: 450, z: 1 };
    (sc.sfx || []).forEach((e) => { if (e.s === 'whoosh') e.s = 'swish'; });
  });
})();

const RITMO = 0.6;   // 1 = ritmo original; menor = mais rápido (tudo no roteiro é escalado)
(function acelerar() {
  const K = ['t', 't2', 'dur', 'until', 'stagger', 'fade', 'mv'];
  // (pops também entram na escala de ritmo)
  const esc = (o) => { if (o && typeof o === 'object') K.forEach((k) => { if (typeof o[k] === 'number' && isFinite(o[k])) o[k] *= RITMO; }); };
  SCENES.forEach((sc) => {
    // Preenchimento rápido: o valor aparece quando o cursor chega ao campo, em vez de ser digitado letra a letra.
    // O tempo que a digitação ocupava (em segundos do roteiro original) é cortado da cena inteira: tudo que vem
    // depois — cursor, câmera, legendas, efeitos — corre para mais cedo, sem perder a ordem.
    const cortes = [];
    (sc.fx || []).filter((a) => a.k === 'type' && a.dur > 0.5).forEach((a) => cortes.push([a.t + 0.25, a.t + a.dur]));
    cortes.sort((x, y) => x[0] - y[0]);
    const uniao = [];
    cortes.forEach((c) => { const u = uniao[uniao.length - 1]; if (u && c[0] <= u[1]) u[1] = Math.max(u[1], c[1]); else uniao.push(c.slice()); });
    if (uniao.length) {
      const mapa = (x) => { if (!isFinite(x)) return x; let tira = 0; for (const [a, b] of uniao) { if (x >= b) tira += b - a; else if (x > a) tira += x - a; } return x - tira; };
      const mp = (o) => { if (o && typeof o === 'object') ['t', 't2', 'until'].forEach((k) => { if (typeof o[k] === 'number') o[k] = mapa(o[k]); }); };
      ['camera', 'cursor', 'spots', 'legendas', 'fx', 'sfx', 'pops'].forEach((l) => (sc[l] || []).forEach(mp));
      (sc.passos || []).forEach((p) => { p[1] = mapa(p[1]); p[2] = mapa(p[2]); });
      (sc.paginas || []).forEach((p) => { p[0] = mapa(p[0]); });
      mp(sc.chamada);
      sc.dur -= uniao.reduce((t, [a, b]) => t + (b - a), 0);
    }
    (sc.fx || []).forEach((a) => { if (a.k === 'type') a.dur = Math.min(a.dur, 0.25); });
    sc.dur *= RITMO;
    ['camera', 'cursor', 'spots', 'legendas', 'fx', 'sfx', 'pops'].forEach((l) => (sc[l] || []).forEach(esc));
    (sc.passos || []).forEach((p) => { p[1] *= RITMO; p[2] *= RITMO; });
    (sc.paginas || []).forEach((p) => { p[0] *= RITMO; });
    esc(sc.chamada);
    // Música: cliques, legendas, avisos, movimentos de câmera e efeitos sonoros são puxados para a batida
    // mais próxima (grade de meia batida). A mesma regra vale para tudo, então a ordem entre eles não muda.
    const g = 60 / CONFIG.ritmo.bpm / 2, ajusta = (v) => Math.round(v / g) * g;
    const bate = (o) => { if (o && typeof o === 'object') ['t', 't2', 'until'].forEach((k) => { if (typeof o[k] === 'number' && isFinite(o[k])) o[k] = ajusta(o[k]); }); };
    ['camera', 'cursor', 'spots', 'legendas', 'fx', 'sfx', 'pops'].forEach((l) => (sc[l] || []).forEach(bate));
    (sc.passos || []).forEach((p) => { p[1] = ajusta(p[1]); p[2] = ajusta(p[2]); });
    (sc.paginas || []).forEach((p) => { p[0] = ajusta(p[0]); });
    bate(sc.chamada);
    ['camera', 'cursor'].forEach((l) => { let ant = -1; (sc[l] || []).forEach((o) => { if (o.t <= ant) o.t = ant + g; ant = o.t; }); });
    // Entradas em sequência (cartões, KPIs, linhas) saem em quartos de batida, e não em intervalos soltos.
    (sc.fx || []).forEach((a) => { if (a.k === 'tw' && a.stagger) a.stagger = Math.max(g / 2, Math.round(a.stagger / (g / 2)) * (g / 2)); });
  });
})();
(function indexar() {
  let acc = 0;
  const meio = 2 * 60 / CONFIG.ritmo.bpm;                       // 2 batidas
  SCENES.forEach((s) => { s.dur = Math.ceil(s.dur / meio - 1e-6) * meio; s.start = acc; acc += s.dur; s.end = acc; });
  SCENES.total = acc;
})();

/* ------------------------------------------------------------ 5. MOTOR DE TIMELINE */
const REDUCED = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
const J = { left: 160, top: 54, chrome: 36 };
const VIEW = { cy: 452, zb: 0.9 };            // área útil do app: acima da faixa de legendas           // posição da janela do app no palco 1920×1080
const stageEl = $('#stage'), playerEl = $('#player');
let appEl, viewEl, fxEl, cursorEl, rippleEl;
let spotEls = [];
const cache = new Map();
const q = (sel) => { let r = cache.get(sel); if (!r) { r = $$(sel, viewEl); cache.set(sel, r); } return r; };

function rebuildApp() {
  viewEl.innerHTML = htmlApp();
  cache.clear();
}

/* Posição/tamanho de um elemento nas coordenadas do app (1600×900), imune ao zoom e à câmera. */
function rectApp(el) {
  let x = 0, y = 0, n = el;
  while (n && n !== appEl) { x += n.offsetLeft; y += n.offsetTop; n = n.offsetParent; }
  return { x, y, w: el.offsetWidth, h: el.offsetHeight };
}
function pontoAlvo(w) {
  if (w.to) {
    const el = q(w.to)[0];
    if (el) {
      const r = rectApp(el), a = w.anchor || [0.5, 0.5];
      return { x: r.x + r.w * a[0] + (w.dx || 0), y: r.y + r.h * a[1] + (w.dy || 0) };
    }
  }
  return { x: w.x ?? 800, y: w.y ?? 450 };
}

/* ---------- cena atual e mudanças de cena ---------- */
let lastIdx = -1;
const dom = {};
function indexDe(t) {
  for (let i = SCENES.length - 1; i >= 0; i--) if (t >= SCENES[i].start) return i;
  return 0;
}
function aoMudarDeCena(i) {
  const sc = SCENES[i];
  lastIdx = i;
  if (sc.tipo === 'app') {
    $('.janela').classList.toggle('sem-chrome', !!sc.semChrome);   // cena na área de trabalho do Windows: sem barra de navegador
    rebuildApp();
    fxEl.querySelectorAll('.spot').forEach((s) => s.remove());
    spotEls = (sc.spots || []).map((sp) => {
      const d = document.createElement('div');
      d.className = 'spot';
      if (sp.label) { const e = document.createElement('em'); e.textContent = sp.label; d.appendChild(e); }
      fxEl.appendChild(d);
      return d;
    });
    dom.cartelaEyebrow.textContent = sc.eyebrow || '';
    dom.cartelaTitulo.textContent = sc.nome || '';
    sc._cw = dom.cartela.offsetWidth; sc._ch = dom.cartela.offsetHeight;
    dom.legendaTxt.innerHTML = ''; dom._legKey = -1;
    dom.pops.innerHTML = (sc.pops || []).map((p) => `<div class="pop"><span class="ic">${ic(p.ic, 30)}</span><div><b>${p.txt}</b><small>${p.sub}</small></div></div>`).join('');
    dom._popEls = $$('.pop', dom.pops);
    dom.passos.innerHTML = (sc.passos || []).map((p, k) => `<span class="passo"><i>${k + 1}</i>${p[0]}</span>`).join('');
  }
}

/* ---------- ações declarativas (sempre recalculadas a partir do tempo) ---------- */
function aplicarFx(sc, lt) {
  const est = new Map();                       // elemento → {x,y,s,opacity,blur,vis}
  const html = new Map();                      // elemento → html desejado
  const estado = (el) => { let e = est.get(el); if (!e) { e = {}; est.set(el, e); } return e; };

  for (const a of sc.fx || []) {
    switch (a.k) {
      case 'cls': for (const el of q(a.sel)) el.classList.toggle(a.name, lt >= a.t && lt < a.t2); break;
      case 'txt':
        for (const el of q(a.sel)) {
          if (el.__o === undefined) el.__o = el.innerHTML;
          if (!html.has(el)) html.set(el, el.__o);
          if (lt >= a.t && lt < a.t2) html.set(el, a.html);
        }
        break;
      case 'type': {
        const el = q(a.sel)[0]; if (!el) break;
        const v = el.querySelector('.val'), ph = el.querySelector('.ph');
        const ate = a.until ?? (a.t + a.dur + 0.6);
        const ativo = lt >= a.t && lt < ate;
        const n = Math.floor(a.text.length * clamp((lt - a.t) / Math.max(a.dur, 0.001)));
        const texto = lt < a.t ? (a.base || '') : (a.until != null && lt >= a.until ? '' : a.text.slice(0, n));
        if (v.textContent !== texto) v.textContent = texto;
        if (ph) ph.style.display = texto.length || ativo ? 'none' : '';
        const alvo = a.focusSel ? q(a.focusSel)[0] : el;
        el.classList.toggle('is-typing', lt >= a.t && lt < a.t + a.dur + 0.5);
        alvo.classList.toggle('is-focus', ativo);
        break;
      }
      case 'tw': {
        const els = q(a.sel);
        els.forEach((el, k) => {
          const p = EASE[a.ease](clamp((lt - a.t - k * (a.stagger || 0)) / Math.max(a.dur, 0.001)));
          for (const [prop, par] of Object.entries(a.props)) {
            const v = lerp(par[0], par[1], p);
            if (prop.startsWith('--')) el.style.setProperty(prop, v + (par[2] || ''));
            else estado(el)[prop] = v;
          }
        });
        break;
      }
      case 'win': {
        const fade = a.fade ?? 0.3;
        const pin = seg(lt, a.t, a.t + fade, 'out'), pout = seg(lt, a.t2, a.t2 + fade, 'in');
        const p = pin * (1 - pout);
        for (const el of q(a.sel)) {
          const e = estado(el);
          e.opacity = p; e.vis = p > 0.002; e.y = (a.y || 0) * (1 - pin) + (a.y || 0) * pout * 0.5;
          if (a.scale) e.s = lerp(a.scale, 1, pin);
        }
        break;
      }
      case 'bars':
        q(a.sel).forEach((el, k) => {
          const p = EASE.out(clamp((lt - a.t - k * a.stagger) / a.dur));
          el.style.setProperty('--barra', parseFloat(el.dataset.v) * p + '%');
        });
        break;
      case 'fn': a.f(clamp((lt - a.t) / Math.max(a.dur, 0.001)) * (lt >= a.t ? 1 : 0), lt / RITMO, q); break;
    }
  }
  html.forEach((h, el) => { if (el.__h !== h) { el.innerHTML = h; el.__h = h; } });
  est.forEach((e, el) => {
    const tr = [];
    if (e.x !== undefined || e.y !== undefined) tr.push(`translate(${(e.x || 0).toFixed(2)}px,${(e.y || 0).toFixed(2)}px)`);
    if (e.s !== undefined) tr.push(`scale(${e.s.toFixed(4)})`);
    el.style.transform = tr.join(' ');
    if (e.opacity !== undefined) el.style.opacity = e.opacity.toFixed(3);
    if (e.vis !== undefined) el.style.visibility = e.vis ? 'visible' : 'hidden';
  });
}

/* ---------- entrada rítmica: os blocos de cada tela aparecem um por batida ---------- */
const BATIDA = 60 / CONFIG.ritmo.bpm, MEIA = BATIDA / 2;
function blocosDe(pg) {
  if (!pg.__blocos) pg.__blocos = [...pg.children].filter((el) => !el.matches('.m-veu,.m-modal,.m-toast,.cc-menu') && el.style.opacity === '' && getComputedStyle(el).position !== 'absolute');
  return pg.__blocos;
}
function aplicarEntrada(sc, lt) {
  const sched = sc.paginas || [];
  if (!sched.length) return;
  let k = 0;
  for (let i = 0; i < sched.length; i++) if (lt >= sched[i][0]) k = i;
  const cur = sched[k][1], ant = SCENES[SCENES.indexOf(sc) - 1];
  const antes = k > 0 ? sched[k - 1][1] : (sc.suave && ant && ant.paginas && ant.paginas.length ? ant.paginas[ant.paginas.length - 1][1] : null);
  if (antes === cur) return;                                   // mesma tela da cena anterior: nada novo para revelar
  const pg = q('#pg-' + cur)[0]; if (!pg) return;
  const lista = blocosDe(pg), passo = lista.length > 6 ? MEIA : BATIDA;
  // 1ª tela da cena: espera a cortina começar a abrir; telas trocadas no meio da cena entram logo.
  const ini = sched[k][0] + (k === 0 ? (sc.suave ? MEIA : 3 * MEIA) : MEIA);
  const fim = ini + lista.length * passo + 0.7;
  lista.forEach((el, i) => {
    const p = EASE.outBack(clamp((lt - ini - i * passo) / 0.55));
    if (lt > fim) { if (el.__rv) { el.style.opacity = ''; el.style.transform = ''; el.__rv = false; } return; }
    el.__rv = true;
    el.style.opacity = clamp(p * 1.4).toFixed(3);
    el.style.transform = `translateY(${((1 - p) * 38).toFixed(1)}px) scale(${(0.965 + 0.035 * p).toFixed(4)})`;
  });
}

/* ---------- páginas, menu lateral ---------- */
function aplicarPaginas(sc, lt) {
  const sched = sc.paginas || [];
  if (!sched.length) return;
  let k = 0;
  for (let i = 0; i < sched.length; i++) if (lt >= sched[i][0]) k = i;
  const antes = sc.suave ? SCENES[SCENES.indexOf(sc) - 1] : null;
  const cur = sched[k][1], prev = k > 0 ? sched[k - 1][1] : (antes && antes.paginas && antes.paginas.length ? antes.paginas[antes.paginas.length - 1][1] : null);
  const p = prev && prev !== cur ? seg(lt, sched[k][0], sched[k][0] + (k === 0 ? MEIA * 2 : 0.25), 'io') : 1;
  const sets = {};
  for (const k of Object.keys(PAGINAS)) if (PAGINAS[k].area) sets[PAGINAS[k].area] = 0;   // uma entrada por área declarada em PAGINAS
  for (const id of Object.keys(PAGINAS)) {
    const el = q('#pg-' + id)[0]; if (!el) continue;
    const op = id === cur ? p : (id === prev && prev !== cur ? 1 - p : 0);
    el.style.opacity = op.toFixed(3);
    el.style.visibility = op > 0.002 ? 'visible' : 'hidden';
    el.style.zIndex = id === cur ? 2 : 1;
    const area = PAGINAS[id].area;
    if (area) sets[area] = Math.max(sets[area], op);
  }
  for (const a of Object.keys(sets)) { const s = q('#sb-' + a)[0]; if (s) s.style.opacity = sets[a].toFixed(3); }
  const navAtivo = p >= 0.5 ? PAGINAS[cur].nav : (prev ? PAGINAS[prev].nav : null);
  q('.sidebar-link').forEach((l) => l.classList.toggle('is-active', l.id === navAtivo));
}

/* ---------- cursor, cliques, hover ---------- */
function aplicarCursor(sc, lt) {
  const w = sc.cursor;
  if (!w || !w.length) { cursorEl.style.opacity = 0; rippleEl.style.opacity = 0; return; }
  // Segmentos: o cursor espera em cada ponto e só se move nos `mv` segundos antes da chegada seguinte.
  let pos = pontoAlvo(w[0]);
  const hover = new Set();
  let clique = null;
  for (let k = 0; k < w.length; k++) {
    const t1 = w[k].t;
    if (k > 0) {
      const mv = Math.min(w[k].mv ?? 1, t1 - w[k - 1].t);
      const t0 = t1 - mv;
      if (lt >= t0) {
        const a = pontoAlvo(w[k - 1]), b = pontoAlvo(w[k]);
        const p = seg(lt, t0, t1, 'io');
        const dx = b.x - a.x, dy = b.y - a.y, dist = Math.hypot(dx, dy) || 1;
        const arco = Math.min(70, dist * 0.14) * Math.sin(Math.PI * p) * (k % 2 ? 1 : -1);
        pos = { x: lerp(a.x, b.x, p) - (dy / dist) * arco, y: lerp(a.y, b.y, p) + (dx / dist) * arco };
      }
    }
    if (w[k].to) {
      const sai = k + 1 < w.length ? w[k + 1].t - Math.min(w[k + 1].mv ?? 1, w[k + 1].t - t1) : Infinity;
      if (lt >= t1 && lt < sai) { const el = q(w[k].to)[0]; if (el) hover.add(el); }
    }
    if (w[k].click && lt >= t1 && lt < t1 + 0.6) clique = { k, dt: lt - t1, ponto: pontoAlvo(w[k]) };
  }
  for (const k of new Set(w.filter((x) => x.to).map((x) => x.to))) {
    const el = q(k)[0]; if (el) el.classList.toggle('is-hover', hover.has(el));
  }
  const aparece = seg(lt, w[0].t - 0.7, w[0].t - 0.1, 'out');
  cursorEl.style.opacity = aparece.toFixed(3);
  cursorEl.style.transform = `translate(${(pos.x - 4).toFixed(1)}px,${(pos.y - 3).toFixed(1)}px)`;
  const press = clique && clique.dt < 0.22 ? 1 - 0.2 * Math.sin((clique.dt / 0.22) * Math.PI) : 1;
  cursorEl.firstElementChild.style.transform = `scale(${press.toFixed(3)})`;
  if (clique) {
    const p = clamp(clique.dt / 0.55);
    rippleEl.style.opacity = (0.9 * (1 - p)).toFixed(3);
    rippleEl.style.transform = `translate(${clique.ponto.x}px,${clique.ponto.y}px) scale(${(1 + 3.2 * EASE.out(p)).toFixed(3)})`;
  } else rippleEl.style.opacity = 0;
}

/* ---------- câmera ---------- */
function resolverKf(kf) {
  if (kf.sel) {
    const el = q(kf.sel)[0];
    if (el) {
      const r = rectApp(el);
      // O foco nunca corta o próprio alvo: o zoom é limitado para o elemento caber na área visível
      // (a janela tem ~904 px de altura acima da faixa de legendas e 1920 de largura).
      const fit = Math.min(1840 / (r.w + 60), 850 / (r.h + 50 + Math.abs(kf.dy || 0) * 2)) / VIEW.zb;
      return { x: r.x + r.w / 2 + (kf.dx || 0), y: r.y + r.h / 2 + (kf.dy || 0), z: Math.min(kf.z, Math.max(fit, 0.6)), rx: kf.rx || 0, ry: kf.ry || 0 };
    }
  }
  return { x: kf.x ?? 800, y: kf.y ?? 450, z: kf.z ?? 1, rx: kf.rx || 0, ry: kf.ry || 0 };
}
function aplicarCamera(sc, lt, extraBlur) {
  const kfs = sc.camera || [{ t: 0, x: 800, y: 450, z: 1 }];
  let a = kfs[0], b = kfs[0], p = 0;
  for (let i = 0; i < kfs.length; i++) {
    if (lt >= kfs[i].t) { a = kfs[i]; b = kfs[Math.min(i + 1, kfs.length - 1)]; }
  }
  if (a !== b) p = seg(lt, a.t, b.t, 'io');
  const A_ = resolverKf(a), B_ = resolverKf(b);
  let x = lerp(A_.x, B_.x, p), y = lerp(A_.y, B_.y, p);
  let z = Math.exp(lerp(Math.log(A_.z), Math.log(B_.z), p));
  let rx = lerp(A_.rx, B_.rx, p), ry = lerp(A_.ry, B_.ry, p);
  if (REDUCED) { z = 1 + (z - 1) * 0.35; rx = ry = 0; }
  z *= VIEW.zb;
  // O foco nunca mostra o vazio fora da janela do app.
  let Sx = J.left + x, Sy = J.top + J.chrome + y;
  const hx = 960 / z, hy = VIEW.cy / z;
  const loX = J.left + hx, hiX = J.left + 1600 - hx, loY = J.top + hy, hiY = J.top + 936 - hy;
  Sx = loX <= hiX ? clamp(Sx, loX, hiX) : J.left + 800;
  Sy = loY <= hiY ? clamp(Sy, loY, hiY) : J.top + 468;
  dom.camera.style.transform = `translate(${(960 - Sx * z).toFixed(2)}px,${(VIEW.cy - Sy * z).toFixed(2)}px) scale(${z.toFixed(4)})`;
  dom.tilt.style.transform = rx || ry ? `perspective(2600px) rotateX(${rx.toFixed(2)}deg) rotateY(${ry.toFixed(2)}deg)` : 'none';
  dom.tilt.style.filter = extraBlur > 0.2 ? `blur(${extraBlur.toFixed(1)}px)` : 'none';
}

/* ---------- destaques ---------- */
function aplicarSpots(sc, lt) {
  (sc.spots || []).forEach((sp, j) => {
    const d = spotEls[j]; if (!d) return;
    const op = seg(lt, sp.t, sp.t + 0.25, 'out') * (1 - seg(lt, sp.t2 - 0.25, sp.t2, 'in'));
    if (op <= 0.002) { d.style.opacity = 0; return; }
    const el = q(sp.sel)[0]; if (!el) { d.style.opacity = 0; return; }
    const r = rectApp(el), pad = sp.pad ?? 6;
    const pulso = 1 + 0.008 * Math.sin(lt * 5);
    d.style.width = r.w + pad * 2 + 'px'; d.style.height = r.h + pad * 2 + 'px';
    d.style.transform = `translate(${r.x - pad}px,${r.y - pad}px) scale(${(lerp(1.06, 1, op) * pulso).toFixed(4)})`;
    d.style.opacity = op.toFixed(3);
    const em = d.firstElementChild;
    if (em) em.className = sp.dentro ? 'dentro' : (sp.baixo || r.y < 70 ? 'baixo' : '');
  });
}

/* ---------- fundo vivo ---------- */
const PARTICULAS = Array.from({ length: 70 }, (_, i) => {
  const r = (n) => { const x = Math.sin(i * 12.9898 + n * 78.233) * 43758.5453; return x - Math.floor(x); };
  return { x: r(1) * 1920, y: r(2) * 1080, v: 8 + r(3) * 22, s: 0.8 + r(4) * 2.2, ph: r(5) * 6.28, a: 0.25 + r(6) * 0.5 };
});
function aplicarFundo(t, escuro) {
  const o = dom.orbs;
  // Pulso na batida: mais forte nos tempos 1 e 3 do compasso, que são os fortes da trilha.
  if (!REDUCED) {
    o[0].style.transform = `translate(${Math.sin(t * 0.17) * 70}px,${Math.cos(t * 0.13) * 50}px)`;
    o[1].style.transform = `translate(${Math.cos(t * 0.15) * -60}px,${Math.sin(t * 0.11) * -40}px)`;
    o[2].style.transform = `translate(${Math.sin(t * 0.21) * 90}px,${Math.cos(t * 0.19) * 60}px)`;
  }
  const c = dom.canvas, g = dom.ctx2d;
  if (!g || REDUCED) return;
  g.clearRect(0, 0, 1920, 1080);
  g.fillStyle = '#E4CC8F';
  for (const p of PARTICULAS) {
    const y = ((p.y - t * p.v) % 1180 + 1180) % 1180 - 50;
    const x = p.x + Math.sin(t * 0.3 + p.ph) * 30;
    g.globalAlpha = p.a * (0.5 + 0.5 * Math.sin(t * 0.8 + p.ph)) * (escuro ? 1 : 0.55);
    g.beginPath(); g.arc(x, y, p.s, 0, 6.283); g.fill();
  }
  g.globalAlpha = 1;
}

/* ---------- abertura e encerramento (camadas próprias, função do tempo global) ---------- */
function montarAbertura() {
  const nome = CONFIG.produto.split('').map((c) => `<span>${c}</span>`).join('');
  const frase = ROTEIRO.frase
    .split(' ').map((w) => `<span class="w" style="display:inline-block;white-space:pre">${w} </span>`).join('');
  dom.intro.innerHTML = `
    <div class="intro-in" style="position:absolute;inset:0">
      <div class="logo-wrap" id="in-logo"><img class="logo" src="${CONFIG.logo}" alt="Logotipo ${CONFIG.produto}"><div class="logo-sweep"></div></div>
      <div class="nome" id="in-nome">${nome}</div>
      <div class="sistema" id="in-sistema">${ROTEIRO.sistema}</div>
      <div class="frase" id="in-frase">${frase}</div>
      <div class="slogan" id="in-slogan">${CONFIG.slogan}</div>
    </div>`;
  dom.inLogo = $('#in-logo'); dom.inLetras = $$('#in-nome span'); dom.inSistema = $('#in-sistema');
  dom.inPalavras = $$('#in-frase .w'); dom.inSlogan = $('#in-slogan'); dom.inIn = $('.intro-in');
  const img = $('.logo', dom.intro);
  img.addEventListener('error', () => { img.replaceWith(Object.assign(document.createElement('div'), { textContent: CONFIG.inicial, style: 'font:700 220px var(--font-display);color:#C9A06A;text-align:center' })); });
}
function aplicarAbertura(ti) {
  const lg = seg(ti, 0.5, 2.7, 'outExpo');
  const resp = REDUCED ? 0 : Math.sin(ti * 1.3) * 0.012;
  dom.inLogo.style.transform = `scale(${(0.55 + 0.45 * lg + resp).toFixed(4)}) rotateY(${((1 - lg) * 70).toFixed(2)}deg)`;
  dom.inLogo.style.opacity = clamp(lg * 2).toFixed(3);
  dom.inLogo.style.filter = REDUCED ? 'none' : `blur(${((1 - lg) * 18).toFixed(1)}px)`;
  dom.inLogo.style.setProperty('--glow', seg(ti, 1.4, 3.6, 'out').toFixed(3));
  dom.inLogo.style.setProperty('--sw', lerp(-40, 140, seg(ti, 2.3, 3.5, 'io')).toFixed(1) + '%');
  dom.inLetras.forEach((s, i) => {
    const p = seg(ti, 2.9 + i * 0.06, 3.8 + i * 0.06, 'outExpo');
    s.style.opacity = p.toFixed(3);
    s.style.transform = `translateY(${((1 - p) * 60).toFixed(1)}px)`;
    s.style.filter = REDUCED ? 'none' : `blur(${((1 - p) * 12).toFixed(1)}px)`;
  });
  const ps = seg(ti, 4.6, 5.8, 'out');
  dom.inSistema.style.opacity = ps.toFixed(3);
  dom.inSistema.style.letterSpacing = lerp(0.9, 0.34, ps).toFixed(3) + 'em';
  dom.inPalavras.forEach((w, i) => {
    const p = seg(ti, 6.4 + i * 0.13, 7.2 + i * 0.13, 'out');
    w.style.opacity = p.toFixed(3); w.style.transform = `translateY(${((1 - p) * 22).toFixed(1)}px)`;
  });
  dom.inSlogan.style.opacity = seg(ti, 10.2, 11.4, 'out').toFixed(3);
  const z = seg(ti, 12.4, 15.4, 'in');
  dom.inIn.style.transform = `scale(${(1 + 0.9 * z).toFixed(4)})`;
}
function montarEncerramento() {
  // Resumo do tutorial: um cartão por passo (ROTEIRO.resumo) e a frase final (ROTEIRO.fim).
  const cards = ROTEIRO.resumo || [];
  dom.closing.innerHTML = `
    <div class="topo" id="ce-topo"><img src="${CONFIG.logo}" alt=""><h2>${ROTEIRO.titulo}</h2></div>
    <div class="grade grade--3" id="ce-grade">${cards.map((c, i) => `
      <div class="bene"><div class="ic">${ic(c.ic, 28)}</div>
        <div class="num" data-n="">${i + 1}</div>
        <div class="tit">${c.tit}</div><p>${c.p}</p></div>`).join('')}</div>
    <div class="final" id="ce-final">${ROTEIRO.fim}</div>
    <div class="fonte" id="ce-fonte">Demonstração · dados fictícios</div>
    <div class="fecha" id="ce-fecha"><img src="${CONFIG.logo}" alt=""><b>Wiki do CertGuard</b><small>${CONFIG.slogan.toUpperCase()}</small></div>`;
  dom.ceTopo = $('#ce-topo'); dom.ceBenes = $$('#ce-grade .bene'); dom.ceFinal = $('#ce-final');
  dom.ceFonte = $('#ce-fonte'); dom.ceFecha = $('#ce-fecha'); dom.ceNums = $$('#ce-grade .num');
}
function aplicarEncerramento(ct) {
  const pt = seg(ct, 1.0, 2.2, 'out');
  dom.ceTopo.style.opacity = pt.toFixed(3); dom.ceTopo.style.transform = `translateY(${((1 - pt) * -24).toFixed(1)}px)`;
  dom.ceBenes.forEach((b, i) => {
    const p = seg(ct, 2.0 + i * 0.4, 3.1 + i * 0.4, 'outBack');
    b.style.opacity = clamp(p * 1.4).toFixed(3); b.style.transform = `translateY(${((1 - p) * 50).toFixed(1)}px)`;
    const n = dom.ceNums[i], alvo = n.dataset.n;
    if (alvo) { const v = Math.round(Number(alvo) * EASE.out(seg(ct, 3.0 + i * 0.4, 5.2 + i * 0.4))); n.firstChild.textContent = v.toLocaleString('pt-BR'); }
  });
  const pf = seg(ct, 5.0, 6.6, 'out');
  dom.ceFinal.style.opacity = pf.toFixed(3); dom.ceFinal.style.transform = `translateY(${((1 - pf) * 28).toFixed(1)}px)`;
  dom.ceFonte.style.opacity = (seg(ct, 6.0, 7.0) * 0.9).toFixed(3);
  const fe = seg(ct, 11.4, 13.4, 'io');
  dom.ceFecha.style.setProperty('--fecha', fe.toFixed(3));
  const fi = seg(ct, 12.4, 13.8, 'out') * (1 - seg(ct, 18.4, 20.8, 'io'));
  dom.ceFecha.querySelectorAll('img,b,small').forEach((e, i) => { e.style.opacity = clamp(fi * 1.2 - i * 0.1).toFixed(3); });
}

/* Cortina de transição: só entre módulos diferentes (cenas `suave` se dissolvem sem ela). */
function temVeu(x) { return !!x && !x.suave && (x.tipo === 'closing' || (x.tipo === 'app' && x.cartela)); }
/* A cortina tem 3 camadas (clara, cor do módulo, escura) que fecham e abrem em degraus de meia batida:
   fecha: clara → cor → escura, terminando na batida forte do fim da cena; abre na ordem inversa, logo depois. */
function camadasVeu(sc, lt) {
  const prox = SCENES[SCENES.indexOf(sc) + 1], m = 30 / CONFIG.ritmo.bpm, c = [0, 0, 0];
  for (let i = 0; i < 3; i++) {
    if (temVeu(prox)) c[i] = Math.max(c[i], seg(lt, sc.dur - (3 - i) * m, sc.dur - (2 - i) * m, 'out'));
    if (temVeu(sc)) c[i] = Math.max(c[i], 1 - seg(lt, (4 - i) * m, (5 - i) * m, 'out'));
  }
  return c;
}
function veuDe(sc, lt) { return Math.max(...camadasVeu(sc, lt)); }

/* ---------- HUD: cartela, legenda, véu, etapas ---------- */
function aplicarHud(sc, lt) {
  const app = sc.tipo === 'app';
  // Cortina de transição na cor do módulo: sai da cena atual (cor do próximo módulo) e abre a seguinte.
  const prox = SCENES[SCENES.indexOf(sc) + 1];
  const cv = camadasVeu(sc, lt);
  const saindo = lt > sc.dur / 2;
  const alvo = (temVeu(prox) && saindo) ? prox : sc, M = modDa(alvo);
  const tr = M.forma;
  if (!dom.veil2) { dom.veil3 = document.createElement('div'); dom.veil3.className = 'veil'; dom.veil.parentNode.insertBefore(dom.veil3, dom.veil); dom.veil2 = document.createElement('div'); dom.veil2.className = 'veil'; dom.veil.parentNode.insertBefore(dom.veil2, dom.veil); }
  const forma = (vv) => {
    const k = clamp(vv);
    if (tr === 'circle') return { clip: `circle(${(k * 78).toFixed(2)}% at 50% 46%)`, tf: 'none' };
    if (tr === 'wipe') { const X = saindo ? k * 130 : (1 - k) * 130; return { clip: saindo ? `polygon(0 0, ${X}% 0, ${X - 25}% 100%, 0 100%)` : `polygon(${X}% 0, 100% 0, 100% 100%, ${X - 25}% 100%)`, tf: 'none' }; }
    if (tr === 'diamond') { const d = k * 115; return { clip: `polygon(50% ${50 - d}%, ${50 + d * 1.78}% 50%, 50% ${50 + d}%, ${50 - d * 1.78}% 50%)`, tf: 'none' }; }
    if (tr === 'band') return { clip: `inset(${((1 - k) * 50).toFixed(2)}% 0 ${((1 - k) * 50).toFixed(2)}% 0)`, tf: 'none' };
    if (tr === 'push') return { clip: 'none', tf: `translateX(${((saindo ? -(1 - k) : (1 - k)) * 100).toFixed(2)}%)` };
    return { clip: 'none', tf: 'none' };                                   // blinds: o padrão faz o desenho
  };
  const pinta = (el, vv, cor, cor2) => {
    const st = el.style, f = forma(vv);
    st.opacity = vv > 0.001 ? '1' : '0'; st.clipPath = f.clip; st.transform = f.tf;
    if (tr === 'blinds') { const w = (clamp(vv) * 130).toFixed(1); st.background = `repeating-linear-gradient(90deg,${cor} 0,${cor} ${w}px,transparent ${w}px,transparent 130px)`; }
    else st.background = cor2 ? `linear-gradient(118deg, ${cor} 0%, ${cor2} 100%)` : cor;
  };
  pinta(dom.veil3, cv[0], M.clara);
  pinta(dom.veil2, cv[1], M.cor);
  pinta(dom.veil, cv[2], M.escura, M.cor);

  // Cartela: grande no centro → pequena no canto.
  if (app) {
    let big = 0, pos = 1;
    if (sc.cartela && !sc.suave) { big = seg(lt, 0, MEIA, 'outBack'); pos = seg(lt, 3 * MEIA, 6 * MEIA, 'io'); }
    else { big = sc.suave ? seg(lt, 0.5, 1.0, 'out') : seg(lt, 0.9, 1.4, 'out'); pos = 1; }
    const w = sc._cw || 600, h = sc._ch || 100;
    const S0 = REDUCED ? 1 : 1.15, S1 = 0.56;
    const s = lerp(S0, S1, pos);
    const fx_ = sc.cfx || 'zoom', off = 1 - big;
    const ox = fx_ === 'slide' ? -420 * off : 0, oy = fx_ === 'drop' ? -360 * off : 0, rot = fx_ === 'spin' ? -14 * off : 0;
    const x = lerp(960 - (w * S0) / 2, 44, pos) + ox, y = lerp(470 - (h * S0) / 2, 912, pos) + oy;
    const saida = sc.cartela ? 1 - (prox && prox.suave ? seg(lt, sc.dur - 0.7, sc.dur - 0.15, 'in') : seg(lt, sc.dur - 5 * MEIA, sc.dur - 3.6 * MEIA, 'in') * (temVeu(prox) ? 1 : 0)) : 1;
    dom.cartela.style.opacity = (big * saida).toFixed(3);
    dom.cartela.style.transform = `translate(${x.toFixed(1)}px,${y.toFixed(1)}px) scale(${s.toFixed(4)}) rotate(${rot.toFixed(2)}deg)`;
    dom.cartela.style.filter = REDUCED || big >= 1 ? 'none' : `blur(${((1 - big) * 12).toFixed(1)}px)`;
  } else dom.cartela.style.opacity = 0;

  // Legenda sincronizada.
  const L = sc.legendas || [];
  let k = -1;
  for (let i = 0; i < L.length; i++) if (lt >= L[i].t && lt < L[i].t2) k = i;
  if (k !== dom._legKey) {
    dom._legKey = k; dom.legendaTxt.innerHTML = k >= 0 ? L[k].txt : '';
    // Cada palavra vira um elemento, para entrar em sequência (tipografia em movimento).
    const w = document.createTreeWalker(dom.legendaTxt, NodeFilter.SHOW_TEXT), nos = [];
    while (w.nextNode()) nos.push(w.currentNode);
    nos.forEach((n) => {
      const f = document.createDocumentFragment();
      n.textContent.split(/(\s+)/).forEach((p) => {
        if (!p) return;
        if (/^\s+$/.test(p)) f.appendChild(document.createTextNode(' '));
        else { const sp = document.createElement('span'); sp.className = 'pw'; sp.textContent = p; f.appendChild(sp); }
      });
      n.replaceWith(f);
    });
    dom._pw = $$('.pw', dom.legendaTxt);
  }
  if (k >= 0) {
    const op = Math.min(seg(lt, L[k].t, L[k].t + 0.15, 'out'), 1 - seg(lt, L[k].t2 - 0.18, L[k].t2, 'in'));
    dom.legenda.style.opacity = op.toFixed(3);
    dom.legenda.style.transform = `scale(${lerp(0.94, 1, op).toFixed(3)})`;
    (dom._pw || []).forEach((e, i) => {
      const p = seg(lt, L[k].t + i * 0.06, L[k].t + i * 0.06 + 0.3, 'outBack');
      e.style.opacity = clamp(p * 1.6).toFixed(3);
      e.style.transform = `translateY(${((1 - p) * 26).toFixed(1)}px) scale(${lerp(0.7, 1, p).toFixed(3)})`;
    });
  } else dom.legenda.style.opacity = 0;

  // Aviso de dados fictícios.
  dom.aviso.style.opacity = app ? (seg(lt, 1.1, 1.7) * (1 - Math.max(...cv))).toFixed(3) : 0;

  // Pop-ups: cada um entra de um jeito diferente.
  (sc.pops || []).forEach((p, i) => {
    const e = dom._popEls && dom._popEls[i]; if (!e) return;
    const pin = seg(lt, p.t, p.t + 0.4, p.fx === 'pop' ? 'outBack' : 'outExpo'), pout = seg(lt, p.t2 - 0.25, p.t2, 'in');
    const op = clamp(pin * 1.6) * (1 - pout), inv = 1 - pin;
    let tr = '';
    if (p.fx === 'slide') tr = `translateX(${(inv * 260).toFixed(1)}px)`;
    else if (p.fx === 'drop') tr = `translateY(${(-inv * 220).toFixed(1)}px)`;
    else if (p.fx === 'flip') tr = `perspective(700px) rotateX(${(inv * 90).toFixed(1)}deg)`;
    else tr = `scale(${lerp(0.3, 1, pin).toFixed(3)})`;
    e.style.left = p.x + 'px'; e.style.top = p.y + 'px';
    e.style.opacity = op.toFixed(3);
    e.style.transform = `translate(-50%,-50%) ${tr} scale(${lerp(1, 0.9, pout).toFixed(3)})`;
  });
  dom.faixa.style.opacity = app ? seg(lt, 0, 0.4).toFixed(3) : 0;

  // Jornada: etapas e chamada.
  const pa = sc.passos && sc.passos.length;
  dom.passos.style.opacity = pa ? seg(lt, 1.4, 1.9).toFixed(3) : 0;
  if (pa) $$('.passo', dom.passos).forEach((el, i) => {
    const [, a, b] = sc.passos[i];
    el.classList.toggle('is-on', lt >= a && lt < b);
    el.classList.toggle('is-done', lt >= b);
  });
  const ch = sc.chamada;
  if (ch) {
    const op = seg(lt, ch.t, ch.t + 0.5, 'out') * (1 - seg(lt, ch.t2 - 0.5, ch.t2, 'in'));
    dom.chamada.style.opacity = op.toFixed(3);
    dom.chamada.style.transform = `translateY(${((1 - op) * -30).toFixed(1)}px)`;
    dom.chamada.style.setProperty('--r', ((lt * 1.6) % 1).toFixed(3));
  } else dom.chamada.style.opacity = 0;
}

/* ---------- renderização de um instante ---------- */
const _falhas = new Set();
function seguro(f) { try { f(); } catch (e) { const k = String(e && e.message); if (!_falhas.has(k)) { _falhas.add(k); console.warn('Quadro com falha (ignorada):', k); } } }
function render(t) {
  const total = SCENES.total;
  t = clamp(t, 0, total);
  const i = indexDe(t), sc = SCENES[i], lt = t - sc.start;
  if (i !== lastIdx) aoMudarDeCena(i);

  const intro = SCENES[0], appIni = SCENES.find((s) => s.tipo === 'app'), fim = SCENES[SCENES.length - 1];
  // `vel` acelera a abertura e o encerramento (vídeos curtos da wiki) sem reescrever os tempos deles.
  const ti = (t - intro.start) / RITMO * (intro.vel || 1), ct = (t - fim.start) / RITMO * (fim.vel || 1), ta = t - appIni.start;

  // Camadas (globais, para os cruzamentos entre abertura → app → encerramento ficarem contínuos).
  const opIntro = seg(t, 0, 0.9) * (1 - seg(ti, 13.0, 15.4, 'io'));
  dom.intro.style.opacity = opIntro.toFixed(3); dom.intro.style.visibility = opIntro > 0.002 ? 'visible' : 'hidden';
  if (opIntro > 0.002) aplicarAbertura(ti);
  const opApp = seg(ta, 0, 1.5, 'io') * (1 - seg(ct, 0, 1.3, 'io'));
  dom.camera.parentElement.style.opacity = opApp.toFixed(3);
  dom.camera.parentElement.style.visibility = opApp > 0.002 ? 'visible' : 'hidden';
  const opFim = seg(ct, 0, 1.5, 'io');
  dom.closing.style.opacity = opFim.toFixed(3); dom.closing.style.visibility = opFim > 0.002 ? 'visible' : 'hidden';
  if (opFim > 0.002) aplicarEncerramento(ct);

  aplicarFundo(t, sc.tipo !== 'app');

  if (sc.tipo === 'app') {
    // Cena suave: a tela anterior se dissolve já no estado final dela (não volta ao estado inicial).
    if (sc.suave && lt < 1.0) { const ant = SCENES[i - 1]; if (ant) seguro(() => aplicarFx(ant, ant.dur - 0.001)); }
    seguro(() => aplicarEntrada(sc, lt));
    seguro(() => aplicarFx(sc, lt)); seguro(() => aplicarPaginas(sc, lt)); seguro(() => aplicarCursor(sc, lt)); seguro(() => aplicarSpots(sc, lt));
    const v = veuDe(sc, lt);
    const entrada = sc.entrada === 'zoom' && !REDUCED ? (1 - seg(lt, 0, 1.1, 'out')) * 16 : 0;
    seguro(() => aplicarCamera(sc, lt, REDUCED ? 0 : v * 6 + entrada));
  }
  seguro(() => aplicarHud(sc, lt));
  dom.sceneIdx = i;
}

/* ------------------------------------------------------------ 6. ÁUDIO */
/*
  Duas fontes de trilha, nessa ordem:
    1) assets/audio/trilha.mp3 (ou o caminho em CONFIG.audio.arquivo), se existir e carregar;
    2) trilha instrumental sintetizada pelo navegador (Web Audio) — sem arquivos, sem rede.
  Os efeitos (cliques, digitação, transições) são sempre sintetizados. Tudo é opcional: se o áudio falhar
  ou o navegador não suportar, a apresentação segue normalmente, em silêncio.
*/
const midi = (n) => 440 * Math.pow(2, (n - 69) / 12);
const Audio_ = {
  ctx: null, master: null, musica: null, sfx: null, el: null, modo: null, ligado: false, ok: false,
  vol: CONFIG.audio.volumeInicial, mudo: true, env: 0, timer: null, proximo: 0, passo: 0,

  iniciar() {
    if (this.ctx || this.falhou) return;
    try {
      const AC = window.AudioContext || window.webkitAudioContext;
      if (!AC) { this.falhou = true; return; }
      this.ctx = new AC();
      const c = this.ctx;
      this.master = c.createGain();
      const comp = c.createDynamicsCompressor();
      comp.threshold.value = -18; comp.ratio.value = 3;
      this.master.connect(comp); comp.connect(c.destination);
      this.sfx = c.createGain(); this.sfx.gain.value = 0.9; this.sfx.connect(this.master);
      this.musica = c.createGain(); this.musica.gain.value = 0; this.musica.connect(this.master);
      this.ok = true;
      this.tentarArquivo();
    } catch (e) { this.falhou = true; this.ok = false; console.warn('Áudio indisponível:', e && e.message); }
  },

  tentarArquivo() {
    // Usa o arquivo local se ele existir; senão, cai para a trilha sintetizada.
    let decidido = false;
    const sintetizar = () => { if (decidido) return; decidido = true; this.modo = 'sintese'; this.iniciarSintese(); this.aplicar(); };
    try {
      const a = new window.Audio();
      a.loop = true; a.preload = 'auto';
      a.addEventListener('canplaythrough', () => { if (decidido) return; decidido = true; this.el = a; this.modo = 'arquivo'; this.aplicar(); if (this.ligado) a.play().catch(() => {}); }, { once: true });
      a.addEventListener('error', sintetizar, { once: true });
      a.src = CONFIG.audio.arquivo;
      setTimeout(sintetizar, 2500);
    } catch (e) { sintetizar(); }
  },

  /* nível final da trilha: volume do usuário × envelope (fade-in na abertura, fade-out no encerramento) */
  aplicar() {
    if (!this.ok) return;
    const g = this.mudo ? 0 : this.vol * this.vol;
    const now = this.ctx.currentTime;
    this.master.gain.setTargetAtTime(g, now, 0.05);
    this.musica.gain.setTargetAtTime(this.env, now, 0.15);
    if (this.el) { try { this.el.volume = clamp(g * this.env * 0.8); } catch (e) { /* mídia sem volume */ } }
  },
  definirEnvelope(t) {
    const total = SCENES.total;
    const e = seg(t, 0, CONFIG.audio.fadeInSeg, 'soft') * (1 - seg(t, total - CONFIG.audio.fadeOutSeg, total - 0.3, 'soft'));
    if (Math.abs(e - this.env) > 0.004) { this.env = e; this.aplicar(); }
  },

  tocar() {
    this.ligado = true;
    if (!this.ok) return;
    try { this.ctx.resume(); } catch (e) { /* ignorado */ }
    if (this.el) this.el.play().catch(() => {});
  },
  pausar() {
    this.ligado = false;
    if (!this.ok) return;
    try { this.ctx.suspend(); } catch (e) { /* ignorado */ }
    if (this.el) this.el.pause();
  },
  reiniciar() { if (this.el) { try { this.el.currentTime = 0; } catch (e) { /* ignorado */ } } },

  /* ---------- trilha eletrônica sintetizada: 124 bpm, kick 4x4, baixo em contratempo com pump, arpejo, riser ---------- */
  iniciarSintese() {
    const c = this.ctx;
    const mk = (tipo, f, q) => { const n = c.createBiquadFilter(); n.type = tipo; n.frequency.value = f; if (q) n.Q.value = q; return n; };
    const conv = c.createConvolver();
    const len = Math.floor(c.sampleRate * 2.2), buf = c.createBuffer(2, len, c.sampleRate);
    for (let ch = 0; ch < 2; ch++) { const d = buf.getChannelData(ch); for (let i = 0; i < len; i++) d[i] = (Math.random() * 2 - 1) * Math.pow(1 - i / len, 3); }
    conv.buffer = buf;
    const rev = c.createGain(); rev.gain.value = 0.45; conv.connect(rev); rev.connect(this.musica);
    // Barramentos com "pump" (sidechain simulado): abaixam a cada kick e voltam.
    this.padBus = c.createGain(); this.baixoBus = c.createGain(); this.arpBus = c.createGain();
    const padF = mk('lowpass', 2200, 0.6); this.padBus.connect(padF); padF.connect(this.musica); padF.connect(conv);
    const arpF = mk('lowpass', 5200, 0.8); this.arpFiltro = arpF; this.arpBus.connect(arpF); arpF.connect(this.musica); arpF.connect(conv);
    this.baixoBus.connect(this.musica);
    this.proximo = c.currentTime + 0.15; this.passo = 0;
    this.timer = setInterval(() => this.agendar(), 100);
  },
  agendar() {
    if (!this.ok || this.modo !== 'sintese' || this.ctx.state !== 'running') return;
    const c = this.ctx, beat = 60 / 124, st = beat / 4;
    const acordes = [[57, 60, 64, 67], [53, 57, 60, 64], [60, 64, 67, 71], [55, 59, 62, 66]];
    const raizes = [45, 41, 48, 43];
    const arp = [0, 2, 1, 3, 2, 4, 3, 1, 0, 2, 4, 3, 2, 1, 3, 5];
    while (this.proximo < c.currentTime + 0.5) {
      const t = this.proximo, i = this.passo, p = i % 16, bar = Math.floor(i / 16);
      const ac = acordes[Math.floor(bar / 2) % 4], raiz = raizes[Math.floor(bar / 2) % 4];
      const intro = bar < 2, fim8 = bar % 8 === 7;
      if (i % 32 === 0) this.pad(ac, t, st * 32);
      if (!intro && p % 4 === 0) { this.bumbo(t); this.pump(t, st * 3.2); }
      if (!intro && (p === 4 || p === 12)) this.palma(t);
      if (p % 2 === 0 && p % 4 !== 0) this.chimbal(t, bar >= 2 ? 0.05 : 0.025, 0.09);
      if (!intro && p % 2 === 1 && Math.random() < 0.5) this.chimbal(t, 0.016, 0.03);
      if (!intro && (p === 2 || p === 6 || p === 10 || p === 14)) this.baixo(raiz, t, st * 1.8);
      if (bar >= 1) this.arpejo(ac[arp[p] % ac.length] + 12 + (bar % 4 >= 2 ? 12 : 0), t, st);
      if (fim8) { if (p === 0) this.riser(t, st * 16); if (p >= 8 && p % 2 === 0) this.caixa(t, 0.03 + (p - 8) * 0.01); }
      if (p === 0 && bar % 8 === 0 && bar > 0) this.impacto(t);
      this.proximo += st; this.passo++;
    }
  },
  pump(t, dur) {
    [this.padBus, this.baixoBus, this.arpBus].forEach((b, k) => {
      b.gain.cancelScheduledValues(t); b.gain.setValueAtTime(0.28, t); b.gain.linearRampToValueAtTime(1, t + dur);
    });
  },
  pad(notas, t, dur) {
    const c = this.ctx;
    notas.forEach((n) => [-12, 0, 12].forEach((det) => {
      const o = c.createOscillator(), g = c.createGain();
      o.type = 'sawtooth'; o.frequency.value = midi(n); o.detune.value = det;
      g.gain.setValueAtTime(0, t); g.gain.linearRampToValueAtTime(0.016, t + 0.6);
      g.gain.setValueAtTime(0.016, t + dur - 0.2); g.gain.linearRampToValueAtTime(0, t + dur + 0.5);
      o.connect(g); g.connect(this.padBus); o.start(t); o.stop(t + dur + 0.6);
    }));
  },
  baixo(n, t, dur) {
    const c = this.ctx, o = c.createOscillator(), g = c.createGain(), f = c.createBiquadFilter();
    o.type = 'sawtooth'; o.frequency.value = midi(n); f.type = 'lowpass'; f.Q.value = 5;
    f.frequency.setValueAtTime(900, t); f.frequency.exponentialRampToValueAtTime(180, t + dur);
    g.gain.setValueAtTime(0.0001, t); g.gain.linearRampToValueAtTime(0.14, t + 0.01); g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
    o.connect(f); f.connect(g); g.connect(this.baixoBus); o.start(t); o.stop(t + dur + 0.05);
  },
  arpejo(n, t, st) {
    const c = this.ctx, o = c.createOscillator(), g = c.createGain(), f = c.createBiquadFilter();
    o.type = 'sawtooth'; o.frequency.value = midi(n); f.type = 'lowpass'; f.Q.value = 3;
    f.frequency.setValueAtTime(3800, t); f.frequency.exponentialRampToValueAtTime(700, t + st * 1.6);
    g.gain.setValueAtTime(0.0001, t); g.gain.linearRampToValueAtTime(0.045, t + 0.005); g.gain.exponentialRampToValueAtTime(0.0001, t + st * 1.7);
    o.connect(f); f.connect(g); g.connect(this.arpBus); o.start(t); o.stop(t + st * 1.8);
  },
  bumbo(t) {
    const c = this.ctx, o = c.createOscillator(), g = c.createGain();
    o.type = 'sine'; o.frequency.setValueAtTime(165, t); o.frequency.exponentialRampToValueAtTime(44, t + 0.12);
    g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(0.36, t + 0.003); g.gain.exponentialRampToValueAtTime(0.0001, t + 0.26);
    o.connect(g); g.connect(this.musica); o.start(t); o.stop(t + 0.3);
  },
  palma(t) {
    const s = this.ruido(0.18), f = this.ctx.createBiquadFilter(), g = this.ctx.createGain();
    f.type = 'bandpass'; f.frequency.value = 1700; f.Q.value = 0.8;
    g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(0.13, t + 0.004); g.gain.exponentialRampToValueAtTime(0.0001, t + 0.16);
    s.connect(f); f.connect(g); g.connect(this.musica); s.start(t); s.stop(t + 0.2);
  },
  caixa(t, v) {
    const s = this.ruido(0.1), f = this.ctx.createBiquadFilter(), g = this.ctx.createGain();
    f.type = 'highpass'; f.frequency.value = 1800;
    g.gain.setValueAtTime(v, t); g.gain.exponentialRampToValueAtTime(0.0001, t + 0.09);
    s.connect(f); f.connect(g); g.connect(this.musica); s.start(t); s.stop(t + 0.11);
  },
  chimbal(t, v = 0.03, dur = 0.05) {
    const s = this.ruido(dur + 0.02), f = this.ctx.createBiquadFilter(), g = this.ctx.createGain();
    f.type = 'highpass'; f.frequency.value = 7500;
    g.gain.setValueAtTime(v, t); g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
    s.connect(f); f.connect(g); g.connect(this.musica); s.start(t); s.stop(t + dur + 0.02);
  },
  riser(t, dur) {
    const s = this.ruido(dur + 0.1), f = this.ctx.createBiquadFilter(), g = this.ctx.createGain();
    f.type = 'bandpass'; f.Q.value = 2; f.frequency.setValueAtTime(400, t); f.frequency.exponentialRampToValueAtTime(7000, t + dur);
    g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(0.09, t + dur);
    s.connect(f); f.connect(g); g.connect(this.musica); s.start(t); s.stop(t + dur + 0.1);
  },
  impacto(t) {
    const c = this.ctx, o = c.createOscillator(), g = c.createGain();
    o.type = 'sine'; o.frequency.setValueAtTime(90, t); o.frequency.exponentialRampToValueAtTime(30, t + 0.6);
    g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(0.3, t + 0.01); g.gain.exponentialRampToValueAtTime(0.0001, t + 0.8);
    o.connect(g); g.connect(this.musica); o.start(t); o.stop(t + 0.9);
    this.caixa(t, 0.12);
  },

  /* ---------- efeitos sutis ---------- */
  ruido(dur) {
    const c = this.ctx, b = c.createBuffer(1, Math.max(1, Math.floor(c.sampleRate * dur)), c.sampleRate), d = b.getChannelData(0);
    for (let i = 0; i < d.length; i++) d[i] = Math.random() * 2 - 1;
    const s = c.createBufferSource(); s.buffer = b; return s;
  },
  efeito(tipo) {
    if (!this.ok || this.mudo || !this.ligado || this.ctx.state !== 'running') return;
    try {
      const c = this.ctx, t = c.currentTime;
      const env = (g, a, pico, dec) => { g.gain.setValueAtTime(0, t); g.gain.linearRampToValueAtTime(pico, t + a); g.gain.exponentialRampToValueAtTime(0.0001, t + a + dec); };
      const tom = (f, tipo_, pico, a, dec, f2) => {
        const o = c.createOscillator(), g = c.createGain(); o.type = tipo_; o.frequency.setValueAtTime(f, t);
        if (f2) o.frequency.exponentialRampToValueAtTime(f2, t + a + dec);
        env(g, a, pico, dec); o.connect(g); g.connect(this.sfx); o.start(t); o.stop(t + a + dec + 0.05);
      };
      const sopro = (f0, f1, dur, pico, q = 1.2) => {
        const s = this.ruido(dur), fl = c.createBiquadFilter(), g = c.createGain();
        fl.type = 'bandpass'; fl.Q.value = q; fl.frequency.setValueAtTime(f0, t); fl.frequency.exponentialRampToValueAtTime(f1, t + dur);
        env(g, dur * 0.35, pico, dur * 0.65); s.connect(fl); fl.connect(g); g.connect(this.sfx); s.start(t); s.stop(t + dur + 0.05);
      };
      switch (tipo) {
        case 'click': tom(1100, 'sine', 0.16, 0.002, 0.07, 640); sopro(3200, 2000, 0.03, 0.09, 2); break;
        case 'key': sopro(3800 + Math.random() * 1200, 2600, 0.02, 0.05, 2); break;
        case 'whoosh': sopro(260, 2600, 0.8, 0.13); break;
        case 'swish': sopro(500, 3200, 0.38, 0.09); break;
        case 'chime': tom(880, 'sine', 0.09, 0.005, 0.7); setTimeout(() => this.efeito('chime2'), 90); break;
        case 'chime2': tom(1318.5, 'sine', 0.07, 0.005, 0.8); break;
        case 'shine': tom(2637, 'sine', 0.04, 0.01, 0.9, 3136); break;
        case 'pop': tom(520, 'sine', 0.12, 0.003, 0.14, 1100); tom(1560, 'triangle', 0.04, 0.003, 0.1); break;
        case 'ring': tom(440, 'sine', 0.06, 0.02, 0.35); tom(480, 'sine', 0.06, 0.02, 0.35); break;
        case 'swell': { const o = c.createOscillator(), g = c.createGain(); o.type = 'sawtooth'; o.frequency.setValueAtTime(110, t); o.frequency.exponentialRampToValueAtTime(220, t + 2.2);
          g.gain.setValueAtTime(0, t); g.gain.linearRampToValueAtTime(0.03, t + 1.6); g.gain.exponentialRampToValueAtTime(0.0001, t + 2.6);
          const fl = c.createBiquadFilter(); fl.type = 'lowpass'; fl.frequency.value = 700; o.connect(fl); fl.connect(g); g.connect(this.sfx); o.start(t); o.stop(t + 2.7); break; }
      }
    } catch (e) { /* efeito é opcional */ }
  },
};

/* Lista de efeitos (clicks, digitação, transições) derivada do roteiro, em tempo absoluto. */
const EVENTOS = [];
(function montarEventos() {
  SCENES.forEach((sc) => {
    (sc.sfx || []).forEach((e) => EVENTOS.push({ t: sc.start + e.t, s: e.s }));
    (sc.cursor || []).forEach((w) => { if (w.click) EVENTOS.push({ t: sc.start + w.t, s: 'click' }); });
    (sc.pops || []).forEach((p) => EVENTOS.push({ t: sc.start + p.t, s: 'pop' }));
    (sc.fx || []).forEach((a) => {
      if (a.k === 'type' && a.dur > 0.2) {
        const n = a.text.length;
        for (let i = 0; i < n; i += 2) EVENTOS.push({ t: sc.start + a.t + (a.dur * i) / n, s: 'key' });
      }
    });
  });
  EVENTOS.sort((x, y) => x.t - y.t);
})();

/* ------------------------------------------------------------ 7. PLAYER */
const P = { t: 0, tocando: false, iniciado: false, ultimo: 0, auto: true, evPtr: 0, fim: false };
const el = (id) => document.getElementById(id);
let ocultar = null;

function mensagem(txt, ms = 2200) {
  const m = el('msg'); m.textContent = txt; m.classList.add('is-on');
  clearTimeout(mensagem._t); mensagem._t = setTimeout(() => m.classList.remove('is-on'), ms);
}
function ajustarEscala() {
  const vp = el('viewport'), w = vp.clientWidth, h = vp.clientHeight;
  const s = Math.min(w / 1920, h / 1080);
  stageEl.style.transform = `scale(${s}) translate(-960px,-540px)`;
}
function seekPara(t, { manter = true } = {}) {
  P.t = clamp(t, 0, SCENES.total);
  P.fim = P.t >= SCENES.total - 0.01;
  P.evPtr = EVENTOS.findIndex((e) => e.t > P.t);
  if (P.evPtr < 0) P.evPtr = EVENTOS.length;
  render(P.t);
  atualizarUI(true);
  if (!manter) pausar();
}
function tocar() {
  if (!P.iniciado) return;
  if (P.t >= SCENES.total - 0.05) { seekPara(0); Audio_.reiniciar(); }
  P.tocando = true; P.fim = false; P.ultimo = performance.now();
  Audio_.tocar();
  playerEl.classList.remove('pausado');
  el('btn-play').innerHTML = ICO.pausa; el('btn-play').setAttribute('aria-label', 'Pausar');
  agendarOcultar();
}
function pausar() {
  P.tocando = false;
  Audio_.pausar();
  playerEl.classList.add('pausado');
  el('btn-play').innerHTML = ICO.play; el('btn-play').setAttribute('aria-label', 'Reproduzir');
  playerEl.classList.remove('idle');
}
const alternar = () => (P.tocando ? pausar() : tocar());
function irParaCena(delta) {
  const i = indexDe(P.t);
  const dentro = P.t - SCENES[i].start;
  let alvo = i + delta;
  if (delta < 0 && dentro > 2.5) alvo = i;                 // “voltar” no meio da cena reinicia a cena
  alvo = clamp(alvo, 0, SCENES.length - 1);
  seekPara(SCENES[alvo].start + (alvo === 0 ? 0 : 0.001));
  mensagem(`Cena ${alvo + 1} de ${SCENES.length} · ${SCENES[alvo].nome}`);
}

// ?audio=1: toca só o som (sem desenhar a tela). Usado para gravar os efeitos sonoros do MP4 sem o relógio atrasar.
const SO_AUDIO = /[?&]audio=1/.test(location.search);
function quadro(agora) {
  requestAnimationFrame(quadro);
  if (!P.iniciado) return;
  const dt = Math.min(0.1, (agora - P.ultimo) / 1000);
  P.ultimo = agora;
  avancar(dt);
}
function avancar(dt) {
  if (P.tocando) {
    const antes = P.t;
    P.t += dt;
    const iA = indexDe(antes), iB = indexDe(Math.min(P.t, SCENES.total));
    // Reprodução automática desligada: para ao fim de cada cena.
    if (!P.auto && iB > iA) { P.t = SCENES[iB].start - 0.001; pausar(); mensagem('Fim da cena — pressione ▶ para continuar'); }
    if (P.t >= SCENES.total) { P.t = SCENES.total; pausar(); P.fim = true; mensagem('Fim da apresentação — pressione ▶ para rever'); }
    while (P.evPtr < EVENTOS.length && EVENTOS[P.evPtr].t <= P.t) {
      if (P.t - EVENTOS[P.evPtr].t < 0.25 && P.tocando) Audio_.efeito(EVENTOS[P.evPtr].s);
      P.evPtr++;
    }
  }
  if (!SO_AUDIO) render(P.t);
  Audio_.definirEnvelope(P.t);
  if (!SO_AUDIO) atualizarUI();
}

let _ui = { seg: -1, pct: -1, cena: -1 };
function atualizarUI(forcar) {
  const s = Math.floor(P.t);
  const pct = (P.t / SCENES.total) * 100;
  if (forcar || pct !== _ui.pct) {
    el('prog-fill').style.width = pct + '%'; el('prog-knob').style.left = pct + '%';
    el('progresso').setAttribute('aria-valuenow', String(Math.round(P.t)));
    _ui.pct = pct;
  }
  if (forcar || s !== _ui.seg) { el('tempo').textContent = `${fmtTempo(P.t)} / ${fmtTempo(SCENES.total)}`; _ui.seg = s; }
  const i = indexDe(P.t);
  if (forcar || i !== _ui.cena) { el('cena-nome').textContent = `${String(i + 1).padStart(2, '0')} · ${SCENES[i].nome}`; _ui.cena = i; }
}

const ICO = {
  play: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>',
  pausa: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M6 5h4v14H6zM14 5h4v14h-4z"/></svg>',
  vol: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 5 6 9H2v6h4l5 4z" fill="currentColor"/><path d="M15.5 8.5a5 5 0 0 1 0 7M18.5 5.5a9 9 0 0 1 0 13"/></svg>',
  mudo: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 5 6 9H2v6h4l5 4z" fill="currentColor"/><path d="m22 9-6 6m0-6 6 6"/></svg>',
  tela: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3"/></svg>',
  sair: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M8 3v3a2 2 0 0 1-2 2H3m18 0h-3a2 2 0 0 1-2-2V3m0 18v-3a2 2 0 0 1 2-2h3M3 16h3a2 2 0 0 1 2 2v3"/></svg>',
};

function alternarMudo(forcar) {
  Audio_.iniciar();
  Audio_.mudo = forcar !== undefined ? forcar : !Audio_.mudo;
  if (!Audio_.mudo && Audio_.vol === 0) Audio_.vol = CONFIG.audio.volumeInicial;
  Audio_.aplicar();
  if (P.tocando) Audio_.tocar();
  atualizarVolumeUI();
  if (!Audio_.mudo && Audio_.falhou) mensagem('Áudio indisponível neste navegador');
}
function atualizarVolumeUI() {
  const mudo = Audio_.mudo || Audio_.vol === 0;
  el('btn-vol').innerHTML = mudo ? ICO.mudo : ICO.vol;
  el('btn-vol').setAttribute('aria-label', mudo ? 'Ativar som' : 'Desativar som');
  el('btn-vol').classList.toggle('is-on', !mudo);
  el('vol').value = String(Math.round((Audio_.mudo ? 0 : Audio_.vol) * 100));
}
function tela() {
  if (document.fullscreenElement) document.exitFullscreen && document.exitFullscreen();
  else if (playerEl.requestFullscreen) playerEl.requestFullscreen().catch(() => mensagem('Tela cheia indisponível'));
}
function agendarOcultar() {
  playerEl.classList.remove('idle');
  clearTimeout(ocultar);
  if (P.tocando) ocultar = setTimeout(() => { if (P.tocando) playerEl.classList.add('idle'); }, 2800);
}

function iniciar(comSom) {
  if (P.iniciado) return;
  P.iniciado = true;
  el('start').classList.add('is-out');
  if (comSom) { Audio_.iniciar(); Audio_.mudo = false; } else { Audio_.mudo = true; }
  atualizarVolumeUI();
  seekPara(0);
  tocar();
  setTimeout(() => el('btn-play').focus({ preventScroll: true }), 600);
}

function ligarControles() {
  el('btn-iniciar').addEventListener('click', () => iniciar(false));
  el('btn-iniciar-som').addEventListener('click', () => iniciar(true));
  el('btn-play').addEventListener('click', alternar);
  el('btn-reiniciar').addEventListener('click', () => { seekPara(0); Audio_.reiniciar(); tocar(); });
  el('btn-ant').addEventListener('click', () => irParaCena(-1));
  el('btn-prox').addEventListener('click', () => irParaCena(1));
  el('btn-vol').addEventListener('click', () => alternarMudo());
  el('vol').addEventListener('input', (e) => { Audio_.iniciar(); Audio_.vol = Number(e.target.value) / 100; Audio_.mudo = Audio_.vol === 0; Audio_.aplicar(); if (P.tocando) Audio_.tocar(); atualizarVolumeUI(); });
  el('btn-tela').addEventListener('click', tela);
  el('auto').addEventListener('change', (e) => { P.auto = e.target.checked; mensagem(P.auto ? 'Reprodução automática das cenas: ligada' : 'Reprodução automática desligada — pausa ao fim de cada cena'); });
  playerEl.addEventListener('dblclick', (e) => { if (!e.target.closest('.controls,.start')) tela(); });
  el('viewport').addEventListener('click', () => { if (P.iniciado) alternar(); });

  // Barra de progresso: clique e arraste.
  const barra = el('progresso'), dica = el('prog-dica');
  const tempoDe = (ev) => { const r = barra.getBoundingClientRect(); return clamp((ev.clientX - r.left) / r.width) * SCENES.total; };
  let arrasto = false, estavaTocando = false;
  barra.addEventListener('pointerdown', (ev) => { if (!P.iniciado) return; arrasto = true; estavaTocando = P.tocando; barra.setPointerCapture(ev.pointerId); barra.classList.add('is-drag'); seekPara(tempoDe(ev)); });
  barra.addEventListener('pointermove', (ev) => {
    const t = tempoDe(ev), r = barra.getBoundingClientRect();
    dica.style.left = clamp(ev.clientX - r.left, 40, r.width - 40) + 'px';
    dica.textContent = `${fmtTempo(t)} · ${SCENES[indexDe(t)].nome}`;
    if (arrasto) seekPara(t);
  });
  const soltar = (ev) => { if (!arrasto) return; arrasto = false; barra.classList.remove('is-drag'); try { barra.releasePointerCapture(ev.pointerId); } catch (e) { /* ignorado */ } if (estavaTocando && !P.fim) tocar(); };
  barra.addEventListener('pointerup', soltar); barra.addEventListener('pointercancel', soltar);
  SCENES.slice(1).forEach((s) => { const m = document.createElement('i'); m.className = 'progress__marca'; m.style.left = (s.start / SCENES.total) * 100 + '%'; el('prog-marcas').appendChild(m); });

  ['pointermove', 'pointerdown', 'keydown'].forEach((ev) => playerEl.addEventListener(ev, agendarOcultar));
  document.addEventListener('fullscreenchange', () => { playerEl.classList.toggle('fs', !!document.fullscreenElement); el('btn-tela').innerHTML = document.fullscreenElement ? ICO.sair : ICO.tela; ajustarEscala(); });
  window.addEventListener('resize', ajustarEscala);

  document.addEventListener('keydown', (e) => {
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    const k = e.key;
    if (!P.iniciado) { if (k === 'Enter') { e.preventDefault(); iniciar(false); } return; }
    const foco = document.activeElement;
    if ((k === ' ' || k === 'Enter') && foco && foco.tagName === 'BUTTON' && foco.id !== 'btn-play') return;   // deixa o botão focado agir
    switch (k) {
      case ' ': case 'k': case 'K': e.preventDefault(); alternar(); break;
      case 'ArrowRight': e.preventDefault(); seekPara(P.t + (e.shiftKey ? 15 : 5)); break;
      case 'ArrowLeft': e.preventDefault(); seekPara(P.t - (e.shiftKey ? 15 : 5)); break;
      case 'PageDown': case ']': case 'n': case 'N': e.preventDefault(); irParaCena(1); break;
      case 'PageUp': case '[': case 'p': case 'P': e.preventDefault(); irParaCena(-1); break;
      case 'Home': e.preventDefault(); seekPara(0); break;
      case 'End': e.preventDefault(); seekPara(SCENES.total - 0.05); break;
      case 'r': case 'R': seekPara(0); Audio_.reiniciar(); tocar(); break;
      case 'm': case 'M': alternarMudo(); break;
      case 'f': case 'F': tela(); break;
      case 'a': case 'A': el('auto').click(); break;
      case 'ArrowUp': e.preventDefault(); Audio_.iniciar(); Audio_.mudo = false; Audio_.vol = clamp(Audio_.vol + 0.1); Audio_.aplicar(); atualizarVolumeUI(); if (P.tocando) Audio_.tocar(); break;
      case 'ArrowDown': e.preventDefault(); Audio_.vol = clamp(Audio_.vol - 0.1); Audio_.aplicar(); atualizarVolumeUI(); break;
      default: break;
    }
  });
}

/* ---------- inicialização ---------- */
function montarPalco() {
  appEl = $('#app'); viewEl = $('#appview'); fxEl = $('#fxlayer');
  cursorEl = $('#cursor'); rippleEl = $('#ripple');
  Object.assign(dom, {
    camera: $('#camera'), tilt: $('#tilt'), intro: $('#layer-intro'), closing: $('#layer-closing'),
    orbs: $$('.bg .orb'), canvas: $('#particulas'),
    cartela: $('#cartela'), cartelaEyebrow: $('#cartela .eyebrow'), cartelaTitulo: $('#cartela .titulo'),
    legenda: $('#legenda'), legendaTxt: $('#legenda span'), veil: $('#veil'), aviso: $('#aviso'),
    passos: $('#passos'), chamada: $('#chamada'), pops: $('#pops'), faixa: $('#faixa'),
  });
  dom.ctx2d = dom.canvas.getContext ? dom.canvas.getContext('2d') : null;
  montarAbertura(); montarEncerramento();
  rebuildApp();
}

function arrancar() {
  try {
    montarPalco();
    ligarControles();
    document.title = `${ROTEIRO.titulo} · ${CONFIG.produto}`;
    el('start-titulo').firstChild.textContent = ROTEIRO.titulo; el('start-sub').textContent = ROTEIRO.sub; el('start-desc').textContent = ROTEIRO.desc;
    el('start-dur').textContent = `Duração aproximada: ${Math.max(1, Math.round(SCENES.total / 60 * 2) / 2).toString().replace('.', ',')} min`;
    const o = el('start-outro'); if (ROTEIRO.outro) { o.href = ROTEIRO.outro[0]; o.textContent = ROTEIRO.outro[1] + ' →'; } else o.style.display = 'none';
    ajustarEscala();
    el('btn-play').innerHTML = ICO.play; el('btn-tela').innerHTML = ICO.tela;
    el('tempo').textContent = `00:00 / ${fmtTempo(SCENES.total)}`;
    atualizarVolumeUI();
    // Anexos de depuração/atalho: ?t=SEGUNDOS abre já na posição indicada, pausado.
    const pq = new URLSearchParams(location.search);
    if (pq.has('t')) { P.iniciado = true; el('start').classList.add('is-out'); seekPara(Number(pq.get('t')) || 0); pausar(); }
    else render(0);
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(() => { if (!P.tocando) { lastIdx = -1; render(P.t); } });
    requestAnimationFrame(quadro);
  } catch (e) {
    console.error('Falha ao iniciar a apresentação:', e);
    const m = el('msg'); m.textContent = 'Não foi possível iniciar a apresentação neste navegador.'; m.classList.add('is-on');
  }
}
window.__apresentacao = { seek: (t) => seekPara(t), avancar, tocar, pausar, estado: () => ({ t: P.t, tocando: P.tocando, cena: indexDe(P.t), total: SCENES.total }), cenas: SCENES };
if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', arrancar); else arrancar();
