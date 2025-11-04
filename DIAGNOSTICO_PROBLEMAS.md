# 🔍 Diagnóstico de Problemas - Sistema BetAuto

## 📊 Análise dos Logs PM2

### Problemas Identificados

#### 1. ❌ **CancelledError** (Crítico)
```
asyncio.exceptions.CancelledError
```
**Causa:** Alguma task async foi cancelada antes de completar, possivelmente devido a timeout ou concorrência.

**Impacto:** Jobs podem estar sendo interrompidos prematuramente.

---

#### 2. ❌ **API não retorna dados** (Recorrente)
```
API não retornou dados, tentando fallback HTML...
```
**Causa:** Todas as requisições à API estão falhando (provavelmente 403 Forbidden).

**Impacto:** Sistema está usando apenas HTML scraping, que é mais lento e menos eficiente.

**Frequência:** 100% das tentativas de API estão falhando.

---

#### 3. ❌ **Falha ao fazer requisição com bypass** (Crítico)
```
⚠️ Tentativa 1/3 falhou: Falha ao fazer requisição com bypass para https://betnacional.bet.br/event/1/0/63369819
❌ Todas as 3 tentativas falharam
```
**Causa:** O sistema de bypass está retornando `None` para todas as requisições, indicando que:
- `_should_use_api()` está retornando `False` (bloqueio ativo)
- Ou o bypass está detectando bloqueio e falhando

**Impacto:** Requisições HTTP não estão funcionando, dependendo 100% do Playwright.

---

#### 4. ⚠️ **Maximum number of running instances reached** (Concorrência)
```
Execution of job "monitor_live_games_job" skipped: maximum number of running instances reached (1)
```
**Causa:** O job está tentando executar múltiplas vezes simultaneamente, mesmo com `max_instances=1`.

**Possíveis causas:**
- Job demora mais de 1 minuto para executar (interval é 1 minuto)
- Múltiplas execuções assíncronas não estão sendo bloqueadas corretamente
- CancelledError está causando execuções duplicadas

**Impacto:** Jobs podem estar sendo executados em paralelo, causando:
- Concorrência no banco de dados
- Requisições duplicadas
- Uso excessivo de recursos

---

#### 5. ⚠️ **0 cookies válidos** (Problema de Sessão)
```
Cookies carregados de cookies/cookies.json: 0 cookies válidos
CookieManager inicializado: 0 cookies carregados
```
**Causa:** 
- Cookies não existem ou expiraram
- Arquivo de cookies não está sendo criado/salvo corretamente
- Warm-up de sessão não está funcionando

**Impacto:** 
- Sem cookies, as requisições são mais facilmente detectadas como bots
- Maior taxa de bloqueios (403)
- Sistema de bypass não consegue manter sessão válida

---

## 🔧 Análise Técnica

### Problema Principal: Bypass Bloqueado

O sistema de bypass está retornando `None` para todas as requisições porque:

1. **`_should_use_api()` retorna False:**
   - `_api_blocked_until` está ativo (bloqueio temporário)
   - `_api_consecutive_failures >= 3` (muitas falhas consecutivas)
   - `_api_use_dom_fallback = True` (flag de fallback ativa)
   - Rate limit atingido

2. **Sem cookies válidos:**
   - Sistema não consegue estabelecer sessão válida
   - Requisições são imediatamente bloqueadas
   - Bypass não consegue contornar sem cookies

3. **Ciclo vicioso:**
   ```
   Sem cookies → 403 Forbidden → Falhas consecutivas → Bloqueio automático → 
   Força DOM scraping → Mais tentativas → Mais 403s → Bloqueio permanente
   ```

---

## ✅ Soluções Implementadas

### 1. ✅ Resetar Estado do Bypass
**Implementado:**
- Método `reset_bypass_state(force=True)` para reset completo
- Método `get_bypass_status()` para diagnóstico
- Reset automático quando bloqueio expirou há mais de 5 minutos (sem fallback)

**Uso:**
```python
from utils.bypass_detection import get_bypass_detector

detector = get_bypass_detector()
detector.reset_bypass_state(force=True)  # Reset completo
status = detector.get_bypass_status()    # Ver status atual
```

**Script:** `scripts/reset_bypass.py` - Para reset manual via linha de comando

---

### 2. ✅ Melhorar Warm-up de Sessão
**Implementado:**
- Warm-up automático em `fetch_requests()` quando não há cookies válidos
- Visita página principal antes de fazer requisição real
- Salva cookies automaticamente após warm-up
- Logs informativos sobre warm-up

**Comportamento:**
- Verifica cookies antes de cada requisição
- Se `valid_cookies == 0`, faz warm-up automaticamente
- Usa sessão HTTP para visitar página principal
- Atualiza cookies após warm-up bem-sucedido

---

### 3. ✅ Corrigir Concorrência de Jobs
**Implementado:**
- Lock assíncrono `_monitor_live_games_lock` para prevenir execuções simultâneas
- Verificação antes de executar: `if _monitor_live_games_lock.locked()`
- Aumentado `misfire_grace_time` de 60s para 120s (2 minutos)
- Tratamento adequado de `CancelledError`

**Comportamento:**
- Se job já está executando, pula nova execução
- Lock previne execuções paralelas mesmo se scheduler tentar iniciar múltiplas
- Logs informativos quando job é pulado

---

### 4. ✅ Melhorar Tratamento de Erros
**Implementado:**
- Tratamento específico de `asyncio.CancelledError` em:
  - `_fetch_requests_async()` - Não loga erro, apenas propaga
  - `monitor_live_games_job()` - Loga warning e re-raise
- Reset automático quando bloqueio expirou (sem fallback)
- Logs de diagnóstico quando bypass está bloqueado

**Comportamento:**
- `CancelledError` não é mais tratado como erro crítico
- Logs reduzidos para erros esperados (com fallback)
- Informações detalhadas quando bypass está bloqueado

---

### 5. ✅ Debugging e Monitoramento
**Implementado:**
- Método `get_bypass_status()` retorna estado completo:
  - `blocked_until`: Timestamp até quando está bloqueado
  - `is_blocked`: Se está bloqueado no momento
  - `consecutive_failures`: Falhas consecutivas
  - `use_dom_fallback`: Se está usando fallback DOM
  - `requests_last_minute`: Requisições no último minuto
  - E mais...
- Logs de status quando reset não remove bloqueio
- Logs de warm-up e cookies

**Script de Diagnóstico:**
```bash
python scripts/reset_bypass.py
```

---

## 🚀 Como Usar

### Resetar Bypass Manualmente

```bash
# No servidor VPS
cd /opt/betauto
source venv/bin/activate
python scripts/reset_bypass.py
```

### Verificar Status do Bypass

```python
from utils.bypass_detection import get_bypass_detector

detector = get_bypass_detector()
status = detector.get_bypass_status()
print(status)
```

### Resetar Programaticamente

```python
from utils.bypass_detection import get_bypass_detector

detector = get_bypass_detector()
detector.reset_bypass_state(force=True)
```

---

## 📊 Resultados Esperados

### Antes das Correções:
- ❌ Todas as requisições falhando
- ❌ Bypass bloqueado permanentemente
- ❌ Jobs executando simultaneamente
- ❌ 0 cookies válidos
- ❌ CancelledError não tratado

### Depois das Correções:
- ✅ Reset automático quando bloqueio expira
- ✅ Warm-up automático quando não há cookies
- ✅ Jobs com lock para prevenir concorrência
- ✅ CancelledError tratado adequadamente
- ✅ Logs de diagnóstico disponíveis

---

## 🔧 Próximos Passos (Se Problemas Persistirem)

1. **Executar reset manual:**
   ```bash
   python scripts/reset_bypass.py
   ```

2. **Verificar logs após reset:**
   ```bash
   pm2 logs betauto --lines 50
   ```

3. **Se ainda bloqueado:**
   - Verificar se há cookies válidos
   - Verificar se warm-up está funcionando
   - Considerar aumentar intervalos de rate limiting

4. **Monitorar métricas:**
   - Taxa de sucesso da API
   - Tempo entre requisições
   - Quantidade de cookies válidos

