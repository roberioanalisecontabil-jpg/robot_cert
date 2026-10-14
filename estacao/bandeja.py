"""A bandeja do Certguard Análise: entrar, ver a situação, receber e instalar.

Veio da parte de certificados do `main.py` do Hardlyze 2.2.0 (tray-only):
`certificados_loop`, `verificar_instalacoes_do_portal`, `on_login`,
`on_sair_certificados` e `on_status`. Roda como a pessoa logada — é isso que
faz o certificado entrar no repositório dela, e não no do SYSTEM.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path

from estacao import NOME, VERSAO_REPORTADA, caminhos

logger = logging.getLogger("estacao")

INTERVALO = 20  # segundos entre as perguntas ao portal, como no Hardlyze


def configurar_log() -> Path:
    """`%LOCALAPPDATA%\\CertguardAnalise\\logs\\bandeja.log`, 2 MB x 5. O formato
    é o que `janela_status.acoes_do_log` sabe ler."""
    pasta = caminhos.pasta_de_log()
    pasta.mkdir(parents=True, exist_ok=True)
    arquivo = pasta / "bandeja.log"
    handler = RotatingFileHandler(arquivo, maxBytes=2_000_000, backupCount=5, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
    raiz = logging.getLogger()
    raiz.setLevel(logging.INFO)
    raiz.addHandler(handler)
    # O rastro de cada requisição do httpx enche o log a cada 20 s sem dizer nada.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    return arquivo


def machine_id() -> str:
    """O MAC que identifica esta máquina no portal: o primeiro em ordem
    alfabética, sem o nulo. TEM de ser o mesmo cálculo do Hardlyze
    (`DataCollector._get_mac_addresses()[0]`): é a mesma máquina para o portal,
    e um id diferente faria todo computador já autorizado virar equipamento
    novo no primeiro login."""
    import psutil

    macs = set()
    try:
        for addrs in psutil.net_if_addrs().values():
            for addr in addrs:
                if addr.family == psutil.AF_LINK:
                    mac = addr.address.replace("-", ":").lower()
                    if mac and mac != "00:00:00:00:00:00":
                        macs.add(mac)
    except Exception:
        logger.exception("Erro ao obter MACs")
    return sorted(macs)[0] if macs else "unknown"


_MUTEX = None


def instancia_unica() -> bool:
    """Uma bandeja por sessão do Windows: duas fariam duas buscas e duas
    instalações do mesmo pedido."""
    global _MUTEX
    if os.name != "nt":
        return True
    try:
        import ctypes

        _MUTEX = ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\CertguardAnaliseBandeja")
        return ctypes.windll.kernel32.GetLastError() != 183  # ERROR_ALREADY_EXISTS
    except Exception:
        # Sem a trava, sobe assim mesmo: duas bandejas são incômodas, nenhuma é pior.
        return True


def _icone():
    from PIL import Image

    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    try:
        return Image.open(base / "ico" / "icone.ico")
    except Exception:
        logger.warning("Ícone não encontrado; usando um quadrado.")
        return Image.new("RGB", (64, 64), (0, 120, 215))


class Bandeja:
    texto = "Certificados: entre com sua conta"

    def __init__(self, caminho_log: Path):
        self.caminho_log = caminho_log
        self.icon = None
        self._parar = threading.Event()
        self._autorizacao_anterior = None
        self._mid = None

    # ── portal ──────────────────────────────────────────────────────────

    def _avisar(self, texto: str) -> None:
        try:
            if self.icon:
                self.icon.notify(texto, NOME)
        except Exception:
            pass

    def laco(self) -> None:
        """Pergunta ao portal, a cada 20 s, se há instalação para esta máquina.
        As chamadas também mantêm a bandeja "Conectada" na aba Computadores."""
        while not self._parar.is_set():
            self.verificar()
            self._parar.wait(INTERVALO)

    def verificar(self) -> None:
        import httpx

        from estacao import conta as cc
        from estacao import instalador_certificado

        if not cc.esta_conectado():
            self.texto = "Certificados: entre com sua conta"
            self._autorizacao_anterior = None
            return
        try:
            with httpx.Client() as http:
                sit = cc.situacao(http, VERSAO_REPORTADA)
                autorizacao = sit.get("autorizacao")
                email = (cc.ler() or {}).get("email") or ""
                self.texto = {
                    "autorizado": f"Certificados: {email} — computador autorizado",
                    "pendente": f"Certificados: {email} — aguardando autorização",
                }.get(autorizacao, f"Certificados: {email} — não vinculado")
                if autorizacao == "autorizado" and self._autorizacao_anterior == "pendente":
                    self._avisar("Este computador foi autorizado no portal de certificados.")
                self._autorizacao_anterior = autorizacao
                if autorizacao != "autorizado":
                    return
                tokens = cc.instalacoes_pendentes(http, VERSAO_REPORTADA)
        except cc.SessaoEncerrada as e:
            logger.info("Portal de certificados encerrou a sessão desta bandeja: %s", e)
            self.texto = "Certificados: sessão encerrada — entre de novo"
            self._avisar("Sua sessão no portal de certificados foi encerrada neste computador. "
                         "Entre de novo para receber certificados.")
            return
        except Exception as e:
            logger.warning("Portal de certificados indisponível agora: %s", e)
            return

        for token in tokens:
            try:
                resultados = instalador_certificado.instalar(
                    token, portal=cc.portal_da_conta(), cabecalhos=cc.cabecalhos(VERSAO_REPORTADA),
                )
            except Exception as e:
                logger.exception("Falha ao instalar certificado vindo do portal")
                self._avisar(f"Não foi possível instalar o certificado: {e}")
                continue
            ok = sum(1 for r in resultados if r.get("status") == "OK")
            falhas = len(resultados) - ok
            logger.info("Instalação pelo portal de certificados: %s ok, %s falha(s).", ok, falhas)
            self._avisar(f"{ok} certificado(s) instalado(s)" + (f", {falhas} com falha" if falhas else "") + ".")

    # ── menu ────────────────────────────────────────────────────────────

    def _machine_id(self) -> str:
        if not self._mid or self._mid == "unknown":
            self._mid = machine_id()
        return self._mid

    def on_login(self, icon=None, item=None) -> None:
        try:
            import httpx

            from estacao import chave_maquina, conta
            from estacao.janela_login import abrir_janela

            mid = self._machine_id()
            if mid == "unknown":
                logger.error("Sem MAC identificável; não dá para registrar o dispositivo.")
                return
            portal = conta.portal_da_conta()

            def _registrar(email: str, senha: str) -> dict:
                with httpx.Client() as http:
                    return conta.registrar(
                        http, portal, email, senha, mid,
                        nome=os.getenv("COMPUTERNAME") or mid,
                        chave_maquina=chave_maquina.ler(),
                    )

            def _pronto() -> None:
                logger.info("Conta do portal de certificados conectada (máquina %s).", mid)
                threading.Thread(target=self.verificar, daemon=True).start()

            abrir_janela(ao_registrar=_registrar, portal=portal, machine_id=mid, ao_concluir=_pronto)
        except Exception:
            logger.exception("Falha ao abrir a janela de login")

    def on_sair_da_conta(self, icon=None, item=None) -> None:
        try:
            import httpx

            from estacao import conta

            with httpx.Client() as http:
                conta.sair(http, VERSAO_REPORTADA)
            self.texto = "Certificados: entre com sua conta"
            self._autorizacao_anterior = None
            logger.info("Conta do portal de certificados desconectada nesta máquina.")
        except Exception:
            logger.exception("Falha ao sair da conta do portal de certificados")

    def on_status(self, icon=None, item=None) -> None:
        try:
            from estacao import conta, janela_status

            def _estado():
                return janela_status.montar_estado(
                    caminho_log=self.caminho_log,
                    portal=conta.portal_da_conta(),
                    versao=VERSAO_REPORTADA,
                    credencial=conta.ler(),
                )

            janela_status.abrir_janela(obter_estado=_estado, ao_entrar=self.on_login,
                                       ao_sair_da_conta=self.on_sair_da_conta)
        except Exception:
            logger.exception("Falha ao abrir a janela de status")

    def on_fechar(self, icon=None, item=None) -> None:
        self._parar.set()
        if self.icon:
            self.icon.stop()

    def _conectado(self) -> bool:
        try:
            from estacao import conta

            return conta.esta_conectado()
        except Exception:
            return False

    # ── partida ─────────────────────────────────────────────────────────

    def rodar(self) -> None:
        import pystray
        from pystray import MenuItem as item

        from estacao import conta

        try:
            conta.migrar_do_hardlyze()
        except Exception:
            logger.exception("Falha ao trazer a conta do Hardlyze")

        threading.Thread(target=self.laco, daemon=True).start()

        menu = (
            item(lambda text: self.texto, lambda icon, item: None, enabled=False),
            item("Status e histórico", self.on_status, default=True),
            item("Entrar no portal de certificados…", self.on_login),
            item("Sair da conta de certificados", self.on_sair_da_conta,
                 visible=lambda item: self._conectado()),
            item("Fechar", self.on_fechar),
        )
        self.icon = pystray.Icon("certguard_analise", _icone(), NOME, menu)

        # Primeira vez nesta conta do Windows (e sem conta trazida do
        # Hardlyze): pede o login sozinho, em vez de esperar alguém achar o item.
        if not self._conectado():
            logger.info("Nenhuma conta do portal de certificados nesta sessão; a pedir login.")
            self.on_login()

        self.icon.run()


def main() -> int:
    caminho_log = configurar_log()
    if not instancia_unica():
        logger.info("Já existe uma bandeja aberta nesta sessão; encerrando esta.")
        return 0
    logger.info("%s %s iniciado.", NOME, VERSAO_REPORTADA)
    Bandeja(caminho_log).rodar()
    return 0
