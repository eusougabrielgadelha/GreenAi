# 🍪 Sistema de Cookies Persistentes

## 📋 Resumo

Sistema completo de gerenciamento de cookies persistentes para requisições HTTP, permitindo manter sessões e reduzir bloqueios.

---

## ✅ Funcionalidades Implementadas

### 1. Gerenciador de Cookies (`utils/cookie_manager.py`)

**Classe:** `CookieManager`

- **Carregamento Automático**: Carrega cookies salvos ao inicializar
- **Persistência em Arquivo**: Salva cookies em JSON (`cookies/cookies.json`)
- **Validação de Expiração**: Remove cookies expirados automaticamente
- **Idade Máxima**: Remove cookies muito antigos (padrão: 30 dias)
- **Sessões HTTP**: Cria sessões com cookies pré-carregados

### 2. Integração com Requisições

**Módulos Atualizados:**
- `scraping/betnacional.py`: `fetch_events_from_api()` e `fetch_event_odds_from_api()`
- `scraping/fetchers.py`: `fetch_requests()`
- `utils/anti_block.py`: `create_session()` com suporte a cookies

### 3. Atualização Automática

- **Após Cada Requisição**: Cookies são atualizados automaticamente
- **Salvamento Automático**: Cookies são salvos em arquivo após cada atualização
- **Persistência**: Cookies são mantidos entre execuções do programa

---

## 🔧 Como Funciona

### 1. Carregamento Inicial

```python
from utils.cookie_manager import get_cookie_manager

manager = get_cookie_manager()
# Cookies são carregados automaticamente de cookies/cookies.json
```

### 2. Uso em Requisições

```python
from utils.anti_block import create_session
from utils.cookie_manager import update_cookies_from_response

# Criar sessão com cookies
session = create_session(use_cookies=True)

# Fazer requisição
response = session.get(url, headers=headers)

# Atualizar cookies automaticamente
update_cookies_from_response(response)
```

### 3. Estrutura de Arquivo

**Localização:** `cookies/cookies.json`

```json
{
  "saved_at": "2025-11-04T20:00:00",
  "domain": "betnacional.bet.br",
  "cookies": [
    {
      "name": "session_id",
      "value": "abc123...",
      "domain": "betnacional.bet.br",
      "path": "/",
      "expires": "2025-12-04T20:00:00"
    },
    {
      "name": "user_pref",
      "value": "xyz789...",
      "domain": "betnacional.bet.br",
      "path": "/",
      "expires": null
    }
  ]
}
```

---

## 📊 Funcionalidades Avançadas

### 1. Validação de Expiração

- **Cookies Expirados**: Removidos automaticamente
- **Cookies Antigos**: Removidos após idade máxima (30 dias)
- **Limpeza Automática**: Antes de carregar e salvar

### 2. Estatísticas

```python
from utils.cookie_manager import get_cookie_manager

manager = get_cookie_manager()
stats = manager.get_stats()

print(stats)
# {
#   'total_cookies': 5,
#   'valid_cookies': 4,
#   'expired_cookies': 1,
#   'oldest_expiry': '2025-11-10T00:00:00',
#   'newest_expiry': '2025-12-04T00:00:00',
#   'cookie_file': 'cookies/cookies.json'
# }
```

### 3. Limpeza de Cookies

```python
from utils.cookie_manager import get_cookie_manager

manager = get_cookie_manager()
manager.clear_cookies()  # Remove todos os cookies e arquivo
```

---

## 🚀 Benefícios

### 1. Redução de Bloqueios

- **Sessões Persistentes**: Mantém estado entre requisições
- **Cookies de Autenticação**: Reutiliza cookies de sessão
- **Comportamento Mais Realista**: Simula navegador real

### 2. Performance

- **Menos Requisições**: Reutiliza cookies válidos
- **Cache de Estado**: Não precisa autenticar a cada requisição

### 3. Continuidade

- **Entre Execuções**: Cookies são mantidos entre reinicializações
- **Persistência**: Cookies são salvos automaticamente

---

## 🔍 Detalhes Técnicos

### 1. Formato de Armazenamento

**JSON (Padrão):**
- Formato legível e editável
- Fácil de debugar
- Suporta múltiplos cookies

**Pickle (Alternativo):**
- Formato binário
- Mais eficiente
- Preserva objetos Python complexos

### 2. Validação de Cookies

**Checagens:**
- ✅ Data de expiração (`expires`)
- ✅ Idade máxima (`max_age_days`)
- ✅ Domínio correto
- ✅ Path válido

### 3. Sessões HTTP

**Requests Session:**
- Reutiliza conexões TCP
- Mantém cookies automaticamente
- Headers persistentes

---

## 📝 Configuração

### Variáveis de Ambiente (Opcional)

```bash
# Caminho do arquivo de cookies
COOKIE_FILE=cookies/cookies.json

# Idade máxima dos cookies (dias)
COOKIE_MAX_AGE_DAYS=30

# Domínio para cookies
COOKIE_DOMAIN=betnacional.bet.br
```

### Uso no Código

```python
from utils.cookie_manager import CookieManager

# Criar gerenciador customizado
manager = CookieManager(
    cookie_file="cookies/custom_cookies.json",
    max_age_days=60,  # Cookies válidos por 60 dias
    domain="betnacional.bet.br"
)
```

---

## 🛠️ Uso Prático

### Exemplo 1: Requisição com Cookies

```python
from utils.anti_block import create_session
from utils.cookie_manager import update_cookies_from_response

# Criar sessão com cookies
session = create_session(use_cookies=True)

# Fazer requisição
response = session.get("https://betnacional.bet.br/api/...")

# Atualizar cookies
update_cookies_from_response(response)
```

### Exemplo 2: Verificar Cookies

```python
from utils.cookie_manager import get_cookie_manager

manager = get_cookie_manager()
stats = manager.get_stats()

if stats['valid_cookies'] > 0:
    print(f"✅ {stats['valid_cookies']} cookies válidos")
    print(f"📅 Mais antigo expira em: {stats['oldest_expiry']}")
else:
    print("⚠️ Nenhum cookie válido. Primeira requisição criará cookies.")
```

### Exemplo 3: Limpar Cookies

```python
from utils.cookie_manager import get_cookie_manager

manager = get_cookie_manager()

# Limpar todos os cookies (útil para resetar sessão)
manager.clear_cookies()
print("Cookies limpos!")
```

---

## 🔄 Fluxo Completo

### Primeira Execução

1. **Sistema Inicia**: CookieManager inicializado
2. **Arquivo Não Existe**: Cookies vazios
3. **Primeira Requisição**: Sem cookies
4. **Resposta Recebida**: Cookies são salvos
5. **Arquivo Criado**: `cookies/cookies.json`

### Execuções Subsequentes

1. **Sistema Inicia**: CookieManager carrega cookies do arquivo
2. **Cookies Válidos**: Usados em todas as requisições
3. **Atualização**: Cookies são atualizados após cada requisição
4. **Persistência**: Cookies são salvos automaticamente

### Limpeza Automática

1. **Antes de Carregar**: Remove cookies expirados
2. **Antes de Salvar**: Remove cookies expirados
3. **Validação**: Verifica idade máxima

---

## 📈 Monitoramento

### Logs

```
INFO: CookieManager inicializado: 5 cookies carregados
DEBUG: Cookies atualizados: 2 novos cookies
DEBUG: Cookie expirado removido: session_id
DEBUG: Cookies salvos em cookies/cookies.json: 4 cookies
```

### Estatísticas

```python
from utils.cookie_manager import get_cookie_manager

manager = get_cookie_manager()
stats = manager.get_stats()

# Exibir estatísticas
for key, value in stats.items():
    print(f"{key}: {value}")
```

---

## ⚠️ Considerações Importantes

### 1. Segurança

- **Arquivo de Cookies**: Não commitar no Git (já adicionado ao `.gitignore`)
- **Permissões**: Arquivo deve ter permissões restritas
- **Conteúdo Sensível**: Cookies podem conter informações de sessão

### 2. Limpeza

- **Cookies Expirados**: Removidos automaticamente
- **Limpeza Manual**: Use `clear_cookies()` se necessário
- **Arquivo Corrompido**: Sistema cria novo arquivo se necessário

### 3. Performance

- **I/O de Arquivo**: Salva após cada requisição (pode ser otimizado)
- **Carregamento**: Apenas na inicialização
- **Validação**: Antes de carregar e salvar

---

## 🔧 Troubleshooting

### Problema: Cookies não estão sendo salvos

**Soluções:**
1. Verificar permissões do diretório `cookies/`
2. Verificar logs para erros de escrita
3. Verificar se `update_cookies_from_response()` está sendo chamado

### Problema: Cookies expiram muito rápido

**Soluções:**
1. Aumentar `max_age_days` no CookieManager
2. Verificar se servidor está enviando cookies com expires válido
3. Verificar data/hora do sistema

### Problema: Cookies não estão sendo usados

**Soluções:**
1. Verificar se `create_session(use_cookies=True)` está sendo usado
2. Verificar se cookies estão no domínio correto
3. Verificar logs para ver quantos cookies foram carregados

---

## ✅ Checklist de Implementação

- [x] Gerenciador de cookies com persistência
- [x] Carregamento automático de cookies
- [x] Salvamento automático após cada requisição
- [x] Validação de expiração
- [x] Limpeza de cookies expirados
- [x] Integração com sessões HTTP
- [x] Estatísticas de cookies
- [x] Limpeza manual de cookies
- [x] Documentação completa
- [x] Adicionado ao `.gitignore`

---

## 🎯 Próximos Passos (Opcional)

### 1. Otimização de I/O

- Salvar cookies em batch (não após cada requisição)
- Usar cache em memória com flush periódico

### 2. Múltiplos Domínios

- Suporte para cookies de múltiplos domínios
- Gerenciadores separados por domínio

### 3. Cookies de Terceiros

- Suporte para cookies de terceiros (3rd party)
- Gerenciamento de SameSite e Secure flags

### 4. Sincronização

- Sincronização de cookies entre múltiplas instâncias
- Lock de arquivo para evitar corrupção

---

## 📝 Notas Finais

1. **Cookies Longos**: Sistema mantém cookies válidos por até 30 dias (configurável)

2. **Reutilização**: Cookies são reutilizados automaticamente entre requisições

3. **Persistência**: Cookies são mantidos entre execuções do programa

4. **Segurança**: Arquivo de cookies não é commitado no Git

5. **Automático**: Funciona automaticamente sem configuração adicional

