"""
Banco de DEMONSTRACAO do portal de certificados (robot_cert), 100% ficticio.

    <venv do robot_cert>\\python.exe seed_wiki.py

O que faz (e refaz do zero a cada execucao):
  1. gera (uma vez) as variaveis do ambiente de demo em ambiente-wiki.env e a
     senha comum dos usuarios em credenciais-demo.txt (nesta mesma pasta);
  2. DERRUBA e recria o banco certguard_wiki (so ele: o nome e conferido);
  3. aplica o esquema com db/aplicar_schema.py + a DDL do lote 3 que o
     aplicar_schema nao executa (cert_history por arquivo_chave);
  4. gera PFX ficticios (AC ficticia, CN "NOME:DOCUMENTO") em acervo/, le com
     o proprio scanner do portal e grava inventario, historico, cofre,
     usuarios, carteiras, computadores, trilhas, SIEG, alertas e movimentos.

Nada aqui e dado real: empresas, pessoas, CNPJ/CPF (digito verificador valido,
numeros sorteados), e-mails @exemplo.com, maquinas e MACs.
"""
from __future__ import annotations

import json
import os
import random
import secrets
import shutil
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

AQUI = Path(__file__).resolve().parent
REPO = AQUI.parent.parent  # scripts/wiki_demo/ -> raiz do repositorio
BANCO = "certguard_wiki"
DSN_ADMIN = "postgresql://postgres@127.0.0.1:5432/postgres"
DSN = f"postgresql://postgres@127.0.0.1:5432/{BANCO}"
AMBIENTE = AQUI / "ambiente-wiki.env"
CREDENCIAIS = AQUI / "credenciais-demo.txt"
ACERVO = AQUI / "acervo"
MAQUINA_SERVIDOR = "ANALISESRV"  # o Dashboard > Renovacoes procura este machine_id por padrao
PASTA_EXIBIDA = "D:/Certificados-Demo/Clientes"
PASTA_VENCIDOS_EXIBIDA = "D:/Certificados-Demo/Vencidos"

RNG = random.Random(20261014)
AGORA = datetime.now(timezone.utc).replace(microsecond=0)


# ---------------------------------------------------------------- ambiente

def _ler_env(p: Path) -> dict:
    out = {}
    if p.is_file():
        for linha in p.read_text(encoding="ascii").splitlines():
            linha = linha.strip()
            if linha and not linha.startswith("#") and "=" in linha:
                k, v = linha.split("=", 1)
                out[k.strip()] = v.strip()
    return out


def preparar_ambiente() -> dict:
    env = _ler_env(AMBIENTE)
    if not env.get("JWT_SECRET_KEY"):
        from cryptography.fernet import Fernet

        env = {
            "DATABASE_URL": DSN,
            "API_KEY": secrets.token_urlsafe(32),
            "JWT_SECRET_KEY": secrets.token_urlsafe(48),
            "CERT_ENCRYPTION_KEY": secrets.token_hex(32),
            "CERT_PASSWORD_ENCRYPTION_KEY": secrets.token_hex(32),
            "ENCRYPTION_KEY": Fernet.generate_key().decode(),
            "LOGIN_EXIGE_CODIGO": "0",
            "NUM_PROXIES_CONFIAVEIS": "0",
            "CERT_SOURCE_DIR": str(ACERVO / "Clientes"),
            "CERT_EXPIRED_DIR": str(ACERVO / "Vencidos"),
        }
        AMBIENTE.write_text(
            "# Ambiente de DEMONSTRACAO (certguard_wiki). Valores aleatorios, so para este banco.\n"
            + "".join(f"{k}={v}\n" for k, v in env.items()),
            encoding="ascii",
        )
    if CREDENCIAIS.is_file():
        senha = next(
            (l.split(":", 1)[1].strip() for l in CREDENCIAIS.read_text(encoding="utf-8").splitlines()
             if l.lower().startswith("senha")), "")
    else:
        senha = ""
    if not senha:
        senha = "Demo-" + secrets.token_urlsafe(9).replace("-", "x").replace("_", "y")
        CREDENCIAIS.write_text(
            "Portal de certificados - ambiente de DEMONSTRACAO (banco certguard_wiki)\n"
            "URL: http://127.0.0.1:8090/login\n"
            f"Senha (a mesma para todos): {senha}\n\n"
            "admin.demo@exemplo.com        Administrador\n"
            "gestor.demo@exemplo.com       Gestor (lidera o departamento Fiscal)\n"
            "colaborador.demo@exemplo.com  Operador (carteira com 12 clientes)\n",
            encoding="utf-8",
        )
    for k, v in env.items():
        os.environ[k] = v
    return {"env": env, "senha": senha}


# ---------------------------------------------------------------- banco

def recriar_banco() -> None:
    import psycopg

    assert BANCO == "certguard_wiki"
    with psycopg.connect(DSN_ADMIN, autocommit=True) as c:
        c.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s AND pid <> pg_backend_pid()", (BANCO,))
        c.execute(f"DROP DATABASE IF EXISTS {BANCO}")
        c.execute(f"CREATE DATABASE {BANCO}")
    r = subprocess.run([sys.executable, str(REPO / "db" / "aplicar_schema.py"), DSN], cwd=str(REPO),
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    print(r.stdout.strip().splitlines()[-1] if r.stdout.strip() else r.stderr)
    if r.returncode != 0:
        print(r.stdout, r.stderr)
        raise SystemExit("aplicar_schema falhou")
    # O .sql do lote 3 e so registro (select 1): a DDL vive em
    # scripts/migracao_lote3_nome_publico.py. Banco vazio -> so a DDL.
    with psycopg.connect(DSN, autocommit=False) as c:
        c.execute("ALTER TABLE cert_history ADD COLUMN arquivo_chave char(64), ADD COLUMN nome_publico text")
        c.execute("ALTER TABLE cert_history DROP CONSTRAINT cert_history_pkey")
        c.execute("ALTER TABLE cert_history DROP COLUMN file_name")
        c.execute("ALTER TABLE cert_history ALTER COLUMN arquivo_chave SET NOT NULL, ALTER COLUMN nome_publico SET NOT NULL")
        c.execute("ALTER TABLE cert_history ADD PRIMARY KEY (arquivo_chave)")
        c.execute("CREATE INDEX IF NOT EXISTS cert_history_nome_publico_idx ON cert_history (nome_publico)")
        c.commit()


# ---------------------------------------------------------------- documentos

def cnpj() -> str:
    base = [RNG.randint(0, 9) for _ in range(8)] + [0, 0, 0, 1]
    for pesos in ([5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2], [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]):
        s = sum(a * b for a, b in zip(base, pesos)) % 11
        base.append(0 if s < 2 else 11 - s)
    return "".join(map(str, base))


def cpf() -> str:
    base = [RNG.randint(0, 9) for _ in range(9)]
    for n in (10, 11):
        s = sum(a * b for a, b in zip(base, range(n, 1, -1))) % 11
        base.append(0 if s < 2 else 11 - s)
    return "".join(map(str, base))


EMPRESAS = [
    "PADARIA PAO DOURADO LTDA", "AUTO PECAS RODA VIVA LTDA", "CLINICA SORRISO PLENO LTDA",
    "MERCEARIA BOM PRECO DO BAIRRO LTDA", "TRANSPORTES ESTRELA DO NORTE LTDA", "CONFECCOES FIO DE OURO LTDA",
    "RESTAURANTE SABOR DA TERRA LTDA", "FARMACIA VIDA SAUDAVEL LTDA", "CONSTRUTORA PEDRA FIRME LTDA",
    "PET SHOP AMIGO FIEL LTDA", "ESCOLA PEQUENO SABER LTDA", "OTICA VISAO CLARA LTDA",
    "SUPERMERCADO CESTA CHEIA LTDA", "GRAFICA TINTA NOVA LTDA", "LAVANDERIA BOLHA AZUL LTDA",
    "HORTIFRUTI FOLHA VERDE LTDA", "SERRALHERIA FERRO FORTE LTDA", "DISTRIBUIDORA AGUA PURA LTDA",
    "ACADEMIA CORPO SAUDAVEL LTDA", "LIVRARIA PAGINA VIRADA LTDA", "MOVEIS CASA ACONCHEGO LTDA",
    "SORVETERIA GELO DOCE LTDA", "INFORMATICA BIT A BIT LTDA", "OFICINA MOTOR CERTO LTDA",
    "AGROPECUARIA CAMPO BELO LTDA", "PAPELARIA LAPIS DE COR LTDA", "CAFETERIA GRAO NOBRE LTDA",
    "VIDRACARIA CRISTAL LIMPO LTDA", "IMOBILIARIA CHAVE CERTA LTDA", "MATERIAIS ELETRICOS LUZ FORTE LTDA",
    "CALCADOS PASSO LEVE LTDA", "FLORICULTURA JARDIM SECRETO LTDA", "TINTAS ARCO IRIS COMERCIO LTDA",
    "EMBALAGENS CAIXA FORTE LTDA",
]
PESSOAS = [
    "MARIANA SILVEIRA CAMPOS", "ROBERTO ALVES NUNES", "FERNANDA COSTA RIBEIRO",
    "PAULO HENRIQUE DIAS", "LUCIANA MOTA FERREIRA", "THIAGO BARROS LEMOS",
]
RESPONSAVEIS = [
    "JOAO CARLOS PEREIRA", "ANA PAULA MENDES", "MARCOS VINICIUS ROCHA", "CLAUDIA REGINA SOUZA",
    "RAFAEL AUGUSTO MARTINS", "SIMONE APARECIDA LOPES", "EDUARDO HENRIQUE GOMES", "PATRICIA HELENA CRUZ",
]

# Dias ate o vencimento do certificado VIGENTE de cada cliente (40 clientes).
DIAS = ([-200, -95, -40, -12, -3]          # vencidos
        + [2, 5, 7]                         # ate 7 dias
        + [10, 15, 22, 29]                  # 8 a 30
        + [35, 44, 58]                      # 31 a 60
        + [70, 85]                          # 61 a 90
        + [100, 120, 140, 160, 180, 200, 220, 240, 260, 280, 300, 320, 340, 360,
           380, 400, 430, 460, 500, 540, 580, 620, 660])  # validos
assert len(DIAS) == 40


def _der_octeto(texto: str) -> bytes:
    b = texto.encode("utf-8")
    assert len(b) < 128
    return b"\x04" + bytes([len(b)]) + b


_AC = None


def ac():
    global _AC
    if _AC is None:
        from cryptography import x509
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID

        chave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        nome = x509.Name([
            x509.NameAttribute(NameOID.COUNTRY_NAME, "BR"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "ICP-Demo Ficticia"),
            x509.NameAttribute(NameOID.COMMON_NAME, "AC FICTICIA DEMONSTRACAO v5"),
        ])
        _AC = (chave, nome)
    return _AC


def gerar_pfx(nome: str, doc: str, senha: str, nao_antes: datetime, nao_depois: datetime,
              responsavel: str | None, resp_cpf: str | None, email: str) -> bytes:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives.serialization import pkcs12
    from cryptography.x509.oid import NameOID, ObjectIdentifier

    chave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pf = len(doc) == 11
    sujeito = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "BR"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "ICP-Demo Ficticia"),
        x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, "Certificado PF A1" if pf else "Certificado PJ A1"),
        x509.NameAttribute(NameOID.COMMON_NAME, f"{nome}:{doc}"),
    ])
    nasc = f"{RNG.randint(1, 28):02d}{RNG.randint(1, 12):02d}{RNG.randint(1960, 1995)}"
    outros = []
    if pf:
        outros.append(x509.OtherName(ObjectIdentifier("2.16.76.1.3.1"), _der_octeto(nasc + doc + "0" * 11)))
    else:
        outros.append(x509.OtherName(ObjectIdentifier("2.16.76.1.3.2"), _der_octeto(responsavel or "")))
        outros.append(x509.OtherName(ObjectIdentifier("2.16.76.1.3.3"), _der_octeto(doc)))
        outros.append(x509.OtherName(ObjectIdentifier("2.16.76.1.3.4"), _der_octeto(nasc + (resp_cpf or "") + "0" * 11)))
    san = x509.SubjectAlternativeName([x509.RFC822Name(email), *outros])
    cert = (
        x509.CertificateBuilder()
        .subject_name(sujeito).issuer_name(ac()[1]).public_key(chave.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(nao_antes).not_valid_after(nao_depois)
        .add_extension(san, critical=False)
        .sign(ac()[0], hashes.SHA256())
    )
    return pkcs12.serialize_key_and_certificates(
        nome.encode()[:60], chave, cert, None, serialization.BestAvailableEncryption(senha.encode()))


def _slug_email(nome: str) -> str:
    palavras = [p.lower() for p in nome.split() if p not in ("LTDA", "DO", "DA", "DE", "EM", "A")]
    return "contato@" + "".join(palavras[:2]) + ".exemplo"


def montar_acervo() -> dict:
    """Escreve os PFX em acervo/ e devolve o plano (clientes, renovacoes, etc.)."""
    if ACERVO.exists():
        shutil.rmtree(ACERVO)
    (ACERVO / "Clientes").mkdir(parents=True)
    (ACERVO / "Vencidos").mkdir(parents=True)
    (ACERVO / "Antigos").mkdir(parents=True)  # o que ja saiu da pasta (so nos snapshots antigos)

    clientes = []
    nomes_tit = EMPRESAS + PESSOAS
    RNG.shuffle(DIAS)
    for i, nome in enumerate(nomes_tit):
        pf = nome in PESSOAS
        doc = cpf() if pf else cnpj()
        clientes.append({
            "nome": nome, "doc": doc, "pf": pf, "dias": DIAS[i],
            "resp": None if pf else RESPONSAVEIS[i % len(RESPONSAVEIS)],
            "resp_cpf": None if pf else cpf(),
            "email": ("pessoal." + nome.split()[0].lower() + "@exemplo.com") if pf else _slug_email(nome),
        })

    def escrever(pasta: Path, cli: dict, dias_validade: int, emitido_ha: int, sufixo: str = "",
                 senha: str | None = None, senha_no_nome: str | None = None) -> Path:
        senha = senha or f"{RNG.randint(100000, 999999)}"
        nb = AGORA - timedelta(days=emitido_ha)
        na = AGORA + timedelta(days=dias_validade)
        letra = cli["nome"][0]
        destino = pasta / letra
        destino.mkdir(parents=True, exist_ok=True)
        rotulo = cli["nome"].title().replace(" Ltda", " LTDA")
        nome_arq = f"{rotulo}_{cli['doc']}{sufixo} senha {senha_no_nome or senha}.pfx"
        p = destino / nome_arq
        p.write_bytes(gerar_pfx(cli["nome"], cli["doc"], senha, nb, na, cli["resp"], cli["resp_cpf"], cli["email"]))
        return p

    plano = {"clientes": clientes, "renovados": [], "novos": [], "saiu": None, "copia": None, "dup_doc": []}
    for cli in clientes:
        emitido = max(30, 365 - cli["dias"]) if cli["dias"] < 365 else 20
        cli["arquivo"] = escrever(ACERVO / "Clientes", cli, cli["dias"], emitido)

    validos = [c for c in clientes if c["dias"] > 60]
    # Renovados nos ultimos 30 dias: o certificado anterior ficou so nos
    # snapshots antigos (o agente o moveu para vencidos).
    for cli, quando in zip(validos[0:3], (20, 12, 6)):
        cli["renovado_ha"] = quando
        cli["arquivo_antigo"] = escrever(ACERVO / "Antigos", cli, -(quando - 4), 365, sufixo=" (anterior)")
        plano["renovados"].append(cli)
    # Duplicidade por documento: o anterior (vencido) continua na pasta.
    for cli in validos[3:5]:
        escrever(ACERVO / "Clientes", cli, -15, 380, sufixo=" (2)")
        plano["dup_doc"].append(cli)
    # Certificado identico (mesmo PFX) em duas pastas.
    cli = validos[5]
    copia = ACERVO / "Clientes" / "_Copias" / (cli["arquivo"].name.replace(cli["doc"], cli["doc"] + " copia"))
    copia.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(cli["arquivo"], copia)
    plano["copia"] = cli
    # Novos (entraram ha poucos dias)
    for cli, quando in zip(validos[6:8], (3, 1)):
        cli["novo_ha"] = quando
        plano["novos"].append(cli)
    # Um cliente que saiu do acervo ha 15 dias (so nos snapshots antigos)
    saiu = {"nome": "DROGARIA FORMULA ANTIGA LTDA", "doc": cnpj(), "pf": False, "dias": 90,
            "resp": "OSVALDO TEIXEIRA LIMA", "resp_cpf": cpf(), "email": "contato@formulaantiga.exemplo"}
    saiu["arquivo"] = escrever(ACERVO / "Antigos", saiu, 90, 200)
    plano["saiu"] = saiu
    # Ilegiveis: senha errada no nome e nome fora do padrao.
    cli_err = {"nome": "BICICLETARIA PEDAL FORTE LTDA", "doc": cnpj(), "pf": False, "dias": 200,
               "resp": "SERGIO MOURA", "resp_cpf": cpf(), "email": "contato@pedalforte.exemplo"}
    escrever(ACERVO / "Clientes", cli_err, 200, 100, senha="111222", senha_no_nome="999888")
    fora = ACERVO / "Clientes" / "C" / "certificado novo cliente sem padrao.pfx"
    fora.parent.mkdir(parents=True, exist_ok=True)
    fora.write_bytes(gerar_pfx("CHAVEIRO SEGREDO LTDA", cnpj(), "123456", AGORA - timedelta(days=10),
                               AGORA + timedelta(days=355), "LUIZ FERNANDO REIS", cpf(), "contato@chaveiro.exemplo"))
    return plano


# ---------------------------------------------------------------- inventario

def itens_da_pasta(pasta: Path) -> list:
    from app.cert_scanner import cert_to_public_dict, scan_folder
    from app import nome_publico

    out = []
    for c in scan_folder(pasta):
        it = nome_publico.sanitizar_item(cert_to_public_dict(c))
        rel = c.path.parent.relative_to(pasta).as_posix()
        base = PASTA_VENCIDOS_EXIBIDA if pasta.name == "Antigos" else PASTA_EXIBIDA
        it["pasta"] = base + ("" if rel == "." else "/" + rel)
        out.append(it)
    return out


def status_em(it: dict, quando: datetime) -> dict:
    it = dict(it)
    if it.get("status") in ("ok", "expirado") and it.get("not_after"):
        na = datetime.fromisoformat(it["not_after"])
        it["status"] = "expirado" if na < quando else "ok"
    return it


def gravar_inventario(cur, plano: dict) -> tuple[list, dict]:
    from psycopg.types.json import Jsonb

    atuais = itens_da_pasta(ACERVO / "Clientes")
    antigos = itens_da_pasta(ACERVO / "Antigos")
    por_doc_antigo = {it.get("documento_numero"): it for it in antigos}
    doc_novo = {c["doc"]: c["novo_ha"] for c in plano["novos"]}
    doc_renov = {c["doc"]: c["renovado_ha"] for c in plano["renovados"]}

    def presente_em(it: dict, dias_atras: int) -> list:
        """Itens deste arquivo no snapshot de `dias_atras` dias atras."""
        doc = it.get("documento_numero")
        if doc in doc_novo and dias_atras >= doc_novo[doc]:
            return []
        if doc in doc_renov and dias_atras >= doc_renov[doc]:
            return [por_doc_antigo[doc]]
        return [it]

    primeira_vez: dict = {}
    ultima_vez: dict = {}
    ultimo_item: dict = {}
    for d in range(40, -1, -1):  # uma varredura por dia, 40 dias
        quando = (AGORA - timedelta(days=d)).replace(hour=6, minute=RNG.randint(0, 20), second=RNG.randint(0, 59))
        if d == 0:
            quando = AGORA - timedelta(minutes=37)
        itens = []
        for it in atuais:
            itens.extend(presente_em(it, d))
        saiu = por_doc_antigo.get(plano["saiu"]["doc"])
        if d >= 15 and saiu:
            itens.append(saiu)
        itens = [status_em(i, quando) for i in itens]
        cur.execute(
            "INSERT INTO cert_snapshots (machine_id, source_folder, expired_folder, scanned_at, items) "
            "VALUES (%s, %s, %s, %s, %s)",
            (MAQUINA_SERVIDOR, PASTA_EXIBIDA.replace("/", "\\"), PASTA_VENCIDOS_EXIBIDA.replace("/", "\\"), quando, Jsonb(itens)),
        )
        for i in itens:
            k = i["arquivo_chave"]
            primeira_vez.setdefault(k, quando)
            ultima_vez[k] = quando
            ultimo_item[k] = i

    # cert_history: estado atual por arquivo. Quem ja estava antes da janela
    # de 40 dias ganha uma primeira data mais antiga.
    for k, it in ultimo_item.items():
        primeira = primeira_vez[k]
        if primeira <= AGORA - timedelta(days=39):
            primeira = AGORA - timedelta(days=RNG.randint(60, 420))
        cur.execute(
            "INSERT INTO cert_history (arquivo_chave, nome_publico, machine_id, nome, documento, documento_numero, "
            "status_ultimo, vencimento_certificado, ultima_data_registrada, updated_at, primeira_data_registrada) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (k, it["nome_publico"], MAQUINA_SERVIDOR, it.get("nome") or it.get("display_name") or it["nome_publico"],
             it.get("documento_formatado") or it.get("documento_numero"), it.get("documento_numero"),
             it.get("status"), it.get("not_after"), ultima_vez[k], ultima_vez[k], primeira),
        )
    return atuais, {"antigos": antigos}


# ---------------------------------------------------------------- pessoas

def gravar_pessoas(cur, senha: str) -> dict:
    from app.auth import get_password_hash

    h = get_password_hash(senha)
    deps = {n: str(uuid.uuid4()) for n in ("Fiscal", "Contabil", "Departamento Pessoal")}
    nomes_dep = {"Fiscal": "Fiscal", "Contabil": "Contábil", "Departamento Pessoal": "Departamento Pessoal"}
    for k, i in deps.items():
        cur.execute("INSERT INTO departamento (id, nome, criado_em) VALUES (%s,%s,%s)",
                    (i, nomes_dep[k], AGORA - timedelta(days=120)))
    U = {}

    def user(chave, email, nome, role, dep, gestor=None, ativo=True, criado=200, trocar=False):
        uid = str(uuid.uuid4())
        U[chave] = uid
        cur.execute(
            "INSERT INTO users (id, email, password_hash, full_name, role, deve_trocar_senha, created_at, ativo, "
            "gestor_id, senha_alterada_em, departamento_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (uid, email, h, nome, role, trocar, AGORA - timedelta(days=criado), ativo, gestor,
             AGORA - timedelta(days=min(criado, 30)), deps[dep] if dep else None),
        )
        return uid

    user("admin", "admin.demo@exemplo.com", "Administrador Demonstração", "admin", None, criado=300)
    g = user("gestor", "gestor.demo@exemplo.com", "Gestora Demonstração", "gestor", "Fiscal", criado=250)
    user("colab", "colaborador.demo@exemplo.com", "Colaborador Demonstração", "user", "Fiscal", gestor=g, criado=180)
    user("ana", "ana.moreira@exemplo.com", "Ana Beatriz Moreira", "user", "Fiscal", gestor=g, criado=150)
    user("carlos", "carlos.lima@exemplo.com", "Carlos Eduardo Lima", "user", "Contabil", criado=140)
    user("juliana", "juliana.prado@exemplo.com", "Juliana Prado Santos", "user", "Departamento Pessoal", criado=90)
    user("bruno", "bruno.teixeira@exemplo.com", "Bruno Teixeira Alves", "gestor", "Contabil", criado=220)
    user("marina", "marina.duarte@exemplo.com", "Marina Duarte Rocha", "user", "Contabil", ativo=False, criado=260)
    user("novato", "pedro.novaes@exemplo.com", "Pedro Novaes", "user", "Fiscal", gestor=g, criado=2, trocar=True)
    cur.execute("INSERT INTO departamento_lider (departamento_id, user_id) VALUES (%s,%s)", (deps["Fiscal"], U["gestor"]))
    cur.execute("INSERT INTO departamento_lider (departamento_id, user_id) VALUES (%s,%s)", (deps["Contabil"], U["bruno"]))
    return U


def gravar_carteiras(cur, U: dict, plano: dict) -> dict:
    docs = [c["doc"] for c in plano["clientes"]]
    RNG2 = random.Random(7)
    ordem = docs[:]
    RNG2.shuffle(ordem)
    carteiras = {"colab": ordem[0:12], "ana": ordem[12:20], "carlos": ordem[20:27], "juliana": ordem[27:31]}
    # o colaborador acompanha os renovados e um vencendo em breve
    for c in plano["renovados"][:1]:
        if c["doc"] not in carteiras["colab"]:
            carteiras["colab"][-1] = c["doc"]
    quem = {"colab": "gestor.demo@exemplo.com", "ana": "gestor.demo@exemplo.com",
            "carlos": "admin.demo@exemplo.com", "juliana": "admin.demo@exemplo.com"}
    autor = {"gestor.demo@exemplo.com": U["gestor"], "admin.demo@exemplo.com": U["admin"]}
    for chave, lista in carteiras.items():
        for i, d in enumerate(lista):
            cur.execute(
                "INSERT INTO carteira (user_id, documento, atribuido_por, atribuido_por_email, atribuido_em) "
                "VALUES (%s,%s,%s,%s,%s)",
                (U[chave], d, autor[quem[chave]], quem[chave], AGORA - timedelta(days=60 - i)),
            )
    # Excecao: um cliente que o Gestor nao alcanca
    cur.execute("INSERT INTO carteira_excecao (user_id, documento, registrado_por, registrado_por_email, registrado_em) "
                "VALUES (%s,%s,%s,%s,%s)", (U["gestor"], ordem[35], U["admin"], "admin.demo@exemplo.com", AGORA - timedelta(days=20)))
    # Acompanhamento (selecoes)
    sel = {"colab": carteiras["colab"][:7], "gestor": ordem[0:4] + ordem[12:14], "admin": ordem[0:5] + ordem[20:23]}
    for chave, lista in sel.items():
        cur.execute("INSERT INTO colaborador_cert_selecoes (user_id, documentos, updated_at, notificar_email) "
                    "VALUES (%s,%s::jsonb,%s,true)", (U[chave], json.dumps(lista), AGORA - timedelta(days=5)))
    return carteiras


# ---------------------------------------------------------------- cofre

def gravar_cofre(plano: dict, atuais: list) -> dict:
    """PFX ficticios no cofre, cifrados com as chaves do ambiente de demo."""
    from app import cert_installer

    por_fp = {}
    validos = [c for c in plano["clientes"] if c["dias"] > 0]
    fora_do_cofre = {validos[-1]["doc"]}            # ainda nao enviado
    bloqueados = {validos[-2]["doc"], validos[-3]["doc"]}  # custodia desligada
    from app.cert_scanner import scan_folder

    infos = {str(c.path): c for c in scan_folder(ACERVO / "Clientes")}
    ids = {}
    for cli in validos:
        if cli["doc"] in fora_do_cofre or cli["doc"] in bloqueados:
            continue
        info = infos[str(cli["arquivo"])]
        senha = info.password_from_name
        rid = cert_installer.upsert_pfx(
            fingerprint=info.fingerprint_sha256, pfx_bytes=cli["arquivo"].read_bytes(), machine_id=MAQUINA_SERVIDOR,
            password=senha, nome_titular=info.nome_titular, documento=info.documento_numero,
            documento_tipo=info.documento_tipo, subject=info.subject,
            not_before=info.not_before.isoformat(), not_after=info.not_after.isoformat(),
            friendly_name=cli["nome"].title(),
        )
        ids[cli["doc"]] = {"id": rid, "fp": info.fingerprint_sha256, "nome": info.nome_titular}
    blq = []
    for cli in validos:
        if cli["doc"] in bloqueados:
            blq.append((MAQUINA_SERVIDOR, infos[str(cli["arquivo"])].fingerprint_sha256))
    return {"ids": ids, "bloqueados": blq, "fora": fora_do_cofre}


# ---------------------------------------------------------------- resto

def gravar_operacao(cur, U: dict, plano: dict, carteiras: dict, cofre: dict, atuais: list) -> None:
    # Bloqueios de custodia
    for maq, fp in cofre["bloqueados"]:
        cur.execute("INSERT INTO cert_vault_bloqueio (machine_id, fingerprint, motivo, bloqueado_por, bloqueado_em) "
                    "VALUES (%s,%s,%s,%s,%s)", (maq, fp, "Cliente pediu para não guardar no portal",
                                                 "admin.demo@exemplo.com", AGORA - timedelta(days=33)))

    # Computadores: dispositivos da bandeja + vinculos
    maquinas = {
        "colab": ("3c:52:82:1a:7f:01", "FISCAL-PC07"),
        "ana": ("3c:52:82:1a:7f:02", "FISCAL-PC08"),
        "gestor": ("3c:52:82:1a:7f:03", "FISCAL-NOTE01"),
        "carlos": ("3c:52:82:1a:7f:04", "CONTABIL-PC02"),
        "juliana": ("3c:52:82:1a:7f:05", "DP-PC01"),
    }
    for chave, (mac, nome) in maquinas.items():
        cur.execute(
            "INSERT INTO agent_devices (user_id, machine_id, nome, segredo_hash, criado_em, visto_em, versao) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (U[chave], mac, nome, secrets.token_hex(32), AGORA - timedelta(days=30),
             AGORA - timedelta(minutes=RNG.randint(1, 4)) if chave != "carlos" else AGORA - timedelta(days=3),
             "1.7.1" if chave != "juliana" else "1.6.1"),
        )
    vinc = [
        # (user, mac, nome, tipo, estado, expira, pedido_ha_h, decidido)
        ("colab", *maquinas["colab"], "principal", "ativo", None, 24 * 25, True),
        ("gestor", *maquinas["gestor"], "principal", "ativo", None, 24 * 24, True),
        ("carlos", *maquinas["carlos"], "principal", "ativo", None, 24 * 20, True),
        ("ana", *maquinas["ana"], "principal", "pendente", None, 2, False),
        ("juliana", *maquinas["juliana"], "emprestimo", "pendente", None, 1, False),
        ("ana", "3c:52:82:1a:7f:09", "FISCAL-PC03", "emprestimo", "encerrado", None, 24 * 12, True),
    ]
    for u, mac, nome, tipo, estado, expira, ha_h, decidido in vinc:
        pedido = AGORA - timedelta(hours=ha_h)
        cur.execute(
            "INSERT INTO computador_vinculo (user_id, machine_id, nome, tipo, estado, expira_em, pedido_em, "
            "decidido_por, decidido_em, encerrado_em, motivo) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (U[u], mac, nome, tipo, estado, expira, pedido,
             "admin.demo@exemplo.com" if decidido else "", pedido + timedelta(minutes=12) if decidido else None,
             pedido + timedelta(days=3) if estado == "encerrado" else None,
             "Prazo do empréstimo encerrado" if estado == "encerrado" else ""),
        )
        if estado == "ativo":
            cur.execute("INSERT INTO maquina_chave (machine_id, chave_hash, fixada_em, fixada_por) VALUES (%s,%s,%s,%s) "
                        "ON CONFLICT DO NOTHING", (mac, secrets.token_hex(32), pedido + timedelta(minutes=12), "admin.demo@exemplo.com"))
    # Credencial de maquina do servidor (agente da varredura)
    cur.execute("INSERT INTO machine_credentials (machine_id, segredo_hash, versao, criado_em, visto_em) VALUES (%s,%s,%s,%s,%s)",
                (MAQUINA_SERVIDOR, secrets.token_hex(32), "1.7.1", AGORA - timedelta(days=45), AGORA - timedelta(minutes=37)))

    # Trilha de instalacao: tokens + eventos
    def cadeia(user_key, email, mac, docs, ha_h, desfecho, detalhe=""):
        tid = str(uuid.uuid4())
        inicio = AGORA - timedelta(hours=ha_h)
        cids = [cofre["ids"][d]["id"] for d in docs if d in cofre["ids"]]
        if not cids:
            return
        cur.execute(
            "INSERT INTO install_token (id, token_hash, user_id, user_email, target_machine, certificate_ids, created_at, "
            "expires_at, consumed_at, client_ip) VALUES (%s,%s,%s,%s,%s,%s::uuid[],%s,%s,%s,%s)",
            (tid, secrets.token_hex(32), U[user_key], email, mac, cids, inicio, inicio + timedelta(minutes=5),
             inicio + timedelta(seconds=40) if desfecho != "incompleto" else None, "10.0.0.%d" % RNG.randint(20, 90)),
        )
        evs = [("SOLICITADO", "OK", "", 0)]
        if desfecho != "incompleto":
            evs.append(("REDIMIDO", "OK", "", 40))
            if desfecho == "concluido":
                evs.append(("CONCLUIDO", "OK", "", 75))
            else:
                evs.append(("ERRO", "FALHA", detalhe, 75))
        for ev, st, det, seg in evs:
            for cid in cids:
                cur.execute(
                    "INSERT INTO install_log (token_id, user_id, user_email, event, certificate_id, fingerprint, "
                    "target_machine, status, detail, client_ip, created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (tid, U[user_key], email, ev, cid,
                     next(v["fp"] for v in cofre["ids"].values() if v["id"] == cid),
                     mac, st, det or None, "10.0.0.31", inicio + timedelta(seconds=seg)),
                )

    cc = [d for d in carteiras["colab"] if d in cofre["ids"]]
    ca = [d for d in carteiras["ana"] if d in cofre["ids"]]
    ck = [d for d in carteiras["carlos"] if d in cofre["ids"]]
    tudo = list(cofre["ids"].keys())
    cadeia("colab", "colaborador.demo@exemplo.com", maquinas["colab"][0], cc[0:2], 3, "concluido")
    cadeia("colab", "colaborador.demo@exemplo.com", maquinas["colab"][0], cc[2:3], 26, "concluido")
    cadeia("colab", "colaborador.demo@exemplo.com", maquinas["colab"][0], cc[3:4], 50, "falhou",
           "Senha ausente no cofre")
    cadeia("colab", "colaborador.demo@exemplo.com", maquinas["colab"][0], cc[4:5], 52, "concluido")
    cadeia("gestor", "gestor.demo@exemplo.com", maquinas["gestor"][0], tudo[0:3], 75, "concluido")
    cadeia("gestor", "gestor.demo@exemplo.com", maquinas["gestor"][0], tudo[5:6], 120, "incompleto")
    cadeia("carlos", "carlos.lima@exemplo.com", maquinas["carlos"][0], ck[0:2], 170, "concluido")
    cadeia("carlos", "carlos.lima@exemplo.com", maquinas["carlos"][0], ck[2:3], 200, "falhou",
           "A estação não respondeu dentro do prazo do token")
    cadeia("admin", "admin.demo@exemplo.com", maquinas["gestor"][0], tudo[8:10], 300, "concluido")
    cadeia("ana", "ana.moreira@exemplo.com", maquinas["ana"][0], ca[0:1], 400, "concluido")

    # Atividade de login (Dashboard > Atividade)
    pessoas = [("admin", "admin.demo@exemplo.com"), ("gestor", "gestor.demo@exemplo.com"),
               ("colab", "colaborador.demo@exemplo.com"), ("ana", "ana.moreira@exemplo.com"),
               ("carlos", "carlos.lima@exemplo.com"), ("juliana", "juliana.prado@exemplo.com")]
    for d in range(29, -1, -1):
        for k, e in pessoas:
            quando_login = (AGORA - timedelta(days=d)).replace(hour=RNG.randint(8, 17), minute=RNG.randint(0, 59))
            if quando_login > AGORA:
                quando_login = AGORA - timedelta(minutes=RNG.randint(5, 300))
            if RNG.random() < 0.7:
                cur.execute("INSERT INTO user_activity (user_id, user_email, evento, client_ip, contexto, ocorrido_em) "
                            "VALUES (%s,%s,'login',%s,'{}'::jsonb,%s)",
                            (U[k], e, "10.0.0.%d" % RNG.randint(20, 90),
                             quando_login))
    for d in (2, 9, 17):
        cur.execute("INSERT INTO user_activity (user_id, user_email, evento, client_ip, contexto, ocorrido_em) "
                    "VALUES (%s,%s,'login_negado',%s,%s::jsonb,%s)",
                    (U["ana"], "ana.moreira@exemplo.com", "10.0.0.44", json.dumps({"motivo": "senha_incorreta"}),
                     AGORA - timedelta(days=d, hours=3)))

    # Alertas enviados (Acompanhamento > Enviados, Dashboard > Alertas)
    por_doc = {it.get("documento_numero"): it for it in atuais if it.get("fingerprint_sha256")}
    destinos = {"colab": "colaborador.demo@exemplo.com", "ana": "ana.moreira@exemplo.com",
                "carlos": "carlos.lima@exemplo.com", "juliana": "juliana.prado@exemplo.com"}
    for k, email in destinos.items():
        for d in carteiras[k]:
            it = por_doc.get(d)
            cli = next(c for c in plano["clientes"] if c["doc"] == d)
            if not it:
                continue
            dias = cli["dias"]
            if dias < 0:
                tipo, quando = "expired", AGORA + timedelta(days=dias, hours=9)
            elif dias <= 30:
                marco = 7 if dias <= 7 else (15 if dias <= 15 else 30)
                tipo, quando = f"expiring:{marco}", AGORA - timedelta(days=max(0, marco - dias), hours=-8)
            else:
                continue
            if quando < AGORA - timedelta(days=60):
                continue
            cur.execute("INSERT INTO sent_alerts (fingerprint_sha256, tipo_alerta, destinatario, data_validade, sent_at) "
                        "VALUES (%s,%s,%s,%s,%s)", (it["fingerprint_sha256"], tipo, email, it["not_after"], min(quando, AGORA)))
    for d in range(0, 20):
        dia = (AGORA - timedelta(days=d)).date().isoformat()
        cur.execute("INSERT INTO sent_alerts (fingerprint_sha256, tipo_alerta, destinatario, data_validade, sent_at) "
                    "VALUES ('__resumo_admin__',%s,'admin.demo@exemplo.com',%s,%s)",
                    (f"digest:{dia}", dia, min(AGORA, (AGORA - timedelta(days=d)).replace(hour=7, minute=2))))
    for cli in plano["novos"]:
        it = por_doc[cli["doc"]]
        for email in ("admin.demo@exemplo.com", "gestor.demo@exemplo.com"):
            cur.execute("INSERT INTO sent_alerts (fingerprint_sha256, tipo_alerta, destinatario, data_validade, sent_at) "
                        "VALUES (%s,'novo',%s,%s,%s)", (it["fingerprint_sha256"], email, it["not_after"],
                                                         AGORA - timedelta(days=cli["novo_ha"]) + timedelta(hours=1)))

    # Movimentos da entrada (Instalador > Movimentos)
    def evento(resultado, nome, doc, ha_h, origem="Entrada", destino="", novo="", motivo="", resolvido=True, na=None):
        tipo = "" if not doc else ("cpf" if len(doc) == 11 else "cnpj")
        cur.execute(
            "INSERT INTO entrada_eventos (id, machine_id, quando, resultado, motivo, arquivo_original, arquivo_novo, "
            "pasta_destino, nome, documento_numero, documento_tipo, fingerprint_sha256, not_after, resolvido_em, pasta_origem) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (str(uuid.uuid4()), MAQUINA_SERVIDOR, AGORA - timedelta(hours=ha_h), resultado, motivo,
             f"{nome.title()} certificado A1.pfx" if resultado != "pendente" else f"{nome.lower()} novo.pfx",
             novo, destino, nome, doc, tipo, secrets.token_hex(32), na,
             None, origem),
        )
    for cli in plano["novos"]:
        letra = cli["nome"][0]
        evento("movido", cli["nome"], cli["doc"], 24 * cli["novo_ha"],
               destino=f"{PASTA_EXIBIDA}/{letra}", novo=f"{cli['nome'].title()}_{cli['doc']}",
               na=AGORA + timedelta(days=cli["dias"]))
    for cli in plano["renovados"]:
        letra = cli["nome"][0]
        evento("substituiu", cli["nome"], cli["doc"], 24 * cli["renovado_ha"],
               destino=f"{PASTA_EXIBIDA}/{letra}", novo=f"{cli['nome'].title()}_{cli['doc']}",
               motivo="O certificado anterior foi para a pasta de vencidos",
               na=AGORA + timedelta(days=cli["dias"]))
    venc = [c for c in plano["clientes"] if c["dias"] < 0]
    evento("vencido", venc[0]["nome"], venc[0]["doc"], 24 * 3, destino=PASTA_VENCIDOS_EXIBIDA,
           novo=f"{venc[0]['nome'].title()}_{venc[0]['doc']}", na=AGORA - timedelta(days=3))
    evento("copia_descartada", plano["copia"]["nome"], plano["copia"]["doc"], 24 * 8,
           motivo="Arquivo idêntico ao que já está na pasta do cliente")
    evento("duplicidade", plano["dup_doc"][0]["nome"], plano["dup_doc"][0]["doc"], 24 * 10,
           motivo="Já existe outro certificado vigente para este documento")
    evento("pendente", "SEM NOME", "", 5, motivo="Senha incorreta: o arquivo não abriu", resolvido=False)
    evento("vencido_preso", venc[1]["nome"], venc[1]["doc"], 30, origem=f"{PASTA_EXIBIDA}/{venc[1]['nome'][0]}",
           motivo="Arquivo em uso: não foi possível mover para vencidos", resolvido=False,
           na=AGORA + timedelta(days=venc[1]["dias"]))

    # SIEG: estado por certificado + trilha
    ids = list(cofre["ids"].items())
    estados = ["no_sieg"] * 6 + ["erro", "substituido"]
    for (doc, v), est in zip(ids[:8], estados):
        quando = AGORA - timedelta(days=RNG.randint(2, 25))
        msg = {"erro": "O SIEG recusou: certificado com CNPJ divergente do cadastro da empresa",
               "substituido": "Substituído por um certificado mais novo do mesmo CNPJ"}.get(est, "")
        sid = str(RNG.randint(100000, 999999)) if est != "erro" else ""
        cur.execute("INSERT INTO sieg_inclusao (fingerprint, documento, nome, estado, sieg_id, solicitado_por, solicitado_em, "
                    "atualizado_em, mensagem) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (v["fp"], doc, v["nome"], est, sid, "gestor.demo@exemplo.com", quando, quando + timedelta(minutes=1), msg))
        cur.execute("INSERT INTO sieg_trilha (fingerprint, documento, nome, evento, por, em) VALUES (%s,%s,%s,'solicitado',%s,%s)",
                    (v["fp"], doc, v["nome"], "gestor.demo@exemplo.com", quando))
        if est == "erro":
            cur.execute("INSERT INTO sieg_trilha (fingerprint, documento, nome, evento, operacao, http_status, mensagem, por, em) "
                        "VALUES (%s,%s,%s,'erro','incluir',400,%s,%s,%s)",
                        (v["fp"], doc, v["nome"], msg, "gestor.demo@exemplo.com", quando + timedelta(minutes=1)))
        else:
            cur.execute("INSERT INTO sieg_trilha (fingerprint, documento, nome, evento, operacao, http_status, mensagem, sieg_id, por, em) "
                        "VALUES (%s,%s,%s,'incluido','incluir',200,'Certificado incluído',%s,%s,%s)",
                        (v["fp"], doc, v["nome"], sid, "gestor.demo@exemplo.com", quando + timedelta(minutes=1)))
        if est == "substituido":
            cur.execute("INSERT INTO sieg_trilha (fingerprint, documento, nome, evento, mensagem, por, em) "
                        "VALUES (%s,%s,%s,'substituido',%s,%s,%s)",
                        (v["fp"], doc, v["nome"], msg, "sistema", quando + timedelta(days=1)))
    cur.execute("INSERT INTO sieg_trilha (fingerprint, documento, nome, evento, mensagem, por, em) "
                "VALUES ('', '', '', 'sincronizado', '6 certificados conferidos no SIEG', 'admin.demo@exemplo.com', %s)",
                (AGORA - timedelta(days=1, hours=2),))

    # Permissoes: um ajuste com trilha
    cur.execute("UPDATE permissoes SET nivel='ler', alterado_em=%s, alterado_por='admin.demo@exemplo.com' "
                "WHERE papel='gestor' AND modulo='instalador'", (AGORA - timedelta(days=12),))
    cur.execute("INSERT INTO permissoes_trilha (papel, modulo, de, para, alterado_por, em) VALUES "
                "('gestor','instalador','nenhum','ler','admin.demo@exemplo.com',%s),"
                "('user','duplicidades','nenhum','ler','admin.demo@exemplo.com',%s)",
                (AGORA - timedelta(days=12), AGORA - timedelta(days=40)))

    # Configuracao
    cur.execute(
        "UPDATE portal_settings SET source_folder=%s, expired_folder=%s, machine_id=%s, updated_at=%s, "
        "smtp_host='smtp.exemplo.com', smtp_port=587, smtp_user='certificados@exemplo.com', smtp_use_tls=true, "
        "smtp_from_email='certificados@exemplo.com', smtp_alerts_enabled=true, "
        "alertas_destinatarios='admin.demo@exemplo.com', alertas_marcos='30,15,7,1', alertas_intervalo_horas=24, "
        "pasta_entrada=%s, pasta_pj=%s, pasta_pf=%s, install_token_ttl_min=5, trilha_retencao_dias=180 WHERE id=1",
        (PASTA_EXIBIDA.replace("/", "\\"), PASTA_VENCIDOS_EXIBIDA.replace("/", "\\"), MAQUINA_SERVIDOR, AGORA - timedelta(days=9),
         "D:\\Certificados-Demo\\Entrada", "D:\\Certificados-Demo\\Clientes", "D:\\Certificados-Demo\\Pessoas"),
    )


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    os.environ["PYTHONIOENCODING"] = "utf-8"
    amb = preparar_ambiente()
    sys.path.insert(0, str(REPO))
    os.chdir(REPO)
    print("1/5 banco e esquema")
    recriar_banco()
    print("2/5 acervo ficticio (PFX gerados por uma AC ficticia)")
    plano = montar_acervo()

    import psycopg

    with psycopg.connect(DSN, autocommit=False) as conn:
        with conn.cursor() as cur:
            print("3/5 inventario, historico, pessoas e carteiras")
            atuais, _ = gravar_inventario(cur, plano)
            U = gravar_pessoas(cur, amb["senha"])
            carteiras = gravar_carteiras(cur, U, plano)
        conn.commit()
    print("4/5 cofre")
    cofre = gravar_cofre(plano, atuais)
    with psycopg.connect(DSN, autocommit=False) as conn:
        with conn.cursor() as cur:
            print("5/5 computadores, trilhas, alertas, movimentos, SIEG, configuracao")
            gravar_operacao(cur, U, plano, carteiras, cofre, atuais)
        conn.commit()
        with conn.cursor() as cur:
            for t in ("users", "cert_snapshots", "cert_history", "cert_pfx_store", "carteira", "computador_vinculo",
                      "install_log", "sent_alerts", "entrada_eventos", "sieg_inclusao", "user_activity"):
                cur.execute(f"SELECT count(*) FROM {t}")
                print(f"   {t:22s} {cur.fetchone()[0]}")
    try:  # o cliente do portal (pool de conexoes) usado pelo cofre
        from app.settings_state import _banco

        cli = _banco()
        if cli is not None and hasattr(cli, "fechar"):
            cli.fechar()
    except Exception:  # noqa: BLE001
        pass
    print(f"Pronto. Credenciais em {CREDENCIAIS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
