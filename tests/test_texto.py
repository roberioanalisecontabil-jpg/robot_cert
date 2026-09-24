"""Textos prontos vindos do servidor (app/texto.py).

Plural, rótulo de status, papel e tipo de alerta moram num lugar só, e a
tela recebe a frase pronta. Antes cada template escrevia "tentativa(s)" e
mostrava a chave interna ("fora_do_padrao", "digest:2026-08-26").
"""

from app import texto


def test_plural_sem_parenteses() -> None:
    assert texto.plural(1, "tentativa") == "1 tentativa"
    assert texto.plural(5, "tentativa") == "5 tentativas"
    assert texto.plural(0, "máquina") == "0 máquinas"
    assert texto.plural(1049, "arquivo") == "1.049 arquivos"
    assert texto.plural(None, "alerta") == "0 alertas"


def test_plural_irregular_recebe_a_forma() -> None:
    assert texto.plural(1, "operador", "operadores") == "1 operador"
    assert texto.plural(2, "operador", "operadores") == "2 operadores"


def test_rotulo_de_status_nao_vaza_chave() -> None:
    assert texto.rotulo_status("fora_do_padrao") == "Fora do padrão de nome"
    assert texto.rotulo_status("ok") == "Lidos sem problema"
    assert texto.rotulo_status("erro") == "Erro de leitura"
    # "Expirado" é o que a última varredura viu; o rótulo diz isso.
    assert "varredura" in texto.rotulo_status("expirado")
    # Chave desconhecida ainda vira texto legível.
    assert "_" not in texto.rotulo_status("algo_novo")


def test_rotulo_de_papel_no_plural_conforme_a_contagem() -> None:
    assert texto.rotulo_papel("user", 1) == "Operador"
    assert texto.rotulo_papel("user", 6) == "Operadores"
    assert texto.rotulo_papel("admin", 1) == "Administrador"
    assert texto.rotulo_papel("gestor", 2) == "Gestores"


def test_alertas_agregam_por_tipo_legivel() -> None:
    assert texto.chave_alerta("digest:2026-08-26") == "digest"
    assert texto.chave_alerta("digest:2026-08-27") == "digest"
    assert texto.rotulo_alerta("digest") == "Resumo diário"
    assert texto.rotulo_alerta("expiring:15") == "Aviso de vencimento em 15 dias"
    assert texto.rotulo_alerta("expiring:1") == "Aviso de vencimento em 1 dia"
    assert texto.rotulo_alerta("expired") == "Aviso de vencido"
