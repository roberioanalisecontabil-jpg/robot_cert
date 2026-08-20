"""Testes de integração HTTP (FastAPI TestClient)."""

import pytest
from fastapi.testclient import TestClient



def _headers_portal(api_key: str, papel: str = "user") -> dict:
    """
    Cabecalhos como o PORTAL manda, e nao como o agente.

    `getHeaders()` em `static/ui-common.js` envia SO o `Authorization: Bearer`;
    a X-API-Key e credencial do agente. Estes testes usavam a chave por
    conveniencia, e passaram a falhar em 20/08 quando os modulos de consulta
    entraram na matriz de permissoes — o agente (`agent@internal`) nao alcanca
    modulo de gente, corretamente.

    A chave continua no dicionario para o caso de a rota ainda a aceitar; o que
    manda e o JWT, como em producao.
    """
    from app import auth as _auth

    return {
        "X-API-Key": api_key,
        "Authorization": "Bearer " + _auth.create_access_token(
            {"sub": f"{papel}@exemplo.com", "role": papel}
        ),
    }


def test_health(client: TestClient) -> None:
    r = client.get("/api/health")
    assert r.status_code == 200
    j = r.json()
    assert j.get("ok") is True
    assert "supabase" in j
    assert "api_key_required" in j


def test_health_reporta_as_duas_chaves_do_cofre(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    O /health precisa distinguir a chave do PFX da chave da SENHA.

    Com só a primeira reportada, um servidor sem CERT_PASSWORD_ENCRYPTION_KEY
    parecia saudável enquanto /upload-pfx devolvia 500 em todo certificado. O
    sintoma aparecia longe: o cofre mantinha o registro antigo, sem senha, e a
    falha só se manifestava na máquina do usuário final, ao rodar o instalador
    avulso — "o portal não enviou a senha deste certificado".
    """
    r = client.get("/api/health")
    j = r.json()

    assert j["cert_senha_key_configurada"] is True
    assert j["cert_senha_key_distinta"] is True


def test_health_acusa_chave_da_senha_ausente(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.config.CERT_PASSWORD_ENCRYPTION_KEY", "", raising=False)

    j = client.get("/api/health").json()

    assert j["cert_senha_key_configurada"] is False
    assert j["cert_senha_key_distinta"] is False


def test_health_acusa_chaves_iguais(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Chaves iguais anulam a separação — a aplicação recusa operar assim."""
    monkeypatch.setattr("app.config.CERT_ENCRYPTION_KEY", "cc" * 32, raising=False)
    monkeypatch.setattr("app.config.CERT_PASSWORD_ENCRYPTION_KEY", "cc" * 32, raising=False)

    j = client.get("/api/health").json()

    assert j["cert_senha_key_configurada"] is True
    assert j["cert_senha_key_distinta"] is False, "chaves iguais têm de aparecer aqui"


def test_pagina_painel_200(client: TestClient) -> None:
    r = client.get("/")
    assert r.status_code == 200
    assert "Certificados" in r.text
    assert "configuracao" in r.text


def test_pagina_config_200(client: TestClient) -> None:
    r = client.get("/configuracao")
    assert r.status_code == 200
    assert "Chave API" in r.text
    assert "Origem (.pfx)" in r.text


def test_pagina_historico_200(client: TestClient) -> None:
    r = client.get("/historico")
    assert r.status_code == 200
    assert "Histórico de Certificados" in r.text


def test_pagina_vencidos_200(client: TestClient) -> None:
    r = client.get("/vencidos")
    assert r.status_code == 200
    assert "Certificados Vencidos" in r.text


def test_pagina_duplicidades_200(client: TestClient) -> None:
    r = client.get("/duplicidades")
    assert r.status_code == 200
    assert "Duplicidades" in r.text


def test_pagina_colaborador_certificados_200(client: TestClient) -> None:
    r = client.get("/acompanhamento")
    assert r.status_code == 200
    assert "Acompanhamento de Certificados" in r.text


def test_api_settings_sem_chave_200(client: TestClient) -> None:
    """Sem API_KEY no servidor, /api/settings deve ser acessível."""
    r = client.get("/api/settings")
    assert r.status_code == 200
    j = r.json()
    assert "source_folder" in j
    assert "effective_source" in j


def test_api_settings_401_se_chave_errada(
    client_com_chave: TestClient, api_key: str
) -> None:
    r = client_com_chave.get("/api/settings", headers={"X-API-Key": "chave-errada"})
    assert r.status_code == 401


def test_api_settings_200_com_chave_correta(
    client_com_chave: TestClient, api_key: str
) -> None:
    r = client_com_chave.get(
        "/api/settings", headers={"X-API-Key": api_key}
    )
    assert r.status_code == 200


def test_certificados_local_200(
    client_com_chave: TestClient, api_key: str
) -> None:
    h = {"X-API-Key": api_key}
    r = client_com_chave.get(
        "/api/certificados?fonte=local", headers=h
    )
    assert r.status_code == 200
    j = r.json()
    assert "itens" in j
    assert isinstance(j["itens"], list)
    assert j.get("data_source") in ("local", "remoto")


def test_certificados_dashboard_paginacao(
    client_com_chave: TestClient, api_key: str
) -> None:
    """O painel envia pagina/por_pagina; a API deve devolver paginacao e resumo."""
    h = {"X-API-Key": api_key}
    r = client_com_chave.get(
        "/api/certificados?fonte=local&pagina=1&por_pagina=5",
        headers=h,
    )
    assert r.status_code == 200
    j = r.json()
    assert "paginacao" in j
    assert j["paginacao"]["por_pagina"] == 5
    assert "resumo" in j
    assert "total" in j["resumo"]


def test_historico_certificados_200(
    client_com_chave: TestClient, api_key: str
) -> None:
    h = _headers_portal(api_key)
    r = client_com_chave.get("/api/certificados/historico", headers=h)
    assert r.status_code == 200
    j = r.json()
    assert "itens" in j
    assert "total" in j
    assert "snapshots_lidos" in j


def test_vencidos_certificados_200(
    client_com_chave: TestClient, api_key: str
) -> None:
    h = _headers_portal(api_key)
    r = client_com_chave.get("/api/certificados/vencidos", headers=h)
    assert r.status_code == 200
    j = r.json()
    assert "itens" in j
    assert "total" in j
    assert "snapshots_lidos" in j
    assert "resumo_anos" in j
    assert isinstance(j["resumo_anos"], list)


def test_historico_certificados_paginacao(
    client_com_chave: TestClient, api_key: str
) -> None:
    h = _headers_portal(api_key)
    r = client_com_chave.get(
        "/api/certificados/historico?pagina=1&por_pagina=5", headers=h
    )
    assert r.status_code == 200
    j = r.json()
    assert "paginacao" in j
    pg = j["paginacao"]
    assert pg["por_pagina"] == 5
    assert "total_paginas" in pg


def test_vencidos_certificados_paginacao(
    client_com_chave: TestClient, api_key: str
) -> None:
    h = _headers_portal(api_key)
    r = client_com_chave.get("/api/certificados/vencidos?pagina=1&por_pagina=5", headers=h)
    assert r.status_code == 200
    j = r.json()
    assert "paginacao" in j
    assert isinstance(j["resumo_anos"], list)


def test_duplicidades_api_200(
    client_com_chave: TestClient, api_key: str
) -> None:
    h = _headers_portal(api_key)
    r = client_com_chave.get("/api/certificados/duplicidades", headers=h)
    assert r.status_code == 200
    j = r.json()
    assert j.get("origem_dados") in ("ultimo_snapshot", "scan_local_servidor")
    assert "grupos_documento" in j
    assert "grupos_nome_similar" in j
    assert "grupos_certificado_igual" in j
    assert "total_itens_analisados" in j


def test_duplicidades_detecta_mesmo_documento(
    client_com_chave: TestClient, api_key: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app import main as main_mod

    def fake_snapshot() -> dict:
        return {
            "scanned_at": "2026-01-01T12:00:00+00:00",
            "items": [
                {
                    "file_name": "cert_a.pfx",
                    "nome": "EMPRESA TESTE",
                    "documento_numero": "11222333000181",
                    "documento_formatado": "11.222.333/0001-81",
                    "not_after": "2027-01-01T00:00:00+00:00",
                    "status": "ok",
                },
                {
                    "file_name": "cert_b.pfx",
                    "nome": "EMPRESA TESTE LTDA",
                    "documento_numero": "11222333000181",
                    "not_after": "2027-06-01T00:00:00+00:00",
                    "status": "ok",
                },
            ],
        }

    monkeypatch.setattr(main_mod, "get_latest_snapshot", fake_snapshot)
    r = client_com_chave.get(
        "/api/certificados/duplicidades", headers=_headers_portal(api_key)
    )
    assert r.status_code == 200
    j = r.json()
    assert j["total_grupos_documento"] >= 1
    assert len(j["grupos_documento"][0]["itens"]) == 2


def test_duplicidades_nome_sem_documento_distinto(
    client_com_chave: TestClient, api_key: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app import main as main_mod

    def fake_snapshot() -> dict:
        return {
            "scanned_at": "2026-02-01T12:00:00+00:00",
            "items": [
                {
                    "file_name": "um.pfx",
                    "nome": "EMPRESA ALFA LTDA",
                    "documento_numero": "",
                    "not_after": "2027-01-01T00:00:00+00:00",
                    "status": "ok",
                },
                {
                    "file_name": "dois.pfx",
                    "nome": "EMPRESA ALFA  LTDA",
                    "documento_numero": "12345678901234",
                    "not_after": "2027-02-01T00:00:00+00:00",
                    "status": "ok",
                },
            ],
        }

    monkeypatch.setattr(main_mod, "get_latest_snapshot", fake_snapshot)
    r = client_com_chave.get(
        "/api/certificados/duplicidades", headers=_headers_portal(api_key)
    )
    assert r.status_code == 200
    j = r.json()
    assert j["total_grupos_nome_similar"] >= 1


def test_duplicidades_mesmo_documento_nao_duplica_quando_so_fingerprint_igual(
    client_com_chave: TestClient, api_key: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mesmo CPF + mesmo fingerprint: só agrupa na tabela criptográfica, não em «mesmo documento»."""
    from app import main as main_mod

    fp = "f" * 64

    def fake_snapshot() -> dict:
        return {
            "scanned_at": "2026-04-01T12:00:00+00:00",
            "items": [
                {
                    "file_name": "a senha x.pfx",
                    "nome": "CHARLES SILVA",
                    "documento_numero": "87875950368",
                    "documento_formatado": "878.759.503-68",
                    "not_after": "2026-07-30T17:25:00+00:00",
                    "status": "ok",
                    "fingerprint_sha256": fp,
                },
                {
                    "file_name": "b senha x.pfx",
                    "nome": "CHARLES SILVA",
                    "documento_numero": "87875950368",
                    "documento_formatado": "878.759.503-68",
                    "not_after": "2026-07-30T17:25:00+00:00",
                    "status": "ok",
                    "fingerprint_sha256": fp,
                },
            ],
        }

    monkeypatch.setattr(main_mod, "get_latest_snapshot", fake_snapshot)
    r = client_com_chave.get(
        "/api/certificados/duplicidades", headers=_headers_portal(api_key)
    )
    assert r.status_code == 200
    j = r.json()
    assert j["total_grupos_documento"] == 0
    assert j["total_grupos_certificado_igual"] >= 1


def test_duplicidades_certificado_igual_por_fingerprint(
    client_com_chave: TestClient, api_key: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app import main as main_mod

    fp = "a" * 64
    fp2 = "b" * 64
    subj = "CN=EMPRESA X:11222333000181"
    iss = "CN=AC TESTE"

    def fake_snapshot() -> dict:
        return {
            "scanned_at": "2026-03-01T12:00:00+00:00",
            "items": [
                {
                    "file_name": "copia1 senha p1.pfx",
                    "nome": "EMPRESA X",
                    "documento_numero": "11222333000181",
                    "not_after": "2027-01-01T00:00:00+00:00",
                    "not_before": "2026-01-01T00:00:00+00:00",
                    "status": "ok",
                    "fingerprint_sha256": fp,
                    "subject": subj,
                    "issuer": iss,
                    "serial_number": "1a",
                },
                {
                    "file_name": "copia2 senha p1.pfx",
                    "nome": "EMPRESA X",
                    "documento_numero": "11222333000181",
                    "not_after": "2027-01-01T00:00:00+00:00",
                    "not_before": "2026-01-01T00:00:00+00:00",
                    "status": "ok",
                    "fingerprint_sha256": fp,
                    "subject": subj,
                    "issuer": iss,
                    "serial_number": "1a",
                },
                {
                    "file_name": "outro senha p1.pfx",
                    "nome": "EMPRESA X",
                    "documento_numero": "11222333000181",
                    "not_after": "2028-01-01T00:00:00+00:00",
                    "status": "ok",
                    "fingerprint_sha256": fp2,
                    "subject": subj,
                    "issuer": iss,
                },
            ],
        }

    monkeypatch.setattr(main_mod, "get_latest_snapshot", fake_snapshot)
    r = client_com_chave.get(
        "/api/certificados/duplicidades", headers=_headers_portal(api_key)
    )
    assert r.status_code == 200
    j = r.json()
    assert j["total_grupos_certificado_igual"] >= 1
    gci = j["grupos_certificado_igual"]
    assert any(
        g.get("fingerprint_sha256") == fp and len(g.get("itens", [])) == 2 for g in gci
    )


def test_colaborador_endpoints_200(
    client_com_chave: TestClient, api_key: str
) -> None:
    h = _headers_portal(api_key)
    r1 = client_com_chave.get("/api/colaborador/certificados/opcoes", headers=h)
    assert r1.status_code == 200
    r2 = client_com_chave.get("/api/colaborador/certificados/selecionados", headers=h)
    assert r2.status_code == 200
    r3 = client_com_chave.put(
        "/api/colaborador/certificados/selecionados",
        json={"documentos": ["12.345.678/0001-90", "12345678901"]},
        headers=h,
    )
    assert r3.status_code == 200
    assert r3.json().get("ok") is True
    r4 = client_com_chave.get("/api/colaborador/certificados/painel", headers=h)
    assert r4.status_code == 200
    assert "itens" in r4.json()


def test_operador_comum_nao_ingere_inventario(
    client_com_chave: TestClient, api_key: str
) -> None:
    """
    Ingestao e consumo da fila sao do AGENTE, nao de qualquer autenticado.

    Ate 19/08/2026 as duas rotas estavam sob `require_auth`, que aceita papel
    'user'. Um operador comum podia sobrescrever o inventario inteiro — e
    `renderTransfer`, os alertas e o dashboard leem dali.

    `require_agent_or_admin` e a mesma guarda que `upload-pfx`, `redeem` e
    `report` ja usavam; o agente ja passava por ela, entao apertar aqui nao
    muda nada para quem legitimamente chama.

    Ver docs/PLANO_niveis_de_acesso.md §1, etapa 1b.
    """
    from app import auth as _auth

    for papel in ("user", "gestor"):
        h = {
            "Authorization": "Bearer " + _auth.create_access_token(
                {"sub": f"{papel}@exemplo.com", "role": papel}
            )
        }
        r = client_com_chave.post("/api/ingest", json={"items": []}, headers=h)
        assert r.status_code == 403, f"{papel} conseguiu ingerir inventario"

        n = client_com_chave.get("/api/agent/next?machine_id=default", headers=h)
        assert n.status_code == 403, f"{papel} conseguiu consumir a fila"

    # O agente, esse sim, passa nas duas. A asserção é "não barrado", e não
    # "200": um corpo incompleto responde 422, que já prova a passagem pela
    # guarda — validação roda DEPOIS da autenticação. Exigir 200 amarraria este
    # teste ao schema do ingest, que não é o que ele mede.
    h_agente = {"X-API-Key": api_key}
    assert client_com_chave.post(
        "/api/ingest", json={"items": []}, headers=h_agente
    ).status_code != 403, "o agente foi barrado no ingest"
    assert client_com_chave.get(
        "/api/agent/next?machine_id=default", headers=h_agente
    ).status_code == 200


def test_operador_comum_nao_enfileira_comando(
    client_com_chave: TestClient, api_key: str
) -> None:
    """
    A rota de enfileirar comando exige admin, e a checagem e do SERVIDOR.

    Ate 19/08/2026 ela estava sob `require_auth`: qualquer autenticado — um
    operador comum, ou o proprio agente com a X-API-Key — podia mandar o
    servidor reescanear ou mover certificados. A unica chamadora legitima e
    `configuracao.html`, que so admin enxerga; mas esconder o menu nao e
    barreira, e este teste existe para que a barreira continue no servidor.

    Ver docs/PLANO_niveis_de_acesso.md §0.1 e §1.
    """
    from app import auth as _auth

    corpo = {"machine_id": "default", "command": "ping"}

    for papel in ("user", "gestor"):
        h = {
            "Authorization": "Bearer " + _auth.create_access_token(
                {"sub": f"{papel}@exemplo.com", "role": papel}
            )
        }
        r = client_com_chave.post("/api/agent/commands", json=corpo, headers=h)
        assert r.status_code == 403, f"{papel} conseguiu enfileirar comando"

    # A chave do agente tambem nao: quem consome a fila nao a alimenta.
    r = client_com_chave.post(
        "/api/agent/commands", json=corpo, headers={"X-API-Key": api_key}
    )
    assert r.status_code == 403, "a chave do agente conseguiu enfileirar comando"


def test_fila_comando_ping(
    client_com_chave: TestClient, api_key: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Enfileirar, consumir e esvaziar a fila (só ficheiro, sem Supabase)."""
    from app import command_queue

    import tempfile
    from pathlib import Path

    monkeypatch.setattr(command_queue, "_supabase", lambda: None)

    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "queue.json"
        monkeypatch.setattr(command_queue, "QUEUE_FILE", p)

        h = {"X-API-Key": api_key}

        # Enfileirar exige admin desde 19/08 (docs/PLANO_niveis_de_acesso.md §1):
        # a rota estava sob `require_auth`, que aceita qualquer autenticado —
        # inclusive o proprio agente, que e quem CONSOME a fila e nao tem por que
        # alimenta-la. A unica chamadora real e `configuracao.html`, pagina de
        # admin. Consumir (`/api/agent/next`) segue com a chave do agente, que e
        # quem faz isso em producao.
        from app import auth as _auth
        h_admin = {
            "Authorization": "Bearer " + _auth.create_access_token(
                {"sub": "admin@exemplo.com", "role": "admin"}
            )
        }
        en = client_com_chave.post(
            "/api/agent/commands",
            json={"machine_id": "default", "command": "ping"},
            headers=h_admin,
        )
        assert en.status_code == 200
        assert en.json().get("ok") is True

        n1 = client_com_chave.get(
            "/api/agent/next?machine_id=default", headers=h
        )
        assert n1.status_code == 200
        assert n1.json().get("command") == "ping"

        n2 = client_com_chave.get(
            "/api/agent/next?machine_id=default", headers=h
        )
        assert n2.status_code == 200
        assert n2.json().get("command") is None
