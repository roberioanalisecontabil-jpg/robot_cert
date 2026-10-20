// Detalhes do certificado e SIEG no modal (06/10/2026; compartilhado desde
// 20/10/2026, quando a página Vencidos passou a abrir o mesmo modal).
// A marcação está em templates/_modal_detalhes.html. Depende de ui-common.js
// (esc, getHeaders, mensagemCorpoErro, logout, showToast, badgeStatus).
//
// Uso: cgDetalhes.iniciar({ badge, nomeExibicao, aoMudarSieg }) uma vez, e
// cgDetalhes.abrir(item, elementoDeOrigem) no clique. `item` precisa de
// `fingerprint_sha256`; o resto vem da rota de detalhes.
(function () {
  let _opcoes = {
    badge: (it) => badgeStatus(it.status === "expirado" ? "vencido" : it.status),
    nomeExibicao: (nome) => String(nome || ""),
    aoMudarSieg: null,
  };
  let _detPedido = 0;   // descarta resposta de um modal que já foi trocado
  let _detOrigem = null;
  let _siegItem = null;
  let _siegTimer = null;
  const _souAdmin = (localStorage.getItem("user_role") || "") === "admin";

  function fmtDataHoraDet(iso) {
    if (!iso) return "—";
    const d = new Date(iso);
    return Number.isNaN(d.getTime()) ? "—" : d.toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });
  }
  function fmtNascimento(iso) {
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso || "");
    return m ? m[3] + "/" + m[2] + "/" + m[1] : "—";
  }
  function fmtCpf(d) {
    const s = String(d || "").replace(/\D/g, "");
    return s.length === 11 ? s.slice(0, 3) + "." + s.slice(3, 6) + "." + s.slice(6, 9) + "-" + s.slice(9) : (d || "—");
  }
  function validadeTexto(it) {
    if (!it.not_after) return "—";
    const dias = Math.ceil((Date.parse(it.not_after) - Date.now()) / 86400000);
    if (dias < 0) return "Vencido há " + (-dias) + (dias === -1 ? " dia" : " dias");
    if (dias === 0) return "Válido · vence hoje";
    return "Válido · vence em " + dias + (dias === 1 ? " dia" : " dias");
  }
  function linhasDet(pares) {
    return pares.map(([rotulo, valor, mono]) =>
      "<div class='cg-det__item'><dt>" + esc(rotulo) + "</dt><dd" + (mono ? " class='cg-det__mono'" : "") + ">" +
      (valor === null || valor === undefined || valor === "" ? "<span class='cg-det__vazio'>—</span>" : esc(String(valor))) +
      "</dd></div>").join("");
  }

  function preencherDetalhes(it, completo) {
    const nome = it.nome || it.display_name || "";
    const tipo = it.tipo_icp || (it.documento_tipo_label ? "e-" + it.documento_tipo_label : null);
    document.getElementById("det-titulo").textContent = _opcoes.nomeExibicao(nome) || "Certificado";
    document.getElementById("det-doc").textContent = it.documento_formatado || "";
    document.getElementById("det-status").innerHTML = _opcoes.badge(it);
    document.getElementById("det-certificado").innerHTML = linhasDet([
      ["Nome", it.documento_numero ? nome + ":" + it.documento_numero : nome],
      ["Tipo", tipo],
      ["Validade", validadeTexto(it)],
      [it.documento_tipo_label || "Documento", it.documento_formatado, true],
      ["Cadeia", it.organizacao],
      ["Emissão", fmtDataHoraDet(it.not_before), true],
      ["Vencimento", fmtDataHoraDet(it.not_after), true],
      ["Emissor", it.emissor],
      ["Número de série", it.serial_number ? String(it.serial_number).toUpperCase() : null, true],
    ]);
    const resp = document.getElementById("det-responsavel");
    const nota = document.getElementById("det-resp-nota");
    if (!completo) {
      resp.innerHTML = "<div class='cg-det__item'><dt>Carregando…</dt><dd></dd></div>";
      nota.hidden = true;
    } else {
      resp.innerHTML = linhasDet([
        ["Nome", it.responsavel_nome],
        ["CPF", it.responsavel_cpf ? fmtCpf(it.responsavel_cpf) : null, true],
        ["Data de nascimento", it.responsavel_nascimento ? fmtNascimento(it.responsavel_nascimento) : null, true],
        ["E-mail", it.email],
      ]);
      // Chave ausente = o agente ainda não lê estes campos (anterior à
      // 1.7.0); chave presente e vazia = o certificado não traz o dado.
      const foraDaCarteira = it.instalavel === false;
      const agenteAntigo = !foraDaCarteira && !("responsavel_cpf" in it);
      nota.hidden = !(agenteAntigo || foraDaCarteira);
      nota.textContent = foraDaCarteira ? "Os dados do responsável aparecem só para quem tem este cliente na carteira."
        : agenteAntigo ? "Estes dados aparecem depois da próxima varredura do agente 1.7.0." : "";
    }
    const portal = [["No cofre", it.no_cofre === true ? "Sim" : it.no_cofre === false ? "Não enviado" : (completo ? "—" : "Carregando…")]];
    if (it.pasta || it.nome_publico) portal.push(["Arquivo", [it.pasta, it.nome_publico].filter(Boolean).join("/"), true]);
    document.getElementById("det-portal").innerHTML = linhasDet(portal);
  }

  // ── SIEG no modal ──────────────────────────────────────────────────
  function fmtQuando(iso) {
    const d = new Date(iso || "");
    return Number.isNaN(d.getTime()) ? "" : d.toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });
  }

  function renderSieg(d) {
    const chk = document.getElementById("det-sieg-chk");
    const est = document.getElementById("det-sieg-estado");
    const txt = document.getElementById("det-sieg-texto");
    const tentar = document.getElementById("det-sieg-tentar");
    const conferir = document.getElementById("det-sieg-conferir");
    const e = d && d.estado;
    // Fora da carteira: vê a situação, sem o interruptor (08/10/2026).
    const semInterruptor = !!(d && d.na_carteira === false);
    const caixa = chk.closest(".ag-switch") || chk.parentElement;
    if (caixa) caixa.style.display = semInterruptor ? "none" : "";
    chk.checked = !!(e && e.ligado);
    // Ligado não desliga; sem condição não liga.
    chk.disabled = !!(e && e.ligado) || !!(d && d.motivo) || !d;
    const tipo = { no_sieg: "success", incluindo: "info", erro: "danger", substituido: "neutral", removido: "neutral" };
    est.innerHTML = e ? "<span class='ag-badge ag-badge--" + (tipo[e.estado] || "neutral") + "'>" + esc(e.rotulo) + "</span>" : "";
    let texto = "";
    if (!d) texto = "Não foi possível consultar o SIEG agora.";
    else if (d.motivo) texto = d.motivo_texto;
    else if (!e && semInterruptor) texto = "Ainda não está no SIEG. Quem tem este cliente na carteira pode incluir.";
    else if (!e) texto = "Inclui este certificado na conta do SIEG. Pede confirmação.";
    else {
      const quem = e.solicitado_por ? "Ligado por " + e.solicitado_por + " em " + fmtQuando(e.solicitado_em) + ". " : "";
      if (e.estado === "incluindo") texto = quem + "Enviando ao SIEG…";
      else if (e.estado === "erro") texto = quem + "A inclusão falhou: " + (e.mensagem || "sem detalhe");
      else if (e.estado === "no_sieg") texto = quem + (e.sieg_id ? "Cadastro no SIEG: " + e.sieg_id + "." : "");
      else texto = quem + (e.mensagem || "");
    }
    txt.textContent = texto;
    tentar.hidden = !(e && e.estado === "erro");
    conferir.hidden = !(_souAdmin && e);
    clearTimeout(_siegTimer);
    if (e && e.estado === "incluindo") _siegTimer = setTimeout(() => void carregarSieg(_siegItem, true), 2500);
  }

  function avisarSieg(it, d) {
    if (_opcoes.aoMudarSieg) _opcoes.aoMudarSieg(it, d.estado ? d.estado.estado : null);
  }

  async function carregarSieg(it, atualizandoLinha) {
    if (!it || !it.fingerprint_sha256) { renderSieg(null); return; }
    try {
      const r = await fetch("/api/sieg/certificado/" + encodeURIComponent(it.fingerprint_sha256), { headers: getHeaders() });
      if (it !== _siegItem) return;
      if (!r.ok) throw new Error(await mensagemCorpoErro(r));
      const d = await r.json();
      renderSieg(d);
      if (atualizandoLinha) avisarSieg(it, d);
    } catch (_e) {
      if (it === _siegItem) renderSieg(null);
    }
  }

  async function pedirInclusao() {
    const it = _siegItem;
    document.getElementById("det-sieg-texto").textContent = "Enviando o pedido…";
    try {
      const r = await fetch("/api/sieg/certificado/" + encodeURIComponent(it.fingerprint_sha256) + "/incluir", {
        method: "POST", headers: getHeaders(true),
      });
      if (!r.ok) throw new Error(await mensagemCorpoErro(r));
      const d = await r.json();
      renderSieg(d);
      avisarSieg(it, d);
    } catch (e) {
      showToast("Não foi possível incluir no SIEG: " + e.message, "error");
      void carregarSieg(it);
    }
  }

  async function conferirNoSieg() {
    const it = _siegItem;
    const btn = document.getElementById("det-sieg-conferir");
    btn.disabled = true;
    try {
      const r = await fetch("/api/sieg/certificado/" + encodeURIComponent(it.fingerprint_sha256) + "/reconciliar", {
        method: "POST", headers: getHeaders(true),
      });
      if (!r.ok) throw new Error(await mensagemCorpoErro(r));
      const d = await r.json();
      renderSieg(d);
      avisarSieg(it, d);
      showToast("Conferido no SIEG: " + (d.estado ? d.estado.rotulo : "—") + ".", "success");
    } catch (e) {
      showToast(e.message, "error");
    } finally {
      btn.disabled = false;
    }
  }

  async function abrir(it, origem) {
    const modal = document.getElementById("modalDetalhes");
    const pedido = ++_detPedido;
    _detOrigem = origem || null;
    preencherDetalhes(it, false);
    _siegItem = it;
    renderSieg({ estado: null, motivo: null });
    document.getElementById("det-sieg-chk").disabled = true;
    document.getElementById("det-sieg-texto").textContent = "Consultando…";
    void carregarSieg(it);
    if (!modal.open) modal.showModal();
    if (!it.fingerprint_sha256) { preencherDetalhes(it, true); return; }
    try {
      const r = await fetch("/api/certificados/" + encodeURIComponent(it.fingerprint_sha256) + "/detalhes", { headers: getHeaders() });
      if (pedido !== _detPedido) return;
      if (r.status === 401) { logout(); return; }
      if (!r.ok) throw new Error(await mensagemCorpoErro(r));
      preencherDetalhes({ ...it, ...(await r.json()) }, true);
    } catch (e) {
      if (pedido !== _detPedido) return;
      preencherDetalhes(it, true);
      const nota = document.getElementById("det-resp-nota");
      nota.hidden = false;
      nota.textContent = "Não foi possível carregar os dados do responsável: " + e.message;
    }
  }

  function iniciar(opcoes) {
    _opcoes = { ..._opcoes, ...(opcoes || {}) };
    const modalDet = document.getElementById("modalDetalhes");
    modalDet.querySelectorAll("[data-det-fechar]").forEach((b) => b.addEventListener("click", () => modalDet.close()));
    // SIEG: ligar pede confirmação; a alavanca só fica ligada depois do OK.
    const confSieg = document.getElementById("modalSiegConfirmar");
    document.getElementById("det-sieg-chk").addEventListener("change", (ev) => {
      if (!ev.target.checked) return;
      ev.target.checked = false;
      const nome = _siegItem ? (_opcoes.nomeExibicao(_siegItem.nome || _siegItem.display_name || "") + " (" + (_siegItem.documento_formatado || "") + ")") : "";
      document.getElementById("sieg-conf-texto").textContent = "Incluir o certificado de " + nome + " na conta do SIEG?";
      confSieg.showModal();
    });
    confSieg.querySelectorAll("[data-sieg-cancelar]").forEach((b) => b.addEventListener("click", () => confSieg.close()));
    document.getElementById("sieg-conf-ok").addEventListener("click", () => {
      confSieg.close();
      void pedirInclusao();
    });
    document.getElementById("det-sieg-tentar").addEventListener("click", () => void pedirInclusao());
    document.getElementById("det-sieg-conferir").addEventListener("click", () => void conferirNoSieg());
    modalDet.addEventListener("close", () => { clearTimeout(_siegTimer); _siegItem = null; });

    // Foco volta para o nome de onde o modal saiu.
    modalDet.addEventListener("close", () => { if (_detOrigem && document.contains(_detOrigem)) _detOrigem.focus(); });
  }

  window.cgDetalhes = { iniciar, abrir };
})();
