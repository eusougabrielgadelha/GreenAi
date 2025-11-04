# ✅ Melhoria #11 Implementada: Configuração Centralizada de Timeouts

## 📋 O Que Foi Implementado

Implementada a **Melhoria #11** do documento `MELHORIAS_PRIORITARIAS.md`: **Configuração Centralizada de Timeouts**.

## 🔧 Mudanças Realizadas

### 1. **Configurações de Timeout Centralizadas**

**Arquivo:** `config/settings.py`

**Timeouts Adicionados:**

#### A. Timeouts para Requisições HTTP (em segundos)

```python
API_TIMEOUT = float(os.getenv("API_TIMEOUT", "20"))              # Requisições à API do Betnacional
HTML_TIMEOUT = float(os.getenv("HTML_TIMEOUT", "30"))            # Scraping de páginas HTML
RESULT_CHECK_TIMEOUT = float(os.getenv("RESULT_CHECK_TIMEOUT", "10"))  # Verificação de resultados
TELEGRAM_TIMEOUT = float(os.getenv("TELEGRAM_TIMEOUT", "15"))    # Requisições ao Telegram
HEALTH_CHECK_TIMEOUT = float(os.getenv("HEALTH_CHECK_TIMEOUT", "10"))  # Health checks
```

#### B. Timeouts para Playwright (em milissegundos)

```python
PLAYWRIGHT_NAVIGATION_TIMEOUT = int(os.getenv("PLAYWRIGHT_NAVIGATION_TIMEOUT", "60000"))  # Navegação (60s)
PLAYWRIGHT_SELECTOR_TIMEOUT = int(os.getenv("PLAYWRIGHT_SELECTOR_TIMEOUT", "15000"))      # Aguardar seletor (15s)
PLAYWRIGHT_NETWORKIDLE_TIMEOUT = int(os.getenv("PLAYWRIGHT_NETWORKIDLE_TIMEOUT", "60000")) # Network idle (60s)
```

#### C. Compatibilidade com Código Existente

```python
# Mantém REQUESTS_TIMEOUT para compatibilidade
# Se não especificado, usa API_TIMEOUT como padrão
if not os.getenv("REQUESTS_TIMEOUT"):
    REQUESTS_TIMEOUT = API_TIMEOUT
```

### 2. **Substituição de Timeouts Hardcoded**

**Arquivos Modificados:**

#### A. `scraping/betnacional.py`

**Antes:**
```python
response = requests.get(api_url, params=params, headers=headers, timeout=20)
```

**Depois:**
```python
from config.settings import API_TIMEOUT
response = requests.get(api_url, params=params, headers=headers, timeout=API_TIMEOUT)
```

**Substituições:**
- ✅ `fetch_events_from_api()` - timeout=20 → API_TIMEOUT
- ✅ `fetch_event_odds_from_api()` - timeout=20 → API_TIMEOUT

#### B. `scraping/fetchers.py`

**Antes:**
```python
r = requests.get(url, headers=HEADERS, timeout=REQUESTS_TIMEOUT)
await page.goto(url, wait_until="networkidle", timeout=60_000)
await page.wait_for_selector(wait_for_selector, timeout=15000)
```

**Depois:**
```python
from config.settings import HTML_TIMEOUT, PLAYWRIGHT_NETWORKIDLE_TIMEOUT, PLAYWRIGHT_SELECTOR_TIMEOUT

r = requests.get(url, headers=HEADERS, timeout=HTML_TIMEOUT)
await page.goto(url, wait_until="networkidle", timeout=PLAYWRIGHT_NETWORKIDLE_TIMEOUT)
await page.wait_for_selector(wait_for_selector, timeout=PLAYWRIGHT_SELECTOR_TIMEOUT)
```

**Substituições:**
- ✅ `fetch_requests()` - timeout=REQUESTS_TIMEOUT → HTML_TIMEOUT
- ✅ `fetch_playwright()` - timeout=60_000 → PLAYWRIGHT_NETWORKIDLE_TIMEOUT
- ✅ `_fetch_with_playwright()` - timeout=60000 → PLAYWRIGHT_NETWORKIDLE_TIMEOUT
- ✅ `_fetch_with_playwright()` - timeout=15000 → PLAYWRIGHT_SELECTOR_TIMEOUT

#### C. `notifications/telegram.py`

**Antes:**
```python
r = requests.post(url, json=payload, timeout=15)
```

**Depois:**
```python
from config.settings import TELEGRAM_TIMEOUT
r = requests.post(url, json=payload, timeout=TELEGRAM_TIMEOUT)
```

**Substituições:**
- ✅ `tg_send_message()` - timeout=15 → TELEGRAM_TIMEOUT

#### D. `utils/health_check.py`

**Antes:**
```python
response = requests.get(url, timeout=10)
```

**Depois:**
```python
from config.settings import HEALTH_CHECK_TIMEOUT
response = requests.get(url, timeout=HEALTH_CHECK_TIMEOUT)
```

**Substituições:**
- ✅ `check_telegram_health()` - timeout=10 → HEALTH_CHECK_TIMEOUT

### 3. **Atualização do env.template**

**Arquivo:** `env.template`

**Novas Variáveis Adicionadas:**
```bash
# Timeouts Centralizados (Opcional)
API_TIMEOUT=20          # Requisições à API do Betnacional
HTML_TIMEOUT=30         # Scraping de páginas HTML
RESULT_CHECK_TIMEOUT=10 # Verificação de resultados
TELEGRAM_TIMEOUT=15     # Requisições ao Telegram
HEALTH_CHECK_TIMEOUT=10 # Health checks do sistema

# Timeout para Playwright (em milissegundos)
PLAYWRIGHT_NAVIGATION_TIMEOUT=60000  # Navegação (60s)
PLAYWRIGHT_SELECTOR_TIMEOUT=15000    # Aguardar seletor (15s)
PLAYWRIGHT_NETWORKIDLE_TIMEOUT=60000 # Network idle (60s)
```

## 📊 Benefícios

### 1. **Configurabilidade Global**
- ✅ Ajustar todos os timeouts de um único lugar
- ✅ Não precisa modificar código para alterar timeouts
- ✅ Fácil ajustar para diferentes ambientes

### 2. **Manutenibilidade**
- ✅ Timeouts não mais espalhados pelo código
- ✅ Fácil identificar onde timeouts são usados
- ✅ Consistência entre diferentes partes do sistema

### 3. **Flexibilidade**
- ✅ Ajustar timeouts por ambiente (dev, prod)
- ✅ Ajustar timeouts por tipo de operação
- ✅ Testar com timeouts diferentes

### 4. **Documentação Implícita**
- ✅ Valores padrão claros em `settings.py`
- ✅ Comentários explicam uso de cada timeout
- ✅ `env.template` documenta todas as opções

## 🧪 Como Funciona

### Configuração Via Variáveis de Ambiente

**Arquivo `.env`:**
```bash
API_TIMEOUT=25
HTML_TIMEOUT=40
TELEGRAM_TIMEOUT=20
```

**Uso no Código:**
```python
from config.settings import API_TIMEOUT

response = requests.get(url, timeout=API_TIMEOUT)
```

### Valores Padrão

Se não especificado no `.env`, usa valores padrão:
- `API_TIMEOUT`: 20 segundos
- `HTML_TIMEOUT`: 30 segundos
- `TELEGRAM_TIMEOUT`: 15 segundos
- `HEALTH_CHECK_TIMEOUT`: 10 segundos
- `PLAYWRIGHT_NAVIGATION_TIMEOUT`: 60000 ms (60s)
- `PLAYWRIGHT_SELECTOR_TIMEOUT`: 15000 ms (15s)
- `PLAYWRIGHT_NETWORKIDLE_TIMEOUT`: 60000 ms (60s)

## 📈 Impacto Esperado

### Antes (Timeouts Hardcoded)
```
scraping/betnacional.py: timeout=20
scraping/fetchers.py: timeout=60_000, timeout=15000
notifications/telegram.py: timeout=15
utils/health_check.py: timeout=10

❌ Difícil ajustar globalmente
❌ Timeouts espalhados pelo código
❌ Inconsistência entre módulos
```

### Depois (Timeouts Centralizados)
```
config/settings.py: Todas as configurações centralizadas

✅ Ajustar de um único lugar
✅ Timeouts consistentes
✅ Fácil configurar por ambiente
```

## ⚙️ Configuração

### Ajustar Timeouts

**Via `.env`:**
```bash
# Aumentar timeout para API lenta
API_TIMEOUT=30

# Aumentar timeout para HTML pesado
HTML_TIMEOUT=45

# Aumentar timeout para Playwright
PLAYWRIGHT_NETWORKIDLE_TIMEOUT=90000
```

**Via Código (não recomendado):**
```python
# Não recomendado - melhor usar .env
import os
os.environ["API_TIMEOUT"] = "30"
```

### Timeouts por Ambiente

**Desenvolvimento:**
```bash
API_TIMEOUT=10
HTML_TIMEOUT=15
```

**Produção:**
```bash
API_TIMEOUT=20
HTML_TIMEOUT=30
```

**Ambiente com Rede Lenta:**
```bash
API_TIMEOUT=40
HTML_TIMEOUT=60
PLAYWRIGHT_NETWORKIDLE_TIMEOUT=120000
```

## 📊 Estrutura de Timeouts

### Timeouts HTTP (em segundos)

| Timeout | Padrão | Uso |
|---------|--------|-----|
| `API_TIMEOUT` | 20s | Requisições à API do Betnacional |
| `HTML_TIMEOUT` | 30s | Scraping de páginas HTML |
| `RESULT_CHECK_TIMEOUT` | 10s | Verificação de resultados |
| `TELEGRAM_TIMEOUT` | 15s | Requisições ao Telegram |
| `HEALTH_CHECK_TIMEOUT` | 10s | Health checks do sistema |

### Timeouts Playwright (em milissegundos)

| Timeout | Padrão | Uso |
|---------|--------|-----|
| `PLAYWRIGHT_NAVIGATION_TIMEOUT` | 60000ms | Navegação de páginas |
| `PLAYWRIGHT_SELECTOR_TIMEOUT` | 15000ms | Aguardar seletor CSS |
| `PLAYWRIGHT_NETWORKIDLE_TIMEOUT` | 60000ms | Aguardar network idle |

## 🔄 Funcionamento

### Fluxo de Configuração

```
1. Sistema carrega .env
   ↓
2. config/settings.py lê variáveis de ambiente
   ↓
3. Valores padrão usados se não especificados
   ↓
4. Módulos importam timeouts de settings
   ↓
5. Timeouts usados em todas as requisições
```

### Compatibilidade

**REQUESTS_TIMEOUT mantido para compatibilidade:**
- ✅ Código existente que usa `REQUESTS_TIMEOUT` continua funcionando
- ✅ Se `REQUESTS_TIMEOUT` não especificado, usa `API_TIMEOUT`
- ✅ Migração gradual possível

## ✅ Status

**IMPLEMENTADO E PRONTO PARA USO**

O sistema agora:
- ✅ Tem configurações de timeout centralizadas
- ✅ Todos os timeouts hardcoded foram substituídos
- ✅ Fácil ajustar timeouts via `.env`
- ✅ Compatibilidade com código existente mantida

---

**Implementação concluída em:** 2025-11-04

**Arquivos criados/modificados:**
- `config/settings.py` - Configurações centralizadas de timeout
- `scraping/betnacional.py` - Uso de API_TIMEOUT
- `scraping/fetchers.py` - Uso de HTML_TIMEOUT e timeouts do Playwright
- `notifications/telegram.py` - Uso de TELEGRAM_TIMEOUT
- `utils/health_check.py` - Uso de HEALTH_CHECK_TIMEOUT
- `env.template` - Documentação das novas variáveis

