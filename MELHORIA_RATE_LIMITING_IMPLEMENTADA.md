# ✅ Melhoria #3 Implementada: Rate Limiting e Retry com Backoff

## 📋 O Que Foi Implementado

Implementada a **Melhoria #3** do documento `MELHORIAS_PRIORITARIAS.md`: **Rate Limiting e Retry com Backoff**.

## 🔧 Mudanças Realizadas

### 1. **Criado Módulo de Rate Limiting**

**Arquivo:** `utils/rate_limiter.py` (NOVO)

**Classe `RateLimiter`:**
- ✅ Controla número máximo de requisições por janela de tempo
- ✅ Thread-safe (usa asyncio.Lock)
- ✅ Remove automaticamente requisições antigas da janela
- ✅ Aguarda automaticamente quando limite é atingido
- ✅ Estatísticas de uso (total de waits, tempo de espera)

**Funcionalidades:**
```python
class RateLimiter:
    def __init__(max_requests=10, window_seconds=60)
    async def acquire()                        # Aguarda até poder fazer requisição
    def get_stats() -> Dict                   # Estatísticas do rate limiter
```

**Instâncias Globais:**
```python
# Para API XHR: 10 requisições por minuto
api_rate_limiter = RateLimiter(max_requests=10, window_seconds=60)

# Para HTML scraping: 5 requisições por minuto (mais conservador)
html_rate_limiter = RateLimiter(max_requests=5, window_seconds=60)
```

### 2. **Função de Retry com Backoff Exponencial**

**Arquivo:** `utils/rate_limiter.py`

**Função `retry_with_backoff()`:**
- ✅ Retry automático com backoff exponencial
- ✅ Suporta funções async e sync
- ✅ Integração opcional com rate limiter
- ✅ Logs informativos sobre tentativas

**Parâmetros:**
- `max_retries`: Número máximo de tentativas (padrão: 3)
- `initial_delay`: Delay inicial em segundos (padrão: 1.0)
- `max_delay`: Delay máximo em segundos (padrão: 60.0)
- `exponential_base`: Base exponencial (padrão: 2.0)
- `exceptions`: Exceções que triggeram retry
- `rate_limiter`: Rate limiter opcional

**Exemplo de Backoff:**
```
Tentativa 1: Falha → Aguarda 2s
Tentativa 2: Falha → Aguarda 4s
Tentativa 3: Falha → Aguarda 8s
Tentativa 4: Falha → Aguarda 16s (max_delay = 30s)
```

**Decorator `@with_retry`:**
```python
@with_retry(max_retries=3, initial_delay=2.0)
async def fetch_data():
    # código que pode falhar
    pass
```

### 3. **Integrado com Funções de API**

**Arquivo:** `scraping/betnacional.py`

**Funções Atualizadas:**
- ✅ `fetch_events_from_api_async()` - Com rate limiting e retry
- ✅ `fetch_event_odds_from_api_async()` - Com rate limiting e retry

**Código Implementado:**
```python
async def fetch_events_from_api_async(...):
    from utils.rate_limiter import api_rate_limiter, retry_with_backoff
    
    async def _fetch():
        # Usar rate limiter antes de fazer requisição
        await api_rate_limiter.acquire()
        return await asyncio.to_thread(fetch_events_from_api, ...)
    
    # Tentar com retry (especialmente para 403 errors)
    return await retry_with_backoff(
        _fetch,
        max_retries=3,
        initial_delay=2.0,
        max_delay=30.0,
        exponential_base=2.0,
        exceptions=(requests.exceptions.HTTPError, ...)
    )
```

### 4. **Integrado com Funções de HTML Scraping**

**Arquivo:** `scraping/fetchers.py`

**Função Atualizada:**
- ✅ `_fetch_requests_async()` - Com rate limiting e retry

**Código Implementado:**
```python
async def _fetch_requests_async(url: str) -> str:
    from utils.rate_limiter import html_rate_limiter, retry_with_backoff
    
    async def _fetch():
        # Usar rate limiter antes de fazer requisição
        await html_rate_limiter.acquire()
        return await asyncio.to_thread(fetch_requests, url)
    
    # Tentar com retry
    return await retry_with_backoff(
        _fetch,
        max_retries=3,
        initial_delay=1.0,
        max_delay=20.0,
        ...
    )
```

## 📊 Benefícios

### 1. **Redução de Erros 403**
- ✅ Limita requisições para evitar rate limiting do servidor
- ✅ Retry automático com backoff exponencial
- ✅ Aguarda automaticamente quando limite é atingido

### 2. **Resiliência**
- ✅ Retry automático em caso de falhas temporárias
- ✅ Backoff exponencial evita sobrecarga
- ✅ Logs informativos sobre tentativas

### 3. **Performance Controlada**
- ✅ API: Máximo 10 requisições/minuto
- ✅ HTML: Máximo 5 requisições/minuto
- ✅ Evita sobrecarga no servidor

### 4. **Estatísticas**
- ✅ Monitora quantas vezes esperou por rate limit
- ✅ Tempo total de espera
- ✅ Facilita ajuste de limites

## 🧪 Como Funciona

### Rate Limiting

```
Requisição 1: Feita → Registrada
Requisição 2: Feita → Registrada
...
Requisição 10: Feita → Registrada
Requisição 11: ⏳ Aguarda até requisição 1 sair da janela (60s)
Requisição 12: ⏳ Aguarda...
```

### Retry com Backoff

```
Tentativa 1: Requisição → 403 Forbidden
  ⏳ Aguarda 2s
Tentativa 2: Requisição → 403 Forbidden
  ⏳ Aguarda 4s
Tentativa 3: Requisição → 200 OK ✅
  Retorna resultado
```

## 📈 Impacto Esperado

### Antes (Sem Rate Limiting)
```
10 requisições simultâneas → 403 Forbidden ❌
Sistema tenta novamente → 403 Forbidden ❌
Sistema tenta novamente → 403 Forbidden ❌
Resultado: Falha total
```

### Depois (Com Rate Limiting)
```
Requisição 1-10: Executadas com sucesso ✅
Requisição 11: ⏳ Aguarda automaticamente
Requisição 12: ⏳ Aguarda automaticamente
Resultado: Sucesso, sem 403 errors
```

### Com Retry
```
Requisição → 403 Forbidden
  ⏳ Aguarda 2s → Retry
  ⏳ Aguarda 4s → Retry  
  ✅ Sucesso na 3ª tentativa
```

## ⚙️ Configuração

### Ajustar Limites de Rate Limiting

**API XHR:**
```python
# utils/rate_limiter.py
api_rate_limiter = RateLimiter(max_requests=15, window_seconds=60)  # 15 req/min
```

**HTML Scraping:**
```python
# utils/rate_limiter.py
html_rate_limiter = RateLimiter(max_requests=10, window_seconds=60)  # 10 req/min
```

### Ajustar Retry

**Número de Tentativas:**
```python
await retry_with_backoff(
    _fetch,
    max_retries=5,  # 5 tentativas ao invés de 3
    ...
)
```

**Delays:**
```python
await retry_with_backoff(
    _fetch,
    initial_delay=3.0,  # Começar com 3s ao invés de 2s
    max_delay=60.0,     # Máximo de 60s
    ...
)
```

## 📊 Estatísticas do Rate Limiter

O rate limiter rastreia:
- **total_waits**: Quantas vezes teve que esperar
- **total_wait_time**: Tempo total de espera
- **current_requests**: Requisições atuais na janela

**Exemplo de Log:**
```
⏳ Rate limit atingido (10/10). Aguardando 5.2s...
```

## 🔄 Funcionamento Completo

### Fluxo com Rate Limiting e Retry

```
1. Sistema precisa fazer requisição
   ↓
2. Rate Limiter verifica se pode fazer
   ├─ Pode fazer → Continua
   └─ Limite atingido → ⏳ Aguarda automaticamente
   ↓
3. Faz requisição
   ├─ Sucesso → Retorna resultado ✅
   └─ Erro (403, timeout, etc) → Retry
   ↓
4. Retry com Backoff Exponencial
   ├─ Tentativa 1: Aguarda 2s
   ├─ Tentativa 2: Aguarda 4s
   ├─ Tentativa 3: Aguarda 8s
   └─ Se todas falharem → Retorna erro
```

## ✅ Status

**IMPLEMENTADO E PRONTO PARA USO**

O sistema agora:
- ✅ Limita requisições para evitar 403 errors
- ✅ Retry automático com backoff exponencial
- ✅ Aguarda automaticamente quando limite é atingido
- ✅ Logs informativos sobre rate limiting e retries
- ✅ Configurável e robusto

---

**Implementação concluída em:** 2025-11-04

**Arquivos criados/modificados:**
- `utils/rate_limiter.py` (NOVO) - Módulo de rate limiting e retry
- `scraping/betnacional.py` - Integração com rate limiting
- `scraping/fetchers.py` - Integração com rate limiting

