// Volta da Microsoft (05/11/2026): o login por senha grava papel e e-mail no
// localStorage (templates/login.html, entrou()); sem isto o menu e as telas
// que leem `user_role` tratam o admin como operador. Script externo porque a
// CSP não aceita script em linha sem nonce.
(function () {
  var d = document.currentScript ? document.currentScript.dataset : {};
  try {
    localStorage.removeItem("cert_robot_api_key");
    if (d.role) localStorage.setItem("user_role", d.role);
    if (d.email) localStorage.setItem("user_email", d.email);
  } catch (_e) {
    // Modo privado ou cota cheia: entra igual, só sem o menu completo.
  }
  window.location.replace("/");
})();
