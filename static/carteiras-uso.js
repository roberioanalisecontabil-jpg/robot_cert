// Aba "Uso" da tela Carteiras (Frente C, 15/11/2026).
// usuario_windows e nomes vêm da estação e podem ser forjados: toda célula é
// montada com createElement/textContent, nunca com HTML em texto.
(function () {
  let pagina = 1;
  let carregouPessoas = false;
  const $ = (id) => document.getElementById(id);

  function celula(tr, linhas) {
    const td = document.createElement("td");
    td.setAttribute("role", "cell");
    (Array.isArray(linhas) ? linhas : [linhas]).forEach((t, i) => {
      if (i) td.appendChild(document.createElement("br"));
      td.appendChild(document.createTextNode(t == null ? "" : String(t)));
    });
    tr.appendChild(td);
  }

  function data(iso) { const d = new Date(iso); return isNaN(d) ? "" : d.toLocaleDateString("pt-BR"); }
  function hm(iso) { const d = new Date(iso); return isNaN(d) ? "" : d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" }); }

  function mensagem(texto) {
    const tr = document.createElement("tr");
    tr.className = "cg-state-row";
    const td = document.createElement("td");
    td.colSpan = 6;
    td.className = "ag-table__vazio";
    td.textContent = texto;
    tr.appendChild(td);
    $("uso-linhas").replaceChildren(tr);
  }

  function coletas(mapa, nomes) {
    const itens = Object.keys(mapa).sort().map((m) => {
      const li = document.createElement("li");
      li.className = "cg-op-vazio";
      const c = mapa[m];
      li.textContent = (nomes[m] || m) + ": " + data(c.ultima_em) + " " + hm(c.ultima_em) +
        (c.auditoria === "desligada" ? " (auditoria desligada)" : "");
      return li;
    });
    $("uso-coletas").replaceChildren(...itens);
  }

  async function carregarPessoas() {
    if (carregouPessoas) return;
    carregouPessoas = true;
    try {
      const r = await fetch("/api/carteira/operadores", { headers: getHeaders() });
      if (!r.ok) return;
      (await r.json()).operadores.forEach((o) => {
        const op = document.createElement("option");
        op.value = o.id;
        op.textContent = o.nome_exibicao;
        $("uso-pessoa").appendChild(op);
      });
    } catch (e) { carregouPessoas = false; }
  }

  async function carregarUso() {
    void carregarPessoas();
    const q = new URLSearchParams({ pagina: String(pagina), por_pagina: $("uso-por-pagina").value });
    [["desde", "uso-desde"], ["ate", "uso-ate"], ["user_id", "uso-pessoa"], ["documento", "uso-documento"]]
      .forEach(([k, id]) => { if ($(id).value) q.set(k, $(id).value); });
    mensagem("Carregando…");
    let pg = null;
    try {
      const r = await fetch("/api/carteira/uso?" + q, { headers: getHeaders() });
      if (!r.ok) { mensagem(await mensagemCorpoErro(r)); paginacao(null); return; }
      const j = await r.json();
      pg = j;
      const nomes = {};
      if (!j.linhas.length) {
        mensagem("Nenhum uso no período.");
      } else {
        $("uso-linhas").replaceChildren(...j.linhas.map((l) => {
          nomes[l.maquina] = l.nome_maquina;
          const tr = document.createElement("tr");
          tr.setAttribute("role", "row");
          celula(tr, data(l.hora) + " " + hm(l.primeiro_em) + "–" + hm(l.ultimo_em));
          celula(tr, l.sem_login ? l.usuario_windows + " (sem login)" : [l.pessoa, l.email]);
          celula(tr, l.nome_maquina);
          celula(tr, [l.titular, l.documento]);
          // Sistema/Página: reservada; a API ainda não manda o campo.
          celula(tr, l.sistema || "—");
          if (!l.sistema) tr.lastChild.className = "cg-uso-futuro";
          celula(tr, l.quantidade);
          return tr;
        }));
      }
      coletas(j.coletas || {}, nomes);
    } catch (e) {
      mensagem("Erro de conexão com o servidor.");
    }
    paginacao(pg);
  }

  // Mesma barra do Início (index.html, atualizarPaginacaoUI).
  function paginacao(pg) {
    cgPageNavRefresh({
      bar: "uso-paginacao", meta: "uso-pagina", ul: "uso-pag-ul", liNext: "uso-pag-li-next",
      prev: "uso-anterior", next: "uso-proxima", pg: pg,
      metaFormatter: (p) => "Página " + p.pagina + " de " + p.total_paginas + " · " + p.total_itens + " linhas",
      hideWhenSingle: true,
      goToPage: (n) => { pagina = n; void carregarUso(); },
      maxButtons: 5,
    });
  }

  window.carregarUso = carregarUso;
  const refiltrar = () => { pagina = 1; void carregarUso(); };
  ["uso-desde", "uso-ate", "uso-pessoa", "uso-documento", "uso-por-pagina"].forEach((id) => $(id).addEventListener("change", refiltrar));
  $("uso-anterior").addEventListener("click", () => { if (pagina > 1) { pagina -= 1; void carregarUso(); } });
  $("uso-proxima").addEventListener("click", () => { pagina += 1; void carregarUso(); });
  if ($("tab-uso").getAttribute("aria-selected") === "true") void carregarUso();
})();
