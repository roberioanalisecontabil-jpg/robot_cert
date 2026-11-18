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

  // Só o admin recebe a coluna Sistema/Página (a API manda mostra_sistema).
  let mostraSistema = false;

  function dataHora(iso) {
    const d = new Date(iso);
    return isNaN(d) ? "" : d.toLocaleDateString("pt-BR") + " " + d.toLocaleTimeString("pt-BR");
  }

  function texto(el, tag, t, cls) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    n.textContent = t;
    el.appendChild(n);
    return n;
  }

  let seqJanelas = 0; // descarta a resposta de um clique antigo se outro já abriu o modal
  async function abrirJanelas(id) {
    const meu = ++seqJanelas;
    const lista = $("usoJanelasLista");
    lista.replaceChildren();
    texto(lista, "p", "Carregando…");
    $("modalUsoJanelas").showModal();
    try {
      const r = await fetch("/api/carteira/uso/" + encodeURIComponent(id) + "/janelas", { headers: getHeaders() });
      if (!r.ok) {
        const msg = await mensagemCorpoErro(r);
        if (meu !== seqJanelas) return;
        lista.replaceChildren(); texto(lista, "p", msg); return;
      }
      const usos = (await r.json()).usos;
      if (meu !== seqJanelas) return;
      lista.replaceChildren();
      if (!usos.length) texto(lista, "p", "Sem janelas registradas para este uso.");
      usos.forEach((u) => {
        const ordem0 = u.janelas.find((w) => w.ordem === 0);
        texto(lista, "h3", ordem0 ? dataHora(ordem0.quando) : "Uso");
        const ul = document.createElement("ul");
        u.janelas.forEach((w) => texto(ul, "li", [w.programa, w.titulo].filter(Boolean).join(" · ") +
          (w.ordem === 0 ? " (no momento)" : "")));
        lista.appendChild(ul);
      });
    } catch (e) {
      if (meu !== seqJanelas) return;
      lista.replaceChildren();
      texto(lista, "p", "Erro de conexão com o servidor.");
    }
  }

  function celulaSistema(tr, l) {
    const td = document.createElement("td");
    td.setAttribute("role", "cell");
    if (l.sistema) {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "ag-btn ag-btn--ghost cg-uso-sistema";
      b.textContent = l.sistema + (l.outras > 0 ? " +" + l.outras : "");
      // O nome acessível contém o texto visível (WCAG 2.5.3).
      b.setAttribute("aria-label", "Ver janelas do uso: " + b.textContent);
      b.addEventListener("click", () => { void abrirJanelas(l.id); });
      td.appendChild(b);
    } else {
      td.appendChild(document.createTextNode("—"));
    }
    tr.appendChild(td);
  }

  function mensagem(texto) {
    const tr = document.createElement("tr");
    tr.className = "cg-state-row";
    const td = document.createElement("td");
    td.colSpan = mostraSistema ? 6 : 5;
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
      mostraSistema = j.mostra_sistema === true;
      $("uso-th-sistema").hidden = !mostraSistema;
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
          if (mostraSistema) celulaSistema(tr, l);
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

  $("modalUsoJanelas").querySelectorAll("[data-ag-modal-close]").forEach((b) =>
    b.addEventListener("click", () => $("modalUsoJanelas").close()));
  window.carregarUso = carregarUso;
  const refiltrar = () => { pagina = 1; void carregarUso(); };
  ["uso-desde", "uso-ate", "uso-pessoa", "uso-documento", "uso-por-pagina"].forEach((id) => $(id).addEventListener("change", refiltrar));
  $("uso-anterior").addEventListener("click", () => { if (pagina > 1) { pagina -= 1; void carregarUso(); } });
  $("uso-proxima").addEventListener("click", () => { pagina += 1; void carregarUso(); });
  if ($("tab-uso").getAttribute("aria-selected") === "true") void carregarUso();
})();
