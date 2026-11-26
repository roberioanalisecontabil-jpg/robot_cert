// Tela Auditoria (26/11/2026): Movimentos e Trilha saíram do Instalador e
// Uso saiu de Carteiras. As APIs continuam as mesmas, com as mesmas guardas:
// /api/cert-installer/entrada e /trilha só para administrador; o Uso
// (static/carteiras-uso.js) para administrador e gestor, no alcance de cada um.
// `esc`, `getHeaders` e `mensagemCorpoErro` vêm de ui-common.js.
(function () {
  const SO_ADMIN = ["movimentos", "trilha"];
  const eAdmin = localStorage.getItem("user_role") === "admin";
  // Conveniência, não barreira: quem não é admin nem vê as abas, e a API
  // devolveria 403 de qualquer jeito.
  const ABAS = eAdmin ? ["movimentos", "trilha", "uso"] : ["uso"];
  const PAINEL = { movimentos: "aba-movimentos", trilha: "aba-trilha", uso: "sec-uso" };
  const AVISO = '<svg class="ag-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4"/><path d="M12 17h.01"/></svg>';
  const CHECK = '<svg class="ag-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M20 6 9 17l-5-5"/></svg>';
  const CIRCULO = '<svg class="ag-icon" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"/></svg>';

  /* ── Formatação (as mesmas do Instalador) ─────────────────────────── */

  function num(v) { return v === null || v === undefined ? "—" : Number(v).toLocaleString("pt-BR"); }
  function fmtHora(d) { return d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" }); }
  function fmtData(iso) { const d = new Date(iso); return Number.isNaN(d.getTime()) ? "—" : d.toLocaleDateString("pt-BR"); }
  function fmtDataHora(iso) { const d = new Date(iso); return Number.isNaN(d.getTime()) ? "—" : d.toLocaleDateString("pt-BR") + " " + fmtHora(d); }
  // "hoje, 10:14" / "ontem, 15:08"; o resto em dd/mm/aaaa hh:mm, sem segundos.
  function fmtQuando(iso) {
    if (!iso) return "—";
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return "—";
    const hoje = new Date(); hoje.setHours(0, 0, 0, 0);
    const ontem = new Date(hoje); ontem.setDate(hoje.getDate() - 1);
    const dia = new Date(d); dia.setHours(0, 0, 0, 0);
    if (dia.getTime() === hoje.getTime()) return "hoje, " + fmtHora(d);
    if (dia.getTime() === ontem.getTime()) return "ontem, " + fmtHora(d);
    return fmtDataHora(iso);
  }
  function tempo(iso, texto) {
    return `<time datetime="${esc(iso)}" title="${esc(fmtDataHora(iso))}">${esc(texto)}</time>`;
  }
  function plural(n, s, p) { return num(n) + " " + (Number(n) === 1 ? s : (p || s + "s")); }

  /* ── Movimentos ───────────────────────────────────────────────────── */

  const ENTRADA_BADGE = {
    movido: "success", substituiu: "success", vencido: "neutral",
    copia_descartada: "info", duplicidade: "warning", pendente: "warning", vencido_preso: "danger",
  };

  function docFormatado(ev) {
    const d = String(ev.documento_numero || "");
    if (d.length === 14) return `${d.slice(0, 2)}.${d.slice(2, 5)}.${d.slice(5, 8)}/${d.slice(8, 12)}-${d.slice(12)}`;
    if (d.length === 11) return `${d.slice(0, 3)}.${d.slice(3, 6)}.${d.slice(6, 9)}-${d.slice(9)}`;
    return d;
  }

  async function loadEntrada() {
    const tbodyP = document.getElementById("tblEntradaPendentes");
    const tbodyE = document.getElementById("tblEntradaEventos");
    const dias = document.getElementById("entradaDias").value;
    try {
      const [res, cfg] = await Promise.all([
        fetch("/api/cert-installer/entrada?dias=" + encodeURIComponent(dias), { headers: getHeaders() }),
        fetch("/api/settings", { headers: getHeaders() }),
      ]);
      if (!res.ok) throw new Error(await mensagemCorpoErro(res));
      const data = await res.json();
      // Só acusa pasta não configurada se /api/settings respondeu; falha na
      // leitura não é prova de que a pasta falta.
      if (cfg.ok) {
        const pastaEntrada = ((await cfg.json()).pasta_entrada || "").trim();
        document.getElementById("entradaSemPasta").hidden = !!pastaEntrada;
      }

      const pend = data.pendentes || [];
      const cont = document.getElementById("tab-movimentos-contagem");
      cont.textContent = pend.length ? String(pend.length) : "";
      document.getElementById("entradaPendentesAviso").hidden = !pend.length;
      document.getElementById("entradaPendentesTabela").hidden = !pend.length;
      document.getElementById("entradaPendentesTitulo").textContent =
        plural(pend.length, "pendência", "pendências");
      tbodyP.innerHTML = pend.map((p) => `
        <tr role="row">
          <td role="cell" class="cg-col-quando">${p.quando ? tempo(p.quando, fmtQuando(p.quando)) : "—"}</td>
          <td role="cell"><span class="ag-cell-sub--mono">${esc(p.arquivo_original || "—")}</span></td>
          <td role="cell"><span class="ag-cell-sub">${esc(p.pasta_origem || "")}</span></td>
          <td role="cell"><span class="ag-badge ag-badge--${ENTRADA_BADGE[p.resultado] || "warning"}">${esc(p.resultado_rotulo || p.resultado)}</span></td>
          <td role="cell">${esc(p.motivo || "")}</td>
        </tr>`).join("");

      const evs = data.eventos || [];
      document.getElementById("entradaResumo").textContent = data.erro
        ? data.erro
        : (evs.length
          ? (data.truncado
            ? `Os ${evs.length} mais recentes; reduza o período para ver todos.`
            : plural(evs.length, "movimento") + " no período.")
          : "");
      if (!evs.length) {
        tbodyE.innerHTML = `<tr class="cg-state-row" role="row"><td role="cell" colspan="5" class="ag-table__vazio">${
          data.banco === false ? "Sem banco de dados: os movimentos não são registrados." : "Nenhum movimento no período."
        }</td></tr>`;
        return;
      }
      tbodyE.innerHTML = evs.map((ev) => {
        const titular = ev.nome
          ? `<span class="ag-cell-stack"><span class="ag-cell-main">${esc(ev.nome)}</span><span class="ag-cell-sub">${esc(docFormatado(ev))}</span></span>`
          : "—";
        const ficou = ev.arquivo_novo
          ? `<span class="ag-cell-stack"><span class="ag-cell-main ag-cell-sub--mono">${esc(ev.arquivo_novo)}</span><span class="ag-cell-sub">${esc(ev.pasta_destino || "")}</span></span>`
          : "—";
        const tom = ENTRADA_BADGE[ev.resultado] || "neutral";
        return `
          <tr role="row">
            <td role="cell" class="cg-col-quando">${ev.quando ? tempo(ev.quando, fmtQuando(ev.quando)) : "—"}</td>
            <td role="cell"><span class="ag-cell-stack"><span class="ag-cell-main ag-cell-sub--mono">${esc(ev.arquivo_original || "—")}</span><span class="ag-cell-sub">${esc(ev.pasta_origem || "")}</span></span></td>
            <td role="cell">${titular}</td>
            <td role="cell">${ficou}</td>
            <td role="cell"><span class="ag-cell-stack"><span class="ag-badge ag-badge--${tom}">${esc(ev.resultado_rotulo || ev.resultado)}</span>${ev.motivo ? `<span class="ag-cell-sub">${esc(ev.motivo)}</span>` : ""}</span></td>
          </tr>`;
      }).join("");
    } catch (e) {
      tbodyE.innerHTML = `<tr class="cg-state-row" role="row"><td role="cell" colspan="5" class="ag-table__vazio">Não foi possível carregar os movimentos: ${esc(e.message)}</td></tr>`;
    }
  }


  /* ── Trilha ───────────────────────────────────────────────────────── */

  // Mesma ordem de ORDEM_DOS_EVENTOS em app/cert_installer.py. REDIMIDO é
  // o resgate: o agente da estação recebeu o token e buscou o certificado.
  const MARCOS = [["SOLICITADO", "Pedido"], ["REDIMIDO", "Resgate"], ["CONCLUIDO", "Conclusão"]];

  function desenharEtapas(c) {
    const nomes = new Set((c.eventos || []).map((e) => e.event));
    const falhou = c.desfecho === "falhou";
    const itens = MARCOS.map(([m, rotulo]) => {
      const feita = nomes.has(m);
      const parouAqui = falhou && c.parou_em === m;
      // A etapa em que a cadeia parou leva a marca de falha; as duas
      // ramificações davam a mesma classe e a falha nunca aparecia.
      const cls = (feita ? "is-feita" : "") + (parouAqui ? " is-falha" : "");
      return `<li class="ag-etapas__item ${cls}">${feita ? CHECK : CIRCULO}${rotulo}</li>`;
    }).join("");
    const sr = MARCOS.map(([m, rotulo]) => rotulo + (nomes.has(m) ? " feito" : " pendente")).join(", ") + (falhou ? ", falhou" : "") + ".";
    return `<ol class="ag-etapas" aria-hidden="true" title="${esc(sr)}">${itens}</ol><span class="cg-sr-only">${esc(sr)}</span>`;
  }

  function badgeDesfecho(d) {
    const mapa = {
      concluido: '<span class="ag-badge ag-badge--success">Concluído</span>',
      falhou: '<span class="ag-badge ag-badge--danger">Falhou</span>',
      incompleto: '<span class="ag-badge ag-badge--warning">Sem desfecho</span>',
    };
    return mapa[d] || '<span class="ag-badge ag-badge--neutral">—</span>';
  }

  // O mesmo bloco do cartão "Instalações" do Dashboard: "2 de 5", barra
  // empilhada e legenda escrita. Os dois lugares mostram o mesmo dado.
  function renderResumoTrilha(r) {
    const el = document.getElementById("trilhaResumo");
    if (!r.total) { el.innerHTML = ""; return; }
    const t = r.textos || {};
    const total = r.total || 1;
    const pct = (n) => Math.round(100 * (n || 0) / total);
    const seg = (n, cls) => (n ? `<span class="ag-barra-empilhada__seg ag-barra-empilhada__seg--${cls}" style="width:${pct(n)}%"></span>` : "");
    const causas = Object.entries(r.causas || {}).slice(0, 3);
    el.innerHTML =
      `<div><p class="cg-numerao">${esc(t.destaque || (r.concluidas + " de " + r.total))}</p><p class="cg-numerao__sub">${esc(t.subtitulo || "tentativas concluídas no período")}</p></div>` +
      `<div><div class="ag-barra-empilhada" aria-hidden="true">${seg(r.concluidas, "ok")}${seg(r.falhadas, "falha")}${seg(r.incompletas, "neutro")}</div>` +
      `<ul class="ag-legenda">` +
      `<li class="ag-legenda__item"><span class="ag-legenda__cor ag-legenda__cor--ok"></span><span class="ag-legenda__n">${num(r.concluidas)}</span> concluídas</li>` +
      `<li class="ag-legenda__item"><span class="ag-legenda__cor ag-legenda__cor--falha"></span><span class="ag-legenda__n">${num(r.falhadas)}</span> com falha</li>` +
      `<li class="ag-legenda__item"><span class="ag-legenda__cor ag-legenda__cor--neutro"></span><span class="ag-legenda__n">${num(r.incompletas)}</span> sem desfecho</li>` +
      `</ul></div>` +
      (causas.length ? `<ul class="ag-dados">${causas.map(([m, n]) => `<li class="ag-dados__item"><span class="ag-dados__rotulo">${esc(m)}</span><span class="ag-dados__valor"><span class="cg-valor-aviso">${AVISO}${num(n)}</span></span></li>`).join("")}</ul>` : "");
  }

  function trilhaVazia(soFalhas, dias, desde) {
    if (soFalhas) return `<tr class="cg-state-row" role="row"><td role="cell" colspan="6" class="ag-table__vazio">Nenhuma falha no período.</td></tr>`;
    const de = desde ? fmtData(desde) : "—";
    const ate = fmtData(new Date().toISOString());
    return `<tr class="cg-state-row" role="row"><td role="cell" colspan="6" class="ag-table__vazio">Nenhuma instalação entre ${esc(de)} e ${esc(ate)}. ${Number(dias) < 90 ? '<a href="#" id="linkTrilha90">Ver últimos 90 dias</a>.' : ""}</td></tr>`;
  }

  // Qual certificado (07/10/2026): nome e documento vêm do cofre. Mais de
  // um na mesma tentativa: o primeiro e "+ N".
  function celulaCertificados(c) {
    const lista = c.certificados_info || [];
    if (!lista.length) return `<span class="ag-cell-sub">${c.certificados ? esc(num(c.certificados)) + " (fora do cofre)" : "—"}</span>`;
    const p = lista[0];
    const mais = lista.length > 1 ? `<span class="ag-cell-sub">+ ${lista.length - 1} ${lista.length === 2 ? "outro" : "outros"}</span>` : "";
    return `<span class="ag-cell-stack" title="${esc(lista.map((x) => x.nome + " " + x.documento).join("\n"))}"><span class="ag-cell-main">${esc(p.nome || "—")}</span><span class="ag-cell-sub ag-cell-sub--mono">${esc(p.documento || "")}</span>${mais}</span>`;
  }

  async function loadInstallLogs() {
    const tbody = document.getElementById("tblInstallLogs");
    const dias = document.getElementById("trilhaDias").value;
    const email = (document.getElementById("trilhaEmail").value || "").trim();
    const soFalhas = document.getElementById("trilhaSoFalhas").checked;
    const params = new URLSearchParams({ dias, apenas_falhas: soFalhas });
    if (email) params.set("user_email", email);
    try {
      const res = await fetch("/api/cert-installer/trilha?" + params.toString(), { headers: getHeaders() });
      if (!res.ok) throw new Error(await mensagemCorpoErro(res));
      const data = await res.json();
      if (data.truncado) {
        // O teto de eventos cortou a lista: dizer "mais recentes" evita que
        // ela pareça completa.
        data.resumo = data.resumo || {};
        data.resumo.textos = Object.assign({}, data.resumo.textos, {
          subtitulo: ((data.resumo.textos || {}).subtitulo || "") + " · lista cortada no limite de eventos; reduza o período",
        });
      }
      renderResumoTrilha(data.resumo || {});
      const cadeias = data.cadeias || [];
      if (!cadeias.length) {
        tbody.innerHTML = trilhaVazia(soFalhas, dias, data.desde);
        const l = document.getElementById("linkTrilha90");
        if (l) l.addEventListener("click", (ev) => { ev.preventDefault(); document.getElementById("trilhaDias").value = "90"; loadInstallLogs(); });
        return;
      }
      tbody.innerHTML = cadeias.map((c) => {
        const motivo = (c.motivos || []).join(" · ");
        const maq = c.target_nome
          ? `<span class="ag-cell-stack"><span class="ag-cell-main">${esc(c.target_nome)}</span><span class="ag-cell-sub">${esc(c.target_machine || "")}</span></span>`
          : `<span class="ag-cell-sub ag-cell-sub--mono">${esc(c.target_machine || "—")}</span>`;
        return `
          <tr role="row">
            <td role="cell" class="cg-col-quando">${c.inicio ? tempo(c.inicio, fmtQuando(c.inicio)) : "—"}</td>
            <td role="cell" class="cg-col-quem">${esc(c.user_email || "—")}</td>
            <td role="cell" class="cg-col-maquina">${maq}</td>
            <td role="cell" class="cg-col-cert">${celulaCertificados(c)}</td>
            <td role="cell" class="cg-col-etapas">${desenharEtapas(c)}</td>
            <td role="cell" class="cg-col-desfecho">${badgeDesfecho(c.desfecho)}${motivo ? `<span class="cg-inst-motivo">${esc(motivo)}</span>` : ""}</td>
          </tr>`;
      }).join("");
    } catch (err) {
      renderResumoTrilha({});
      tbody.innerHTML = `<tr class="cg-state-row" role="row"><td role="cell" colspan="6" class="ag-table__vazio">Falha ao carregar a trilha: ${esc(err.message)}</td></tr>`;
    }
  }


  /* ── Abas ─────────────────────────────────────────────────────────── */

  const carregou = {};
  function carregar(aba) {
    if (aba === "movimentos") void loadEntrada();
    else if (aba === "trilha") void loadInstallLogs();
    else if (aba === "uso" && window.carregarUso) void window.carregarUso();
    carregou[aba] = true;
  }

  function showTab(aba, anunciar) {
    if (!ABAS.includes(aba)) aba = ABAS[0];
    Object.keys(PAINEL).forEach((a) => {
      document.getElementById(PAINEL[a]).hidden = a !== aba;
      const t = document.getElementById("tab-" + a);
      t.setAttribute("aria-selected", a === aba ? "true" : "false");
      t.tabIndex = a === aba ? 0 : -1;
    });
    const url = new URL(location.href);
    url.searchParams.set("aba", aba);
    history.replaceState(null, "", url.pathname + url.search);
    if (anunciar) document.getElementById("abas-anuncio").textContent = "Aba " + document.getElementById("tab-" + aba).textContent.trim() + " aberta.";
    if (!carregou[aba]) carregar(aba);
  }

  /* ── Início ───────────────────────────────────────────────────────── */

  if (!eAdmin) SO_ADMIN.forEach((a) => { const t = document.getElementById("tab-" + a); t.hidden = true; t.style.display = "none"; });  // .ag-abas__aba{display:inline-flex} vence o [hidden]
  document.querySelectorAll(".ag-abas__aba").forEach((t) => {
    t.addEventListener("click", (ev) => { ev.preventDefault(); showTab(t.dataset.aba, true); t.focus(); });
    t.addEventListener("keydown", (ev) => {
      if (ev.key !== "ArrowLeft" && ev.key !== "ArrowRight") return;
      ev.preventDefault();
      const i = ABAS.indexOf(t.dataset.aba);
      const prox = ABAS[(i + (ev.key === "ArrowRight" ? 1 : ABAS.length - 1)) % ABAS.length];
      showTab(prox, true);
      document.getElementById("tab-" + prox).focus();
    });
  });

  const q = new URLSearchParams(location.search);
  if (["7", "30", "90", "365"].includes(q.get("dias"))) {
    document.getElementById("trilhaDias").value = q.get("dias");
    document.getElementById("entradaDias").value = q.get("dias");
  }
  if (q.get("email")) document.getElementById("trilhaEmail").value = q.get("email");
  if (q.get("falhas") === "1") document.getElementById("trilhaSoFalhas").checked = true;
  document.getElementById("formEntrada").addEventListener("submit", (ev) => { ev.preventDefault(); loadEntrada(); });
  document.getElementById("formTrilha").addEventListener("submit", (ev) => { ev.preventDefault(); loadInstallLogs(); });

  // carteiras-uso.js já carrega sozinho quando a página abre no Uso.
  const inicial = document.querySelector('.ag-abas__aba[aria-selected="true"]');
  if (inicial && inicial.dataset.aba === "uso") carregou.uso = true;
  showTab(inicial ? inicial.dataset.aba : ABAS[0], false);
})();
