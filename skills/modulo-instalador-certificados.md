# Módulo Instalador de Certificados Digitais

> Blueprint de arquitetura e implementação para um módulo que entrega, via executável
> com token efêmero, certificados digitais criptografados e os instala de forma
> **não-exportável** no repositório do Windows, com trilha de auditoria por usuário.

---

## 1. Objetivo

Adicionar ao portal existente uma funcionalidade em que o usuário autenticado:

1. Seleciona um ou mais certificados digitais que já constam no banco.
2. Em vez de baixar o `.pfx` diretamente, baixa um **executável instalador**.
3. Ao rodar o executável, ele:
   - autentica-se no servidor com um **token de uso único** (TTL ~5 min);
   - recebe os certificados **criptografados ponta a ponta**;
   - descriptografa em memória e os instala via CryptoAPI/linha de comando **marcados como não-exportáveis**;
   - reporta de volta o resultado.
4. Todo o fluxo gera **log por usuário**: quando foi solicitado e quais certificados foram efetivamente instalados.

Escopo: **módulo acoplável** a um portal e banco já existentes. Não reconstrói autenticação de usuário nem o cadastro de certificados — apenas consome o que já existe.

---

## 2. Premissas e decisões-chave

Antes da arquitetura, quatro decisões que definem tudo. Se alguma estiver errada para o seu caso, o desenho muda.

| # | Decisão | Recomendação | Por quê |
|---|---------|--------------|---------|
| 1 | Chave de descriptografia | **Efêmera, gerada no cliente a cada execução** — nunca embutida no `.exe` | O binário roda na máquina do usuário; qualquer segredo embutido é extraível |
| 2 | Onde descriptografar | **Em memória**, sem escrever `.pfx` em claro no disco | Reduz a janela de exposição do arquivo com a chave privada |
| 3 | Não-exportável | Marca via `X509KeyStorageFlags.NonExportable` / `certutil ... NoExport` | **Limitação honesta**: freio, não cofre — ver §9 |
| 4 | Assinatura do `.exe` | **Authenticode obrigatório** | Sem assinatura, SmartScreen/AV bloqueiam e derrubam a experiência |

---

## 3. Visão geral da arquitetura

```
┌────────────────────────────────────────────────────────────────────┐
│                         PORTAL (já existe)                          │
│  ┌──────────────┐   seleciona certs    ┌──────────────────────────┐ │
│  │  Front-end   │─────────────────────▶│  Módulo Instalador (API) │ │
│  │  (usuário)   │◀─────────────────────│  - gera token            │ │
│  └──────────────┘   baixa .exe + token │  - monta bundle cripto   │ │
│                                        │  - grava logs            │ │
│                                        └───────────┬──────────────┘ │
│                                                    │                │
│                            ┌───────────────────────┼──────────────┐ │
│                            │  Banco (já existe)     │              │ │
│                            │  + tabelas novas:      │              │ │
│                            │    install_token       │              │ │
│                            │    install_log         │              │ │
│                            └────────────────────────┘              │ │
└────────────────────────────────────────────────────────────────────┘
             ▲  (2) POST /redeem  { token, clientPubKey }
             │  (3) bundle criptografado
             ▼
┌────────────────────────────────────────────────────────────────────┐
│              INSTALADOR (.exe assinado, na máquina do user)         │
│  1. lê token embutido                                               │
│  2. gera par de chaves efêmero (ECDH/RSA)                          │
│  3. redeem → recebe bundle cripto                                  │
│  4. descriptografa em memória (AES-GCM)                            │
│  5. importa cada cert NÃO-EXPORTÁVEL no store do usuário           │
│  6. POST /report → thumbprints instalados + status                │
└────────────────────────────────────────────────────────────────────┘
```

---

## 4. Fluxo detalhado (sequência)

```
Usuário        Front-end          API do módulo         Banco         Instalador(.exe)
  │  seleciona     │                    │                 │                  │
  │───────────────▶│                    │                 │                  │
  │                │  POST /prepare     │                 │                  │
  │                │───────────────────▶│                 │                  │
  │                │                    │ cria token(TTL) │                  │
  │                │                    │────────────────▶│                  │
  │                │                    │ log SOLICITADO  │                  │
  │                │                    │────────────────▶│                  │
  │                │  URL do .exe+token │                 │                  │
  │                │◀───────────────────│                 │                  │
  │  baixa .exe    │                    │                 │                  │
  │◀───────────────│                    │                 │                  │
  │  executa ─────────────────────────────────────────────────────────────▶│
  │                │                    │  POST /redeem { token, pubKey }    │
  │                │                    │◀───────────────────────────────────│
  │                │                    │ valida+consome  │                  │
  │                │                    │────────────────▶│                  │
  │                │                    │ busca certs     │                  │
  │                │                    │────────────────▶│                  │
  │                │                    │ bundle cripto p/ pubKey            │
  │                │                    │───────────────────────────────────▶│
  │                │                    │                 │  instala não-exp │
  │                │                    │  POST /report { thumbprints,status}│
  │                │                    │◀───────────────────────────────────│
  │                │                    │ log CONCLUÍDO   │                  │
  │                │                    │────────────────▶│                  │
```

---

## 5. Modelo de segurança

### 5.1 Ameaças consideradas
- **Interceptação de rede** → TLS + criptografia de aplicação sobre o bundle.
- **Replay do token** → uso único + TTL curto + vínculo a usuário e IDs de certificado.
- **Segredo extraível do binário** → nenhuma chave de descriptografia no `.exe`; chave efêmera do cliente.
- **`.exe` adulterado / falsificado** → Authenticode; opcionalmente pin do certificado do servidor.
- **PFX em claro no disco** → descriptografia em memória.

### 5.2 Handshake de chave efêmera (o coração do desenho)

O instalador **não carrega segredo nenhum**. A cada execução:

1. Instalador gera um par de chaves efêmero (recomendado: **ECDH P-256** ou RSA-2048).
2. Envia a **chave pública** no `POST /redeem`, junto do token.
3. Servidor:
   - valida o token, busca os certificados,
   - gera uma **chave AES-256 aleatória** (CEK),
   - cifra cada `.pfx` com **AES-256-GCM**,
   - cifra a CEK para a **pública do cliente** (RSA-OAEP, ou ECDH+HKDF),
   - devolve `{ encryptedKey, iv, tag, ciphertext[] }`.
4. Instalador decifra a CEK com sua **privada efêmera** (que nunca saiu da memória do processo) e então decifra os PFX.

Resultado: mesmo quem capturar o tráfego ou o binário não tem como decifrar o bundle, porque a chave privada só existe na RAM daquela execução.

### 5.3 O que este desenho **não** garante
Ver §9. Em resumo: contra um **usuário administrador da própria máquina**, a não-exportabilidade em software é um obstáculo, não uma barreira criptográfica.

---

## 6. Banco de dados (tabelas novas)

Apenas duas tabelas. Assumindo que `users` e `certificates` já existem.

```sql
-- Token de uso único para uma sessão de instalação
CREATE TABLE install_token (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    token_hash      CHAR(64)      NOT NULL UNIQUE,   -- SHA-256 do token (nunca o token cru)
    user_id         BIGINT        NOT NULL REFERENCES users(id),
    certificate_ids BIGINT[]      NOT NULL,          -- certs autorizados nesta sessão
    created_at      TIMESTAMPTZ   NOT NULL DEFAULT now(),
    expires_at      TIMESTAMPTZ   NOT NULL,          -- created_at + 5 min
    consumed_at     TIMESTAMPTZ,                     -- NULL = ainda não usado
    client_ip       INET,
    user_agent      TEXT
);
CREATE INDEX idx_install_token_expires ON install_token(expires_at);

-- Trilha de auditoria: um registro por evento
CREATE TABLE install_log (
    id              BIGSERIAL PRIMARY KEY,
    token_id        UUID          REFERENCES install_token(id),
    user_id         BIGINT        NOT NULL REFERENCES users(id),
    event           TEXT          NOT NULL,          -- 'SOLICITADO' | 'REDIMIDO' | 'CONCLUIDO' | 'ERRO'
    certificate_id  BIGINT        REFERENCES certificates(id), -- NULL em eventos de sessão
    thumbprint      CHAR(40),                        -- preenchido no CONCLUIDO por cert
    status          TEXT,                            -- 'OK' | 'FALHA'
    detail          TEXT,
    client_ip       INET,
    created_at      TIMESTAMPTZ   NOT NULL DEFAULT now()
);
CREATE INDEX idx_install_log_user ON install_log(user_id, created_at);
```

> **Nota de segurança:** guarde só o **hash** do token (`token_hash`), nunca o token em claro.
> Assim, um vazamento do banco não permite redimir tokens.

Rotina de limpeza (cron/worker): `DELETE FROM install_token WHERE expires_at < now() - interval '1 day';`

---

## 7. API do módulo (endpoints)

Três endpoints. Prefixo sugerido: `/api/cert-installer`.

### 7.1 `POST /prepare` — (sessão autenticada do portal)
Gera o token e registra a solicitação.

**Request** (usuário já autenticado via sessão/JWT do portal):
```json
{ "certificateIds": [1023, 1099] }
```
**Regras:**
- Verificar que **todos** os `certificateIds` pertencem ao usuário logado.
- Gerar token aleatório (≥ 32 bytes, base64url). Guardar `SHA-256(token)`.
- `expires_at = now() + 5min`.
- Gravar `install_log(event='SOLICITADO')` para cada certificado.

**Response:**
```json
{
  "downloadUrl": "https://portal/api/cert-installer/download?t=<token>",
  "expiresAt": "2026-08-02T14:35:00Z"
}
```

### 7.2 `GET /download?t=<token>` — entrega o `.exe`
- Valida token (existe, não expirado, não consumido) — **sem** consumir ainda.
- Retorna o **mesmo binário assinado** para todos, com o token injetado.
  - Estratégia recomendada: binário genérico + token entregue como **recurso anexado** (ver §8.3), preservando a assinatura Authenticode.
- `Content-Disposition: attachment; filename="InstaladorCertificado.exe"`.

### 7.3 `POST /redeem` — (chamado pelo instalador)
Consome o token e devolve o bundle criptografado.

**Request:**
```json
{
  "token": "<token cru>",
  "clientPublicKey": "<SPKI base64>",
  "keyAlg": "ECDH-P256"
}
```
**Regras (em transação):**
- `SELECT ... FOR UPDATE` no token pelo `token_hash`.
- Rejeitar se: inexistente, expirado, ou `consumed_at IS NOT NULL`.
- Marcar `consumed_at = now()`.
- Buscar os PFX dos `certificate_ids`.
- Montar bundle criptografado (§5.2).
- Gravar `install_log(event='REDIMIDO')`.

**Response:**
```json
{
  "encryptedKey": "<CEK cifrada p/ clientPublicKey, base64>",
  "certificates": [
    {
      "certificateId": 1023,
      "friendlyName": "Fulano A1",
      "iv": "<base64>",
      "authTag": "<base64>",
      "ciphertext": "<PFX cifrado AES-256-GCM, base64>",
      "pfxPassword": "<opcional: senha do PFX, também dentro do bundle cifrado>"
    }
  ]
}
```

### 7.4 `POST /report` — (chamado pelo instalador ao final)
```json
{
  "token": "<token cru>",
  "results": [
    { "certificateId": 1023, "thumbprint": "AB12...", "status": "OK" },
    { "certificateId": 1099, "status": "FALHA", "detail": "chave já existe" }
  ]
}
```
- Aceitar report só para token já `REDIMIDO` (mesmo já consumido).
- Gravar `install_log(event='CONCLUIDO' | 'ERRO')` por certificado.

---

## 8. O instalador (.exe)

### 8.1 Stack recomendada
**.NET 8 / C#**, publicado como **single-file self-contained** para `win-x64`.
Motivos: acesso nativo ao repositório de certificados (`System.Security.Cryptography.X509Certificates`), criptografia na BCL, e assinatura Authenticode direta.

### 8.2 Esqueleto do fluxo

```csharp
using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;

class Program
{
    const string ApiBase = "https://portal/api/cert-installer";

    static async Task<int> Main()
    {
        try
        {
            // 1. Ler token embutido (recurso anexado ao binário)
            string token = TokenLoader.ReadEmbeddedToken();

            // 2. Par de chaves efêmero (só existe nesta execução)
            using var ecdh = ECDiffieHellman.Create(ECCurve.NamedCurves.nistP256);
            string clientPubKey = Convert.ToBase64String(ecdh.PublicKey.ExportSubjectPublicKeyInfo());

            // 3. Redeem
            var bundle = await Api.Redeem(ApiBase, token, clientPubKey);

            // 4. Derivar CEK a partir da privada efêmera + encryptedKey
            byte[] cek = KeyAgreement.UnwrapCek(ecdh, bundle.EncryptedKey);

            var results = new List<InstallResult>();
            foreach (var c in bundle.Certificates)
            {
                try
                {
                    // 5. Descriptografar PFX em memória (AES-256-GCM)
                    byte[] pfxBytes = AesGcmHelper.Decrypt(cek, c.Iv, c.AuthTag, c.Ciphertext);

                    // 6. Importar NÃO-EXPORTÁVEL
                    string thumb = CertInstaller.ImportNonExportable(pfxBytes, c.PfxPassword, c.FriendlyName);

                    // limpar o buffer do PFX imediatamente
                    CryptographicOperations.ZeroMemory(pfxBytes);

                    results.Add(new(c.CertificateId, thumb, "OK", null));
                }
                catch (Exception ex)
                {
                    results.Add(new(c.CertificateId, null, "FALHA", ex.Message));
                }
            }

            CryptographicOperations.ZeroMemory(cek);

            // 7. Reportar
            await Api.Report(ApiBase, token, results);
            Console.WriteLine("Instalação concluída.");
            return 0;
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine($"Erro: {ex.Message}");
            return 1;
        }
    }
}
```

### 8.3 Instalação não-exportável

**Opção A — nativo em C# (recomendado, sem tocar o disco):**
```csharp
static class CertInstaller
{
    public static string ImportNonExportable(byte[] pfx, string? password, string? friendlyName)
    {
        // NonExportable = chave privada não pode ser exportada pela API comum
        // PersistKeySet   = mantém a chave no store após o import
        var flags = X509KeyStorageFlags.UserKeySet
                  | X509KeyStorageFlags.PersistKeySet
                  | X509KeyStorageFlags.NonExportable;

        using var cert = X509CertificateLoader.LoadPkcs12(pfx, password, flags);
        if (!string.IsNullOrEmpty(friendlyName))
            cert.FriendlyName = friendlyName;

        using var store = new X509Store(StoreName.My, StoreLocation.CurrentUser);
        store.Open(OpenFlags.ReadWrite);
        store.Add(cert);
        store.Close();
        return cert.Thumbprint!;
    }
}
```

**Opção B — via linha de comando (`certutil`)**, caso você prefira o caminho CLI que mencionou:
```bat
certutil -f -user -p "SENHA_DO_PFX" -importpfx My "caminho\cert.pfx" NoExport
```
- `NoExport` marca a chave como **não-exportável**.
- `-user` instala no store do usuário atual (use `-enterprise`/omita para máquina).
- **Desvantagem:** exige o `.pfx` em disco por um instante → prefira a Opção A. Se usar B, grave em `%TEMP%` com ACL restrita e faça overwrite+delete logo após.

### 8.4 Injeção do token preservando a assinatura
Assinar o `.exe` **depois** de embutir o token quebraria a assinatura se o token variasse por download. Soluções:
- **(recomendada)** Token num **recurso appended** lido em runtime, fora da área coberta pela assinatura Authenticode (a assinatura fica num slot próprio do PE; dados anexados ao fim do arquivo não a invalidam se feitos corretamente). Assine uma vez o binário genérico; o servidor só concatena o token no download.
- **Alternativa simples:** entregar `Instalador.exe` + `token.dat` num `.zip`. Menos elegante, zero risco de invalidar assinatura.
- **Alternativa robusta:** token em nome de arquivo/URL e o instalador o recebe como **argumento** passado por um wrapper. (Requer o portal orquestrar o parâmetro.)

Comece pela alternativa do `.zip` (mais simples) e evolua para o recurso appended.

---

## 9. Limitações honestas (leia antes de prometer ao cliente)

- **Não-exportável ≠ inextraível.** A flag impede exportação pela API/UI comum, mas um **administrador local** com ferramentas específicas ainda pode extrair a chave de um provedor em **software**. Inextrabilidade real exige **hardware** (TPM, token/smartcard, ou chave em KSP de hardware). Se o requisito for "impedir que o próprio usuário copie o certificado", deixe claro que isso é um freio contra o usuário casual, não uma garantia criptográfica.
- **SmartScreen/AV.** Sem Authenticode (idealmente EV), o Windows exibirá avisos. Orçe o certificado de assinatura de código.
- **A senha do PFX** viaja dentro do bundle cifrado — correto — mas continua sendo o elo que dá acesso à chave. Trate o bundle como material altamente sensível em todos os logs (nunca logue conteúdo, só metadados).
- **Ambiente.** Todo o desenho assume **Windows**. macOS/Linux usam outro repositório de chaves (Keychain / NSS) e exigiriam um instalador próprio.

---

## 10. Build e assinatura

```bash
# Publicar single-file self-contained
dotnet publish -c Release -r win-x64 \
  -p:PublishSingleFile=true \
  -p:SelfContained=true \
  -p:IncludeNativeLibrariesForSelfExtract=true

# Assinar (Authenticode) — requer certificado de code signing
signtool sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 \
  /a bin\Release\net8.0\win-x64\publish\InstaladorCertificado.exe
```

Checklist de release:
- [ ] Certificado de **code signing** adquirido (EV reduz drasticamente avisos de SmartScreen).
- [ ] Binário assinado **e** com timestamp (assinatura sobrevive à expiração do cert).
- [ ] Testado em Windows 10 e 11, usuário padrão e com UAC.
- [ ] Verificado que a chave importada aparece como **não-exportável** (`certutil -store -user My`).

---

## 11. Integração com o portal existente

Pontos de contato mínimos — você **não** mexe no que já roda:

1. **Autenticação:** o endpoint `/prepare` reaproveita a sessão/JWT atual do portal. Só precisa de um middleware que resolva "quem é o usuário logado".
2. **Consulta de certificados:** `/redeem` usa a **consulta que você já tem** para buscar os PFX — encapsule numa interface `ICertificateRepository.GetPfx(certificateId)`.
3. **Banco:** roda só as duas migrations da §6.
4. **Front-end:** um botão "Baixar instalador" que chama `/prepare` e redireciona para `downloadUrl`.

---

## 12. Roteiro de implementação (fases)

**Fase 0 — Fundação (meio dia)**
- Migrations das tabelas `install_token` e `install_log`.
- Interface `ICertificateRepository` mapeando para sua consulta atual.

**Fase 1 — Backend do token (1–2 dias)**
- `/prepare`, `/download` (servindo `.exe` estático por enquanto), `/redeem`, `/report`.
- Logs SOLICITADO/REDIMIDO/CONCLUIDO.
- Testes de expiração e uso único.

**Fase 2 — Cripto ponta a ponta (1–2 dias)**
- Handshake ECDH + AES-256-GCM no servidor.
- Testes de round-trip cifra/decifra com um cliente de teste.

**Fase 3 — Instalador (2–3 dias)**
- App .NET: redeem → decifrar → importar não-exportável → report.
- Empacotamento `.zip` (token.dat) na primeira versão.

**Fase 4 — Assinatura e endurecimento (1–2 dias)**
- Authenticode, timestamp, testes em VM limpa.
- Zeroização de buffers, tratamento de erros, mensagens ao usuário.

**Fase 5 — Refinamento**
- Token via recurso appended (elimina o `.zip`).
- Rotina de limpeza de tokens expirados.
- Métricas/alertas de falha de instalação.

---

## 13. Decisões em aberto (preciso confirmar com você)

1. **Backend do portal:** qual linguagem/framework? (define se o código do servidor sai em C#/ASP.NET, Node, PHP, Python…)
2. **Banco:** PostgreSQL, SQL Server, MySQL? (ajusto tipos: `UUID[]`, `INET`, etc.)
3. **Formato dos certificados** no banco: PFX/PKCS#12 (`.pfx`/`.p12`) com senha? Estão cifrados em repouso hoje?
4. **Store de destino:** usuário atual (`CurrentUser\My`) ou máquina (`LocalMachine\My`)?
5. **Só Windows** ou precisa de macOS/Linux também?

Respondendo esses cinco, eu já gero o código real da Fase 1 no seu stack.
