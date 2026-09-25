"""
Lote 9 das correções do SECURITY_AUDIT.md — o restante.

  #23  JWT de 24 h sem revogação individual; "Sair" só limpava o navegador
  #25  política de senha: mínimo 6 em cinco lugares, sem teto de 72 bytes
  #37  HSTS emitido sem nenhuma configuração do proxy TLS versionada
  #38  documentação e script orientavam HTTP em 0.0.0.0
  #40  ponte com o INVENT aceitava http:// para fora da própria máquina
  #51  DSN do PostgreSQL remoto sem sslmode
  #52  409 ecoava o e-mail; importação de carteiras ecoava o e-mail
  #57  o formatador de log apagava a mensagem inteira e não redigia exc_info
  #59  script de serviço subia com --reload

Cada teste foi escrito antes da correção e falhava em `4150e51` (fim do
lote 8).
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.main as m
from app import auth, config
from tests.test_seguranca_lote1 import _Fake, _usuario

RAIZ = Path(__file__).resolve().parents[1]


@pytest.fixture
def banco(monkeypatch: pytest.MonkeyPatch) -> _Fake:
    fake = _Fake({
        "users": [
            _usuario("u-adm", "admin@x.com", "admin", sessao_versao=0),
            _usuario("u-ana", "ana@x.com", "user", sessao_versao=0),
        ],
        "user_activity": [],
        "rate_limit_tentativas": [],
        "carteira": [],
    })
    monkeypatch.setattr("app.settings_state._banco", lambda: fake)
    return fake


def _h(email: str = "admin@x.com", papel: str = "admin", **claims) -> dict:
    return {"Authorization": "Bearer " + auth.create_access_token({"sub": email, "role": papel, **claims})}


# ──────────────────────────────────────────────────────────────────────────
# #23 — sair de verdade
# ──────────────────────────────────────────────────────────────────────────

def test_logout_derruba_o_token_que_saiu(client: TestClient, banco: _Fake) -> None:
    """O 'Como testar' do #23: guardar o JWT, chamar /api/logout, reusar → 401."""
    h = _h(sv=0)
    assert client.get("/api/users", headers=h).status_code == 200
    r = client.post("/api/logout", headers=h)
    assert r.status_code == 200, r.text
    assert client.get("/api/users", headers=h).status_code == 401
    # A conta continua entrando: um login novo nasce na versão nova.
    h2 = _h(sv=1)
    assert client.get("/api/users", headers=h2).status_code == 200


def test_token_antigo_sem_claim_de_versao_continua_valendo_ate_o_primeiro_logout(
    client: TestClient, banco: _Fake
) -> None:
    """Janela: tokens emitidos antes do deploy não têm `sv`. Valem como
    versão 0 — ninguém é deslogado pelo deploy — e morrem no primeiro Sair."""
    h = _h()  # sem sv
    assert client.get("/api/users", headers=h).status_code == 200
    client.post("/api/logout", headers=h)
    assert client.get("/api/users", headers=h).status_code == 401


def test_sem_a_coluna_a_sessao_nao_e_derrubada(client: TestClient, banco: _Fake) -> None:
    """Banco anterior à migration: a coluna não vem na linha. Fail-open aqui,
    como `senha_alterada_em` — a alternativa deslogaria o portal inteiro."""
    for u in banco.tabelas["users"]:
        u.pop("sessao_versao", None)
    assert client.get("/api/users", headers=_h(sv=3)).status_code == 200


def test_login_emite_token_com_a_versao_da_sessao(client: TestClient, banco: _Fake) -> None:
    from tests.test_seguranca_lote1 import SENHA

    banco.tabelas["users"][1]["sessao_versao"] = 4
    r = client.post("/api/login", json={"email": "ana@x.com", "password": SENHA})
    assert r.status_code == 200, r.text
    dados = auth.decode_access_token(r.json()["access_token"])
    assert dados is not None and dados.sessao_versao == 4


def test_validade_do_jwt_caiu_para_no_maximo_8h() -> None:
    assert auth.ACCESS_TOKEN_EXPIRE_MINUTES <= 8 * 60
    assert auth.SESSAO_HORAS_PADRAO == 8


def test_o_sair_do_navegador_chama_a_rota() -> None:
    js = (RAIZ / "static" / "ui-common.js").read_text(encoding="utf-8")
    assert "/api/logout" in js


def test_migration_da_versao_de_sessao_existe() -> None:
    sqls = list((RAIZ / "supabase" / "migrations").glob("*sessao_versao*.sql"))
    assert sqls, "falta a migration"
    sql = sqls[0].read_text(encoding="utf-8")
    assert "sessao_versao" in sql and "IF NOT EXISTS" in sql


def test_a_sessao_le_a_coluna_da_versao() -> None:
    """Mesma lógica de `test_sessao_le_a_coluna_da_troca_de_senha`: o fake
    devolve a linha inteira e não pegaria a coluna fora do select."""
    fonte = (RAIZ / "app" / "main.py").read_text(encoding="utf-8")
    trecho = fonte.split("def _conta_da_sessao")[1].split("\ndef ")[0]
    selects = re.findall(r'\.select\(\s*"([^"]*)"', trecho)
    assert selects and all("sessao_versao" in s for s in selects)


# ──────────────────────────────────────────────────────────────────────────
# #25 — política de senha única
# ──────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("senha, trecho", [
    ("123456", "12"),
    ("curta-11chr", "12"),
    ("a" * 80, "72"),
    ("aaaaaaaaaaaaaa", "repet"),
    ("123456789012", "comum"),
    ("password1234", "comum"),
])
def test_validar_senha_recusa(senha: str, trecho: str) -> None:
    erro = auth.validar_senha(senha)
    assert erro and trecho in erro.lower(), erro


def test_validar_senha_recusa_o_proprio_email() -> None:
    assert auth.validar_senha("ana.silva@x.com", email="ana.silva@x.com")
    assert auth.validar_senha("ana.silva2026!", email="ana.silva@x.com"), "a parte local do e-mail dentro da senha"


def test_validar_senha_aceita_senha_razoavel() -> None:
    assert auth.validar_senha("senha-123456", email="ana@x.com") is None
    assert auth.validar_senha("uma frase longa e boa", email="ana@x.com") is None
    # 36 caracteres de 2 bytes = exatamente 72 bytes: cabe; um a mais, não.
    assert len(("çé" * 18).encode("utf-8")) == 72 and auth.validar_senha("çé" * 18) is None
    assert auth.validar_senha("çé" * 18 + "x"), "73 bytes: o bcrypt truncaria em silêncio"


def test_criar_usuario_recusa_senha_fraca(client: TestClient, banco: _Fake) -> None:
    r = client.post("/api/users", json={"email": "z@x.com", "password": "123456", "full_name": "Z", "role": "user"}, headers=_h())
    assert r.status_code == 422 and "12" in r.json()["detail"]
    r = client.post("/api/users", json={"email": "z@x.com", "password": "b" * 80, "full_name": "Z", "role": "user"}, headers=_h())
    assert r.status_code == 422 and "72" in r.json()["detail"]


def test_redefinir_pelo_admin_recusa_senha_fraca(client: TestClient, banco: _Fake) -> None:
    r = client.post("/api/users/u-ana/reset-password", json={"password": "123456"}, headers=_h())
    assert r.status_code == 422 and "12" in r.json()["detail"]


def test_trocar_a_propria_senha_recusa_senha_fraca(client: TestClient, banco: _Fake) -> None:
    from tests.test_seguranca_lote1 import SENHA

    r = client.post("/api/senha/trocar", headers=_h("ana@x.com", "user", sv=0),
                    json={"senha_atual": SENHA, "nova_senha": "curta-11chr"})
    assert r.status_code == 422 and "12" in r.json()["detail"]


def test_a_regra_mora_num_lugar_so() -> None:
    fonte = (RAIZ / "app" / "main.py").read_text(encoding="utf-8")
    assert "len(new_pw) < 6" not in fonte
    assert "no mínimo 6 caracteres" not in fonte
    assert "SENHA_MINIMA = 6" not in fonte
    assert fonte.count("_exigir_senha_valida(") >= 4, "criar, redefinir pelo admin, redefinir por código, trocar"
    assert fonte.count("validar_senha(") >= 1, "a importação usa a mesma função"


# ──────────────────────────────────────────────────────────────────────────
# #37 / #38 — TLS na frente, aplicação em 127.0.0.1
# ──────────────────────────────────────────────────────────────────────────

def test_configuracao_do_proxy_esta_versionada_sem_segredo() -> None:
    caddy = (RAIZ / "deploy" / "Caddyfile").read_text(encoding="utf-8")
    assert "reverse_proxy 127.0.0.1:" in caddy and "8020" in caddy, "a aplicação só é alcançada por loopback"
    assert "{env." in caddy, "o token do DNS vem do ambiente, não do arquivo"
    assert not re.search(r"[A-Za-z0-9_-]{40}", caddy), "parece um token literal"


def test_documentacao_nao_orienta_mais_http_em_todas_as_interfaces() -> None:
    guia = (RAIZ / "docs" / "GUIA_MIGRACAO_WINDOWS_SERVER.md").read_text(encoding="utf-8")
    assert "0.0.0.0" not in guia
    assert "127.0.0.1" in guia and "Caddy" in guia
    script = (RAIZ / "scripts" / "setup_porta_servidor.ps1").read_text(encoding="utf-8", errors="replace")
    assert "0.0.0.0" not in script
    assert "443" in script, "o firewall abre a porta do proxy, não a da aplicação"
    assert not re.search(r"-LocalPort\s+\$PORTA\b", script), "a porta da aplicação não é aberta para fora"


# ──────────────────────────────────────────────────────────────────────────
# #40 — ponte só por https fora da própria máquina
# ──────────────────────────────────────────────────────────────────────────

def _producao(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "DATABASE_URL", "postgresql://u:p@127.0.0.1:5433/x")
    monkeypatch.setattr(config, "CERT_ENCRYPTION_KEY", "11" * 32)
    monkeypatch.setattr(config, "CERT_PASSWORD_ENCRYPTION_KEY", "22" * 32)
    monkeypatch.setattr(config, "API_KEY", "chave")
    monkeypatch.setattr(config, "CERT_PORTAL_TOKEN", "t")


def test_ponte_por_http_para_outro_host_e_fatal_em_producao(monkeypatch) -> None:
    _producao(monkeypatch)
    monkeypatch.setattr(config, "INVENT_API_URL", "http://10.200.0.9:8021")
    fatais, _ = config.verificar_ambiente()
    assert any("INVENT_API_URL" in f and "https" in f for f in fatais)


def test_ponte_por_http_na_propria_maquina_e_aceita(monkeypatch) -> None:
    """O ANALISESRV fala com o INVENT por 127.0.0.1:8021: não sai da máquina."""
    _producao(monkeypatch)
    monkeypatch.setattr(config, "INVENT_API_URL", "http://127.0.0.1:8021")
    fatais, _ = config.verificar_ambiente()
    assert not any("INVENT_API_URL" in f for f in fatais)


# ──────────────────────────────────────────────────────────────────────────
# #51 — sslmode no DSN remoto
# ──────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("dsn, esperado", [
    ("postgresql://u:p@127.0.0.1:5433/x", "postgresql://u:p@127.0.0.1:5433/x"),
    ("postgresql://u:p@localhost/x", "postgresql://u:p@localhost/x"),
    ("postgresql://u:p@10.200.0.4:5433/x", "postgresql://u:p@10.200.0.4:5433/x?sslmode=require"),
    ("postgresql://u:p@db.exemplo:5432/x?application_name=a", "postgresql://u:p@db.exemplo:5432/x?application_name=a&sslmode=require"),
    ("postgresql://u:p@db.exemplo/x?sslmode=disable", "postgresql://u:p@db.exemplo/x?sslmode=disable"),
])
def test_dsn_remoto_ganha_sslmode_require(dsn: str, esperado: str) -> None:
    assert config.dsn_efetivo(dsn) == esperado


def test_dsn_remoto_sem_tls_explicito_gera_aviso(monkeypatch) -> None:
    _producao(monkeypatch)
    monkeypatch.setattr(config, "DATABASE_URL", "postgresql://u:p@db.exemplo/x?sslmode=disable")
    _, avisos = config.verificar_ambiente()
    assert any("sslmode" in a for a in avisos)


def test_o_cliente_do_banco_usa_o_dsn_efetivo() -> None:
    fonte = (RAIZ / "app" / "settings_state.py").read_text(encoding="utf-8")
    assert "dsn_efetivo(" in fonte


# ──────────────────────────────────────────────────────────────────────────
# #52 — sem eco do e-mail
# ──────────────────────────────────────────────────────────────────────────

def test_409_nao_ecoa_o_email(client: TestClient, banco: _Fake) -> None:
    r = client.post("/api/users", json={"email": "ana@x.com", "password": "senha-123456", "full_name": "A", "role": "user"}, headers=_h())
    assert r.status_code == 409
    assert "ana@x.com" not in r.json()["detail"]


def test_importacao_de_carteiras_nao_ecoa_o_email() -> None:
    fonte = (RAIZ / "app" / "main.py").read_text(encoding="utf-8")
    assert "Não existe usuário com o e-mail {email}" not in fonte


# ──────────────────────────────────────────────────────────────────────────
# #57 — redigir VALORES, não frases
# ──────────────────────────────────────────────────────────────────────────

def _formatar(msg: str, exc: BaseException | None = None) -> dict:
    import json

    rec = logging.LogRecord("t", logging.WARNING, __file__, 1, msg, None, None)
    if exc is not None:
        try:
            raise exc
        except Exception:  # noqa: BLE001
            import sys

            rec.exc_info = sys.exc_info()
    return json.loads(m.SecureJSONFormatter().format(rec))


def test_mensagem_com_token_mantem_o_texto_e_mascara_o_valor() -> None:
    """O 'Como testar' do #57."""
    saida = _formatar("token abc.def.ghi rejeitado")["message"]
    assert "abc.def.ghi" not in saida
    assert saida.startswith("token") and "rejeitado" in saida


def test_aviso_operacional_deixa_de_ser_apagado() -> None:
    """O WARNING da X-API-Key compartilhada e o log de resgate recusado
    sumiam inteiros — era o que dizia quais estações ainda não migraram."""
    saida = _formatar("X-API-Key compartilhada aceita para a máquina SRV-01 (token de máquina ausente)")["message"]
    assert "compartilhada" in saida and "SRV-01" in saida


def test_jwt_e_bearer_sao_mascarados_onde_aparecerem() -> None:
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJhIn0.c2lnbmF0dXJl"
    saida = _formatar(f"cabeçalho Authorization: Bearer {jwt} recusado")["message"]
    assert "eyJ" not in saida and "recusado" in saida


def test_exc_info_tambem_e_redigido() -> None:
    saida = _formatar("falhou", ValueError("senha=SuperSecreta123 X-API-Key: abcdefghijklmnopqrstuvwxyz0123456789"))
    texto = saida["exc_info"]
    assert "SuperSecreta123" not in texto
    assert "abcdefghijklmnopqrstuvwxyz0123456789" not in texto
    assert "ValueError" in texto


# ──────────────────────────────────────────────────────────────────────────
# #59 — --reload só em desenvolvimento
# ──────────────────────────────────────────────────────────────────────────

def test_servir_so_recarrega_com_dev() -> None:
    ps1 = (RAIZ / "scripts" / "servir.ps1").read_text(encoding="utf-8", errors="replace")
    assert "[switch] $Dev" in ps1 or "[switch]$Dev" in ps1
    # Só a linha que acrescenta a flag ao comando conta (a mensagem ao usuário
    # também menciona --reload).
    codigo = [l for l in ps1.splitlines() if '"--reload"' in l and not l.strip().startswith("#")]
    assert len(codigo) == 1, codigo
    assert ps1.index("if ($Dev)") < ps1.index(codigo[0]), "o --reload tem de estar dentro do if ($Dev)"
