"""Sessão e permissões das rotas (Frente 3, leva 1 — 09/10/2026).

Saiu de `app/main.py` sem mudar comportamento: quem é a pessoa da
requisição (JWT no cabeçalho ou no cookie da Leva D, X-API-Key do agente),
se a sessão ainda vale (conta ativa, senha não trocada, logout), e as
dependências `require_*` que as rotas usam. `app/main.py` reimporta os mesmos
nomes, então `app.main.require_auth` etc. continuam existindo.

É o alicerce para as rotas saírem de `main.py` em routers: um router importa
daqui, e não de `main`, que importaria o router de volta.
"""

from __future__ import annotations

import hmac
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, Header, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app import agent_devices, auth, config, machine_credentials, permissoes, sessao_cookie

logger = logging.getLogger("app.main")


security = HTTPBearer(auto_error=False)

# Identidade atribuída quando API_KEY não está configurada (ambiente aberto).
# Rotas sensíveis devem recusá-la — é o oposto de "autenticado".
ANONYMOUS_IDENTITY_EMAIL = "anonymous@local"

# Mensagem única para "este token não vale mais". Não distingue conta excluída
# de conta desativada de propósito: quem está do outro lado já perdeu o acesso,
# e a diferença só serviria para dizer a um ex-usuário em que estado a conta
# dele ficou.
SESSAO_ENCERRADA = "Sessão encerrada. Entre novamente."

# Rotas que continuam funcionando com senha provisória. Lista fechada, e
# curta de propósito: tudo o mais é recusado. Fosse uma lista de bloqueio em
# vez de liberação, cada rota nova nasceria acessível por omissão — e o
# esquecimento não daria sintoma nenhum.
# `/api/logout` entra (revisão de 01/10/2026): o "Sair" do modal de troca
# obrigatória caía neste 403 e a sessão provisória nunca era revogada.
ROTAS_COM_SENHA_PROVISORIA = frozenset({"/api/senha/trocar", "/api/logout"})

ERRO_SENHA_PROVISORIA = (
    "Sua senha foi definida por outra pessoa. Escolha uma senha própria para "
    "continuar."
)


class ContaIndisponivel(RuntimeError):
    """O diretório de usuários existe, mas não respondeu."""


class ContaInvalida(RuntimeError):
    """A conta que o token nomeia não existe mais no diretório."""


def _conta_da_sessao(email: str) -> Optional[dict]:
    """
    Relê a conta a cada requisição, para o token não congelar a permissão.

    Devolve `None` quando **não há** diretório de usuários configurado — dev e
    testes sem banco. Aí não existe conta contra a qual conferir, e o token é
    a única informação disponível. Isso não abre brecha em produção: sem
    banco o `/api/login` responde 503 e ninguém chega a ter um token para
    apresentar.

    Levanta `ContaInvalida` quando a conta sumiu — excluída, ou com o e-mail
    alterado, porque aí o `sub` do token deixa de casar com qualquer linha.
    Levanta `ContaIndisponivel` quando a leitura falha. Barrar no segundo caso é
    deliberado: "não consegui verificar" não é "está tudo certo". É a mesma
    escolha já feita em `CustodiaIndisponivel`, e pela mesma razão — a variante
    permissiva não daria sintoma nenhum.
    """
    from app.settings_state import _banco

    sb = _banco()
    if not sb:
        return None
    try:
        r = (
            sb.table("users")
            # `senha_alterada_em` PRECISA estar aqui: é o que
            # `_senha_trocada_depois_do_token` compara. Omiti-la não daria erro
            # — a chave chegaria ausente, seria lida como "nunca trocou", e a
            # invalidação de sessão simplesmente nunca dispararia. Fixado por
            # `test_sessao_le_a_coluna_da_troca_de_senha`, porque o fake dos
            # testes devolve a linha inteira e não pega isto sozinho.
            # `sessao_versao` pelo mesmo motivo (lote 9, achado #23): sem ela
            # aqui, "Sair" incrementaria a coluna e nenhum token morreria.
            .select("id, email, role, ativo, senha_alterada_em, deve_trocar_senha, sessao_versao")
            .eq("email", email)
            .limit(1)
            .execute()
        )
    except Exception as e:
        logger.warning("Não foi possível verificar a conta da sessão: %s", e)
        raise ContaIndisponivel(str(e)) from e
    if not r.data:
        raise ContaInvalida(email)
    return r.data[0]


def _senha_trocada_depois_do_token(
    conta: dict, token_data: auth.TokenData
) -> bool:
    """
    A senha mudou depois de este token ter sido emitido?

    Devolve False quando falta informação — coluna nula (conta que nunca trocou
    a senha), token sem instante de emissão, ou data ilegível. É o único ponto
    fail-OPEN do `_sessao_do_token`, e é deliberado: um erro de leitura aqui
    deslogaria o portal inteiro de uma vez, e a ausência de dado significa
    literalmente "não houve troca a invalidar".

    A margem de 5s absorve relógios ligeiramente fora de sincronia entre o
    processo que emitiu o token e o que gravou a troca. Sem ela, uma diferença
    de milissegundos poderia derrubar a sessão de quem acabou de entrar.
    """
    marca = conta.get("senha_alterada_em")
    if not marca or not token_data.emitido_em:
        return False
    try:
        trocada = _parse_iso_utc(str(marca))
    except Exception:  # noqa: BLE001
        logger.warning("senha_alterada_em ilegível para %s", conta.get("email"))
        return False
    if trocada is None:
        return False
    return token_data.emitido_em < (trocada - timedelta(seconds=5))


def _sessao_do_token(token_data: auth.TokenData) -> auth.TokenData:
    """
    O papel que vale é o do banco, não o que veio dentro do token.

    Sem isto, `require_admin` decidia com `token.role` — gravado no login e
    válido por 24h (`auth.ACCESS_TOKEN_EXPIRE_MINUTES`). Duas consequências, e a
    segunda é a pior: desativar alguém não derrubava a sessão aberta dele, e
    **rebaixar um administrador não tirava o poder de administrador**; os dois
    efeitos só chegavam quando o token expirasse.

    Era tolerável enquanto desativar era operação rara. Com a hierarquia
    gestor/operador de 15/08, desativar passou a ser a forma principal de
    revogar acesso — e revogação que leva um dia para valer não é revogação.

    Custa uma leitura em `users` por requisição autenticada. É o preço honesto:
    a alternativa por `token_version` faria a mesma leitura, só que precisando
    também de migration.
    """
    try:
        conta = _conta_da_sessao(token_data.email)
    except ContaInvalida:
        raise HTTPException(
            status_code=401,
            detail=SESSAO_ENCERRADA,
            headers={"WWW-Authenticate": "Bearer"},
        )
    except ContaIndisponivel:
        # 503, e não 401: o front derruba a sessão em todo 401
        # (`static/ui-common.js`), e uma instabilidade do banco não deve
        # deslogar quem está trabalhando.
        raise HTTPException(
            status_code=503,
            detail="Não foi possível confirmar a sua sessão. Tente novamente.",
        )

    if conta is None:
        return token_data
    if not auth.conta_ativa(conta):
        raise HTTPException(
            status_code=401,
            detail=SESSAO_ENCERRADA,
            headers={"WWW-Authenticate": "Bearer"},
        )
    if _senha_trocada_depois_do_token(conta, token_data):
        # Trocar a senha derruba as sessões abertas. Sem isto, quem redefine a
        # senha por suspeitar que alguém entrou continuaria com esse alguém
        # dentro por até 24h — exatamente enquanto acredita ter resolvido.
        raise HTTPException(
            status_code=401,
            detail=SESSAO_ENCERRADA,
            headers={"WWW-Authenticate": "Bearer"},
        )
    if _sessao_encerrada_por_logout(conta, token_data):
        # "Sair" (achado #23): a rota /api/logout incrementa
        # `users.sessao_versao`; todo token emitido com a versão anterior
        # morre aqui. Antes o botão só limpava o navegador, e um token copiado
        # valia até o `exp`.
        raise HTTPException(
            status_code=401,
            detail=SESSAO_ENCERRADA,
            headers={"WWW-Authenticate": "Bearer"},
        )
    # Reconstruído a partir da linha, nunca do token: é o ponto inteiro daqui.
    # Com `.get`, e não `[...]`: papel ausente vira None, que `require_admin`
    # reprova. Indexar levantaria KeyError, e a rota responderia 500 — falha
    # aberta na cara do usuário onde cabia uma recusa silenciosa.
    return auth.TokenData(
        email=conta.get("email") or token_data.email,
        role=conta.get("role"),
        user_id=str(conta["id"]) if conta.get("id") is not None else None,
        emitido_em=token_data.emitido_em,
        deve_trocar_senha=bool(conta.get("deve_trocar_senha")),
        sessao_versao=token_data.sessao_versao,
    )


def _sessao_encerrada_por_logout(conta: dict, token_data: auth.TokenData) -> bool:
    """O token é de uma versão de sessão anterior à da conta?

    Token sem `sv` (anterior ao lote 9) vale como 0 — o DEFAULT da coluna —
    para o deploy não deslogar ninguém; ele morre no primeiro "Sair" da
    pessoa, como qualquer outro. Conta sem a coluna (migration ainda não
    rodou) não derruba nada: é o mesmo fail-open deliberado de
    `_senha_trocada_depois_do_token`, e pelo mesmo motivo.
    """
    atual = conta.get("sessao_versao")
    if atual is None:
        return False
    try:
        return int(token_data.sessao_versao or 0) != int(atual)
    except (TypeError, ValueError):
        logger.warning("sessao_versao ilegível para %s", conta.get("email"))
        return False


def _user_id_da_sessao(token: auth.TokenData) -> Optional[str]:
    """
    O UUID de quem está na requisição.

    `_sessao_do_token` já leu a linha inteira em `users` para validar a sessão, e
    o `id` veio junto. Reaproveitá-lo poupa repetir a MESMA consulta poucas
    linhas depois — foi o que pagou a leitura extra que a revogação introduziu.

    O `_resolve_user_id` continua como saída para quando não houve leitura: sem
    banco configurado, e no agente por X-API-Key. Nesses casos ele devolve o
    mesmo `None` de antes, e as rotas seguem respondendo 404 como respondiam.
    """
    return token.user_id or _resolve_user_id(token.email or "")


async def require_auth(
    request: Request,
    auth_creds: Optional[HTTPAuthorizationCredentials] = Depends(security),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
) -> auth.TokenData:
    """
    Dependência híbrida:
    1. Se houver Token JWT (Navegador), valida o usuário.
    2. Se houver X-API-Key (Agente Windows), valida a chave estática.
    """
    # 1. Tentar JWT. Assinatura válida ainda não é sessão válida: `_sessao_do_token`
    #    confere no banco se a conta segue existindo, ativa, e com qual papel.
    #    O navegador manda o JWT no cookie HttpOnly (Leva D, 09/10/2026); o
    #    cabeçalho Bearer continua aceito na transição e vale primeiro.
    credencial = auth_creds.credentials if auth_creds else None
    via_cookie = False
    if not credencial and not x_api_key:
        # Credencial explícita (Bearer, X-API-Key do agente) vale antes do
        # cookie: o cookie é o que o navegador manda sozinho.
        credencial = sessao_cookie.token_do_cookie(request)
        via_cookie = bool(credencial)
    if credencial:
        token_data = auth.decode_access_token(credencial)
        if token_data and via_cookie and not sessao_cookie.csrf_confere(request):
            # Outro site consegue fazer o navegador mandar o cookie (num
            # formulário, por exemplo), mas não consegue ler o par anti-CSRF.
            raise HTTPException(status_code=403, detail="Sessão sem a confirmação de origem. Recarregue a página.")

        # 1b. (Até 05/09/2026 havia aqui um segundo caminho: token do Supabase
        #     Auth, a "lista única de pessoas" da fase 3. O portal não roda mais
        #     no Supabase; a lista única, se voltar, será uma tabela no mesmo
        #     PostgreSQL que os dois portais leem — não um emissor externo.)

        if token_data:
            sessao = _sessao_do_token(token_data)
            # A barreira mora AQUI, e não na tela. Um modal pode ser fechado
            # pelo Esc, pelo devtools, ou simplesmente ignorado por quem chama
            # a API direto — e a senha provisória é conhecida por outra pessoa.
            if sessao.deve_trocar_senha and request.url.path not in ROTAS_COM_SENHA_PROVISORIA:
                raise HTTPException(
                    status_code=403,
                    detail=ERRO_SENHA_PROVISORIA,
                    # Cabeçalho, e não texto: o front precisa reconhecer este
                    # caso entre todos os 403 possíveis, e casar por string de
                    # mensagem quebraria ao reescrever a frase.
                    headers={"X-Senha-Provisoria": "1"},
                )
            return sessao

    # 2. Credencial do agente, no header X-API-Key que ele já manda: primeiro a
    #    credencial de MÁQUINA (própria, revogável — app/machine_credentials.py),
    #    depois a chave estática compartilhada, que é o legado em transição.
    #
    #    O TokenData sai IGUAL nos dois caminhos, de propósito: o ganho da
    #    credencial de máquina é rotação e revogação, não privilégio novo — e
    #    qualquer diferença aqui mudaria o alcance de rotas que hoje funcionam.
    if config.API_KEY:
        if x_api_key:
            # Tempo constante (achado #41): `==` em str devolve no primeiro
            # byte diferente, e a diferença de tempo é mensurável pela rede
            # para adivinhar a chave byte a byte. `/api/cron/alerts` já fazia
            # assim; aqui era a única credencial comparada com `==`.
            if hmac.compare_digest(x_api_key.encode("utf-8"), config.API_KEY.encode("utf-8")):
                if not config.ACEITAR_API_KEY_COMPARTILHADA:
                    # Janela fechada (lote 2). 401 SEM o marcador de credencial
                    # inválida: o agente não tem o que descartar — o problema é
                    # a estação não ter migrado, e o log diz isso.
                    logger.warning(
                        "X-API-Key compartilhada RECUSADA (ACEITAR_API_KEY_COMPARTILHADA "
                        "desligada). Provisione a credencial de máquina desta estação."
                    )
                    raise HTTPException(
                        status_code=401,
                        detail="A chave compartilhada não é mais aceita. Use a credencial de máquina.",
                        headers={"WWW-Authenticate": "Bearer"},
                    )
                # WARNING de propósito: é o que permite responder "já dá para
                # desligar a chave compartilhada?" olhando o log, em vez de
                # adivinhar. Some quando o ANALISESRV migrar (R2 fecha aí).
                logger.warning(
                    "Agente autenticou pela X-API-Key compartilhada (legado). "
                    "Estação ainda não migrada para credencial de máquina."
                )
                # Sem `machine_id`: a chave compartilhada não prova estação
                # nenhuma. As rotas que precisam saber DE QUEM é a fila ou o
                # token recusam esta identidade (`_machine_da_credencial`).
                return auth.TokenData(email="agent@internal", role="agent")

            marcar = True
            try:
                maquina = machine_credentials.autenticar(x_api_key)
            except (machine_credentials.SemBanco, machine_credentials.SemTabela):
                # Problema de implantação, não da credencial: sem o marcador,
                # para o agente não descartar um segredo válido por causa de
                # uma migration que falta.
                logger.warning("machine_credentials indisponível; só a X-API-Key vale.")
                maquina, marcar = None, False
            if maquina:
                # A identidade da máquina VIAJA no TokenData: é ela, e não o
                # `machine_id` declarado na requisição, que as rotas do agente
                # usam para decidir fila, custódia e cofre (lote 2, #3/#4).
                return auth.TokenData(
                    email="agent@internal", role="agent",
                    machine_id=str(maquina.get("machine_id") or "").strip().lower() or None,
                )

            # X-API-Key presente e inválida: o marcador diz ao agente que o
            # problema é a CREDENCIAL (descarte e caia na chave compartilhada),
            # não a operação. Protocolo portado do INVENT — casar string de
            # mensagem quebraria em silêncio no dia em que alguém a melhorasse.
            cabecalhos = {"WWW-Authenticate": "Bearer"}
            if marcar:
                cabecalhos[machine_credentials.CABECALHO_CREDENCIAL_INVALIDA] = "1"
            raise HTTPException(
                status_code=401,
                detail="Não autorizado. Faça login ou forneça uma chave de API válida.",
                headers=cabecalhos,
            )
    else:
        # Ambiente aberto (sem API_KEY): mantém compatibilidade para rotas /api/*
        # que usam require_auth, sem elevar privilégios administrativos.
        # ATENÇÃO: esta identidade é anônima. Rotas que manipulam material
        # criptográfico devem recusá-la — ver require_agent_or_admin.
        return auth.TokenData(email=ANONYMOUS_IDENTITY_EMAIL, role="agent")

    raise HTTPException(
        status_code=401, 
        detail="Não autorizado. Faça login ou forneça uma chave de API válida.",
        headers={"WWW-Authenticate": "Bearer"},
    )

# Definidos em `auth` porque o login e o envio de alertas precisam da mesma
# regra; duas cópias divergiriam, e a divergência permissiva não daria sintoma.
PAPEIS_VALIDOS = auth.PAPEIS_VALIDOS
# O que se escolhe à mão no cadastro e na planilha. Gestor deriva da
# liderança de departamento (ADR 0001) e não entra aqui.
PAPEIS_IMPORTAVEIS = tuple(p for p in PAPEIS_VALIDOS if p != "gestor")
conta_ativa = auth.conta_ativa


async def require_admin(token: auth.TokenData = Depends(require_auth)) -> auth.TokenData:
    if token.role != "admin":
        raise HTTPException(status_code=403, detail="Acesso restrito a administradores.")
    return token


ERRO_ACESSO_MAQUINA = "Acesso restrito ao agente e a administradores."


def require_modulo(
    modulo: str,
    minimo: str = permissoes.NIVEL_LER,
    *,
    permitir_agente: bool = False,
    recusar_anonimo: bool = False,
):
    """
    Guarda por MODULO, lida da matriz de permissoes (`app/permissoes.py`).

    Substitui `require_admin` onde a alcada deixa de ser "so admin" e passa a
    ser configuravel pela tela. O nome do modulo e conferido AQUI, na
    importacao: um erro de digitacao vira erro de partida do servidor, e nao um
    403 silencioso em producao para um modulo que ninguem mexeu.

    `permitir_agente=True` para rota de mao dupla: usada por gente E por maquina.
    `GET /api/settings` e o caso — pertence ao modulo `configuracao`, e a tela de
    Configuracao a consome, mas `agent/run_agent.py` tambem, para saber quais
    pastas monitorar (e `scripts/diagnostico.py` idem).

    Sem essa valvula so haveria escolha ruim: deixar a rota fora da matriz, e ai
    "Nao entra" mentiria (a pessoa continuaria lendo a configuracao), ou liga-la
    sem ressalva e parar o agente em producao. Com ela, o modulo governa a GENTE
    e a maquina segue pelo caminho dela.

    `recusar_anonimo=True` fecha a porta de compatibilidade para rotas que
    entregam material sensivel. `GET /api/cert-installer/vault-optin` diz quais
    certificados estao no cofre, e estava em `require_agent_or_admin` justamente
    porque aquela guarda recusa `anonymous@local` — a identidade que aparece
    quando nao ha API_KEY configurada. Governar o modulo sem esta opcao teria
    AFROUXADO a rota, trocando uma protecao deliberada por uma configuravel.

    Rota EXCLUSIVA de maquina continua com `require_agent_or_admin`.
    """
    if modulo not in permissoes.MODULOS:
        raise ValueError(f"modulo desconhecido em require_modulo: {modulo!r}")
    if minimo not in permissoes.NIVEIS:
        raise ValueError(f"nivel desconhecido em require_modulo: {minimo!r}")

    async def _guarda(token: auth.TokenData = Depends(require_auth)) -> auth.TokenData:
        # Ambiente sem API_KEY: `require_auth` devolve a identidade ANONIMA com
        # papel 'agent' e o portal inteiro fica aberto — compatibilidade
        # documentada no proprio `require_auth`. Esta guarda nao pode ser MAIS
        # estrita que ela nesse modo, senao o portal para de funcionar em dev e
        # em qualquer instalacao que ainda nao configurou a chave.
        #
        # A distincao e por e-mail e nao por papel: o agente DE VERDADE chega
        # como `agent@internal` e continua barrado aqui, porque nao tem o que
        # fazer num modulo de gente. `require_agent_or_admin` faz a mesma
        # separacao, pelo mesmo motivo.
        if token.email == ANONYMOUS_IDENTITY_EMAIL:
            if recusar_anonimo:
                raise HTTPException(status_code=403, detail=ERRO_ACESSO_MAQUINA)
            return token

        # Rota de mao dupla: a maquina passa pelo caminho dela. Papel 'agent' so
        # existe via X-API-Key valida, entao isto nao afrouxa nada para humanos.
        if permitir_agente and (token.role or "") == "agent":
            return token

        try:
            if permissoes.pode(token.role or "", modulo, minimo):
                return token
        except permissoes.PermissoesIndisponiveis:
            # 503, e nao 403: "nao consegui verificar" nao e "voce nao pode".
            # Mesmo criterio de `require_admin_ou_gestor` e `_exigir_alcance`.
            raise HTTPException(
                status_code=503,
                detail="Não foi possível verificar suas permissões. Tente de novo.",
            )
        raise HTTPException(
            status_code=403,
            detail=f"Seu perfil não tem acesso {permissoes.ROTULO_MODULO.get(modulo, 'a ' + modulo)}.",
        )

    return _guarda


ERRO_MAQUINA_SEM_IDENTIDADE = (
    "Esta operação exige a credencial de máquina da própria estação. "
    "A chave compartilhada não identifica a estação; provisione a credencial."
)
ERRO_MAQUINA_DIVERGENTE = "machine_id não confere com a credencial desta estação."


def _machine_da_credencial(
    token: auth.TokenData,
    declarado: Optional[str],
    *,
    exigir_identidade: bool = False,
) -> str:
    """A máquina que a credencial PROVA ser — e só ela (achados #3 e #4).

    Admin pode declarar qualquer máquina: é diagnóstico. Credencial de máquina
    só fala por si: declarar outra é 403, e declarar nada vale a própria.

    A X-API-Key compartilhada não tem identidade. Com `exigir_identidade`
    (fila, resgate de token) ela é recusada sempre — não há como saber de quem
    é a fila. Sem ele (inventário, cofre) ela ainda passa com o `machine_id`
    declarado, avisando no log: é a janela para as estações não migradas, e
    `ACEITAR_API_KEY_COMPARTILHADA` desligada a fecha antes de chegar aqui.
    """
    pedido = (declarado or "").strip()
    if (token.role or "").strip().lower() == "admin":
        return pedido
    propria = (token.machine_id or "").strip().lower()
    if not propria:
        if exigir_identidade or token.email == ANONYMOUS_IDENTITY_EMAIL:
            # Com aviso (29/09/2026): a recusa silenciosa deixava o operador
            # sem pista — só a diferença 401 × 403 nas sondas apontava aqui.
            logger.warning(
                "Recusado (403): a credencial não identifica a estação e a operação exige "
                "identidade; machine_id declarado %r.", pedido,
            )
            raise HTTPException(status_code=403, detail=ERRO_MAQUINA_SEM_IDENTIDADE)
        logger.warning(
            "Chave compartilhada agindo como a máquina declarada %r (janela de "
            "compatibilidade). Provisione a credencial de máquina desta estação.",
            pedido,
        )
        return pedido
    if pedido and pedido.lower() != propria:
        # No ANALISESRV a credencial fora provisionada com o nome do arquivo de
        # exemplo e o agente declarava outro: o inventário parou em 403 e nada
        # no log dizia por quê. Agora diz — com os dois nomes, que é o que se
        # precisa para corrigir (ajustar o agent_config.json ou a credencial).
        logger.warning(
            "Recusado (403): machine_id divergente — a credencial é da estação %r, "
            "o agente declarou %r. Ajuste o machine_id do agent_config.json ou "
            "reemita a credencial com o nome certo.", propria, pedido,
        )
        raise HTTPException(status_code=403, detail=ERRO_MAQUINA_DIVERGENTE)
    return pedido or propria


async def require_agent_or_admin(token: auth.TokenData = Depends(require_auth)) -> auth.TokenData:
    """
    Endpoints da máquina: alimentados pelo agente (X-API-Key -> role 'agent') e
    acessíveis a administradores para diagnóstico.

    Existe porque `require_auth` sozinho é permissivo demais para estas rotas.

    1. Aceita qualquer usuário do portal, inclusive role 'user'. Em /upload-pfx
       isso permitia a um usuário comum enviar um PFX próprio reaproveitando o
       fingerprint de um certificado já armazenado: como `upsert_pfx` usa
       `on_conflict="fingerprint"`, o registro legítimo seria sobrescrito e o
       certificado do atacante acabaria instalado num servidor pelo fluxo
       normal de instalação. `require_admin` não serve como alternativa: o
       agente tem role 'agent', não 'admin'.

    2. Quando API_KEY não está configurada, `require_auth` devolve uma
       identidade ANÔNIMA com role 'agent' para manter compatibilidade. Para as
       rotas antigas isso é aceitável; para estas, que entregam PFX e senhas,
       significaria acesso sem credencial nenhuma. Aqui a identidade anônima é
       recusada explicitamente.
    """
    if token.role not in ("agent", "admin") or token.email == ANONYMOUS_IDENTITY_EMAIL:
        raise HTTPException(status_code=403, detail=ERRO_ACESSO_MAQUINA)
    return token


async def require_admin_ou_agente_leitura(token: auth.TokenData = Depends(require_auth)) -> auth.TokenData:
    """`GET /api/settings`: o agente lê as pastas que deve varrer (inclusive a
    identidade anônima do modo sem API_KEY, para o robô continuar funcionando
    em desenvolvimento); a escrita e o resto da Configuração são só do
    administrador (decisão L1, 01/10/2026)."""
    if (token.role or "").strip().lower() in ("agent", "admin"):
        return token
    raise HTTPException(status_code=403, detail="Acesso restrito a administradores.")


def _parse_iso_utc(iso_value: Optional[str]) -> datetime:
    if not iso_value:
        return datetime.min.replace(tzinfo=timezone.utc)
    s = str(iso_value).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)



def _resolve_user_id(email: str) -> Optional[str]:
    """Busca o UUID do usuário pelo email."""
    from app.settings_state import _banco
    sb = _banco()
    if not sb:
        return None
    try:
        r = sb.table("users").select("id").eq("email", email).limit(1).execute()
        if r.data:
            return str(r.data[0]["id"])
    except Exception:
        logger.exception("Erro ao resolver user_id para email=%s", email)
    return None


def _sb_do_login():
    from app.settings_state import _banco
    sb = _banco()
    if not sb:
        raise HTTPException(status_code=503, detail="Sistema sem banco configurado para login.")
    return sb


def _erro_sem_banco(e: agent_devices.SemBanco) -> HTTPException:
    return HTTPException(status_code=503, detail=str(e))
