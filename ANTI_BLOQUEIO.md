# 🛡️ Estratégias Anti-Bloqueio para Requisições XHR

## 📋 Resumo

Este documento descreve as estratégias implementadas para evitar bloqueios (403 Forbidden) nas requisições XHR da API BetNacional.

---

## ✅ Estratégias Implementadas

### 1. Rotação de User-Agents

**Módulo:** `utils/anti_block.py`

- **Rotador de User-Agents**: Simula diferentes navegadores (Chrome, Firefox, Edge, Safari)
- **Rotação Aleatória**: Cada requisição pode usar um User-Agent diferente
- **Rotação Inteligente**: Rotaciona após 3 falhas consecutivas

**Benefícios:**
- Dificulta detecção por padrão único de User-Agent
- Simula tráfego de diferentes navegadores
- Reduz chances de bloqueio por fingerprinting

### 2. Headers Completos de Navegador

**Função:** `get_browser_headers()`

Headers incluídos:
- `User-Agent`: Rotacionado
- `Accept`: `application/json, text/plain, */*`
- `Accept-Language`: `pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7`
- `Accept-Encoding`: `gzip, deflate, br`
- `Referer`: Dinâmico baseado na URL
- `Origin`: `https://betnacional.bet.br`
- `sec-ch-ua`: Versão do Chrome extraída do User-Agent
- `sec-ch-ua-mobile`: `?0`
- `sec-ch-ua-platform`: `"Windows"`
- `sec-fetch-dest`: `empty`
- `sec-fetch-mode`: `cors`
- `sec-fetch-site`: `cross-site`
- `Connection`: `keep-alive`
- `Cache-Control`: `no-cache`
- `Pragma`: `no-cache`
- `DNT`: `1` (Do Not Track)

**Benefícios:**
- Headers completos simulam navegador real
- Versão do Chrome sincronizada com User-Agent
- Referer dinâmico baseado no contexto

### 3. Throttle de Requisições

**Classe:** `RequestThrottle`

- **Delay Mínimo**: 1.5s para API, 2.0s para HTML
- **Delay Máximo**: 3.0s para API, 4.0s para HTML
- **Jitter**: Variação aleatória de ±0.5s para API, ±1.0s para HTML

**Benefícios:**
- Evita requisições muito rápidas (padrão de bot)
- Simula comportamento humano com delays variáveis
- Reduz carga no servidor

### 4. Rate Limiting Global

**Módulo:** `utils/rate_limiter.py`

- **API XHR**: Máximo 8 requisições por minuto (reduzido de 10)
- **HTML Scraping**: Máximo 3 requisições por minuto (reduzido de 5)

**Benefícios:**
- Limita taxa de requisições globalmente
- Previne sobrecarga do servidor
- Mais conservador para evitar bloqueios

### 5. Delays Aleatórios

**Função:** `add_random_delay()`

- **Após Requisições Bem-Sucedidas**: 0.3s a 1.0s
- **Simula Comportamento Humano**: Não faz requisições instantâneas

**Benefícios:**
- Adiciona naturalidade ao padrão de requisições
- Dificulta detecção de automação

### 6. Retry com Backoff Exponencial

**Módulo:** `utils/rate_limiter.py`

- **Máximo de Tentativas**: 3
- **Delay Inicial**: 1.0s
- **Delay Máximo**: 20.0s (HTML) ou 60.0s (API)
- **Base Exponencial**: 2.0

**Benefícios:**
- Recupera de erros temporários
- Evita sobrecarga em caso de falhas
- Aumenta delay progressivamente

### 7. Sessões HTTP Persistentes

**Função:** `create_session()`

- **Reutilização de Conexões**: Reduz overhead de TCP handshake
- **Retry Automático**: Para erros 429, 500, 502, 503, 504
- **Timeout Configurado**: 30 segundos

**Benefícios:**
- Melhor performance
- Recuperação automática de erros temporários
- Menos requisições detectadas como suspeitas

---

## 🔧 Configuração

### Variáveis de Ambiente (Opcionais)

```bash
# Rate limiting (já configurado no código)
API_MAX_REQUESTS_PER_MINUTE=8
HTML_MAX_REQUESTS_PER_MINUTE=3

# Throttle delays
API_MIN_DELAY=1.5
API_MAX_DELAY=3.0
HTML_MIN_DELAY=2.0
HTML_MAX_DELAY=4.0
```

### Ajustes de Throttle

Para tornar mais conservador (menos bloqueios, mais lento):
```python
api_throttle = RequestThrottle(min_delay=2.0, max_delay=4.0, jitter=1.0)
```

Para tornar mais agressivo (mais rápido, maior risco):
```python
api_throttle = RequestThrottle(min_delay=0.5, max_delay=1.5, jitter=0.3)
```

---

## 📊 Como Funciona na Prática

### Fluxo de Requisição API XHR

1. **Antes da Requisição:**
   - Throttle verifica tempo desde última requisição
   - Aguarda se necessário (1.5s a 3.0s + jitter)
   - Headers são gerados com User-Agent rotacionado

2. **Durante a Requisição:**
   - Headers completos de navegador
   - Rate limiter global verifica limite (8/min)
   - Timeout de 30s

3. **Após a Requisição:**
   - Delay aleatório de 0.3s a 1.0s
   - Log de sucesso/erro

### Em Caso de 403 Forbidden

1. **Retry Automático:**
   - 3 tentativas com backoff exponencial
   - User-Agent pode ser rotacionado após 3 falhas

2. **Fallback para HTML:**
   - Se API falhar, usa HTML scraping
   - HTML scraping tem throttle ainda mais conservador

3. **Logging:**
   - Erros 403 são logados em DEBUG (não WARNING)
   - Reduz verbosidade quando há fallback disponível

---

## 🚀 Melhorias Futuras (Opcionais)

### 1. Uso de Proxies

```python
# Exemplo de integração com proxies
proxies = {
    'http': 'http://proxy1:8080',
    'https': 'http://proxy2:8080',
}
response = requests.get(url, headers=headers, proxies=proxies)
```

**Benefícios:**
- Rotação de IPs
- Evita bloqueio por IP
- Mais difícil de detectar

**Desvantagens:**
- Custo adicional
- Complexidade de gerenciamento
- Pode ser mais lento

### 2. Cookies/Sessões Realistas

```python
# Manter cookies entre requisições
session = requests.Session()
session.cookies.set('session_id', '...')
```

**Benefícios:**
- Simula sessão de usuário real
- Mantém estado entre requisições

### 3. Request Fingerprinting

Adicionar headers específicos para evitar detecção por fingerprinting:
- `X-Requested-With`: `XMLHttpRequest`
- Headers específicos do navegador

### 4. Monitoramento de Taxa de Bloqueio

```python
# Estatísticas de bloqueios
block_rate = failed_requests / total_requests
if block_rate > 0.5:  # Mais de 50% de bloqueios
    # Aumentar delays ou rotacionar User-Agent
    api_throttle.min_delay *= 1.5
```

---

## 📈 Métricas de Sucesso

### Indicadores de Eficácia

1. **Taxa de Sucesso da API:**
   - Objetivo: > 80% de requisições bem-sucedidas
   - Monitorar: `success_rate = successful_requests / total_requests`

2. **Taxa de Bloqueio:**
   - Objetivo: < 20% de 403 Forbidden
   - Monitorar: `block_rate = 403_errors / total_requests`

3. **Uso de Fallback HTML:**
   - Objetivo: < 30% de requisições usando fallback
   - Monitorar: `fallback_rate = html_fallback_requests / total_requests`

### Ajustes Baseados em Métricas

- **Se block_rate > 30%**: Aumentar delays, reduzir rate limit
- **Se success_rate < 70%**: Rotacionar User-Agents mais frequentemente
- **Se fallback_rate > 50%**: Revisar headers e throttle

---

## ✅ Checklist de Implementação

- [x] Rotação de User-Agents
- [x] Headers completos de navegador
- [x] Throttle de requisições
- [x] Rate limiting global
- [x] Delays aleatórios
- [x] Retry com backoff exponencial
- [x] Sessões HTTP persistentes
- [x] Fallback para HTML scraping
- [ ] Uso de proxies (opcional)
- [ ] Cookies/Sessões realistas (opcional)
- [ ] Monitoramento de métricas (opcional)

---

## 🔍 Troubleshooting

### Problema: Ainda recebendo 403 Forbidden

**Soluções:**
1. Aumentar delays do throttle:
   ```python
   api_throttle = RequestThrottle(min_delay=3.0, max_delay=5.0)
   ```

2. Reduzir rate limit:
   ```python
   api_rate_limiter = RateLimiter(max_requests=5, window_seconds=60)
   ```

3. Verificar se User-Agents estão sendo rotacionados

4. Considerar usar proxies

### Problema: Requisições muito lentas

**Soluções:**
1. Reduzir delays do throttle (com cuidado):
   ```python
   api_throttle = RequestThrottle(min_delay=1.0, max_delay=2.0)
   ```

2. Aumentar rate limit (com cuidado):
   ```python
   api_rate_limiter = RateLimiter(max_requests=12, window_seconds=60)
   ```

---

## 📝 Notas Importantes

1. **Balanceamento**: Mais proteção = mais lento. Ajuste conforme necessário.

2. **Monitoramento**: Monitore logs para identificar padrões de bloqueio.

3. **Fallback**: O sistema sempre tem fallback HTML, então mesmo com bloqueios, continua funcionando.

4. **Responsabilidade**: Respeite os termos de serviço do site e não sobrecarregue o servidor.

