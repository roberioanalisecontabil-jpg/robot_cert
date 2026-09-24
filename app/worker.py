"""Worker do gunicorn sem o cabeçalho `server: uvicorn`.

O uvicorn escreve esse cabeçalho depois de a aplicação responder, então o
`del response.headers["Server"]` em `app/main.py` nunca o alcançava
(SECURITY_AUDIT #50). Na linha de comando a opção é `--no-server-header`;
dentro do gunicorn a única forma é um worker com `CONFIG_KWARGS` próprio —
é só isso que esta classe faz. O `Procfile` aponta para cá.
"""

from uvicorn.workers import UvicornWorker


class Worker(UvicornWorker):
    CONFIG_KWARGS = {**UvicornWorker.CONFIG_KWARGS, "server_header": False}
