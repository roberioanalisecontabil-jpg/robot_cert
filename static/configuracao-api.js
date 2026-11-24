// Aba "Chaves de API" (24/11/2026): chave de leitura do administrador.
// O texto da chave aparece uma vez, logo depois de criar; o portal guarda só o hash.
(function () {
  const $ = (id) => document.getElementById(id);
  let carregou = false;

  function quando(iso) {
    const d = new Date(iso);
    return iso && !isNaN(d) ? d.toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" }) : "—";
  }

  function estado(c) {
    if (c.revogada_em) return "Revogada";
    if (c.expira_em && new Date(c.expira_em) <= new Date()) return "Vencida";
    return "Ativa";
  }

  function celula(tr, texto) {
    const td = document.createElement("td");
    td.setAttribute("role", "cell");
    td.textContent = texto;
    tr.appendChild(td);
    return td;
  }

  function aviso(tbody, texto) {
    const tr = document.createElement("tr");
    tr.className = "cg-state-row";
    const td = celula(tr, texto);
    td.colSpan = 6;
    td.className = "ag-table__vazio";
    tbody.replaceChildren(tr);
  }

  async function carregar() {
    const tbody = $("api-linhas");
    try {
      const r = await fetch("/api/api-chaves", { headers: getHeaders() });
      if (!r.ok) throw new Error();
      const { chaves } = await r.json();
      if (!chaves.length) { aviso(tbody, "Nenhuma chave."); return; }
      tbody.replaceChildren();
      for (const c of chaves) {
        const tr = document.createElement("tr");
        tr.setAttribute("role", "row");
        celula(tr, c.nome);
        celula(tr, c.dono || "—");
        celula(tr, quando(c.expira_em));
        celula(tr, c.ultimo_uso_em ? quando(c.ultimo_uso_em) + (c.ultimo_ip ? " · " + c.ultimo_ip : "") : "Nunca");
        const st = estado(c);
        celula(tr, st);
        const td = celula(tr, "");
        if (st === "Ativa") {
          const b = document.createElement("button");
          b.type = "button";
          b.className = "ag-btn ag-btn--ghost ag-btn--sm";
          b.textContent = "Revogar";
          b.addEventListener("click", () => revogar(c, b));
          td.appendChild(b);
        }
        tbody.appendChild(tr);
      }
    } catch (_) {
      aviso(tbody, "Não foi possível carregar as chaves.");
    }
  }

  async function revogar(c, b) {
    b.disabled = true;
    try {
      const r = await fetch("/api/api-chaves/" + encodeURIComponent(c.id) + "/revogar", { method: "POST", headers: getHeaders(true) });
      if (r.ok) showToast("Chave “" + c.nome + "” revogada.", "success");
      else { showToast("Não foi possível revogar.", "error"); b.disabled = false; }
    } catch (_) {
      showToast("Erro de conexão com o servidor.", "error");
      b.disabled = false;
    }
    void carregar();
  }

  $("form-api-chave").addEventListener("submit", async (e) => {
    e.preventDefault();
    const msg = $("api-msg");
    const botao = $("api-criar");
    msg.textContent = "";
    botao.disabled = true;
    try {
      const r = await fetch("/api/api-chaves", {
        method: "POST", headers: getHeaders(true),
        body: JSON.stringify({ nome: $("api-nome").value.trim(), dias: Number($("api-dias").value), senha_atual: $("api-senha").value }),
      });
      let d = {};
      try { d = await r.json(); } catch (_) {}
      if (!r.ok) { msg.textContent = typeof d.detail === "string" ? d.detail : "Confira o nome e a senha."; return; }
      $("api-segredo").textContent = d.segredo;
      $("api-nova").hidden = false;
      $("api-nome").value = "";
      $("api-senha").value = "";
      void carregar();
    } catch (_) {
      msg.textContent = "Erro de conexão com o servidor.";
    } finally {
      botao.disabled = false;
    }
  });

  $("api-copiar").addEventListener("click", async () => {
    try { await navigator.clipboard.writeText($("api-segredo").textContent); showToast("Chave copiada.", "success"); }
    catch (_) { showToast("Selecione a chave e copie.", "warning"); }
  });

  window.carregarApiChaves = function () {
    if (carregou) return;
    carregou = true;
    void carregar();
  };
})();
