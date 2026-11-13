// Aba Certificados da tela Carteiras (13/11/2026). Usa os globais da página:
// esc, getHeaders, mensagemCorpoErro (ui-common.js) e msg, nomeDe,
// _operadores, operadoresVisiveis, carregarOperadores (carteiras.html).
// Na URL o documento vai SÓ com dígitos: CNPJ formatado tem "/" e quebra a rota.
(function () {
  const ABAS = { pessoas: "sec-pessoas", certificados: "sec-certificados" };
  const TETO_DIAS = 700; // mesmo teto do servidor (validar_prazo)
  let certs = [];
  let atual = null;      // detalhe do certificado aberto
  let alvo = null;       // user_id quando o modal é "Alterar prazo"
  let carregou = false;
  const $ = (id) => document.getElementById(id);

  const iso = (d) => d.toLocaleDateString("sv-SE");
  const br = (s) => (s ? new Date(String(s).slice(0, 10) + "T00:00:00").toLocaleDateString("pt-BR") : "");
  const mais = (s, dias) => { const d = new Date(s + "T00:00:00"); d.setDate(d.getDate() + dias); return iso(d); };

  // ── Abas ──────────────────────────────────────────────────────────
  function trocarAba(aba, anunciar) {
    Object.keys(ABAS).forEach((a) => {
      $(ABAS[a]).hidden = a !== aba;
      const t = $("tab-" + a);
      t.setAttribute("aria-selected", a === aba ? "true" : "false");
      t.tabIndex = a === aba ? 0 : -1;
    });
    const u = new URL(location.href);
    u.searchParams.set("aba", aba);
    history.replaceState(null, "", u.pathname + u.search);
    if (anunciar) $("abas-anuncio").textContent = "Aba " + $("tab-" + aba).textContent.trim() + " aberta.";
    if (aba === "certificados") iniciar();
  }
  Object.keys(ABAS).forEach((a) => {
    const t = $("tab-" + a);
    t.addEventListener("click", (ev) => { ev.preventDefault(); trocarAba(a, true); t.focus(); });
    t.addEventListener("keydown", (ev) => {
      if (ev.key !== "ArrowLeft" && ev.key !== "ArrowRight") return;
      ev.preventDefault();
      const outra = a === "pessoas" ? "certificados" : "pessoas";
      trocarAba(outra, true);
      $("tab-" + outra).focus();
    });
  });

  // ── Lista ─────────────────────────────────────────────────────────
  async function iniciar() {
    if (carregou) return;
    carregou = true;
    try {
      const r = await fetch("/api/carteira/certificados", { headers: getHeaders() });
      if (!r.ok) throw new Error(await mensagemCorpoErro(r));
      certs = (await r.json()).certificados || [];
      renderLista();
      if (CERTIFICADO_INICIAL) abrir(CERTIFICADO_INICIAL);
    } catch (e) {
      carregou = false;
      $("listaCerts").innerHTML = `<li class="cg-op-vazio">${esc(e.message)}</li>`;
    }
  }

  function renderLista() {
    const q = $("buscaCert").value.trim().toLowerCase();
    const dig = q.replace(/\D/g, "");
    const lista = certs.filter((c) => !q || (c.nome || "").toLowerCase().includes(q) || (dig && c.documento.includes(dig)));
    $("certResumo").textContent = certs.length + (certs.length === 1 ? " certificado" : " certificados");
    $("listaCerts").innerHTML = lista.length ? lista.map((c) => {
      const venc = c.vence_em ? " · vence " + String(c.vence_em).slice(5, 7) + "/" + String(c.vence_em).slice(0, 4) : "";
      return `<li><a class="cg-op-item" href="?aba=certificados&certificado=${encodeURIComponent(c.documento)}" data-doc="${esc(c.documento)}"
          aria-current="${atual && atual.documento === c.documento ? "true" : "false"}">
        <span class="ag-cell-stack"><span class="ag-cell-main">${esc(c.nome || "(sem nome)")}</span>
        <span class="ag-cell-sub">${esc((c.tipo || "") + venc + " · " + c.pessoas + (c.pessoas === 1 ? " pessoa" : " pessoas"))}</span></span></a></li>`;
    }).join("") : `<li class="cg-op-vazio">${q ? "Nenhum certificado encontrado." : "Nenhum certificado ao seu alcance."}</li>`;
    $("listaCerts").querySelectorAll(".cg-op-item").forEach((a) => a.addEventListener("click", (ev) => {
      ev.preventDefault();
      history.replaceState(null, "", a.getAttribute("href"));
      abrir(a.dataset.doc);
    }));
  }

  async function abrir(doc) {
    try {
      const r = await fetch("/api/carteira/certificados/" + encodeURIComponent(doc), { headers: getHeaders() });
      if (!r.ok) throw new Error(await mensagemCorpoErro(r));
      atual = await r.json();
    } catch (e) { msg(e.message, "error"); return; }
    renderLista();
    renderDetalhe();
  }

  function origemTexto(p) {
    if (p.origem === "acessorias") return "Acessórias";
    if (p.origem === "planilha") return "Planilha";
    const por = p.atribuido_por ? " · por " + p.atribuido_por : "";
    const em = p.atribuido_em ? " · " + br(p.atribuido_em).slice(0, 5) : "";
    const hoje = iso(new Date());
    const prazo = p.valido_desde && p.valido_desde > hoje ? " · começa em " + br(p.valido_desde)
      : p.valido_ate ? " · até " + br(p.valido_ate) : " · sem prazo";
    return "manual" + por + em + prazo;
  }

  function renderDetalhe() {
    $("certSemSelecao").hidden = true;
    $("certDetalhe").hidden = false;
    $("certTitulo").textContent = atual.nome || "(sem nome)";
    $("certSub").textContent = [atual.documento_formatado, atual.tipo, atual.vence_em ? "vence " + br(atual.vence_em) : ""].filter(Boolean).join(" · ");
    $("certPessoas").innerHTML = atual.pessoas.length ? atual.pessoas.map((p) => {
      const manual = p.origem !== "acessorias" && p.origem !== "planilha";
      return `<tr data-uid="${esc(p.user_id)}">
        <td><span class="ag-cell-stack"><span class="ag-cell-main">${esc(p.nome)}</span><span class="ag-cell-sub">${esc(p.email)}</span></span></td>
        <td>${esc(origemTexto(p))}${p.vigente ? "" : ' <span class="ag-badge ag-badge--neutral">fora do prazo</span>'}</td>
        <td>${manual ? '<button type="button" class="ag-btn ag-btn--ghost" data-acao="prazo">Alterar prazo</button> ' : ""}<button type="button" class="ag-btn ag-btn--ghost" data-acao="retirar">Retirar</button></td></tr>`;
    }).join("") : `<tr><td colspan="3">Ninguém tem este certificado ainda. Gestores acessam pela regra do papel e não aparecem aqui.</td></tr>`;
  }

  $("certPessoas").addEventListener("click", async (ev) => {
    const b = ev.target.closest("button[data-acao]");
    if (!b) return;
    const uid = b.closest("tr").dataset.uid;
    const p = atual.pessoas.find((x) => x.user_id === uid);
    if (b.dataset.acao === "prazo") return abrirModal(p);
    if (!confirm(`Retirar ${p.nome} deste certificado?\n\nA pessoa deixa de ver e instalar este certificado.`)) return;
    try {
      const r = await fetch(`/api/carteira/${encodeURIComponent(uid)}/${encodeURIComponent(atual.documento)}`, { method: "DELETE", headers: getHeaders() });
      if (!r.ok) throw new Error(await mensagemCorpoErro(r));
      msg("Pessoa retirada do certificado.", "success");
    } catch (e) { msg(e.message, "error"); }
    await recarregar();
  });

  async function recarregar() {
    const doc = atual.documento;
    const r = await fetch("/api/carteira/certificados", { headers: getHeaders() });
    if (r.ok) certs = (await r.json()).certificados || certs;
    await abrir(doc);
  }

  // ── Modal Incluir pessoas / Alterar prazo ─────────────────────────
  const modal = $("modalIncluir");
  const tipoPrazo = () => document.querySelector('input[name="prazoTipo"]:checked').value;

  function ajustarFim() {
    const desde = $("prazoDesde").value || iso(new Date());
    $("prazoAte").min = desde;
    $("prazoAte").max = mais(desde, TETO_DIAS);
  }
  function mostrarPeriodo() { $("prazoCampos").hidden = tipoPrazo() !== "periodo"; }

  async function abrirModal(p) {
    alvo = p ? p.user_id : null;
    $("tit-incluir").textContent = p ? "Alterar prazo de " + p.nome : "Incluir pessoas";
    $("incluirPessoasBloco").hidden = !!p;
    const hoje = iso(new Date());
    $("prazoDesde").min = hoje;
    $("prazoDesde").value = p && p.valido_desde && p.valido_desde > hoje ? p.valido_desde : hoje;
    $("prazoAte").value = p && p.valido_ate ? p.valido_ate : "";
    document.querySelector(`input[name="prazoTipo"][value="${p && p.valido_ate ? "periodo" : "sem"}"]`).checked = true;
    mostrarPeriodo();
    ajustarFim();
    if (!p) {
      if (!_operadores.length) await carregarOperadores();
      $("buscaIncluir").value = "";
      renderPessoas();
    }
    modal.showModal();
  }

  // Quem ainda não tem o certificado vigente; Gestor fica de fora (acesso por papel).
  function candidatos() {
    const tem = new Set(atual.pessoas.filter((p) => p.vigente).map((p) => p.user_id));
    return operadoresVisiveis().filter((o) => o.ativo && o.role !== "gestor" && !tem.has(o.id));
  }

  function renderPessoas() {
    const q = $("buscaIncluir").value.trim().toLowerCase();
    const marcados = new Set([...$("listaIncluir").querySelectorAll("input:checked")].map((i) => i.value));
    const lista = candidatos().filter((o) => !q || (nomeDe(o) + " " + (o.email || "")).toLowerCase().includes(q));
    $("listaIncluir").innerHTML = lista.length ? lista.map((o) =>
      `<li><label class="cg-op-item"><input type="checkbox" value="${esc(o.id)}"${marcados.has(o.id) ? " checked" : ""} />
        <span class="ag-cell-stack"><span class="ag-cell-main">${esc(nomeDe(o))}</span><span class="ag-cell-sub">${esc(o.email || "")}</span></span></label></li>`
    ).join("") : `<li class="cg-op-vazio">${q ? "Ninguém encontrado." : "Não há ninguém a incluir: todos já têm este certificado ou você não gere ninguém."}</li>`;
  }

  async function salvar(ev) {
    ev.preventDefault();
    const ids = alvo ? [alvo] : [...$("listaIncluir").querySelectorAll("input:checked")].map((i) => i.value);
    if (!ids.length) { msg("Marque ao menos uma pessoa.", "warning"); return; }
    const periodo = tipoPrazo() === "periodo";
    const corpo = {
      user_ids: ids,
      valido_desde: periodo ? $("prazoDesde").value || null : null,
      valido_ate: periodo ? $("prazoAte").value || null : null,
    };
    if (periodo && !corpo.valido_ate) { msg("Informe o fim do período.", "warning"); return; }
    try {
      const r = await fetch(`/api/carteira/certificados/${encodeURIComponent(atual.documento)}/pessoas`, {
        method: "POST", headers: getHeaders(true), body: JSON.stringify(corpo),
      });
      if (!r.ok) throw new Error(await mensagemCorpoErro(r));
      modal.close();
      msg(alvo ? "Prazo atualizado." : ids.length === 1 ? "Pessoa incluída." : ids.length + " pessoas incluídas.", "success");
      await recarregar();
    } catch (e) { msg(e.message, "error"); }
  }

  $("btnIncluirPessoas").addEventListener("click", () => abrirModal(null));
  $("buscaCert").addEventListener("input", renderLista);
  $("buscaIncluir").addEventListener("input", renderPessoas);
  $("prazoDesde").addEventListener("change", ajustarFim);
  document.querySelectorAll('input[name="prazoTipo"]').forEach((i) => i.addEventListener("change", mostrarPeriodo));
  $("formIncluir").addEventListener("submit", salvar);
  modal.querySelectorAll("[data-ag-modal-close]").forEach((b) => b.addEventListener("click", () => modal.close()));

  if ($("tab-certificados").getAttribute("aria-selected") === "true") iniciar();
})();
