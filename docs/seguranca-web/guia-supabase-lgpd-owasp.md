# Guia Completo de Segurança: Supabase + LGPD/ANPD + OWASP Dependency-Check

> **Versão:** 1.0 — Maio/2026
> **Stack de referência:** Next.js 14+, Supabase (PostgreSQL + Auth + Edge Functions), Vercel
> **Base normativa:** LGPD (Lei 13.709/2018), Resoluções ANPD 2024, OWASP Top 10 2025

---

## Sumário

1. [Supabase Security — Segurança no Banco de Dados](#1-supabase-security)
   - 1.1 Row Level Security (RLS)
   - 1.2 Gerenciamento de Chaves de API
   - 1.3 Segurança de Autenticação
   - 1.4 Segurança de Edge Functions
   - 1.5 Configuração do Data API
   - 1.6 Monitoramento e Auditoria
   - 1.7 Checklist Supabase
2. [ANPD — Boas Práticas LGPD para Sistemas Web](#2-anpd--lgpd)
   - 2.1 Princípios Fundamentais da LGPD
   - 2.2 Bases Legais para Tratamento
   - 2.3 Medidas Técnicas Exigidas
   - 2.4 Comunicação de Incidentes (Resolução CD/ANPD nº 15/2024)
   - 2.5 Direitos dos Titulares
   - 2.6 Privacy by Design aplicado ao Next.js/Supabase
   - 2.7 Checklist LGPD
3. [OWASP Dependency-Check — Auditoria de Dependências](#3-owasp-dependency-check)
   - 3.1 O que é e por que é crítico
   - 3.2 Instalação e Configuração
   - 3.3 Integração com GitHub Actions (CI/CD)
   - 3.4 npm audit — Camada nativa de auditoria
   - 3.5 Interpretando os Relatórios
   - 3.6 Gestão de Vulnerabilidades em Dependências
   - 3.7 Checklist Supply Chain
4. [Matriz de Prioridade Unificada](#4-matriz-de-prioridade-unificada)
5. [Referências](#5-referências)

---

## 1. Supabase Security

### 1.1 Row Level Security (RLS)

O RLS (Row Level Security) é a camada de segurança mais crítica do Supabase. Sem ele, qualquer pessoa que obtiver sua `anon key` poderá ler e modificar todos os dados da sua schema pública via Data API (PostgREST).

> **Regra absoluta:** Toda tabela criada na schema `public` DEVE ter RLS habilitado antes de ir para produção.

#### Habilitando o RLS

```sql
-- Habilitar RLS em uma tabela
ALTER TABLE public.alvaras ENABLE ROW LEVEL SECURITY;

-- Verificar quais tabelas ainda NÃO têm RLS habilitado
SELECT schemaname, tablename, rowsecurity
FROM pg_tables
WHERE schemaname = 'public'
  AND rowsecurity = false;
```

> **Atenção:** Se você habilitar RLS em uma tabela sem criar nenhuma política, o comportamento padrão do PostgreSQL é **negar todo acesso** — nem usuários autenticados conseguirão ler dados. Sempre crie ao menos uma política após habilitar.

---

#### Padrões de Políticas RLS

**Padrão 1 — Usuário só vê seus próprios dados (mais comum)**

```sql
-- SELECT: usuário lê apenas suas próprias linhas
CREATE POLICY "usuario_ve_proprios_dados"
ON public.empresas
FOR SELECT
TO authenticated
USING ((SELECT auth.uid()) = user_id);

-- INSERT: usuário só cria registros em seu nome
CREATE POLICY "usuario_insere_proprio"
ON public.empresas
FOR INSERT
TO authenticated
WITH CHECK ((SELECT auth.uid()) = user_id);

-- UPDATE: usuário só altera seus próprios registros
CREATE POLICY "usuario_atualiza_proprio"
ON public.empresas
FOR UPDATE
TO authenticated
USING ((SELECT auth.uid()) = user_id)
WITH CHECK ((SELECT auth.uid()) = user_id);

-- DELETE: usuário só exclui seus próprios registros
CREATE POLICY "usuario_exclui_proprio"
ON public.empresas
FOR DELETE
TO authenticated
USING ((SELECT auth.uid()) = user_id);
```

**Padrão 2 — Leitura pública, escrita autenticada**

```sql
-- Qualquer visitante pode ler (ex: catálogo público de alvarás)
CREATE POLICY "leitura_publica"
ON public.alvaras
FOR SELECT
TO anon, authenticated
USING (true);

-- Apenas autenticados podem criar
CREATE POLICY "escrita_autenticada"
ON public.alvaras
FOR INSERT
TO authenticated
WITH CHECK (true);
```

**Padrão 3 — Acesso baseado em papel (RBAC) via JWT claims**

```sql
-- Apenas usuários com papel 'admin' no JWT podem ver tudo
CREATE POLICY "admin_acesso_total"
ON public.alvaras
FOR ALL
TO authenticated
USING (
  (SELECT auth.jwt() ->> 'role') = 'admin'
);

-- Usuários comuns veem apenas alvarás da própria empresa
CREATE POLICY "usuario_ve_propria_empresa"
ON public.alvaras
FOR SELECT
TO authenticated
USING (
  empresa_id IN (
    SELECT id FROM public.empresas
    WHERE user_id = (SELECT auth.uid())
  )
);
```

> **Cuidado com `user_metadata`:** Nunca baseie políticas RLS no campo `user_metadata` do JWT — ele pode ser modificado pelo próprio usuário autenticado. Use apenas `auth.uid()` e claims do servidor.

---

#### Segurança em Views

Em PostgreSQL 15+, views têm `security definer` por padrão, o que significa que bypassam o RLS. Para corrigir:

```sql
-- Forçar a view a respeitar o RLS do usuário atual (PostgreSQL 15+)
CREATE VIEW public.alvaras_view
WITH (security_invoker = true)
AS
SELECT * FROM public.alvaras;
```

Em versões anteriores, revogue o acesso das roles `anon` e `authenticated` à view, ou mova-a para uma schema não exposta.

---

#### Índices para Performance com RLS

Sem índices corretos, o RLS pode transformar queries rápidas em varreduras completas de tabela.

```sql
-- Sempre indexe a coluna usada na cláusula USING das políticas
CREATE INDEX idx_alvaras_user_id ON public.alvaras (user_id);
CREATE INDEX idx_alvaras_empresa_id ON public.alvaras (empresa_id);
CREATE INDEX idx_empresas_user_id ON public.empresas (user_id);
```

---

#### Testando Políticas RLS

> **Nunca teste RLS pelo SQL Editor do Supabase Studio** — ele executa com permissão de superusuário e bypassa todas as políticas.

```sql
-- Simular consulta como usuário específico (substitua o UUID)
SET LOCAL role = authenticated;
SET LOCAL request.jwt.claims = '{"sub": "uuid-do-usuario-aqui", "role": "authenticated"}';

SELECT * FROM public.alvaras;

-- Resetar ao final
RESET role;
```

Use o **Supabase Studio → Impersonation** para testar como usuários reais via interface.

---

#### Privilégios de Coluna (complemento ao RLS)

O RLS controla linhas; privilégios de coluna controlam colunas. Use ambos para dados sensíveis:

```sql
-- Permitir que autenticados vejam tudo, EXCETO CPF e dados bancários
GRANT SELECT (id, razao_social, cnpj, status, created_at) ON public.empresas TO authenticated;

-- Apenas a role 'admin' vê colunas sensíveis
GRANT SELECT ON public.empresas TO admin_role;
```

---

### 1.2 Gerenciamento de Chaves de API

O Supabase possui dois tipos principais de chaves JWT:

| Chave | Nível de Acesso | Onde usar |
|---|---|---|
| `anon key` | Acesso público, sujeito ao RLS | Frontend (seguro com RLS ativado) |
| `service_role key` | Bypassa RLS completamente | **Somente no servidor/backend** |

> **Regra crítica:** A `service_role key` NUNCA deve aparecer em código de frontend, variáveis `NEXT_PUBLIC_*`, repositórios Git, logs ou qualquer lugar acessível ao cliente.

#### Configuração correta no Next.js

```bash
# .env.local — variáveis de ambiente
# ✅ Seguro — exposta ao cliente (sem acesso privilegiado)
NEXT_PUBLIC_SUPABASE_URL=https://seu-projeto.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=eyJhbGci...

# ✅ Seguro — disponível APENAS no servidor (sem prefixo NEXT_PUBLIC_)
SUPABASE_SERVICE_ROLE_KEY=eyJhbGci...
```

```typescript
// lib/supabase/client.ts — Uso no frontend (Server Components e Client Components)
import { createBrowserClient } from '@supabase/ssr'

export function createClient() {
  return createBrowserClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!
  )
}

// lib/supabase/admin.ts — Uso EXCLUSIVO no servidor (Route Handlers, Server Actions)
import { createClient } from '@supabase/supabase-js'

export function createAdminClient() {
  return createClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.SUPABASE_SERVICE_ROLE_KEY!, // NUNCA expor ao cliente
    { auth: { autoRefreshToken: false, persistSession: false } }
  )
}
```

---

### 1.3 Segurança de Autenticação

#### Configurações recomendadas no Supabase Auth

No painel Supabase → Authentication → Settings:

- **Site URL:** defina exatamente o domínio de produção (ex: `https://operacao.seusite.com.br`)
- **Redirect URLs:** liste apenas URLs explícitas e autorizadas; nunca use wildcards (`*`) em produção
- **JWT expiry:** reduza para 3600 segundos (1 hora) em vez do padrão de 1 semana para sistemas sensíveis
- **Password strength:** habilite verificação de força de senha

#### Proteção de rotas no Next.js com Supabase Auth

```typescript
// middleware.ts — Proteção de rotas autenticadas
import { createServerClient } from '@supabase/ssr'
import { NextResponse } from 'next/server'
import type { NextRequest } from 'next/server'

export async function middleware(request: NextRequest) {
  let supabaseResponse = NextResponse.next({ request })

  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() { return request.cookies.getAll() },
        setAll(cookiesToSet) {
          cookiesToSet.forEach(({ name, value, options }) =>
            supabaseResponse.cookies.set(name, value, options)
          )
        },
      },
    }
  )

  const { data: { user } } = await supabase.auth.getUser()

  // Redirecionar para login se não autenticado
  if (!user && request.nextUrl.pathname.startsWith('/dashboard')) {
    return NextResponse.redirect(new URL('/login', request.url))
  }

  return supabaseResponse
}

export const config = {
  matcher: ['/dashboard/:path*', '/api/admin/:path*'],
}
```

#### Cookies de sessão seguros

Configure cookies com atributos de segurança adequados:

```typescript
// Configuração de cookies de autenticação
{
  name: 'sb-auth-token',
  value: session.access_token,
  httpOnly: true,   // Impede acesso via JavaScript (proteção XSS)
  secure: true,     // Apenas HTTPS
  sameSite: 'lax',  // Proteção CSRF
  maxAge: 3600,     // 1 hora
  path: '/',
}
```

---

### 1.4 Segurança de Edge Functions

Edge Functions executam no servidor e têm acesso privilegiado. Proteja-as corretamente:

```typescript
// supabase/functions/processar-alvara/index.ts
import { serve } from 'https://deno.land/std@0.177.0/http/server.ts'
import { createClient } from 'https://esm.sh/@supabase/supabase-js@2'

serve(async (req) => {
  // 1. Verificar autenticação — SEMPRE valide o JWT de entrada
  const authHeader = req.headers.get('Authorization')
  if (!authHeader) {
    return new Response('Unauthorized', { status: 401 })
  }

  // 2. Use o token do usuário, não a service_role key
  //    Isso garante que o RLS seja respeitado
  const supabase = createClient(
    Deno.env.get('SUPABASE_URL')!,
    Deno.env.get('SUPABASE_ANON_KEY')!,
    { global: { headers: { Authorization: authHeader } } }
  )

  const { data: { user }, error } = await supabase.auth.getUser()
  if (error || !user) {
    return new Response('Unauthorized', { status: 401 })
  }

  // 3. Validar input antes de qualquer operação
  const body = await req.json()
  if (!body.empresa_id || typeof body.empresa_id !== 'string') {
    return new Response('Bad Request', { status: 400 })
  }

  // ... lógica de negócio
})
```

> **Nunca coloque** `SUPABASE_SERVICE_ROLE_KEY` em variáveis de Edge Functions acessíveis via cliente.

---

### 1.5 Configuração do Data API

O Supabase expõe automaticamente uma API REST (PostgREST) e GraphQL para tabelas da schema `public`. Se seu sistema for uma aplicação com backend dedicado (Next.js API Routes/Server Actions), considere:

**Opção A — Restringir a schema exposta**

No painel: Settings → API → Schema exposta → adicione apenas schemas que precisam de acesso direto.

**Opção B — Desabilitar o Data API completamente**

Se toda a lógica de acesso passar pelo Next.js (Server Actions, Route Handlers), você pode desabilitar a API pública:

Settings → API → Disable the Data API.

Isso transforma o Supabase em um PostgreSQL gerenciado puro, acessado apenas via conexão direta ou connection pooler.

---

### 1.6 Monitoramento e Auditoria

#### Habilitando logs de auditoria

```sql
-- Criar tabela de auditoria para operações críticas
CREATE TABLE audit_log (
  id          UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  user_id     UUID REFERENCES auth.users(id),
  action      TEXT NOT NULL,
  table_name  TEXT NOT NULL,
  record_id   TEXT,
  old_data    JSONB,
  new_data    JSONB,
  ip_address  INET,
  created_at  TIMESTAMPTZ DEFAULT now()
);

-- Aplicar RLS na própria tabela de auditoria
ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY;

-- Apenas admins leem logs
CREATE POLICY "apenas_admin_le_logs"
ON audit_log FOR SELECT
TO authenticated
USING ((SELECT auth.jwt() ->> 'role') = 'admin');

-- Trigger para registrar alterações em tabela crítica
CREATE OR REPLACE FUNCTION registrar_auditoria()
RETURNS TRIGGER AS $$
BEGIN
  INSERT INTO audit_log (user_id, action, table_name, record_id, old_data, new_data)
  VALUES (
    auth.uid(),
    TG_OP,
    TG_TABLE_NAME,
    COALESCE(NEW.id::TEXT, OLD.id::TEXT),
    CASE WHEN TG_OP = 'DELETE' THEN row_to_json(OLD)::JSONB ELSE NULL END,
    CASE WHEN TG_OP IN ('INSERT', 'UPDATE') THEN row_to_json(NEW)::JSONB ELSE NULL END
  );
  RETURN COALESCE(NEW, OLD);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Aplicar trigger em tabela crítica
CREATE TRIGGER auditoria_alvaras
AFTER INSERT OR UPDATE OR DELETE ON public.alvaras
FOR EACH ROW EXECUTE FUNCTION registrar_auditoria();
```

---

### 1.7 Checklist Supabase

```
[ ] RLS habilitado em TODAS as tabelas da schema public
[ ] Políticas RLS criadas para SELECT, INSERT, UPDATE e DELETE por tabela
[ ] Nenhuma política usa user_metadata como base de autorização
[ ] Índices criados nas colunas referenciadas pelas políticas RLS
[ ] Views com security_invoker = true (PostgreSQL 15+)
[ ] service_role key ausente de qualquer código de frontend
[ ] service_role key ausente de variáveis NEXT_PUBLIC_*
[ ] Redirect URLs explícitas (sem wildcards) no Supabase Auth
[ ] JWT expiry configurado adequadamente (máx 1h para sistemas sensíveis)
[ ] Cookies de sessão com HttpOnly, Secure e SameSite configurados
[ ] Edge Functions validam JWT de entrada antes de qualquer operação
[ ] Backup automático configurado com teste de restauração periódico
[ ] Tabela de auditoria para operações críticas
[ ] Data API configurada apenas para schemas necessárias
```

---

## 2. ANPD / LGPD

### 2.1 Princípios Fundamentais da LGPD

A Lei 13.709/2018 (LGPD) exige que todo tratamento de dados pessoais respeite dez princípios definidos no Art. 6º. Para sistemas web, os mais críticos são:

| Princípio | O que significa na prática |
|---|---|
| **Finalidade** | Colete apenas dados com propósito específico, explícito e legítimo |
| **Adequação** | Os dados coletados devem ser compatíveis com a finalidade declarada |
| **Necessidade** | Colete o mínimo necessário — evite campos opcionais sem propósito |
| **Livre Acesso** | O titular pode consultar seus dados a qualquer momento |
| **Qualidade** | Mantenha dados exatos e atualizados |
| **Transparência** | Informe claramente como os dados são usados |
| **Segurança** | Adote medidas técnicas e administrativas contra acessos não autorizados |
| **Prevenção** | Aja preventivamente para evitar danos ao titular |
| **Não Discriminação** | Proíbe o uso de dados para fins discriminatórios |
| **Responsabilização** | Demonstre ativamente a conformidade (accountability) |

---

### 2.2 Bases Legais para Tratamento

Antes de coletar qualquer dado pessoal, identifique a base legal (Art. 7º da LGPD):

```
┌─────────────────────────────────────────────────────────────────┐
│                     BASES LEGAIS LGPD                           │
├─────────────────┬───────────────────────────────────────────────┤
│ Consentimento   │ Manifestação livre, informada e inequívoca     │
│                 │ → Use quando não há outra base mais adequada   │
├─────────────────┼───────────────────────────────────────────────┤
│ Contrato        │ Necessário para execução de contrato           │
│                 │ → Ex: CPF/CNPJ para emissão de nota fiscal     │
├─────────────────┼───────────────────────────────────────────────┤
│ Obrigação Legal │ Exigido por lei ou regulação                   │
│                 │ → Ex: dados contábeis exigidos pela Receita    │
├─────────────────┼───────────────────────────────────────────────┤
│ Legítimo        │ Interesses legítimos do controlador            │
│ Interesse       │ → Requer teste de balanceamento documentado    │
│                 │ (Guia ANPD, fevereiro/2024)                   │
├─────────────────┼───────────────────────────────────────────────┤
│ Proteção ao     │ Saúde, segurança do titular ou de terceiros    │
│ Crédito         │ → Exclusivo para entidades de proteção crédito │
└─────────────────┴───────────────────────────────────────────────┘
```

> **Dados sensíveis** (Art. 11 — origem racial, saúde, biometria, religião, vida sexual, etc.) exigem base legal mais restrita: consentimento explícito ou obrigação legal. Tratá-los sem base adequada é infração grave sujeita à multa de até 2% do faturamento (máx. R$ 50 milhões por infração).

---

### 2.3 Medidas Técnicas Exigidas

A LGPD (Art. 46 e 49) e o Guia da ANPD estabelecem medidas técnicas e administrativas obrigatórias:

#### Criptografia e Proteção de Dados

```typescript
// ✅ Dados em trânsito — sempre HTTPS (TLS 1.2+)
// Configurar no next.config.ts

// ✅ Dados sensíveis em repouso — criptografia antes de armazenar
import { createCipheriv, createDecipheriv, randomBytes } from 'crypto'

const ALGORITHM = 'aes-256-gcm'
const KEY = Buffer.from(process.env.ENCRYPTION_KEY!, 'hex') // 32 bytes

export function encryptData(plaintext: string): string {
  const iv = randomBytes(16)
  const cipher = createCipheriv(ALGORITHM, KEY, iv)
  const encrypted = Buffer.concat([cipher.update(plaintext, 'utf8'), cipher.final()])
  const authTag = cipher.getAuthTag()
  return `${iv.toString('hex')}:${authTag.toString('hex')}:${encrypted.toString('hex')}`
}

export function decryptData(ciphertext: string): string {
  const [ivHex, authTagHex, encryptedHex] = ciphertext.split(':')
  const iv = Buffer.from(ivHex, 'hex')
  const authTag = Buffer.from(authTagHex, 'hex')
  const encrypted = Buffer.from(encryptedHex, 'hex')
  const decipher = createDecipheriv(ALGORITHM, KEY, iv)
  decipher.setAuthTag(authTag)
  return Buffer.concat([decipher.update(encrypted), decipher.final()]).toString('utf8')
}
```

#### Pseudonimização e Anonimização no PostgreSQL

```sql
-- Pseudonimização: substitui identificadores por tokens reversíveis
-- Use para logs e analytics onde o ID real não é necessário
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Função para gerar hash de CPF para analytics (irreversível)
CREATE OR REPLACE FUNCTION anonimizar_cpf(cpf TEXT)
RETURNS TEXT AS $$
  SELECT encode(digest(cpf || current_setting('app.hash_salt'), 'sha256'), 'hex')
$$ LANGUAGE SQL IMMUTABLE;

-- View anonimizada para relatórios
CREATE VIEW relatorios_anonimizados AS
SELECT
  anonimizar_cpf(cpf) AS cpf_hash,
  DATE_TRUNC('month', created_at) AS mes_cadastro,
  uf,
  COUNT(*) AS total_alvaras
FROM empresas
GROUP BY 1, 2, 3;
```

#### Controle de Acesso Mínimo

```sql
-- Princípio do menor privilégio — cada role acessa apenas o necessário
-- Role para relatórios (somente leitura em tabelas específicas)
CREATE ROLE relatorio_role;
GRANT USAGE ON SCHEMA public TO relatorio_role;
GRANT SELECT (id, razao_social, uf, status, created_at) ON public.empresas TO relatorio_role;

-- Role para operador (sem DELETE, sem acesso a colunas sensíveis)
CREATE ROLE operador_role;
GRANT USAGE ON SCHEMA public TO operador_role;
GRANT SELECT, INSERT, UPDATE ON public.alvaras TO operador_role;
REVOKE DELETE ON public.alvaras FROM operador_role;
```

---

### 2.4 Comunicação de Incidentes (Resolução CD/ANPD nº 15/2024)

A Resolução nº 15 de abril de 2024 regulamenta os prazos e o processo de comunicação de incidentes de segurança que envolvam dados pessoais.

#### Prazos obrigatórios

```
Descoberta do incidente
         │
         ▼
    ┌──────────┐
    │  72h     │ ──→ Comunicação PRELIMINAR à ANPD
    │ (3 dias) │     (via portal gov.br/anpd)
    └──────────┘
         │
         ▼
    ┌──────────┐
    │   5 dias │ ──→ Notificação aos TITULARES afetados
    └──────────┘     (direta e individualizada quando possível)
         │
         ▼
    ┌──────────┐
    │  30 dias │ ──→ Relatório COMPLETO à ANPD com:
    └──────────┘     - Natureza dos dados
                     - Número de titulares afetados
                     - Medidas de mitigação adotadas
                     - Análise de risco
```

> **Atenção:** O não cumprimento dos prazos foi causa de sanção administrativa em casos investigados pela ANPD em 2024. A comunicação tardia é tratada como agravante na dosimetria das multas.

#### Plano de Resposta a Incidentes — Modelo Básico

```markdown
## Plano de Resposta a Incidentes de Dados Pessoais

### 1. Identificação e Classificação
- [ ] Identificar o tipo de incidente (vazamento, acesso indevido, perda, etc.)
- [ ] Classificar o risco (Alto / Médio / Baixo) para os titulares
- [ ] Registrar: data/hora da descoberta, sistemas afetados, dados envolvidos

### 2. Contenção (primeiras horas)
- [ ] Isolar sistemas comprometidos
- [ ] Revogar acessos suspeitos
- [ ] Preservar evidências (logs, backups)
- [ ] Acionar responsável pelo DPO / Encarregado

### 3. Comunicação (até 72h da descoberta)
- [ ] Preencher formulário de comunicação preliminar à ANPD
- [ ] Notificar titulares afetados (até 5 dias úteis)
- [ ] Comunicar internamente (TI, Jurídico, Diretoria)

### 4. Investigação e Remediação
- [ ] Análise forense dos logs
- [ ] Identificação da causa raiz
- [ ] Implementação de correções
- [ ] Atualização das políticas e controles

### 5. Relatório Final (até 30 dias)
- [ ] Elaborar relatório completo para a ANPD
- [ ] Documentar lições aprendidas
- [ ] Atualizar o RIPD se necessário
```

---

### 2.5 Direitos dos Titulares

Os titulares de dados têm direitos garantidos pelo Art. 18 da LGPD. Implemente endpoints para atendê-los:

```typescript
// app/api/privacidade/[acao]/route.ts
// Endpoint para atender direitos dos titulares

import { NextRequest, NextResponse } from 'next/server'
import { createAdminClient } from '@/lib/supabase/admin'

export async function POST(
  request: NextRequest,
  { params }: { params: { acao: string } }
) {
  // Validar autenticação do titular
  const authHeader = request.headers.get('authorization')
  // ... validar token ...

  const supabase = createAdminClient()

  switch (params.acao) {
    case 'acesso':
      // Art. 18, I — Confirmação e acesso aos dados
      const { data } = await supabase
        .from('empresas')
        .select('*')
        .eq('user_id', userId)
      return NextResponse.json({ dados: data })

    case 'correcao':
      // Art. 18, III — Correção de dados incompletos ou incorretos
      const updates = await request.json()
      await supabase.from('empresas').update(updates).eq('user_id', userId)
      return NextResponse.json({ mensagem: 'Dados atualizados' })

    case 'exclusao':
      // Art. 18, VI — Eliminação dos dados (quando a base for consentimento)
      await supabase.from('empresas').delete().eq('user_id', userId)
      await supabase.auth.admin.deleteUser(userId)
      return NextResponse.json({ mensagem: 'Dados eliminados' })

    case 'portabilidade':
      // Art. 18, V — Portabilidade (exportar dados em formato interoperável)
      const { data: dadosExportar } = await supabase
        .from('empresas')
        .select('*')
        .eq('user_id', userId)
      // Retornar como JSON estruturado (pode ser CSV conforme solicitado)
      return new NextResponse(JSON.stringify(dadosExportar), {
        headers: {
          'Content-Type': 'application/json',
          'Content-Disposition': 'attachment; filename="meus-dados.json"'
        }
      })

    default:
      return NextResponse.json({ erro: 'Ação não reconhecida' }, { status: 400 })
  }
}
```

---

### 2.6 Privacy by Design Aplicado ao Next.js/Supabase

Os 7 princípios de Privacy by Design aplicados ao seu stack:

```
1. PROATIVO, NÃO REATIVO
   → Habilite RLS e defina políticas ANTES de criar as tabelas em produção
   → Use migrations versionadas com controles de segurança embutidos

2. PRIVACIDADE COMO PADRÃO (Privacy by Default)
   → Campos opcionais devem ser NULL por padrão, não strings vazias
   → Logs não devem capturar dados pessoais por padrão
   → Cookies de sessão com HttpOnly e Secure por padrão

3. PRIVACIDADE EMBUTIDA NO DESIGN
   → Separe dados pessoais em tabelas específicas com RLS próprio
   → Use UUIDs em vez de IDs sequenciais (evita enumeração)
   → Criptografe dados sensíveis antes de armazenar

4. FUNCIONALIDADE COMPLETA (não trade-off)
   → RLS não deve reduzir funcionalidades — projete políticas corretas
   → Segurança não deve ser desculpa para UX ruim

5. SEGURANÇA PONTA A PONTA
   → TLS em trânsito (Supabase gerencia) + criptografia em repouso (sua responsabilidade)
   → JWT com expiração curta + refresh token rotativo

6. VISIBILIDADE E TRANSPARÊNCIA
   → Política de Privacidade acessível e em linguagem clara
   → Logs de auditoria visíveis ao DPO
   → Titulares podem ver e exportar seus dados

7. RESPEITO PELA PRIVACIDADE DO USUÁRIO
   → Formulários com apenas campos necessários
   → Consentimento granular (não "aceitar tudo")
   → Fácil revogação de consentimento
```

---

### 2.7 Checklist LGPD

```
BASES LEGAIS
[ ] Cada campo coletado tem base legal documentada
[ ] Consentimentos são granulares, explícitos e revogáveis
[ ] Teste de balanceamento documentado para Legítimo Interesse
[ ] Dados sensíveis têm base legal específica (Art. 11)

SEGURANÇA TÉCNICA
[ ] Todos os dados pessoais em trânsito protegidos por TLS 1.2+
[ ] Dados sensíveis criptografados em repouso (AES-256)
[ ] Controle de acesso baseado no princípio do menor privilégio
[ ] Logs de auditoria para operações em dados pessoais
[ ] Pseudonimização aplicada em analytics e relatórios

DIREITOS DOS TITULARES
[ ] Endpoint de consulta de dados próprios implementado
[ ] Endpoint de correção de dados implementado
[ ] Endpoint de exclusão de dados implementado
[ ] Endpoint de portabilidade (exportação) implementado
[ ] Prazo de atendimento: até 15 dias (Art. 18, §3°)

GOVERNANÇA
[ ] Encarregado (DPO) designado e identificado na Política de Privacidade
[ ] Inventário/Mapeamento de dados pessoais (RIPD) elaborado
[ ] Plano de resposta a incidentes documentado
[ ] Comunicação à ANPD em até 72h após descoberta de incidente
[ ] Notificação a titulares em até 5 dias úteis
[ ] Política de Privacidade publicada e acessível

CONTRATOS
[ ] Contratos de operadores (Supabase, Vercel, etc.) com cláusulas de proteção de dados
[ ] Verificação se fornecedores são certificados para transferência internacional (ANPD nº 19/2024)
```

---

## 3. OWASP Dependency-Check

### 3.1 O que é e por que é crítico

O OWASP Dependency-Check é uma ferramenta de Software Composition Analysis (SCA) que detecta vulnerabilidades conhecidas publicamente (CVEs do banco de dados NVD/NIST) em dependências de terceiros do seu projeto.

O OWASP Top 10 2025 classifica **Falhas na Cadeia de Suprimentos de Software** como A03 — na lista atual as dependências vulneráveis são responsáveis por um enorme volume de incidentes reais.

**Por que importa para projetos Next.js:**
- Um projeto Next.js típico possui centenas de dependências transitivas (dependências de dependências)
- Vulnerabilidades em pacotes como `next`, `react`, `@supabase/ssr`, parsers de imagem, etc., são reportadas regularmente
- `npm install` não avisa sobre vulnerabilidades — você precisa verificar ativamente

---

### 3.2 Instalação e Configuração

#### Opção A — npm audit (nativo, zero configuração)

O `npm audit` é a forma mais simples e já vem com o Node.js:

```bash
# Auditar todas as dependências
npm audit

# Auditar apenas vulnerabilidades de alta severidade e acima
npm audit --audit-level=high

# Auditar apenas vulnerabilidades críticas (para CI — falha o build)
npm audit --audit-level=critical

# Corrigir automaticamente quando possível
npm audit fix

# Ver relatório em formato JSON para automação
npm audit --json > audit-report.json
```

#### Opção B — OWASP Dependency-Check CLI (mais abrangente)

O OWASP Dependency-Check vai além do npm audit — ele cruza suas dependências com o banco de dados NVD do NIST, que contém CVEs de múltiplas fontes.

**Pré-requisito:** Java 11+ instalado.

```bash
# Download e instalação (Linux/macOS)
wget https://github.com/jeremylong/DependencyCheck/releases/download/v12.1.0/dependency-check-12.1.0-release.zip
unzip dependency-check-12.1.0-release.zip
cd dependency-check/bin

# Primeira execução (baixa base NVD — pode levar 20-30 minutos)
./dependency-check.sh \
  --project "MeuPortal" \
  --scan /caminho/para/seu/projeto \
  --format HTML \
  --format JSON \
  --out ./relatorios \
  --nvdApiKey SEU_API_KEY_NVD

# Obtenha uma API key gratuita do NVD em: https://nvd.nist.gov/developers/request-an-api-key
# Sem a API key, o download é throttled e muito mais lento
```

#### Opção C — via npm wrapper (sem Java diretamente)

```bash
# Instalar wrapper Node.js
npm install --save-dev owasp-dependency-check

# Adicionar ao package.json
{
  "scripts": {
    "security:full": "owasp-dependency-check --project \"MeuPortal\" -f HTML -f JSON",
    "security:audit": "npm audit --audit-level=high",
    "security:check": "npm run security:audit && npm run security:full"
  }
}
```

---

### 3.3 Integração com GitHub Actions (CI/CD)

Esta é a abordagem recomendada: executar auditoria automaticamente em todo Pull Request e push na branch principal.

#### Workflow completo para Next.js

```yaml
# .github/workflows/security.yml
name: Security Audit

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main]
  schedule:
    # Executa todo dia às 6h (pega CVEs publicados durante a noite)
    - cron: '0 6 * * *'

jobs:
  npm-audit:
    name: npm audit
    runs-on: ubuntu-latest
    steps:
      - name: Checkout código
        uses: actions/checkout@v4

      - name: Setup Node.js
        uses: actions/setup-node@v4
        with:
          node-version: '20'
          cache: 'npm'

      - name: Instalar dependências (sem audit automático)
        run: npm ci --audit=false

      - name: Executar npm audit
        run: npm audit --audit-level=high
        # Falha o build se houver vulnerabilidades HIGH ou CRITICAL

      - name: Gerar relatório JSON
        if: always()
        run: npm audit --json > npm-audit-report.json || true

      - name: Upload relatório npm audit
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: npm-audit-report
          path: npm-audit-report.json
          retention-days: 30

  owasp-dependency-check:
    name: OWASP Dependency-Check
    runs-on: ubuntu-latest
    steps:
      - name: Checkout código
        uses: actions/checkout@v4

      - name: Setup Java (necessário para OWASP DC)
        uses: actions/setup-java@v4
        with:
          java-version: '17'
          distribution: 'temurin'

      - name: Executar OWASP Dependency-Check
        uses: dependency-check/Dependency-Check_Action@main
        with:
          project: 'MeuPortal'
          path: '.'
          format: 'HTML,JSON'
          out: 'relatorios'
          args: >
            --failOnCVSS 7
            --enableRetired
            --nvdApiKey ${{ secrets.NVD_API_KEY }}

      - name: Upload relatório OWASP
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: owasp-dependency-check-report
          path: relatorios/
          retention-days: 30

      - name: Publicar relatório como GitHub Summary
        if: always()
        run: |
          echo "## 🔐 OWASP Dependency-Check Report" >> $GITHUB_STEP_SUMMARY
          echo "Relatório gerado em: $(date)" >> $GITHUB_STEP_SUMMARY
          echo "Veja o artefato anexo para o relatório HTML completo." >> $GITHUB_STEP_SUMMARY

  dependency-review:
    name: Dependency Review (PRs)
    runs-on: ubuntu-latest
    if: github.event_name == 'pull_request'
    steps:
      - name: Checkout código
        uses: actions/checkout@v4

      - name: Dependency Review
        uses: actions/dependency-review-action@v4
        with:
          fail-on-severity: high
          # Bloqueia merge de PRs que introduzam dependências com CVEs HIGH/CRITICAL
```

> **Importante:** Adicione `NVD_API_KEY` nos segredos do repositório GitHub (Settings → Secrets → Actions). A API key é gratuita em https://nvd.nist.gov/developers/request-an-api-key

---

### 3.4 npm audit — Camada nativa de auditoria

O `npm audit` é mais rápido e simples que o OWASP DC, mas cobre apenas o banco de dados npm Advisory. Use ambos em conjunto.

#### Configuração no package.json

```json
{
  "scripts": {
    "audit:critical": "npm audit --audit-level=critical",
    "audit:high": "npm audit --audit-level=high",
    "audit:fix": "npm audit fix",
    "audit:fix:force": "npm audit fix --force",
    "preinstall": "npm audit --audit-level=critical"
  }
}
```

#### Ignorar falsos positivos de forma rastreável

Às vezes uma vulnerabilidade não é explorável no seu contexto. Documente isso, não silencie silenciosamente:

```json
// .nsprc ou .auditignore
{
  "exceptions": {
    "1089234": {
      "reason": "Vulnerabilidade afeta apenas o modo de desenvolvimento (webpack-dev-server). Não implantado em produção.",
      "expires": "2026-12-31",
      "responsible": "roberio@empresa.com",
      "reviewed": "2026-05-17"
    }
  }
}
```

---

### 3.5 Interpretando os Relatórios

O OWASP Dependency-Check gera relatórios com pontuação CVSS (Common Vulnerability Scoring System). Saiba priorizar:

```
┌─────────────────────────────────────────────────────────────┐
│                    ESCALA CVSS v3.x                         │
├──────────────┬──────────┬──────────────────────────────────┤
│ Score        │ Nível    │ Ação                              │
├──────────────┼──────────┼──────────────────────────────────┤
│ 9.0 – 10.0   │ CRÍTICO  │ Corrigir IMEDIATAMENTE           │
│              │          │ Bloquear deploy até correção      │
├──────────────┼──────────┼──────────────────────────────────┤
│ 7.0 – 8.9   │ ALTO     │ Corrigir em até 7 dias            │
│              │          │ Avaliar se bloqueia deploy        │
├──────────────┼──────────┼──────────────────────────────────┤
│ 4.0 – 6.9   │ MÉDIO    │ Corrigir no próximo sprint        │
│              │          │ Não bloqueia deploy               │
├──────────────┼──────────┼──────────────────────────────────┤
│ 0.1 – 3.9   │ BAIXO    │ Corrigir quando possível          │
│              │          │ Monitorar                         │
├──────────────┼──────────┼──────────────────────────────────┤
│ 0.0          │ NENHUM   │ Sem impacto de segurança         │
└──────────────┴──────────┴───────────────────────────────────┘
```

#### O que analisar em cada CVE reportado

1. **CVE ID** — Ex: CVE-2024-12345 — busque no NVD para contexto completo
2. **Dependência afetada** — É direta ou transitiva?
3. **Versão vulnerável vs. versão corrigida** — `npm outdated` ajuda a ver
4. **Vetor de exploração** — Network? Local? Requer autenticação?
5. **Exploitabilidade no seu contexto** — A função vulnerável é usada? Em produção?

---

### 3.6 Gestão de Vulnerabilidades em Dependências

#### Fluxo de correção

```bash
# 1. Identificar o problema
npm audit --audit-level=high

# 2. Ver quais versões corrigem a vulnerabilidade
npm audit --json | jq '.vulnerabilities | to_entries[] | {name: .key, severity: .value.severity, fixAvailable: .value.fixAvailable}'

# 3a. Correção automática (segura — apenas semver compatível)
npm audit fix

# 3b. Forçar upgrade de major version (pode quebrar APIs)
npm audit fix --force
# ⚠ Teste exaustivamente após --force

# 4. Para dependências transitivas — override no package.json
{
  "overrides": {
    "pacote-vulneravel": ">=versao-corrigida"
  }
}

# 5. Verificar se a correção funcionou
npm audit
```

#### Dependências desatualizadas (não necessariamente vulneráveis, mas risco futuro)

```bash
# Ver todas as dependências com versões novas disponíveis
npm outdated

# Atualizar dependências respeitando semver
npm update

# Atualizar para a versão mais recente (ignora semver — cuidado)
npx npm-check-updates -u
npm install
```

---

### 3.7 Checklist Supply Chain

```
AUDITORIA DE DEPENDÊNCIAS
[ ] npm audit executado e sem vulnerabilidades HIGH/CRITICAL
[ ] OWASP Dependency-Check configurado no repositório
[ ] GitHub Actions com security workflow ativo
[ ] Dependabot ou Renovate Bot habilitado para atualizações automáticas
[ ] Dependências revisadas trimestralmente

CI/CD
[ ] Build falha automaticamente em vulnerabilidade CRITICAL (CVSS >= 9.0)
[ ] Build falha automaticamente em vulnerabilidade HIGH (CVSS >= 7.0)
[ ] Relatórios de auditoria arquivados por 90+ dias
[ ] Dependency Review Action ativa em Pull Requests
[ ] NVD API Key configurada como secret do repositório

BOAS PRÁTICAS
[ ] npm ci usado em vez de npm install no CI (usa package-lock.json exato)
[ ] package-lock.json commitado no repositório (nunca no .gitignore)
[ ] Sem dependências com zero manutenção (+2 anos sem commits)
[ ] Exceções/supressões de falsos positivos documentadas com prazo
[ ] Processo documentado para resposta a CVE crítico descoberto
```

---

## 4. Matriz de Prioridade Unificada

Use esta matriz para definir a ordem de implementação nos seus projetos:

| Prioridade | Ação | Pilar | Esforço | Impacto |
|:---:|---|---|:---:|:---:|
| 🔴 **P0** | Habilitar RLS em TODAS as tabelas | Supabase | Baixo | Crítico |
| 🔴 **P0** | Remover `service_role key` do frontend | Supabase | Baixo | Crítico |
| 🔴 **P0** | `npm audit --audit-level=critical` no CI | OWASP | Baixo | Crítico |
| 🟠 **P1** | Criar políticas RLS por tabela e operação | Supabase | Médio | Alto |
| 🟠 **P1** | Configurar GitHub Actions com security workflow | OWASP | Médio | Alto |
| 🟠 **P1** | Mapear dados pessoais e bases legais | LGPD | Médio | Alto |
| 🟡 **P2** | Índices nas colunas de políticas RLS | Supabase | Baixo | Médio |
| 🟡 **P2** | Implementar endpoints de direitos dos titulares | LGPD | Alto | Alto |
| 🟡 **P2** | Plano de resposta a incidentes | LGPD | Médio | Alto |
| 🟡 **P2** | Criptografia AES-256 para dados sensíveis | LGPD | Médio | Alto |
| 🟢 **P3** | Logs de auditoria via triggers PostgreSQL | Supabase | Médio | Médio |
| 🟢 **P3** | OWASP DC completo + relatórios arquivados | OWASP | Alto | Médio |
| 🟢 **P3** | Pseudonimização em analytics | LGPD | Alto | Médio |
| 🔵 **P4** | Testes automatizados de políticas RLS | Supabase | Alto | Médio |
| 🔵 **P4** | RIPD (Relatório de Impacto) elaborado | LGPD | Alto | Baixo |

---

## 5. Referências

### Supabase
- Documentação oficial de Row Level Security: https://supabase.com/docs/guides/database/postgres/row-level-security
- Supabase Security Retro 2025: https://supabase.com/blog/supabase-security-2025-retro
- Supabase + Next.js SSR: https://supabase.com/docs/guides/auth/server-side/nextjs

### LGPD / ANPD
- Lei 13.709/2018 (LGPD): https://www.planalto.gov.br/ccivil_03/_ato2015-2018/2018/lei/l13709.htm
- Portal ANPD: https://www.gov.br/anpd/pt-br
- Guia de Segurança da Informação ANPD: https://www.gov.br/anpd/pt-br/documentos-e-publicacoes
- Resolução CD/ANPD nº 15/2024 (Incidentes): Publicada no DOU de 25/04/2024
- Resolução CD/ANPD nº 19/2024 (Transferência Internacional): Publicada no DOU de 23/08/2024
- Guia Orientativo de Legítimo Interesse ANPD (fev/2024): https://www.gov.br/anpd/pt-br/documentos-e-publicacoes/guias-e-orientacoes

### OWASP Dependency-Check
- Projeto oficial: https://owasp.org/www-project-dependency-check/
- GitHub releases: https://github.com/jeremylong/DependencyCheck/releases
- NVD API Key (gratuita): https://nvd.nist.gov/developers/request-an-api-key
- OWASP Developer Guide — Dependencies: https://devguide.owasp.org/en/05-implementation/02-dependencies/01-dependency-check/
- GitHub Actions — Dependency Review: https://github.com/actions/dependency-review-action

### Ferramentas Complementares
- Snyk (alternativa comercial ao OWASP DC): https://snyk.io
- Socket.dev (análise de supply chain para npm): https://socket.dev
- Dependabot (GitHub nativo): https://docs.github.com/en/code-security/dependabot

---

*Guia elaborado com base nas documentações oficiais do Supabase, ANPD/LGPD e OWASP — atualizado em maio/2026.*
