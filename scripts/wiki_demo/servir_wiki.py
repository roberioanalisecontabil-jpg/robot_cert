"""Sobe o portal de DEMONSTRACAO (banco certguard_wiki) em 127.0.0.1:8091.

Chamado por subir_portal_wiki.ps1. Le ambiente-wiki.env (gerado pelo
seed_wiki.py) e, antes de importar o app, desliga o que mandaria e-mail ou
escreveria na pasta data/ do repositorio:
  * o job diario de alertas e o aviso de certificados novos por hora cheia;
  * os arquivos locais de fallback (data/*.json) apontam para esta pasta.
Nada no repositorio e alterado.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
REPO = AQUI.parent.parent  # scripts/wiki_demo/ -> raiz do repositorio


def main() -> None:
    porta = int(sys.argv[1]) if len(sys.argv) > 1 else 8091  # 8090 e do Wondershare
    amb = AQUI / "ambiente-wiki.env"
    if not amb.is_file():
        raise SystemExit("ambiente-wiki.env nao existe: rode antes o seed_wiki.py")
    for linha in amb.read_text(encoding="ascii").splitlines():
        linha = linha.strip()
        if linha and not linha.startswith("#") and "=" in linha:
            k, v = linha.split("=", 1)
            os.environ[k.strip()] = v.strip()  # sobrepoe o .env do repositorio
    # O batimento abaixo escreve no banco: so no de demonstracao, nunca num
    # DATABASE_URL de verdade que tenha vazado para o ambiente-wiki.env.
    if not os.environ.get("DATABASE_URL", "").rstrip("/").endswith("/certguard_wiki"):
        raise SystemExit("DATABASE_URL nao aponta para o banco certguard_wiki; recusado.")
    if "--codigo" in sys.argv:
        os.environ["LOGIN_EXIGE_CODIGO"] = "1"  # so para os prints da tela do codigo

    os.chdir(REPO)
    sys.path.insert(0, str(REPO))

    dados = AQUI / "data-local"
    dados.mkdir(exist_ok=True)
    from app import alert_state, settings_state

    alert_state.SENT_ALERTS_FILE = dados / "sent_alerts.json"
    alert_state.JOB_STATE_FILE = dados / "alerts_job_state.json"
    settings_state.DATA_FILE = dados / "portal_settings.json"
    settings_state.INGEST_FILE = dados / "last_ingest.json"
    settings_state.COLAB_SELECAO_FILE = dados / "colaborador_certificados.json"

    import app.main as m

    m.job_ja_executado_recentemente = lambda *a, **k: True  # job de alertas nunca roda
    m.enviar_novos_pendentes = lambda *a, **k: {}           # aviso por hora cheia nunca envia

    # Bandejas "vivas": o portal so considera vivo o dispositivo visto ha
    # menos de 3 min (agent_devices.JANELA_VIVO_SEG). Sem isto, minutos depois
    # do seed o Inicio diria "bandeja parada" e nada seria instalavel. Simula
    # o heartbeat das estacoes de demo; CONTABIL-PC02 fica parada de proposito.
    import threading

    import psycopg

    def batimento() -> None:
        import time

        while True:
            try:
                with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as c:
                    c.execute("UPDATE agent_devices SET visto_em = now() WHERE nome <> 'CONTABIL-PC02' AND revogado_em IS NULL")
                    c.execute("UPDATE machine_credentials SET visto_em = now() WHERE revogado_em IS NULL")
            except Exception as e:  # noqa: BLE001
                print("batimento das bandejas de demo falhou:", e, file=sys.stderr)
            time.sleep(60)

    threading.Thread(target=batimento, daemon=True).start()

    import uvicorn

    uvicorn.run(m.app, host="127.0.0.1", port=porta, server_header=False, log_level="info")


if __name__ == "__main__":
    main()
