"""O texto do e-mail de alerta, editável pela tela (22/08).

As mesmas três invariantes de `test_alertas_configuraveis.py`, porque é a mesma
convenção — vazio é padrão, o job não cala, a tela recusa o que o job tolera —
mais duas que só aparecem quando o texto vira **conteúdo de e-mail**:

4. **O que a pessoa digita é texto, não marcação.** Um `<` digitado tem de
   chegar como `<`. Sem escape, quem edita o assunto escreve HTML no e-mail de
   todo mundo.
5. **O assunto vira cabeçalho SMTP.** `send_smtp_email` faz
   `msg["Subject"] = subject` sem sanitizar, o que nunca importou porque o
   assunto sempre veio do código. Uma quebra de linha ali injeta cabeçalho.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app import alert_state
from app import email_modelo as em


AGORA = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)
VALORES = {"data": "22/08/2026", "a_vencer": 12, "vencidos": 3, "janela": 30}


class _Settings:
    """Só o que `do_settings` e `previa_do_resumo` leem."""

    def __init__(self, **kw) -> None:
        self.alertas_marcos = ""
        for campo, coluna in em.CAMPO_COLUNA.items():
            setattr(self, coluna, kw.get(campo, ""))


# ══════════════════════════════════════════════════════════════════════════
# 1. Vazio é o padrão
# ══════════════════════════════════════════════════════════════════════════

def test_todos_os_campos_vazios_dao_o_email_de_antes() -> None:
    """A instalação que nunca abriu o modal recebe o e-mail que já recebia.

    Se este teste falhar depois de alguém "melhorar" um padrão, a falha está
    certa: mudar `PADROES` muda o e-mail de toda instalação que nunca editou o
    texto. É uma decisão, e tem de ser tomada de olho aberto.
    """
    assunto, html = alert_state._montar_resumo([], [], AGORA, 30, "motivo.", None)
    assert assunto == "Resumo de certificados — 0 a vencer, 0 vencidos recentemente"
    assert "Resumo de certificados</h2>" in html
    assert "Situação em 22/08/2026" in html
    assert "consulte a página Vencidos" in html


@pytest.mark.parametrize("campo", sorted(em.PADROES))
def test_campo_em_branco_devolve_o_padrao_daquele_campo(campo: str) -> None:
    assert em.campo_efetivo(campo, "") == em.PADROES[campo]
    assert em.campo_efetivo(campo, "   ") == em.PADROES[campo]
    assert em.campo_efetivo(campo, None) == em.PADROES[campo]


def test_apagar_um_campo_e_como_se_desfaz_a_edicao() -> None:
    """Vazio passa na validação de propósito: é o "restaurar padrão"."""
    assert em.validar_campo("titulo", "") == ""
    assert em.campo_efetivo("titulo", em.validar_campo("titulo", "")) == em.TITULO_PADRAO


# ══════════════════════════════════════════════════════════════════════════
# 2. O job não cala / 3. A tela recusa
# ══════════════════════════════════════════════════════════════════════════

def test_a_tela_recusa_marcador_inventado_e_diz_quais_existem() -> None:
    with pytest.raises(em.ModeloInvalido) as e:
        em.validar_campo("abertura", "Faltam {tota} certificados.")
    assert "{tota}" in str(e.value)
    assert "{a_vencer}" in str(e.value)


def test_o_job_nao_cala_diante_do_texto_que_a_tela_recusaria() -> None:
    """Editado direto no banco, ou salvo por uma versão que conhecia outro
    marcador. O alerta SAI — com o padrão, não com o texto quebrado."""
    ruim = "Faltam {tota} certificados."
    with pytest.raises(em.ModeloInvalido):
        em.validar_campo("abertura", ruim)
    assert em.campo_efetivo("abertura", ruim) == em.ABERTURA_PADRAO


def test_texto_ruim_no_banco_nao_impede_o_email_de_ser_montado() -> None:
    """A invariante de verdade: `_montar_resumo` não levanta, e o e-mail sai."""
    modelo = {"assunto": "{nao_existe}", "titulo": "x" * 5000, "abertura": "{bad}"}
    assunto, html = alert_state._montar_resumo([], [], AGORA, 30, "motivo.", modelo)
    assert assunto == "Resumo de certificados — 0 a vencer, 0 vencidos recentemente"
    assert "Resumo de certificados</h2>" in html


def test_texto_longo_demais_e_recusado_pela_tela() -> None:
    with pytest.raises(em.ModeloInvalido, match="limite"):
        em.validar_campo("assunto", "x" * (em.LIMITES["assunto"] + 1))


# ══════════════════════════════════════════════════════════════════════════
# 4. O que a pessoa digita é texto, não marcação
# ══════════════════════════════════════════════════════════════════════════

def test_html_digitado_aparece_como_texto_e_nao_como_marcacao() -> None:
    modelo = {"titulo": "Certificados <b>urgentes</b>"}
    _, html = alert_state._montar_resumo([], [], AGORA, 30, "motivo.", modelo)
    assert "&lt;b&gt;urgentes&lt;/b&gt;" in html
    assert "<b>urgentes</b>" not in html


def test_script_digitado_nao_vira_script() -> None:
    """Quem edita a configuração já é admin — mas o e-mail é lido por outras
    pessoas, em clientes que renderizam HTML. O escape protege o leitor."""
    _, html = alert_state._montar_resumo(
        [], [], AGORA, 30, "motivo.", {"abertura": "<script>alert(1)</script>"}
    )
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_quebra_de_linha_no_corpo_vira_br() -> None:
    """Parágrafo digitado em duas linhas chega em duas linhas."""
    _, html = alert_state._montar_resumo(
        [], [], AGORA, 30, "motivo.", {"recado": "Primeira.\nSegunda."}
    )
    assert "Primeira.<br>Segunda." in html


# ══════════════════════════════════════════════════════════════════════════
# 5. O assunto vira cabeçalho SMTP
# ══════════════════════════════════════════════════════════════════════════

def test_quebra_de_linha_no_assunto_e_achatada_na_gravacao() -> None:
    """`\\nBcc: alguem@fora.com` num cabeçalho é um destinatário a mais."""
    limpo = em.validar_campo("assunto", "Certificados\nBcc: fora@exemplo.com")
    assert "\n" not in limpo and "\r" not in limpo
    assert limpo == "Certificados Bcc: fora@exemplo.com"


def test_assunto_injetado_direto_no_banco_chega_limpo_ao_cabecalho() -> None:
    """O caminho que a tela nao alcanca.

    A gravacao limpa o que a pessoa digita, mas a coluna aceita `update` direto
    no banco. Este teste percorre banco -> `_montar_resumo` -> assunto, que e o
    valor que vira `msg["Subject"]`.

    Substituiu um teste que passava por acidente: ele chamava `assunto_final`
    com o texto sujo e afirmava cobrir uma "segunda camada" de limpeza que era
    inalcancavel — `campo_efetivo` ja valida antes de devolver. A mutacao que
    apagava aquela camada nao matava teste nenhum, e foi assim que apareceu.
    """
    sujo = _Settings(assunto="Resumo\r\nBcc: fora@exemplo.com")
    assunto, _ = alert_state._montar_resumo(
        [], [], AGORA, 30, "motivo.", em.do_settings(sujo)
    )
    assert "\n" not in assunto and "\r" not in assunto
    assert assunto == "Resumo Bcc: fora@exemplo.com"


# ══════════════════════════════════════════════════════════════════════════
# Marcadores
# ══════════════════════════════════════════════════════════════════════════

def test_marcadores_recebem_os_numeros_do_proprio_envio() -> None:
    texto = em.preencher(
        "{a_vencer} a vencer e {vencidos} vencidos em {data}, janela {janela}.",
        VALORES,
    )
    assert texto == "12 a vencer e 3 vencidos em 22/08/2026, janela 30."


def test_os_numeros_do_email_sao_os_das_listas_e_nao_um_palpite() -> None:
    """O marcador tem de acompanhar a tabela. Um assunto dizendo "3 a vencer"
    sobre uma tabela de 12 linhas é pior que assunto genérico."""
    expirando = [({"nome": f"E{i}", "not_after": (AGORA + timedelta(days=i + 1)).isoformat()}, i + 1) for i in range(4)]
    vencidos = [({"nome": "V1", "not_after": (AGORA - timedelta(days=2)).isoformat()}, -2)]
    assunto, _ = alert_state._montar_resumo(
        expirando, vencidos, AGORA, 30, "motivo.", {"assunto": "{a_vencer}/{vencidos}"}
    )
    assert assunto == "4/1"


def test_chave_maiuscula_ou_com_espaco_nao_e_marcador() -> None:
    """`{ data }` e `{DATA}` ficam literais em vez de virarem erro confuso."""
    assert em.validar_campo("titulo", "{ data } {DATA}") == "{ data } {DATA}"


# ══════════════════════════════════════════════════════════════════════════
# A ponte com PortalSettings
# ══════════════════════════════════════════════════════════════════════════

def test_do_settings_le_as_quatro_colunas() -> None:
    s = _Settings(titulo="Meu título", recado="Meu recado")
    assert em.do_settings(s)["titulo"] == "Meu título"
    assert em.do_settings(s)["assunto"] == ""


def test_coluna_ausente_nao_derruba_a_leitura() -> None:
    """Se a migration ainda não rodou, o padrão continua valendo — mesma
    tolerância de `_from_row`."""
    assert em.do_settings(object()) == {c: "" for c in em.CAMPO_COLUNA}


# ══════════════════════════════════════════════════════════════════════════
# A prévia
# ══════════════════════════════════════════════════════════════════════════

def _sem_inventario(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.main as m
    from app import settings_state
    monkeypatch.setattr(settings_state, "get_latest_snapshot", lambda *a, **k: None)
    monkeypatch.setattr(m, "_list_certificados_payload", lambda *a, **k: {"itens": []})


def test_previa_usa_exemplo_quando_a_janela_esta_vazia(monkeypatch) -> None:
    """Base em dia não pode produzir uma prévia em branco — quem abrisse o modal
    concluiria que quebrou alguma coisa."""
    _sem_inventario(monkeypatch)
    p = alert_state.previa_do_resumo(_Settings(), None, AGORA)
    assert p["exemplo"] is True
    assert p["a_vencer"] and p["vencidos"]
    assert "EMPRESA EXEMPLO LTDA" in p["html"]


def test_previa_e_montada_pela_mesma_funcao_que_envia(monkeypatch) -> None:
    """O ponto todo da prévia.

    Se alguém escrever um segundo montador para a tela, este teste falha: o HTML
    da prévia deixa de ser byte-a-byte o do envio com as mesmas listas. Prévia
    que diverge do que sai é pior que nenhuma, porque é acreditada.
    """
    _sem_inventario(monkeypatch)
    modelo = {"titulo": "Aviso do escritório"}
    p = alert_state.previa_do_resumo(_Settings(), modelo, AGORA)

    exp, venc = alert_state._linhas_de_exemplo(AGORA)
    assunto, html = alert_state._montar_resumo(
        exp, venc, AGORA, 30,
        "Você recebe este resumo porque tem perfil de administrador no portal.",
        modelo,
    )
    assert p["html"] == html
    assert p["assunto"] == assunto


def test_previa_sobrevive_a_inventario_indisponivel(monkeypatch) -> None:
    """Banco ruim não pode impedir alguém de julgar o texto que escreveu."""
    import app.main as m
    def _explode(*a, **k):
        raise RuntimeError("supabase fora")
    monkeypatch.setattr(m, "_list_certificados_payload", _explode)
    p = alert_state.previa_do_resumo(_Settings(), None, AGORA)
    assert p["exemplo"] is True
    assert "Resumo de certificados" in p["html"]


def test_previa_reflete_o_texto_ainda_nao_salvo(monkeypatch) -> None:
    """É o que a torna útil: julgar antes de gravar."""
    _sem_inventario(monkeypatch)
    salvo = _Settings(titulo="O que está gravado")
    p = alert_state.previa_do_resumo(salvo, {"titulo": "O que estou digitando"}, AGORA)
    assert "O que estou digitando" in p["html"]
    assert "O que está gravado" not in p["html"]
