"""Ponto de entrada do `certguard_analise.exe`.

  (sem argumento)    a bandeja da pessoa
  --preparar-chave   chamado pelo instalador, como administrador: copia a
                     chave da máquina do Hardlyze ou gera uma (chave_maquina)
  --preparar-atualizacao <instalador>
                     também do instalador: tranca a pasta de atualização,
                     guarda o instalador para voltar atrás e cria as tarefas
  --atualizacao      a tarefa agendada (SYSTEM) da atualização automática
  --atualizar <p>    o atualizador, rodando de uma cópia do exe (estacao/tarefa)
"""

from __future__ import annotations

import logging
import sys


def _preparar_chave() -> int:
    from estacao import caminhos, chave_maquina

    pasta = caminhos.pasta_maquina() / "logs"
    pasta.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=str(pasta / "instalacao.log"), level=logging.INFO, encoding="utf-8",
        format="%(asctime)s - %(levelname)s - %(message)s",
    )
    try:
        resultado = chave_maquina.preparar()
    except Exception:
        logging.exception("Não foi possível preparar a chave da máquina")
        return 1
    logging.info("Chave da máquina: %s.", resultado)
    return 0


def main(argv: list[str]) -> int:
    if "--preparar-chave" in argv:
        return _preparar_chave()
    if "--preparar-atualizacao" in argv:
        from estacao import tarefa

        tarefa.configurar_log("instalacao.log")
        i = argv.index("--preparar-atualizacao")
        if i + 1 >= len(argv):
            return 2
        try:
            return tarefa.preparar_atualizacao(argv[i + 1], sys.executable)
        except Exception:
            logging.exception("Não foi possível preparar a atualização automática")
            return 1
    if "--atualizacao" in argv:
        from estacao import tarefa

        return tarefa.rodar_tarefa()
    if "--atualizar" in argv:
        from estacao import tarefa

        i = argv.index("--atualizar")
        return tarefa.rodar_atualizador(argv[i + 1]) if i + 1 < len(argv) else 2
    from estacao import bandeja

    return bandeja.main()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
