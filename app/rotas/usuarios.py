"""Usuários, login/logout, senha e LGPD — Frente 3, leva 6 (10/10/2026).

Saiu de `app/main.py` sem mudar comportamento: entrar e sair, o cadastro de
contas (criar, editar, importar CSV, desativar, reativar, código e senha
provisória pelo administrador), a recuperação de senha por código, a troca da
própria senha e as duas rotas LGPD sobre a própria conta.
"""

from __future__ import annotations

import csv
import html
import io
import logging
import os
import re
import secrets
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel, Field

from app import atividade, auth, cert_installer, computadores, correio, nomes, papeis, permissoes, senha_reset, sessao_cookie, taxa
from app.alcance import _papel_da_conta
from app.comum import ERRO_INTERNO_VEJA_LOG, ERRO_LINHAS_DEMAIS, MAX_LINHAS_IMPORT, _ler_upload_limitado, _norm_header
from app.rotas.departamentos import _nome_de_departamento
from app.sessao import (
    PAPEIS_IMPORTAVEIS,
    PAPEIS_VALIDOS,
    SESSAO_ENCERRADA,
    _ip_do_cliente,
    _limitar,
    _sb_do_login,
    _user_id_da_sessao,
    conta_ativa,
    require_admin,
    require_auth,
)
from app.settings_state import load_settings

logger = logging.getLogger("app.main")
router = APIRouter()


class LoginBody(BaseModel):
    email: str = Field(max_length=320)
    # Teto de DoS, não política de senha (essa é o #25): o bcrypt custa o
    # mesmo para 20 ou 20.000 bytes, mas o corpo não precisa chegar a 20.000.
    password: str = Field(max_length=1024)




def _conferir_credenciais(email: str, senha: str, ip: Optional[str]) -> dict:
    """
    E-mail + senha viram a linha de `users`, ou levantam o HTTP certo.

    Extraído de `login` em 22/08/2026, quando o agente ganhou tela de login:
    passaram a existir dois caminhos que autenticam com senha. O módulo `auth`
    já explica por que uma regra de acesso duplicada é perigosa — a cópia que
    divergisse para o lado permissivo não daria sintoma nenhum. Aqui isso
    significaria conta desativada continuar registrando dispositivo depois de
    já ter perdido o portal.

    Normalizado ANTES da consulta. A coluna guarda tudo em minúsculas (o portal
    grava assim, e o índice único é sobre `lower(email)`), mas a consulta usava
    o valor cru do formulário: quem digitasse "Ana@X.com" não casava com linha
    nenhuma e levava 401 "E-mail ou senha incorretos" — mensagem que manda a
    pessoa caçar a senha por causa de uma maiúscula.

    O `trim` está aqui pelo mesmo motivo: colar o e-mail de um e-mail costuma
    trazer espaço junto.
    """
    email_login = (email or "").strip().lower()
    r = _sb_do_login().table("users").select("*").eq("email", email_login).limit(1).execute()
    user = r.data[0] if r.data else None

    # Sempre paga o bcrypt, exista a conta ou não (achado #26). O `or` que
    # pulava a conferência quando `user` era None respondia em ~0 ms para
    # e-mail inexistente e em ~250 ms para e-mail existente: a mensagem era
    # idêntica, o tempo não — e isso enumerava contas com precisão.
    hash_alvo = user["password_hash"] if user else _hash_falso()
    senha_ok = auth.verify_password(senha, hash_alvo)

    if not user or not senha_ok:
        # Só registra quando a conta EXISTE: e-mail inexistente viraria guardar
        # entrada arbitrária de quem chamou. Com conta existente, o registro
        # responde "alguém está tentando entrar aqui", que é o caso que importa.
        if user:
            atividade.registrar(
                atividade.EVENTO_LOGIN_NEGADO,
                user_id=str(user.get("id") or "") or None,
                user_email=email_login,
                client_ip=ip,
                contexto={"motivo": "senha_incorreta"},
            )
        raise HTTPException(status_code=401, detail=CREDENCIAL_INVALIDA)

    if not conta_ativa(user):
        atividade.registrar(
            atividade.EVENTO_LOGIN_NEGADO,
            user_id=str(user.get("id") or "") or None,
            user_email=email_login,
            client_ip=ip,
            contexto={"motivo": "conta_desativada"},
        )
        # Mesmo 401 da senha errada (achado #27). O 403 "Usuário desativado"
        # só chegava depois de a senha conferir — e confirmava a quem tinha a
        # credencial vazada que a conta existe e em que estado ficou. O motivo
        # fica no registro de atividade, onde o administrador o lê.
        raise HTTPException(status_code=401, detail=CREDENCIAL_INVALIDA)

    return user


CREDENCIAL_INVALIDA = "E-mail ou senha incorretos."

_HASH_FALSO: Optional[str] = None


def _hash_falso() -> str:
    """Um hash bcrypt de custo real para conferir quando a conta não existe.

    Gerado uma vez, sob demanda: custa os mesmos ~250 ms de um hash de
    verdade, e é isso que iguala o tempo dos dois caminhos do login.
    """
    global _HASH_FALSO
    if _HASH_FALSO is None:
        _HASH_FALSO = auth.get_password_hash(secrets.token_urlsafe(32))
    return _HASH_FALSO


@router.post("/api/login")
def login(body: LoginBody, request: Request, response: Response) -> dict:
    # Teto por IP ANTES de qualquer ida ao banco (junto do item 13 da Frente
    # 2; achado do levantamento de superfície anônima de 01/09/2026): o /claim
    # sempre teve teto e o login não — e login é o alvo clássico de spray de
    # senhas. Vinte por minuto não atrapalha um escritório inteiro atrás de um
    # NAT; adivinhação vira exercício inútil. A janela é a durável de
    # `app/taxa.py`, a mesma do claim — em memória de instância, na Vercel, o
    # teto seria sugestão.
    if not taxa.permitir(f"login:{_ip_do_cliente(request)}", 20, 60):
        raise HTTPException(status_code=429, detail="Muitas tentativas. Aguarde um minuto.")

    load_settings()  # trigger client init
    _sb_do_login()

    ip = request.client.host if request and request.client else None
    try:
        # Login local: `users` + bcrypt + JWT deste portal. (Até 05/09/2026 o
        # Supabase Auth era tentado primeiro, como "lista única de pessoas" da
        # fase 3; o portal não roda mais no Supabase e esse caminho saiu.)
        user = _conferir_credenciais(body.email, body.password, ip)
        atividade.registrar(
            atividade.EVENTO_LOGIN,
            user_id=str(user.get("id") or "") or None,
            user_email=user["email"],
            client_ip=ip,
        )
        token = auth.create_access_token({
            "sub": user["email"],
            "role": user["role"],
            # Versão da sessão em vigor (#23): `/api/logout` a incrementa e
            # este token deixa de valer. Coluna ausente (migration pendente) → 0.
            "sv": int(user.get("sessao_versao") or 0),
        })
        # Leva D: a sessão do navegador vai SÓ no cookie HttpOnly. O token não
        # volta no corpo desde 09/10/2026 (fim da transição): no corpo, um
        # script da página o leria. O cabeçalho Bearer continua aceito para
        # quem tem um token por outro meio (testes, credencial de dispositivo).
        sessao_cookie.gravar(response, request, token)
        return {"token_type": "cookie", "role": user["role"]}
    except HTTPException:
        # O `except Exception` abaixo engolia estas: uma senha errada saía como
        # 500 com "401: E-mail ou senha incorretos." no corpo — mensagem certa,
        # status errado, e todo tratamento no front que olhasse o código via
        # "erro do servidor" onde houve credencial inválida.
        raise
    except Exception:
        logger.exception("Erro no login")
        raise HTTPException(status_code=500, detail="Não foi possível concluir o login. Tente de novo.")


@router.post("/api/logout")
def logout(request: Request, response: Response, token: auth.TokenData = Depends(require_auth)) -> dict:
    """
    Sair de verdade (achado #23): incrementa `users.sessao_versao`, e todo
    token desta conta emitido com a versão anterior passa a ser recusado por
    `_sessao_do_token`. Até o lote 9 "Sair" só limpava o `localStorage`, e um
    JWT copiado valia até o `exp`.

    É a sessão inteira da conta, não só este token: sem um `jti` por token
    (que exigiria tabela de revogados) é o que dá para revogar com uma coluna
    — e é o que a pessoa espera de "sair em todos os dispositivos".
    """
    from app.settings_state import _banco

    sessao_cookie.apagar(response, request)
    sb = _banco()
    uid = _user_id_da_sessao(token)
    if not sb or not uid:
        # Sem banco não há sessão a encerrar (dev sem diretório de usuários).
        return {"ok": True, "revogado": False}
    try:
        r = sb.table("users").select("sessao_versao").eq("id", uid).limit(1).execute()
        linhas = r.data or []
        if not linhas or "sessao_versao" not in linhas[0]:
            logger.warning("Logout sem revogação: users.sessao_versao ausente (rode a migration 20260926110000).")
            return {"ok": True, "revogado": False}
        nova = int(linhas[0].get("sessao_versao") or 0) + 1
        sb.table("users").update({"sessao_versao": nova}).eq("id", uid).execute()
    except Exception:  # noqa: BLE001
        logger.exception("Falha ao encerrar a sessão no servidor")
        raise HTTPException(status_code=503, detail="Não foi possível encerrar a sessão agora.")
    # Sem evento em `user_activity`: a tabela tem CHECK fechado sobre os
    # eventos e "logout" exigiria migration — fora do escopo do lote 9
    # (anotado como achado novo). Fica no log do servidor.
    logger.info("Sessão encerrada por logout: %s (v%d)", token.email, nova)
    return {"ok": True, "revogado": True}


# Modulo `usuarios` na matriz de permissoes desde 20/08. Leitura e escrita
# separadas de proposito: e o que torna "so visualizar" configuravel depois. As
# 13 rotas eram `require_admin`, e a matriz da `nenhum` a gestor e user — entao
# o comportamento nao muda hoje.
#
# `/api/users/me/export` e `/api/users/me/delete` NAO entram: sao LGPD sobre a
# propria conta, e amarra-las a permissao do modulo Usuarios tiraria de um
# operador o direito de exportar os proprios dados.
@router.get("/api/users", dependencies=[Depends(require_admin)])
def list_users() -> List[dict]:
    from app.settings_state import _banco
    sb = _banco()
    if not sb: return []
    r = sb.table("users").select(
        "id, email, full_name, role, ativo, departamento_id, created_at"
    ).execute()
    usuarios = list(r.data or [])
    # Contagem da carteira por pessoa, numa consulta só: a coluna "Carteira"
    # liga esta tela ao cartão "Acesso" do Dashboard e à tela Carteiras.
    quantos: Dict[str, int] = {}
    try:
        for c in sb.table("carteira").select("user_id").execute().data or []:
            k = str(c.get("user_id"))
            quantos[k] = quantos.get(k, 0) + 1
    except Exception:  # noqa: BLE001 — sem a contagem a lista continua servindo
        logger.exception("Falha ao contar carteiras para a lista de usuários")
    from app import texto as _texto
    for u in usuarios:
        n = quantos.get(str(u.get("id")), 0)
        # Só na exibição: "irla" → "Irla", caixa alta → título.
        u["nome_exibicao"] = nomes.nome_pessoa(u.get("full_name")) or str(u.get("email") or "")
        u["carteira"] = n
        u["textos"] = {"carteira": _texto.plural(n, "cliente")}
    return usuarios


class UserCreateBody(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=1024)
    full_name: str = Field(max_length=200)
    role: str = Field(default="user", max_length=16)
    departamento_id: Optional[str] = None


class UserUpdateBody(BaseModel):
    email: str
    full_name: str
    role: str = "user"
    # Omitir mantém o que está gravado. `role: "disabled"` continua aceito como
    # forma antiga de desativar (ver `update_user`), mas não escreve mais em
    # `role` — o papel deixou de ser o lugar onde o estado mora.
    ativo: Optional[bool] = None
    # `gestor_id` ("Gestor responsável") saiu em 01/10/2026: era informativo,
    # não autorizava nada e divergia do que Departamentos diz. A coluna fica no
    # banco até uma migration futura.
    # Omitir mantém o departamento gravado; vazio é recusado (obrigatório).
    departamento_id: Optional[str] = None


class UserResetPasswordBody(BaseModel):
    password: str


@router.post("/api/users/import", dependencies=[Depends(require_admin)])
async def import_users(request: Request, file: UploadFile = File(...), ator: auth.TokenData = Depends(require_auth)) -> dict:
    from app.settings_state import _banco

    sb = _banco()
    if not sb:
        raise HTTPException(status_code=503, detail="Sistema sem banco configurado.")

    name = (file.filename or "").lower()
    if not name.endswith(".csv"):
        raise HTTPException(
            status_code=422,
            detail="Formato inválido. Exporte a planilha como CSV e envie um arquivo .csv.",
        )

    raw = await _ler_upload_limitado(request, file)
    if not raw:
        raise HTTPException(status_code=422, detail="Arquivo vazio.")

    # [OWASP A08] Validação de Magic Bytes (Assinatura real do arquivo)
    # Rejeita ativamente se for um binário executável ou arquivo restrito disfarçado de CSV
    if raw.startswith(b'MZ') or raw.startswith(b'\x7fELF') or raw.startswith(b'%PDF') or raw.startswith(b'PK'):
        raise HTTPException(status_code=422, detail="Conteúdo do arquivo suspeito. Apenas texto puro (CSV) é permitido.")

    text = raw.decode("utf-8-sig", errors="replace")
    sniffer = csv.Sniffer()
    try:
        dialect = sniffer.sniff(text[:2048], delimiters=",;")
        delim = dialect.delimiter
    except csv.Error:
        delim = ";"

    reader = csv.DictReader(io.StringIO(text), delimiter=delim)
    if not reader.fieldnames:
        raise HTTPException(status_code=422, detail="CSV sem cabeçalho.")

    map_headers = {_norm_header(h): h for h in reader.fieldnames}

    def pick(*aliases: str) -> Optional[str]:
        for a in aliases:
            key = map_headers.get(_norm_header(a))
            if key:
                return key
        return None

    h_nome = pick("nome", "full_name", "nome completo")
    h_email = pick("email", "e-mail")
    h_senha = pick("senha", "password")
    h_role = pick("role", "nivel", "papel", "perfil")
    h_dep = pick("departamento", "setor", "depto")
    if not h_nome or not h_email or not h_senha:
        raise HTTPException(
            status_code=422,
            detail="Cabeçalho obrigatório: nome, email, senha.",
        )
    if not h_role:
        raise HTTPException(
            status_code=422,
            detail="Cabeçalho obrigatório também para nível: use 'nivel' ou 'role' com valores 'admin' ou 'user'.",
        )
    if not h_dep:
        # Departamento é obrigatório no cadastro (ADR 0001): sem ele a pessoa
        # não tem Gestor que lhe libere nada. A planilha segue a mesma regra do
        # formulário, pelo nome do departamento — é o que a operação conhece.
        raise HTTPException(
            status_code=422,
            detail="Cabeçalho obrigatório também para departamento: coluna 'departamento' com o nome do departamento.",
        )

    criados = 0
    ignorados = 0
    erros: List[dict[str, Any]] = []
    # Quem importa 40 linhas e le "3 ignoradas" abre a planilha para adivinhar
    # quais. Cada ignorada diz a linha e o motivo (decisao de 01/10/2026).
    ignoradas: List[dict[str, Any]] = []

    # Teto de linhas ANTES de qualquer bcrypt (achado #11), e os e-mails que
    # já existem numa consulta só — era uma ida ao banco por linha.
    import itertools

    linhas_csv = list(itertools.islice(reader, MAX_LINHAS_IMPORT + 1))
    if len(linhas_csv) > MAX_LINHAS_IMPORT:
        raise HTTPException(status_code=413, detail=ERRO_LINHAS_DEMAIS)
    try:
        ja_existem = {
            str(u.get("email") or "").strip().lower()
            for u in (sb.table("users").select("email").execute().data or [])
        }
        departamentos_por_nome = {
            _nome_de_departamento(d.get("nome")).lower(): str(d.get("id"))
            for d in (sb.table("departamento").select("id, nome").execute().data or [])
            if d.get("nome")
        }
    except Exception:  # noqa: BLE001
        logger.exception("Falha ao ler os e-mails existentes para a importação")
        raise HTTPException(status_code=503, detail="Não foi possível ler as contas existentes. Tente de novo.")

    linha = 1
    for row in linhas_csv:
        linha += 1
        nome = str(row.get(h_nome) or "").strip()
        email = str(row.get(h_email) or "").strip().lower()
        senha = str(row.get(h_senha) or "").strip()
        role = str(row.get(h_role) or "").strip().lower()
        dep_nome = str(row.get(h_dep) or "").strip()

        if not nome or not email or not senha or not role:
            ignorados += 1
            faltam = [c for c, v in (("nome", nome), ("email", email), ("senha", senha), ("nivel", role)) if not v]
            ignoradas.append({"linha": linha, "email": email, "motivo": "Campo vazio: " + ", ".join(faltam) + "."})
            continue
        if role == papeis.GESTOR:
            erros.append({"linha": linha, "email": email, "erro": papeis.PAPEL_GESTOR_E_DERIVADO})
            continue
        if role not in PAPEIS_IMPORTAVEIS:
            erros.append(
                {
                    "linha": linha,
                    "email": email,
                    "erro": f"Nível inválido. Use exatamente: {', '.join(PAPEIS_IMPORTAVEIS)}.",
                }
            )
            continue
        departamento_id = departamentos_por_nome.get(dep_nome.lower())
        if not departamento_id:
            erros.append({"linha": linha, "email": email,
                          "erro": f"Departamento {dep_nome or '(vazio)'} não existe. Cadastre-o em Departamentos antes."})
            continue
        motivo_senha = auth.validar_senha(senha, email)
        if motivo_senha:
            erros.append({"linha": linha, "email": email, "erro": motivo_senha})
            continue
        # A mesma barreira de `create_user`: a planilha não é um caminho
        # paralelo para nascer administrador.
        try:
            _exigir_alcance_de_papel(ator, role)
        except HTTPException as e:
            erros.append({"linha": linha, "email": email, "erro": str(e.detail)})
            continue
        # O CSV era o caminho que escapava de tudo: nem o formulário HTML o
        # cobre, nem a API validava.
        if not _EMAIL_PLAUSIVEL.match(email):
            erros.append({"linha": linha, "email": email, "erro": "E-mail inválido."})
            continue
        try:
            if email in ja_existem:
                ignorados += 1
                ignoradas.append({"linha": linha, "email": email, "motivo": "Já existe uma conta com esse e-mail."})
                continue
            ja_existem.add(email)
            sb.table("users").insert(
                {
                    "email": email,
                    "password_hash": auth.get_password_hash(senha),
                    "full_name": str(nome or "").strip().upper(),
                    "role": role,
                    "departamento_id": departamento_id,
                    # As mesmas duas colunas que `create_user` grava (achado
                    # #10). A senha do CSV esteve numa planilha que circulou
                    # por e-mail: serve para o primeiro acesso e nada mais.
                    # Sem isto a coluna caía no DEFAULT false e a conta
                    # nascia com uma senha conhecida por terceiros, válida
                    # para sempre.
                    "deve_trocar_senha": True,
                    "ativo": True,
                }
            ).execute()
            criados += 1
        except Exception:  # noqa: BLE001
            # O texto do banco não vai para a planilha de resposta (achado
            # #35): traz nome de tabela, constraint e às vezes o valor.
            logger.exception("Falha ao importar a linha %d", linha)
            erros.append({"linha": linha, "email": email,
                          "erro": "Não foi possível gravar esta linha. Veja o log do servidor."})

    return {"ok": True, "criados": criados, "ignorados": ignorados, "ignoradas": ignoradas, "erros": erros}


# Validação deliberadamente frouxa: exige um "@" com algo dos dois lados e um
# ponto no domínio, e nada além disso. Regex de e-mail "completo" rejeita
# endereços válidos e dá falsa sensação de rigor — o que prova que um e-mail
# funciona é uma mensagem chegar nele.
_EMAIL_PLAUSIVEL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")

# A política de senha mora em `auth.validar_senha` (lote 9, achado #25): um
# mínimo só, teto de 72 bytes (o bcrypt trunca em silêncio), lista curta de
# senhas comuns e nada de e-mail dentro da senha. Antes eram cinco cópias do
# número 6. O nome fica para quem ainda o lê.
SENHA_MINIMA = auth.SENHA_MINIMA


def _exigir_senha_valida(senha: str, email: Optional[str] = None) -> None:
    """422 com o motivo, para as quatro rotas que recebem senha nova."""
    motivo = auth.validar_senha(senha, email)
    if motivo:
        raise HTTPException(status_code=422, detail=motivo)

SO_ADMIN_CONCEDE_ADMIN = "Só um administrador pode conceder o papel de administrador."
SO_ADMIN_MEXE_EM_ADMIN = "Só um administrador pode alterar a conta de outro administrador."


def _e_admin(ator: auth.TokenData) -> bool:
    return (ator.role or "").strip().lower() in permissoes.PAPEIS_TOTAIS


def _exigir_alcance_de_papel(ator: auth.TokenData, papel_alvo: Optional[str]) -> None:
    """Só admin concede o papel de admin (achado #9).

    Sem isto, `usuarios:editar` é indistinguível de admin: quem edita contas
    cria um administrador novo, ou promove a si mesmo. A matriz de permissões
    oferece esse nível a gestor como se fosse um degrau intermediário — e não
    era. A barreira fica aqui, num lugar só, chamada por criar, editar e
    importar.
    """
    if (papel_alvo or "").strip().lower() not in permissoes.PAPEIS_TOTAIS:
        return
    if not _e_admin(ator):
        raise HTTPException(status_code=403, detail=SO_ADMIN_CONCEDE_ADMIN)


def _exigir_alcance_sobre_conta(sb, ator: auth.TokenData, user_id: str) -> None:
    """Conta de administrador só é alterada por administrador (achado #9).

    Redefinir a senha do admin era o caminho óbvio; trocar o e-mail dele e
    pedir um código de redefinição para o endereço novo era o menos óbvio e
    dava no mesmo. Desativar, reativar e apagar entram pela mesma razão: cada
    um é uma forma de decidir quem administra o portal. Falha fechada — se não
    dá para ler o papel do alvo, não dá para provar que ele não é admin.
    """
    if _e_admin(ator):
        return
    try:
        r = sb.table("users").select("id, role").eq("id", user_id).limit(1).execute()
    except Exception:  # noqa: BLE001
        logger.exception("Falha ao ler o papel da conta alvo")
        raise HTTPException(
            status_code=503,
            detail="Não foi possível verificar a conta. Tente de novo.",
        )
    alvo = (r.data or [None])[0]
    if alvo and (alvo.get("role") or "").strip().lower() in permissoes.PAPEIS_TOTAIS:
        raise HTTPException(status_code=403, detail=SO_ADMIN_MEXE_EM_ADMIN)


def _validar_email(email: str) -> str:
    limpo = (email or "").strip().lower()
    if not _EMAIL_PLAUSIVEL.match(limpo):
        raise HTTPException(status_code=422, detail=f"E-mail inválido: {email!r}")
    return limpo


def _garantir_email_livre(sb: Any, email: str, ignorar_id: Optional[str] = None) -> None:
    """
    Recusa e-mail já usado por outra conta.

    O índice único no banco é quem fecha de verdade — esta checagem tem janela
    de corrida e existe para a mensagem ser legível em vez de um 400 cru do
    PostgREST. As duas camadas servem a coisas diferentes.
    """
    try:
        existentes = sb.table("users").select("id, email").execute().data or []
    except Exception:
        logger.exception("Falha ao verificar e-mail duplicado")
        raise HTTPException(
            status_code=503, detail="Não foi possível verificar o e-mail agora."
        )
    for u in existentes:
        if str(u.get("email") or "").strip().lower() == email and str(u.get("id")) != str(ignorar_id):
            # Sem ecoar o endereço (achado #52): quem chamou já o tem, e a
            # resposta não precisa carregá-lo de volta para logs e telas.
            raise HTTPException(
                status_code=409,
                detail=(
                    "Já existe uma conta com esse e-mail. O e-mail identifica "
                    "a pessoa no login — duas contas com o mesmo endereço deixam "
                    "uma delas inacessível."
                ),
            )


@router.post("/api/users", dependencies=[Depends(require_admin)])
def create_user(body: UserCreateBody, ator: auth.TokenData = Depends(require_auth)) -> dict:
    from app.settings_state import _banco
    sb = _banco()
    if not sb: raise HTTPException(status_code=503)

    # A validação não existia aqui: qualquer string virava papel. Com o CHECK
    # no banco isso passaria a estourar como 400 genérico do PostgREST, sem
    # dizer qual valor era aceito.
    role = (body.role or "user").strip().lower()
    if role not in PAPEIS_VALIDOS:
        raise HTTPException(
            status_code=422,
            detail=f"Nível inválido. Use: {', '.join(PAPEIS_VALIDOS)}.",
        )
    # Gestor deriva da liderança (ADR 0001): ninguém nasce Gestor pelo
    # cadastro; nasce Operador e é designado em Departamentos.
    if role == papeis.GESTOR:
        raise HTTPException(status_code=422, detail=papeis.PAPEL_GESTOR_E_DERIVADO)
    _exigir_alcance_de_papel(ator, role)

    email = _validar_email(body.email)
    _exigir_senha_valida(body.password, email)
    _garantir_email_livre(sb, email)
    departamento_id = _exigir_departamento(sb, body.departamento_id)

    hash_pw = auth.get_password_hash(body.password)
    try:
        r = sb.table("users").insert({
            # Quem cadastrou sabe a senha que digitou. Ela serve para o primeiro
            # acesso e nada mais — `require_auth` recusa o resto do portal até a
            # pessoa escolher uma própria.
            "deve_trocar_senha": True,
            "departamento_id": departamento_id,
            "email": email,
            "password_hash": hash_pw,
            # Máscara de nome (30/09/2026): gravado em maiúsculas, como a tela mostra.
            "full_name": (body.full_name or "").strip().upper(),
            "role": role,
            "ativo": True,
        }).execute()
    except Exception:
        logger.exception("Falha ao criar usuário")
        raise HTTPException(status_code=400, detail="Não foi possível criar o usuário.")
    return {"ok": True}


def _exigir_departamento(sb: Any, departamento_id: Optional[str]) -> str:
    """Departamento é obrigatório e tem de existir (ADR 0001).

    Sem departamento a pessoa não tem Gestor que lhe libere nada — só o
    Administrador. A FK já recusaria um id inexistente, mas como 400 genérico
    do PostgREST; aqui vira 422 com o motivo.
    """
    did = (departamento_id or "").strip()
    if not did:
        raise HTTPException(status_code=422, detail=papeis.DEPARTAMENTO_OBRIGATORIO)
    try:
        achado = sb.table("departamento").select("id").eq("id", did).limit(1).execute().data or []
    except Exception:  # noqa: BLE001
        logger.exception("Falha ao conferir o departamento %s", did)
        raise HTTPException(status_code=503, detail="Não foi possível conferir o departamento. Tente de novo.")
    if not achado:
        raise HTTPException(status_code=422, detail="Esse departamento não existe mais. Recarregue a tela e escolha outro.")
    return did


def _garantir_que_sobra_admin(
    sb: Any,
    user_id: str,
    *,
    novo_role: Optional[str] = None,
    novo_ativo: Optional[bool] = None,
    apagar: bool = False,
) -> None:
    """
    Recusa a operação se ela deixaria o portal **sem nenhum administrador ativo**.

    A regra é "tem de sobrar um", e não "não mexa em si mesmo". A segunda
    formulação parece equivalente e não é: com dois admins, um poderia
    rebaixar o outro e depois sair, e nenhuma das duas ações seria sobre si
    mesmo. E com um admin só — que é o caso do portal hoje — a versão correta
    também bloqueia desativar, rebaixar e apagar, que são três caminhos para o
    mesmo buraco.

    O buraco é sem fundo: a tela de Usuários é `require_admin`, então sem admin
    ativo **não há como voltar pela interface**. Só SQL direto no banco.

    Simula a mudança e conta o que restaria — assim as três rotas usam a mesma
    regra e não há como uma delas divergir.
    """
    try:
        us = sb.table("users").select("id, role, ativo").execute().data or []
    except Exception:
        # Não dá para afirmar que sobra admin. Recusar é o lado seguro: o custo
        # é uma operação adiada; o do contrário é um portal sem dono.
        logger.exception("Falha ao verificar administradores restantes")
        raise HTTPException(
            status_code=503,
            detail="Não foi possível verificar os administradores agora. Tente novamente.",
        )

    restantes = 0
    for u in us:
        if str(u.get("id")) == str(user_id):
            if apagar:
                continue
            papel = novo_role if novo_role is not None else (u.get("role") or "")
            ativo = novo_ativo if novo_ativo is not None else u.get("ativo")
            u = {**u, "role": papel, "ativo": ativo}
        if (u.get("role") or "").strip().lower() == "admin" and auth.conta_ativa(u):
            restantes += 1

    if restantes == 0:
        raise HTTPException(
            status_code=409,
            detail=(
                "Esta é a única conta de administrador ativa. Promova outro "
                "administrador antes de desativar, rebaixar ou apagar esta — "
                "sem nenhum admin, não há como voltar pela tela."
            ),
        )


@router.put("/api/users/{user_id}", dependencies=[Depends(require_admin)])
def update_user(user_id: str, body: UserUpdateBody, ator: auth.TokenData = Depends(require_auth)) -> dict:
    from app.settings_state import _banco
    sb = _banco()
    if not sb:
        raise HTTPException(status_code=503)
    _exigir_alcance_sobre_conta(sb, ator, user_id)
    role = (body.role or "user").strip().lower()
    ativo = body.ativo
    # O papel ANTES da gravação diz se houve troca: toda troca esvazia a
    # carteira e derruba as sessões (ADR 0001). Editar sem trocar o papel não
    # mexe em nada — senão renomear alguém apagaria as Exceções dele.
    papel_anterior = _papel_da_conta(sb, user_id)

    # Cliente antigo mandando role="disabled" quer dizer "desative" — nunca
    # quis dizer "o papel dele agora é disabled", embora fosse isso que
    # acontecia. Traduz para o estado e preserva o papel gravado.
    if role == "disabled":
        ativo = False
        role = None

    if role is not None and role not in PAPEIS_VALIDOS:
        raise HTTPException(
            status_code=422,
            detail=f"Nível inválido. Use: {', '.join(PAPEIS_VALIDOS)}.",
        )
    if role == papeis.GESTOR:
        raise HTTPException(status_code=422, detail=papeis.PAPEL_GESTOR_E_DERIVADO)
    if role is not None:
        # "Operador" pedido para quem lidera um departamento grava Gestor: o
        # papel deriva da liderança, e o que rebaixa é tirar a liderança.
        role = papeis.papel_efetivo(sb, user_id, role)
    _exigir_alcance_de_papel(ator, role)

    email = _validar_email(body.email)
    _garantir_email_livre(sb, email, ignorar_id=user_id)
    _garantir_que_sobra_admin(sb, user_id, novo_role=role, novo_ativo=ativo)

    campos: Dict[str, Any] = {
        "email": email,
        # Máscara de nome (30/09/2026): gravado em maiúsculas, como a tela mostra.
        "full_name": body.full_name.strip().upper(),
    }
    if role is not None:
        campos["role"] = role
    if ativo is not None:
        campos["ativo"] = bool(ativo)
    if body.departamento_id is not None:
        # String vazia já não tira ninguém do setor: departamento é
        # obrigatório (ADR 0001). Para mudar de setor, escolhe-se outro.
        campos["departamento_id"] = _exigir_departamento(sb, body.departamento_id)

    # Nada a fazer com as seleções de alerta ao trocar o e-mail: desde a fase
    # 3c elas são chaveadas por `user_id`, então a identidade não se move. O
    # `_mover_selecoes_de_email` que existia aqui, e a leitura do endereço
    # anterior que o alimentava, viraram código morto e saíram — poder apagar
    # aquele helper era o sinal de que o rechaveamento tinha terminado.
    try:
        sb.table("users").update(campos).eq("id", user_id).execute()
    except Exception:
        logger.exception("Falha ao atualizar usuário %s", user_id)
        raise HTTPException(status_code=400, detail="Não foi possível salvar o usuário.")
    if ativo is False:
        _revogar_tokens_de_instalacao(user_id)
    saida: Dict[str, Any] = {"ok": True}
    if role is not None and role != papel_anterior:
        saida["papel"] = papeis.apos_troca_de_papel(sb, user_id)
    return saida




@router.post(
    "/api/users/{user_id}/enviar-codigo",
    dependencies=[Depends(require_admin), Depends(_limitar("enviar-codigo", 20, 3600))],
)
def enviar_codigo_de_redefinicao(
    user_id: str, request: Request, background: BackgroundTasks, ator: auth.TokenData = Depends(require_auth)
) -> dict:
    """O administrador dispara, para a conta, o mesmo código de 6 dígitos do
    "esqueci minha senha" (03/10/2026). Sem link novo: dá o mesmo resultado
    para quem recebe e não cria uma segunda forma de redefinir senha.

    Diferente da rota pública, aqui a resposta é concreta: quem chama é
    administrador autenticado, e saber que a conta existe é o trabalho dele."""
    from app.settings_state import _banco

    sb = _banco()
    if not sb:
        raise HTTPException(status_code=503, detail="Sistema sem banco configurado.")
    _exigir_alcance_sobre_conta(sb, ator, user_id)
    try:
        r = sb.table("users").select("id, email, full_name, role, ativo").eq("id", user_id).limit(1).execute()
    except Exception:
        logger.exception("Falha ao ler a conta %s", user_id)
        raise HTTPException(status_code=500, detail=ERRO_INTERNO_VEJA_LOG)
    conta = (r.data or [None])[0]
    if not conta:
        raise HTTPException(status_code=404, detail="Usuário não encontrado.")
    if conta.get("ativo") is False:
        raise HTTPException(status_code=400, detail="A conta está desativada; reative antes de enviar o código.")
    try:
        codigo = senha_reset.criar_codigo(str(conta["id"]), client_ip=_ip_do_cliente(request))
    except senha_reset.LimiteDePedidos:
        raise HTTPException(status_code=429, detail=f"Essa conta já recebeu {senha_reset.MAX_PEDIDOS_HORA} códigos na última hora. Aguarde.")
    except Exception:  # noqa: BLE001
        logger.exception("Falha ao criar código de redefinição por pedido do administrador")
        raise HTTPException(status_code=503, detail="Não foi possível gerar o código agora. Tente de novo em instantes.")
    background.add_task(_enviar_codigo_em_segundo_plano, conta, codigo)
    logger.info("Código de redefinição enviado a pedido do administrador %s para a conta %s", ator.email, user_id)
    return {"ok": True, "message": f"Código enviado para {conta.get('email')}. Vale 15 minutos."}


@router.post("/api/users/{user_id}/reset-password", dependencies=[Depends(require_admin)])
def reset_user_password(user_id: str, body: UserResetPasswordBody, ator: auth.TokenData = Depends(require_auth)) -> dict:
    from app.settings_state import _banco
    sb = _banco()
    if not sb:
        raise HTTPException(status_code=503)
    _exigir_alcance_sobre_conta(sb, ator, user_id)
    new_pw = (body.password or "").strip()
    _exigir_senha_valida(new_pw)
    hash_pw = auth.get_password_hash(new_pw)
    try:
        # Mesma razão do cadastro: o admin conhece a senha que acabou de
        # digitar. Sem isto ela valeria indefinidamente.
        sb.table("users").update(
            {
                "password_hash": hash_pw,
                "deve_trocar_senha": True,
                # Mesmo carimbo de `senha_redefinir` e `senha_trocar` (achado
                # #24): trocar a senha derruba as sessões abertas, venha a
                # troca de quem vier. Sem ele, o token de quem acabou de ter a
                # senha redefinida continuava válido — e a proteção inteira
                # pendurava só em `deve_trocar_senha`.
                "senha_alterada_em": datetime.now(timezone.utc).isoformat(),
            }
        ).eq("id", user_id).execute()
        computadores.sair_de_tudo(user_id, "senha redefinida pelo administrador")
        return {"ok": True}
    except Exception:
        logger.exception("Falha ao redefinir a senha de %s", user_id)
        raise HTTPException(status_code=400, detail="Não foi possível redefinir a senha.")


@router.post("/api/users/{user_id}/deactivate", dependencies=[Depends(require_admin)])
def deactivate_user(user_id: str, ator: auth.TokenData = Depends(require_auth)) -> dict:
    """
    Desativa a conta **preservando o papel**.

    Até 15/08 isto gravava `role = "disabled"`, o que apagava o papel: reativar
    um administrador virava adivinhação, e o mesmo teria acontecido com gestor —
    levando junto o sentido das carteiras que ele tivesse criado.
    """
    from app.settings_state import _banco
    sb = _banco()
    if not sb:
        raise HTTPException(status_code=503)
    _exigir_alcance_sobre_conta(sb, ator, user_id)
    _garantir_que_sobra_admin(sb, user_id, novo_ativo=False)
    try:
        sb.table("users").update({"ativo": False}).eq("id", user_id).execute()
    except Exception:
        logger.exception("Falha ao desativar %s", user_id)
        raise HTTPException(status_code=400, detail="Não foi possível desativar a conta.")
    _revogar_tokens_de_instalacao(user_id)

    # Liderancas saem junto (decisao de 01/10/2026): gestor que nao entra no
    # portal nao libera nada, e um departamento com gestor inativo parece
    # atendido sem estar. Sem lideranca, `rederivar` o devolve a Operador;
    # reativar comeca do zero, como Operador — o administrador o nomeia de
    # novo se quiser. Nunca derruba a desativacao: a conta ja caiu.
    papel: Dict[str, Any] = {}
    try:
        sb.table("departamento_lider").delete().eq("user_id", user_id).execute()
        mudancas = papeis.rederivar(sb, [user_id])
        papel = mudancas[0] if mudancas else {}
    except Exception:  # noqa: BLE001
        logger.exception("Conta %s desativada, mas as liderancas nao foram removidas", user_id)
        papel = {"erro": "As lideranças de departamento não puderam ser removidas."}

    # A carteira e removida DEPOIS de a conta cair, e nunca antes.
    #
    # Se a ordem fosse inversa e a inativacao falhasse, a pessoa continuaria
    # entrando no portal e teria perdido a carteira — o pior dos dois mundos.
    # Nesta ordem, a falha aqui deixa uma carteira orfa de uma conta que ja nao
    # entra: inofensiva, e visivel na tela de Carteiras para ser limpa a mao.
    #
    # Nao e barreira de seguranca: `require_auth` ja recusa conta inativa com
    # 401, entao a carteira de quem foi inativado nao concede nada mesmo antes
    # disto. E higiene — e uma decisao IRREVERSIVEL, por isso a tela mostra a
    # contagem antes de perguntar.
    try:
        esvaziado = cert_installer.esvaziar_carteira(user_id)
    except Exception as e:  # noqa: BLE001
        logger.error("Conta %s desativada, mas a carteira NAO foi limpa: %s", user_id, e)
        return {"ok": True, "carteira_removida": 0, "carteira_falhou": True}

    # Se a pessoa deixou de ser gestor logo acima, `rederivar` já esvaziou a
    # carteira; a resposta soma as duas passagens para a tela dizer o total.
    atrib = esvaziado["atribuicoes"] + int(papel.get("atribuicoes") or 0)
    exc = esvaziado["excecoes"] + int(papel.get("excecoes") or 0)
    return {
        "ok": True,
        "carteira_removida": atrib + exc,
        "atribuicoes": atrib,
        "excecoes": exc,
        "papel": papel,
    }


@router.get(
    "/api/users/{user_id}/carteira/contagem",
    dependencies=[Depends(require_admin)],
)
def contar_carteira_do_usuario(user_id: str) -> dict:
    """Quantos clientes a pessoa tem, para a confirmacao dizer o numero.

    Rota separada, e nao um campo em `/api/users`: aquela lista carrega dezenas
    de linhas em toda abertura da tela, e esta contagem so interessa no
    instante de inativar alguem.
    """
    from app.settings_state import _banco
    sb = _banco()
    if not sb:
        # Sem contagem, a tela pergunta sem o numero — o que ainda e melhor do
        # que travar a inativacao por causa do texto do aviso.
        return {"total": None}
    try:
        linhas = sb.table("carteira").select("user_id").eq("user_id", user_id).execute().data or []
        excecoes = sb.table(cert_installer.TABELA_EXCECOES).select("user_id").eq("user_id", user_id).execute().data or []
        return {"total": len(linhas) + len(excecoes), "atribuicoes": len(linhas), "excecoes": len(excecoes)}
    except Exception:  # noqa: BLE001
        logger.warning("Nao foi possivel contar a carteira de %s", user_id)
        return {"total": None}


@router.post("/api/users/{user_id}/reactivate", dependencies=[Depends(require_admin)])
def reactivate_user(user_id: str, ator: auth.TokenData = Depends(require_auth)) -> dict:
    """
    Reativa a conta, devolvendo o papel que ela sempre teve.

    Não existia contrapartida para o desativar: o único caminho de volta era
    editar o nível na mão e escolher um papel de memória. Com estado e papel
    separados, reativar deixa de ser uma decisão.

    As contas desativadas ANTES desta separação são a exceção: o papel delas foi
    sobrescrito e a migration as pôs em 'user', o menor privilégio. Se alguma
    era admin, promover é ato explícito — e é assim que deve ser.
    """
    from app.settings_state import _banco
    sb = _banco()
    if not sb:
        raise HTTPException(status_code=503)
    _exigir_alcance_sobre_conta(sb, ator, user_id)
    try:
        sb.table("users").update({"ativo": True}).eq("id", user_id).execute()
        return {"ok": True}
    except Exception:
        logger.exception("Falha ao reativar %s", user_id)
        raise HTTPException(status_code=400, detail="Não foi possível reativar a conta.")


# Nao ha DELETE /api/users/{id} (decisao de 01/10/2026, revisao da pagina
# Usuarios): a conta desativada e o historico — install_log e install_token
# apontam para ela. Apagar perderia a trilha de quem instalou o que.


def _revogar_tokens_de_instalacao(user_id: str) -> None:
    """Desativar, excluir ou inativar alguém alcança os tokens que ele pediu (#22).

    O comentário antigo em `deactivate_user` dizia que `require_auth` já
    recusava a conta inativa — verdade para o portal, falso para `/claim`,
    que não autentica. O token pendente continuava trocável por chave privada
    até o TTL. Nunca levanta: a conta já foi desativada; falhar aqui não pode
    desfazer isso, só avisar.
    """
    # ADR 0002: a bandeja da estação também deixa de valer.
    computadores.sair_de_tudo(user_id, "conta desativada")
    try:
        n = cert_installer.revogar_tokens_pendentes(user_id)
    except Exception:  # noqa: BLE001
        logger.exception("Falha ao revogar tokens de instalação de %s", user_id)
        return
    if n:
        logger.info("Conta %s: %d token(s) de instalação pendente(s) revogado(s).", user_id, n)


# ══════════════════════════════════════════════════════════════════════════
# Recuperação de senha por código (A8 da auditoria de UI/UX)
# ══════════════════════════════════════════════════════════════════════════

# Resposta única para todos os desfechos do pedido: e-mail inexistente, conta
# desativada, envio bem-sucedido e até estouro do teto de pedidos. Distinguir
# transformaria a tela num detector de quem tem conta no sistema — e a lista de
# quem tem conta aqui é a lista de quem administra certificados de clientes.
RESPOSTA_GENERICA = (
    "Se houver uma conta com esse e-mail, enviamos um código de 6 dígitos. "
    "Ele vale por 15 minutos."
)

CODIGO_INVALIDO = "Código inválido ou expirado. Peça um novo se precisar."
SENHA_NAO_GRAVADA = "Não foi possível gravar a senha nova. Tente de novo em instantes."


class SenhaCodigoBody(BaseModel):
    email: str


class SenhaVerificarBody(BaseModel):
    email: str
    codigo: str


class SenhaRedefinirBody(BaseModel):
    email: str
    codigo: str
    password: str


def _conta_para_reset(sb, email: str) -> Optional[dict]:
    """
    A conta que pode receber código: existe e está ativa.

    Desativada não recebe — redefinir senha não pode ser caminho de volta para
    quem foi removido do portal. De fora não dá para distinguir, porque a
    resposta é a mesma.
    """
    try:
        r = (
            sb.table("users")
            .select("id, email, full_name, role, ativo")
            .eq("email", email)
            .limit(1)
            .execute()
        )
    except Exception:  # noqa: BLE001
        logger.exception("Falha ao procurar conta para recuperação de senha")
        return None
    linhas = r.data or []
    if not linhas:
        return None
    conta = linhas[0]
    return conta if auth.conta_ativa(conta) else None


def _enviar_codigo_por_email(conta: dict, codigo: str) -> None:
    """Manda o código. Levanta se o SMTP falhar — o chamador decide o que fazer."""
    s = load_settings()
    if not correio.configurado(s):
        raise RuntimeError("Envio de e-mail não configurado")

    base = (os.getenv("PORTAL_BASE_URL") or "").strip().rstrip("/")
    # Link só de conveniência, e só se o endereço vier de configuração. Nunca
    # do cabeçalho `Host`: ele é controlado por quem chama, e um Host forjado
    # faria o portal mandar a própria vítima para o site do atacante.
    atalho = (
        f'<p style="margin:16px 0 0;">'
        f'<a href="{base}/login">Abrir o portal</a></p>' if base else ""
    )
    nome = html.escape(str(conta.get("full_name") or "").strip() or "Olá")

    correio.send_smtp_email(
        host=s.smtp_host,
        port=s.smtp_port,
        user=s.smtp_user,
        password_enc=s.smtp_password_encrypted,
        use_tls=s.smtp_use_tls,
        use_ssl=s.smtp_use_ssl,
        from_email=s.smtp_from_email,
        to_email=str(conta["email"]),
        settings=s,
        subject="Código para redefinir sua senha",
        html_content=(
            f"<p>{nome},</p>"
            "<p>Recebemos um pedido para redefinir a senha da sua conta no "
            "Monitor de Certificados. Use o código abaixo:</p>"
            f'<p style="font-size:28px;letter-spacing:6px;font-weight:700;'
            f'margin:24px 0;">{codigo}</p>'
            f"<p>Ele vale por {senha_reset.VALIDADE_MIN} minutos e só pode ser "
            "usado uma vez.</p>"
            "<p><strong>Se não foi você que pediu</strong>, ignore este e-mail: "
            "sua senha continua a mesma. Ninguém consegue trocá-la sem este "
            "código.</p>"
            f"{atalho}"
        ),
    )


def _enviar_codigo_em_segundo_plano(conta: dict, codigo: str) -> None:
    """Corre depois da resposta. Aqui o `except` é obrigatório: uma exceção em
    tarefa de fundo não tem quem a receba, e o log é o único sintoma."""
    try:
        _enviar_codigo_por_email(conta, codigo)
    except Exception:  # noqa: BLE001
        # ERROR e não warning: a pessoa está olhando para uma tela que diz que
        # o código foi enviado, e ele não foi. Sem este log ninguém descobre.
        logger.exception(
            "Código gerado mas NÃO enviado — a pessoa vai esperar um e-mail que não chega."
        )


@router.post("/api/senha/codigo")
def senha_pedir_codigo(body: SenhaCodigoBody, request: Request, background: BackgroundTasks) -> dict:
    """
    Pede um código de redefinição. **Responde sempre a mesma coisa.**

    O 200 genérico é o ponto: qualquer variação de mensagem, status ou tempo
    de resposta entre "existe" e "não existe" vira enumeração de contas.
    """
    from app.settings_state import _banco

    sb = _banco()
    if not sb:
        raise HTTPException(status_code=503, detail="Sistema sem banco configurado.")

    ip = _ip_do_cliente(request)
    # Teto por IP (achado #8). Os tetos de `senha_reset` são por CONTA: com
    # uma lista de endereços, um anônimo disparava 3 e-mails/hora por endereço
    # pelo SMTP da empresa, sem credencial nenhuma. Estourou → 200 genérico, e
    # não 429: um 429 aqui já seria sinal para quem está enumerando.
    if not taxa.permitir(f"reset-ip:{ip}", 5, 3600):
        logger.warning("Teto de pedidos de código por IP atingido.")
        return {"ok": True, "message": RESPOSTA_GENERICA}

    email = (body.email or "").strip().lower()
    if not email:
        return {"ok": True, "message": RESPOSTA_GENERICA}

    conta = _conta_para_reset(sb, email)
    if not conta:
        # Log em nível de info, sem alarde: e-mail digitado errado é o caso
        # comum, e não um incidente.
        logger.info("Pedido de código para e-mail sem conta ativa.")
        return {"ok": True, "message": RESPOSTA_GENERICA}

    try:
        codigo = senha_reset.criar_codigo(str(conta["id"]), client_ip=ip)
    except senha_reset.LimiteDePedidos:
        # Mesma resposta de propósito: dizer "você pediu demais" confirmaria
        # que a conta existe, que é justamente o que o genérico esconde.
        logger.warning(
            "Teto de %d pedidos/hora atingido para uma conta.",
            senha_reset.MAX_PEDIDOS_HORA,
        )
        return {"ok": True, "message": RESPOSTA_GENERICA}
    except Exception:  # noqa: BLE001
        logger.exception("Falha ao criar código de redefinição")
        raise HTTPException(
            status_code=503,
            detail="Não foi possível gerar o código agora. Tente de novo em instantes.",
        )

    # O SMTP sai do caminho da resposta. Dentro dele, fazia duas coisas ruins:
    # segurava o worker por até 10 s (o pool tem 6 conexões), e era o oráculo
    # de timing — conta inexistente respondia na hora, existente esperava o
    # servidor de e-mail. O 200 genérico não escondia nada.
    background.add_task(_enviar_codigo_em_segundo_plano, conta, codigo)

    return {"ok": True, "message": RESPOSTA_GENERICA}


def _exigir_teto_de_conferencia(request: Request) -> None:
    """Teto por IP para conferir ou consumir código (achado #8).

    Responde com o MESMO 400 de código errado: 429 seria uma terceira resposta,
    e o fluxo inteiro foi desenhado para ter só duas.
    """
    if not taxa.permitir(f"reset-verif:{_ip_do_cliente(request)}", 20, 3600):
        logger.warning("Teto de conferências de código por IP atingido.")
        raise HTTPException(status_code=400, detail=CODIGO_INVALIDO)


@router.post("/api/senha/verificar")
def senha_verificar_codigo(body: SenhaVerificarBody, request: Request) -> dict:
    """
    Confere o código **sem consumi-lo**, para a tela avançar antes de a pessoa
    digitar a senha nova.

    Sem este passo, um código errado só apareceria depois de ela preencher a
    senha duas vezes — e já teria queimado uma das três tentativas à toa.
    """
    from app.settings_state import _banco

    sb = _banco()
    if not sb:
        raise HTTPException(status_code=503, detail="Sistema sem banco configurado.")

    _exigir_teto_de_conferencia(request)
    conta = _conta_para_reset(sb, (body.email or "").strip().lower())
    if not conta:
        # Sem conta, não há código. Recusa com a mesma mensagem de código
        # errado, para não distinguir os dois casos.
        raise HTTPException(status_code=400, detail=CODIGO_INVALIDO)

    ok, _ = senha_reset.conferir(str(conta["id"]), body.codigo or "")
    if not ok:
        raise HTTPException(status_code=400, detail=CODIGO_INVALIDO)
    return {"ok": True}


@router.post("/api/senha/redefinir")
def senha_redefinir(body: SenhaRedefinirBody, request: Request) -> dict:
    """
    Consome o código e grava a senha nova.

    Reconfere o código aqui em vez de confiar no `/verificar`: aquele passo é
    conveniência de tela, não credencial. Quem chamar esta rota direto tem de
    apresentar o código do mesmo jeito.
    """
    from app.settings_state import _banco

    sb = _banco()
    if not sb:
        raise HTTPException(status_code=503, detail="Sistema sem banco configurado.")

    nova = (body.password or "").strip()
    _exigir_senha_valida(nova, body.email)

    _exigir_teto_de_conferencia(request)
    email = (body.email or "").strip().lower()
    conta = _conta_para_reset(sb, email)
    if not conta:
        raise HTTPException(status_code=400, detail=CODIGO_INVALIDO)

    if not senha_reset.consumir(str(conta["id"]), body.codigo or ""):
        raise HTTPException(status_code=400, detail=CODIGO_INVALIDO)

    agora = datetime.now(timezone.utc).isoformat()
    try:
        sb.table("users").update(
            {
                "password_hash": auth.get_password_hash(nova),
                # Carimbado na MESMA gravação da senha: separá-los abriria uma
                # janela em que a senha já mudou mas as sessões antigas ainda
                # valem — que é exatamente o que esta coluna existe para fechar.
                "senha_alterada_em": agora,
                # Aqui foi a própria pessoa quem escolheu, com um código que só
                # ela recebeu. Não há nada a cobrar depois.
                "deve_trocar_senha": False,
            }
        ).eq("id", conta["id"]).execute()
    except Exception:  # noqa: BLE001
        logger.exception("Falha ao gravar a senha nova")
        raise HTTPException(status_code=400, detail=SENHA_NAO_GRAVADA)

    computadores.sair_de_tudo(str(conta["id"]), "senha redefinida por código")
    atividade.registrar(
        atividade.EVENTO_SENHA_REDEFINIDA,
        user_id=str(conta["id"]),
        user_email=email,
        client_ip=request.client.host if request and request.client else None,
    )
    return {
        "ok": True,
        "message": "Senha alterada. Entre com a nova senha.",
    }


class SenhaTrocarBody(BaseModel):
    senha_atual: str
    nova_senha: str


@router.post("/api/senha/trocar")
def senha_trocar(
    body: SenhaTrocarBody,
    request: Request,
    token: auth.TokenData = Depends(require_auth),
) -> dict:
    """
    A própria pessoa troca a senha. É a única rota que responde com senha
    provisória — ver `ROTAS_COM_SENHA_PROVISORIA`.

    Exige a senha atual mesmo já estando autenticada. Parece redundante, e não
    é: com a sessão aberta e a máquina destravada, qualquer um que sente na
    cadeira definiria a senha nova sem saber a antiga, e a pessoa perderia a
    conta para quem passou por ali.
    """
    from app.settings_state import _banco

    sb = _banco()
    if not sb:
        raise HTTPException(status_code=503, detail="Sistema sem banco configurado.")

    nova = (body.nova_senha or "").strip()
    _exigir_senha_valida(nova, token.email)

    uid = _user_id_da_sessao(token)
    if not uid:
        raise HTTPException(status_code=401, detail=SESSAO_ENCERRADA)

    try:
        r = sb.table("users").select("password_hash").eq("id", uid).limit(1).execute()
    except Exception:  # noqa: BLE001
        logger.exception("Falha ao ler a conta para troca de senha")
        raise HTTPException(status_code=503, detail="Não foi possível trocar a senha agora.")

    linhas = r.data or []
    if not linhas or not auth.verify_password(body.senha_atual or "", linhas[0]["password_hash"]):
        raise HTTPException(status_code=400, detail="A senha atual não confere.")

    if auth.verify_password(nova, linhas[0]["password_hash"]):
        # Sem isto, "trocar a senha" seria satisfeito repetindo a provisória —
        # e a senha que outra pessoa conhece continuaria valendo, agora com a
        # flag desligada e ninguém mais cobrando a troca.
        raise HTTPException(
            status_code=422,
            detail="A senha nova precisa ser diferente da atual.",
        )

    agora = datetime.now(timezone.utc).isoformat()
    try:
        sb.table("users").update(
            {
                "password_hash": auth.get_password_hash(nova),
                "senha_alterada_em": agora,
                "deve_trocar_senha": False,
            }
        ).eq("id", uid).execute()
    except Exception:  # noqa: BLE001
        logger.exception("Falha ao gravar a senha nova")
        raise HTTPException(status_code=400, detail=SENHA_NAO_GRAVADA)

    atividade.registrar(
        atividade.EVENTO_SENHA_REDEFINIDA,
        user_id=uid,
        user_email=token.email or "",
        client_ip=request.client.host if request and request.client else None,
        contexto={"origem": "troca_propria"},
    )
    # `senha_alterada_em` acabou de ser carimbado, então o token que fez esta
    # chamada morre na requisição seguinte — de propósito, é a mesma regra que
    # derruba sessão aberta em qualquer troca de senha. O front reconhece o 401
    # e manda para o login.
    return {"ok": True, "message": "Senha alterada. Entre novamente com a nova senha."}


# =========================================================================
# LGPD / PRIVACY BY DESIGN - DIREITOS DOS TITULARES
# =========================================================================

@router.get("/api/users/me/export")
def export_my_data(token: auth.TokenData = Depends(require_auth)) -> dict:
    """[LGPD] Portabilidade e Consulta de Dados (Art. 18, incisos II e X)"""
    from app.settings_state import load_colaborador_selecao
    email = token.email
    docs = load_colaborador_selecao(email, _user_id_da_sessao(token))
    
    return {
        "titular": email,
        "vinculo_role": token.role,
        "documentos_monitorados_cnpj_cpf": docs,
        "exportado_em": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "aviso_lgpd": "Este arquivo contém seus dados pessoais conforme registro no sistema."
    }

@router.delete("/api/users/me/delete")
def delete_my_data(token: auth.TokenData = Depends(require_auth)) -> dict:
    """[LGPD] Direito ao Esquecimento / Eliminação (Art. 18, inciso VI)"""
    from app.settings_state import _banco
    email = token.email
    sb = _banco()
    
    # 1. Apagar seleções (Ações do usuário no app)
    if sb:
        # Pela identidade. O apagamento por `user_email` que acompanhava este
        # daqui saiu na fase 3c: a coluna deixou de ser escrita e some na 3d,
        # então continuar filtrando por ela seria apagar por um valor que o
        # portal já não grava — e daria a impressão de cobertura que não há.
        #
        # Sem `user_id` não dá para apagar nada com segurança, e numa rota de
        # LGPD isso não pode passar calado.
        uid = _user_id_da_sessao(token)
        if uid:
            sb.table("colaborador_cert_selecoes").delete().eq("user_id", uid).execute()
        else:
            logger.error(
                "Pedido de eliminação de %s não removeu as seleções: sessão sem "
                "user_id. O dado continua no banco.",
                email,
            )
    else:
        # Modo arquivo local: limpa a entrada
        from app.settings_state import save_colaborador_selecao
        save_colaborador_selecao(email, [])
        
    return {
        "status": "ok", 
        "message": "Seus dados operacionais associados foram permanentemente removidos."
    }
