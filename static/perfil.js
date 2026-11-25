/* Meu perfil (25/11/2026). `getHeaders`, `mensagemCorpoErro`, `showToast`,
   `logout`, `iniciaisDe` e `pintarConta` vêm do ui-common.js. */
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  let perfil = null;

  function formatarTelefone(digitos) {
    const d = String(digitos || "").replace(/\D/g, "").slice(0, 11);
    if (d.length <= 2) return d ? "(" + d : "";
    const meio = d.length === 11 ? 7 : 6;
    if (d.length <= meio) return "(" + d.slice(0, 2) + ") " + d.slice(2);
    return "(" + d.slice(0, 2) + ") " + d.slice(2, meio) + "-" + d.slice(meio);
  }

  function pintarAvatar() {
    const av = $("perfil-avatar");
    if (perfil && perfil.foto_versao) {
      const img = document.createElement("img");
      img.alt = "";
      img.src = "/api/perfil/foto?v=" + encodeURIComponent(perfil.foto_versao);
      av.replaceChildren(img);
    } else {
      av.textContent = iniciaisDe(perfil ? perfil.nome || perfil.email : "");
    }
    $("perfil-remover-foto").hidden = !(perfil && perfil.foto_versao);
    // O botão da conta na barra lateral acompanha a troca.
    if (perfil) {
      pintarConta(perfil);
      try { localStorage.setItem("cg_conta_cache", JSON.stringify(perfil)); } catch (_e) { /* sem storage */ }
    }
  }

  async function carregar() {
    try {
      const r = await fetch("/api/perfil", { headers: getHeaders() });
      if (!r.ok) throw new Error(await mensagemCorpoErro(r));
      perfil = await r.json();
    } catch (e) {
      $("perfil-msg").textContent = "Não foi possível carregar o perfil: " + e.message;
      return;
    }
    $("perfil-nome").value = perfil.nome || "";
    $("perfil-telefone").value = formatarTelefone(perfil.telefone);
    $("perfil-email").value = perfil.email || "";
    if (perfil.microsoft) {
      $("form-senha").hidden = true;
      $("perfil-senha-microsoft").hidden = false;
    }
    pintarAvatar();
  }

  $("perfil-telefone").addEventListener("input", (e) => {
    e.target.value = formatarTelefone(e.target.value);
  });

  $("form-perfil").addEventListener("submit", async (e) => {
    e.preventDefault();
    const msg = $("perfil-msg");
    const btn = $("perfil-salvar");
    btn.disabled = true;
    msg.textContent = "Salvando…";
    try {
      const r = await fetch("/api/perfil", {
        method: "PUT", headers: getHeaders(true),
        body: JSON.stringify({ nome: $("perfil-nome").value, telefone: $("perfil-telefone").value }),
      });
      if (!r.ok) throw new Error(await mensagemCorpoErro(r));
      const j = await r.json();
      perfil = Object.assign({}, perfil, { nome: j.nome, telefone: j.telefone });
      $("perfil-nome").value = j.nome;
      $("perfil-telefone").value = formatarTelefone(j.telefone);
      msg.textContent = "Salvo.";
      pintarAvatar();
    } catch (err) {
      msg.textContent = err.message;
    } finally {
      btn.disabled = false;
    }
  });

  // A foto é cortada em quadrado e reduzida a 256px aqui, antes de subir:
  // uma foto de celular de 5 MB vira ~30 KB. O servidor reabre e regrava.
  function reduzir(arquivo) {
    return new Promise((ok, falha) => {
      const url = URL.createObjectURL(arquivo);
      const img = new Image();
      img.onload = () => {
        const lado = Math.min(img.naturalWidth, img.naturalHeight);
        const alvo = Math.min(256, lado);
        const c = document.createElement("canvas");
        c.width = c.height = alvo;
        c.getContext("2d").drawImage(img, (img.naturalWidth - lado) / 2, (img.naturalHeight - lado) / 2, lado, lado, 0, 0, alvo, alvo);
        URL.revokeObjectURL(url);
        c.toBlob((b) => (b ? ok(b) : falha(new Error("Não deu para ler a imagem."))), "image/jpeg", 0.88);
      };
      img.onerror = () => { URL.revokeObjectURL(url); falha(new Error("O arquivo não é uma imagem válida.")); };
      img.src = url;
    });
  }

  $("perfil-arquivo").addEventListener("change", async (e) => {
    const arquivo = e.target.files && e.target.files[0];
    e.target.value = "";
    if (!arquivo) return;
    const msg = $("perfil-foto-msg");
    msg.textContent = "Enviando…";
    try {
      const blob = await reduzir(arquivo);
      const fd = new FormData();
      fd.append("arquivo", blob, "foto.jpg");
      const r = await fetch("/api/perfil/foto", { method: "PUT", headers: getHeaders(), body: fd });
      if (!r.ok) throw new Error(await mensagemCorpoErro(r));
      perfil = Object.assign({}, perfil, { foto_versao: (await r.json()).foto_versao });
      msg.textContent = "Foto trocada.";
      pintarAvatar();
    } catch (err) {
      msg.textContent = err.message;
    }
  });

  $("perfil-remover-foto").addEventListener("click", async () => {
    const msg = $("perfil-foto-msg");
    try {
      const r = await fetch("/api/perfil/foto", { method: "DELETE", headers: getHeaders() });
      if (!r.ok) throw new Error(await mensagemCorpoErro(r));
      perfil = Object.assign({}, perfil, { foto_versao: null });
      msg.textContent = "Foto removida.";
      pintarAvatar();
    } catch (err) {
      msg.textContent = err.message;
    }
  });

  $("form-senha").addEventListener("submit", async (e) => {
    e.preventDefault();
    const msg = $("senha-msg");
    const nova = $("senha-nova").value;
    if (nova.length < 12) { msg.textContent = "A senha nova precisa de pelo menos 12 caracteres."; return; }
    if (nova !== $("senha-confirma").value) { msg.textContent = "As duas senhas novas não são iguais."; return; }
    const btn = $("senha-trocar");
    btn.disabled = true;
    msg.textContent = "Trocando…";
    try {
      const r = await fetch("/api/senha/trocar", {
        method: "POST", headers: getHeaders(true),
        body: JSON.stringify({ senha_atual: $("senha-atual").value, nova_senha: nova }),
      });
      if (!r.ok) throw new Error(await mensagemCorpoErro(r));
      // A troca derruba as sessões, inclusive esta: volta ao login.
      try {
        sessionStorage.setItem("cg_toast_pendente", JSON.stringify({ message: "Senha alterada. Entre com a senha nova.", type: "success" }));
      } catch (_e) { /* sem storage */ }
      logout();
    } catch (err) {
      msg.textContent = err.message;
      btn.disabled = false;
    }
  });

  carregar();
})();
