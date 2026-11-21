// Aba "Uso" da tela Carteiras (Frente C, 15/11/2026). Visão por certificado
// (proposta B, 21/11/2026): /api/carteira/uso/resumo dá a lista e o detalhe;
// o histórico paginado continua em /api/carteira/uso.
// usuario_windows e nomes vêm da estação e podem ser forjados: toda célula é
// montada com createElement/textContent, nunca com HTML em texto.
(function () {
  let pagina = 1;
  let carregouPessoas = false;
  let dias = 7;            // 0 = Personalizado (De/Até)
  let docSel = "";         // certificado aberto no detalhe
  let certs = [];          // última lista do resumo
  let seqResumo = 0, seqHist = 0;
  const $ = (id) => document.getElementById(id);

  function celula(tr, linhas, cls) {
    const td = document.createElement("td");
    td.setAttribute("role", "cell");
    if (cls) td.className = cls;
    (Array.isArray(linhas) ? linhas : [linhas]).forEach((t, i) => {
      if (i) td.appendChild(document.createElement("br"));
      td.appendChild(document.createTextNode(t == null ? "" : String(t)));
    });
    tr.appendChild(td);
    return td;
  }

  function data(iso) { const d = new Date(iso); return isNaN(d) ? "" : d.toLocaleDateString("pt-BR"); }
  function hm(iso) { const d = new Date(iso); return isNaN(d) ? "" : d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" }); }
  function diaCurto(iso) {
    // "2026-11-20" é data de Brasília, sem hora: meio-dia evita virar o dia por fuso.
    const d = new Date(iso.length === 10 ? iso + "T12:00:00" : iso);
    return isNaN(d) ? "" : d.toLocaleDateString("pt-BR", { weekday: "short", day: "2-digit", month: "2-digit" }).replace(".", "");
  }
  function fmtDoc(d) {
    if (/^\d{14}$/.test(d)) return d.replace(/(\d{2})(\d{3})(\d{3})(\d{4})(\d{2})/, "$1.$2.$3/$4-$5");
    if (/^\d{11}$/.test(d)) return d.replace(/(\d{3})(\d{3})(\d{3})(\d{2})/, "$1.$2.$3-$4");
    return d || "";
  }
  function isoLocal(d) { return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0"); }

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
        // A hora do uso (evento_em), não a da janela que ganhou o foco antes dele.
        const quando = u.evento_em || (ordem0 && ordem0.quando);
        texto(lista, "h3", quando ? dataHora(quando) : "Uso");
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
    td.colSpan = mostraSistema ? 5 : 4;
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

  // Filtros comuns às duas rotas. Período: atalho em dias ou De/Até.
  function filtros() {
    const q = new URLSearchParams();
    if (dias) {
      const hoje = new Date(), ini = new Date();
      ini.setDate(hoje.getDate() - dias + 1);
      q.set("desde", isoLocal(ini)); q.set("ate", isoLocal(hoje));
    } else {
      if ($("uso-desde").value) q.set("desde", $("uso-desde").value);
      if ($("uso-ate").value) q.set("ate", $("uso-ate").value);
    }
    if ($("uso-pessoa").value) q.set("user_id", $("uso-pessoa").value);
    return q;
  }

  function semDetalhe(msg) {
    $("uso-detalhe-corpo").hidden = true;
    $("uso-detalhe-vazio").hidden = false;
    $("uso-detalhe-vazio").textContent = msg;
    paginacao(null);
  }

  // Busca local: a lista do período já veio inteira (uma linha por certificado).
  function renderLista() {
    const busca = $("uso-busca").value.trim().toLowerCase();
    const digitos = busca.replace(/\D/g, "");
    const vis = certs.filter((c) => !busca || (c.titular || "").toLowerCase().includes(busca) ||
      (digitos && c.documento.includes(digitos)));
    $("uso-ncerts").textContent = vis.length === certs.length ? String(certs.length) : vis.length + " de " + certs.length;
    const max = Math.max(1, ...vis.map((c) => c.usos));
    $("uso-certs").replaceChildren(...vis.map((c) => {
      const li = document.createElement("li");
      const b = document.createElement("button");
      b.type = "button";
      b.className = "cg-uso-cert";
      b.setAttribute("aria-current", String(c.documento === docSel));
      texto(b, "span", c.titular || fmtDoc(c.documento), "cg-uso-cert__nome");
      texto(b, "span", String(c.usos), "cg-uso-cert__qtd");
      texto(b, "span", fmtDoc(c.documento) + " · " + c.pessoas + (c.pessoas === 1 ? " pessoa" : " pessoas"), "cg-uso-doc");
      const barra = texto(b, "span", "", "cg-uso-barra");
      barra.setAttribute("aria-hidden", "true");
      const i = document.createElement("i");
      i.style.width = (c.usos / max * 100) + "%";
      barra.appendChild(i);
      b.setAttribute("aria-label", (c.titular || fmtDoc(c.documento)) + ": " + c.usos + " usos");
      b.addEventListener("click", () => { docSel = c.documento; pagina = 1; void carregarResumo(); });
      li.appendChild(b);
      return li;
    }));
    if (!certs.length) texto($("uso-certs"), "li", "Nenhum uso no período.", "cg-uso-fraco cg-uso-cab");
    else if (!vis.length) texto($("uso-certs"), "li", "Nenhum certificado com essa busca.", "cg-uso-fraco cg-uso-cab");
  }

  function renderDetalhe(d) {
    $("uso-detalhe-vazio").hidden = true;
    $("uso-detalhe-corpo").hidden = false;
    $("uso-tit-cert").textContent = d.titular || fmtDoc(d.documento);
    $("uso-doc-cert").textContent = fmtDoc(d.documento);
    const mini = $("uso-mini");
    mini.replaceChildren();
    [[d.usos, "usos no período"], [d.pessoas, d.pessoas === 1 ? "pessoa" : "pessoas"],
     [d.maquinas, d.maquinas === 1 ? "máquina" : "máquinas"], [diaCurto(d.ultimo_em) + " " + hm(d.ultimo_em), "último uso"]]
      .forEach(([v, t]) => { const div = document.createElement("div"); texto(div, "dt", t); texto(div, "dd", String(v)); mini.appendChild(div); });
    // Uma série só: o título nomeia, sem legenda; o valor de cada dia vai no title e no nome acessível.
    const vmax = Math.max(1, ...d.por_dia.map((p) => p.usos));
    const cols = $("uso-colunas");
    cols.replaceChildren(...d.por_dia.map((p) => {
      const c = document.createElement("div");
      c.className = "cg-uso-col";
      c.title = diaCurto(p.dia) + ": " + p.usos + " usos";
      const i = document.createElement("i");
      i.style.height = (p.usos / vmax * 100) + "%";
      c.appendChild(i);
      return c;
    }));
    cols.setAttribute("aria-label", "Usos por dia: " + d.por_dia.map((p) => diaCurto(p.dia) + " " + p.usos).join(", "));
    const eixo = $("uso-eixo");
    eixo.replaceChildren();
    if (d.por_dia.length) { texto(eixo, "span", diaCurto(d.por_dia[0].dia)); texto(eixo, "span", diaCurto(d.por_dia[d.por_dia.length - 1].dia)); }
    $("uso-quem").replaceChildren(...d.quem.map((q) => {
      const li = document.createElement("li");
      texto(li, "span", q.sem_login ? q.nome + " (sem login)" : q.nome, q.sem_login ? "cg-uso-semlogin" : "");
      texto(li, "span", String(q.usos));
      return li;
    }));
  }

  async function carregarResumo() {
    void carregarPessoas();
    const meu = ++seqResumo;
    const q = filtros();
    if (docSel) q.set("documento", docSel);
    try {
      const r = await fetch("/api/carteira/uso/resumo?" + q, { headers: getHeaders() });
      if (meu !== seqResumo) return;
      if (!r.ok) { const msg = await mensagemCorpoErro(r); if (meu === seqResumo) { certs = []; renderLista(); semDetalhe(msg); } return; }
      const j = await r.json();
      if (meu !== seqResumo) return;
      certs = j.certificados;
      // Sem escolha (ou a escolhida saiu do período): abre o mais usado.
      if (!j.detalhe && certs.length) {
        docSel = certs[0].documento; pagina = 1;
        return void carregarResumo();
      }
      renderLista();
      if (!j.detalhe) { docSel = ""; semDetalhe("Nenhum uso no período."); void carregarColetas(); return; }
      renderDetalhe(j.detalhe);
      void carregarHistorico();
    } catch (e) {
      if (meu !== seqResumo) return;
      semDetalhe("Erro de conexão com o servidor.");
    }
  }

  // Sem certificado no período, as coletas ainda importam (auditoria desligada).
  async function carregarColetas() {
    try {
      const r = await fetch("/api/carteira/uso?" + filtros() + "&por_pagina=10", { headers: getHeaders() });
      if (r.ok) coletas((await r.json()).coletas || {}, {});
    } catch (e) { /* a lista só fica como estava */ }
  }

  async function carregarHistorico() {
    const meu = ++seqHist;
    const q = filtros();
    q.set("documento", docSel);
    q.set("pagina", String(pagina));
    q.set("por_pagina", $("uso-por-pagina").value);
    mensagem("Carregando…");
    let pg = null;
    try {
      const r = await fetch("/api/carteira/uso?" + q, { headers: getHeaders() });
      if (meu !== seqHist) return;
      if (!r.ok) { mensagem(await mensagemCorpoErro(r)); paginacao(null); return; }
      const j = await r.json();
      if (meu !== seqHist) return;
      pg = j;
      mostraSistema = j.mostra_sistema === true;
      $("uso-th-sistema").hidden = !mostraSistema;
      const nomes = {};
      if (!j.linhas.length) {
        mensagem("Nenhum uso neste período.");
      } else {
        $("uso-linhas").replaceChildren(...j.linhas.map((l) => {
          nomes[l.maquina] = l.nome_maquina;
          const tr = document.createElement("tr");
          tr.setAttribute("role", "row");
          celula(tr, data(l.hora).slice(0, 5) + " " + hm(l.primeiro_em) + "–" + hm(l.ultimo_em), "cg-uso-quando");
          const p = celula(tr, l.sem_login ? l.usuario_windows + " (sem login)" : l.pessoa);
          if (l.sem_login) p.classList.add("cg-uso-semlogin");
          celula(tr, l.nome_maquina);
          if (mostraSistema) celulaSistema(tr, l);
          celula(tr, l.quantidade, "cg-uso-num");
          return tr;
        }));
      }
      coletas(j.coletas || {}, nomes);
    } catch (e) {
      if (meu !== seqHist) return;
      mensagem("Erro de conexão com o servidor.");
    }
    paginacao(pg);
  }

  // Mesma barra do Início (index.html, atualizarPaginacaoUI). Sempre visível:
  // é nela que fica o "por página" (10, 20, 50, 100).
  function paginacao(pg) {
    cgPageNavRefresh({
      bar: "uso-paginacao", meta: "uso-pagina", ul: "uso-pag-ul", liNext: "uso-pag-li-next",
      prev: "uso-anterior", next: "uso-proxima", pg: pg,
      metaFormatter: (p) => {
        const por = Number($("uso-por-pagina").value);
        const ini = p.total_itens ? (p.pagina - 1) * por + 1 : 0;
        return ini + "–" + Math.min(p.total_itens, p.pagina * por) + " de " + p.total_itens + " usos";
      },
      hideWhenSingle: false,
      goToPage: (n) => { pagina = n; void carregarHistorico(); },
      maxButtons: 5,
    });
  }

  $("modalUsoJanelas").querySelectorAll("[data-ag-modal-close]").forEach((b) =>
    b.addEventListener("click", () => $("modalUsoJanelas").close()));
  window.carregarUso = carregarResumo;

  const refiltrar = () => { pagina = 1; void carregarResumo(); };
  document.querySelectorAll(".cg-uso-seg").forEach((b) => b.addEventListener("click", () => {
    dias = Number(b.dataset.dias);
    document.querySelectorAll(".cg-uso-seg").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    $("uso-datas").hidden = dias !== 0;
    if (dias === 0 && !$("uso-desde").value) { $("uso-desde").focus(); return; }
    refiltrar();
  }));
  ["uso-desde", "uso-ate", "uso-pessoa"].forEach((id) => $(id).addEventListener("change", refiltrar));
  $("uso-busca").addEventListener("input", renderLista);
  $("uso-por-pagina").addEventListener("change", () => { pagina = 1; void carregarHistorico(); });
  $("uso-anterior").addEventListener("click", () => { if (pagina > 1) { pagina -= 1; void carregarHistorico(); } });
  $("uso-proxima").addEventListener("click", () => { pagina += 1; void carregarHistorico(); });
  $("uso-limpar").addEventListener("click", () => {
    dias = 7;
    document.querySelectorAll(".cg-uso-seg").forEach((x) => x.setAttribute("aria-pressed", String(x.dataset.dias === "7")));
    $("uso-datas").hidden = true;
    $("uso-desde").value = ""; $("uso-ate").value = ""; $("uso-pessoa").value = ""; $("uso-busca").value = "";
    docSel = "";
    refiltrar();
  });
  if ($("tab-uso").getAttribute("aria-selected") === "true") void carregarResumo();
})();
