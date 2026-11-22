// Relatório da aba "Remoção nas estações" (Frente B, 14/11/2026).
// usuario_windows, motivo e detalhe vêm da estação e podem ser forjados: toda
// célula é montada com createElement/textContent, nunca com HTML em texto.
(function () {
  const ESTADOS = {
    removeria: "Removeria (relatório)", aviso: "Em aviso", remover: "Remoção pendente",
    removido: "Removido", falhou: "Falhou",
  };
  const REGRAS = {
    carteira: "Carteira", desativada: "Conta desativada",
    vinculo: "Computador recusado/desvinculado", emprestimo: "Empréstimo vencido",
    sem_login: "Perfil sem login",
  };
  let pagina = 1;
  let ultimaCheia = false;
  // Descarta a resposta de um pedido superado por outro mais novo.
  let seqRemocao = 0;

  function celula(tr, texto, titulo) {
    const td = document.createElement("td");
    td.setAttribute("role", "cell");
    td.textContent = texto == null ? "" : String(texto);
    if (titulo) td.title = titulo;
    tr.appendChild(td);
    return td;
  }

  function quando(iso) {
    const d = new Date(iso);
    return isNaN(d) ? "" : d.toLocaleString("pt-BR");
  }

  function mensagem(tbody, texto) {
    const tr = document.createElement("tr");
    tr.className = "cg-state-row";
    const td = document.createElement("td");
    td.colSpan = 8;
    td.className = "ag-table__vazio";
    td.textContent = texto;
    tr.appendChild(td);
    tbody.replaceChildren(tr);
  }

  async function carregarRemocao() {
    const tbody = document.getElementById("remocao-linhas");
    const estado = document.getElementById("sel-remocao-estado").value;
    const q = new URLSearchParams({ pagina: String(pagina) });
    if (estado) q.set("estado", estado);
    const seq = ++seqRemocao;
    // Travados até a resposta: duplo clique em Próxima pularia uma página.
    document.getElementById("btn-remocao-anterior").disabled = true;
    document.getElementById("btn-remocao-proxima").disabled = true;
    mensagem(tbody, "Carregando…");
    try {
      const r = await fetch("/api/remocao?" + q, { headers: getHeaders() });
      if (seq !== seqRemocao) return;
      if (!r.ok) {
        ultimaCheia = false;
        const erro = await mensagemCorpoErro(r);
        if (seq !== seqRemocao) return;
        mensagem(tbody, erro);
      } else {
        const j = await r.json();
        if (seq !== seqRemocao) return;
        const itens = j.itens || [];
        ultimaCheia = itens.length >= (j.por_pagina || 50);
        if (!itens.length) {
          mensagem(tbody, pagina > 1 ? "Nada nesta página." : "Nada a mostrar.");
        } else {
          tbody.replaceChildren(...itens.map((l) => {
            const tr = document.createElement("tr");
            tr.setAttribute("role", "row");
            celula(tr, quando(l.atualizado_em));
            celula(tr, l.machine_id);
            celula(tr, l.usuario_windows);
            celula(tr, l.pessoa);
            celula(tr, l.titular);
            celula(tr, REGRAS[l.regra] || l.regra);
            celula(tr, l.motivo);
            celula(tr, ESTADOS[l.estado] || l.estado, l.detalhe || "")
              .append(l.detalhe ? " — " + l.detalhe : "");
            return tr;
          }));
        }
      }
    } catch (e) {
      if (seq !== seqRemocao) return;
      ultimaCheia = false;
      mensagem(tbody, "Erro de conexão com o servidor.");
    }
    document.getElementById("btn-remocao-anterior").disabled = pagina <= 1;
    document.getElementById("btn-remocao-proxima").disabled = !ultimaCheia;
    document.getElementById("remocao-pagina").textContent = "Página " + pagina;
  }

  window.carregarRemocao = carregarRemocao;
  document.addEventListener("DOMContentLoaded", () => {
    document.getElementById("sel-remocao-estado").addEventListener("change", () => { pagina = 1; void carregarRemocao(); });
    document.getElementById("btn-remocao-anterior").addEventListener("click", () => { pagina -= 1; void carregarRemocao(); });
    document.getElementById("btn-remocao-proxima").addEventListener("click", () => { pagina += 1; void carregarRemocao(); });
  });
})();
