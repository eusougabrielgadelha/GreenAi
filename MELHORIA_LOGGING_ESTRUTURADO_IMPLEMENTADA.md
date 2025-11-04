# ✅ Melhoria #12 Implementada: Melhorar Logging Estruturado

## 📋 O Que Foi Implementado

Implementada a **Melhoria #12** do documento `MELHORIAS_PRIORITARIAS.md`: **Melhorar Logging Estruturado**.

## 🔧 Mudanças Realizadas

### 1. **StructuredFormatter Criado**

**Arquivo:** `utils/logger.py`

**Classe:** `StructuredFormatter`

**Funcionalidades:**
- ✅ Formata logs com contexto estruturado
- ✅ Extrai campos de contexto do LogRecord
- ✅ Adiciona contexto ao formato de saída
- ✅ Suporta campos padrão e customizados

**Campos Suportados:**
- `game_id` - ID do jogo
- `ext_id` - ID externo do jogo
- `url` - URL relacionada
- `duration_ms` - Duração em milissegundos
- `status` - Status do processo
- `stage` - Etapa do processo
- `backend` - Backend usado
- `attempt` - Número da tentativa
- `sport_id`, `category_id`, `tournament_id` - IDs de campeonato
- `events_count`, `method` - Metadados de extração
- `outcome`, `hit`, `result_msg` - Resultados de jogos
- Campos customizados via `**extra_fields`

### 2. **Função Helper `log_with_context()`**

**Arquivo:** `utils/logger.py`

**Funcionalidades:**
- ✅ Loga mensagens com contexto estruturado
- ✅ Suporta todos os níveis de log (debug, info, warning, error, critical)
- ✅ Remove valores None automaticamente
- ✅ Suporta campos customizados via `**extra_fields`

**Assinatura:**
```python
def log_with_context(
    level: str,
    message: str,
    game_id: Optional[int] = None,
    ext_id: Optional[str] = None,
    url: Optional[str] = None,
    duration_ms: Optional[float] = None,
    status: Optional[str] = None,
    stage: Optional[str] = None,
    backend: Optional[str] = None,
    attempt: Optional[int] = None,
    **extra_fields
) -> None
```

### 3. **Logs Melhorados em Funções Críticas**

**Arquivos Modificados:**

#### A. `scraping/fetchers.py`

**Função:** `fetch_events_from_link()`

**Antes:**
```python
logger.info("🔎 Varredura iniciada para %s", url)
logger.info("📡 Tentando buscar via API XHR (sport_id=%d, category_id=%d, tournament_id=%d)", ...)
```

**Depois:**
```python
from utils.logger import log_with_context

log_with_context(
    "info",
    f"Varredura iniciada para {url}",
    url=url,
    stage="fetch_events",
    status="started"
)

log_with_context(
    "info",
    f"Tentando buscar via API XHR (sport_id={sport_id}, category_id={category_id}, tournament_id={tournament_id})",
    url=url,
    stage="api_xhr",
    status="attempting",
    extra_fields={
        "sport_id": sport_id,
        "category_id": category_id,
        "tournament_id": tournament_id
    }
)
```

#### B. `scraping/betnacional.py`

**Função:** `parse_events_from_api()`

**Antes:**
```python
logger.info(f"📊 → {len(events)} eventos extraídos via API XHR | URL: {source_url}")
```

**Depois:**
```python
from utils.logger import log_with_context

log_with_context(
    "info",
    f"Eventos extraídos via API XHR: {len(events)} eventos",
    url=source_url,
    stage="parse_events_api",
    status="success",
    extra_fields={"events_count": len(events), "method": "api_xhr"}
)
```

**Função:** `try_parse_events()`

**Antes:**
```python
logger.info(f"🧮 → eventos extraídos via HTML: {len(evs)} | URL: {url}")
```

**Depois:**
```python
from utils.logger import log_with_context

log_with_context(
    "info",
    f"Eventos extraídos via HTML: {len(evs)} eventos",
    url=url,
    stage="parse_events_html",
    status="success",
    extra_fields={"events_count": len(evs), "method": "html"}
)
```

#### C. `scheduler/jobs.py`

**Função:** `monitor_live_games_job()`

**Antes:**
```python
logger.info("⚽ Iniciando monitoramento de %d jogo(s) ao vivo...", len(live_games))
logger.info("⚽ Monitoramento de jogos ao vivo concluído.")
```

**Depois:**
```python
from utils.logger import log_with_context

log_with_context(
    "info",
    f"Iniciando monitoramento de {len(live_games)} jogo(s) ao vivo",
    stage="monitor_live_games",
    status="started",
    extra_fields={"games_count": len(live_games)}
)

log_with_context(
    "info",
    "Monitoramento de jogos ao vivo concluído",
    stage="monitor_live_games",
    status="completed"
)
```

**Função:** `_handle_finished_game()`

**Antes:**
```python
logger.info(f"🏁 Resultado obtido para jogo {game.id}: {outcome} | {result_msg}")
```

**Depois:**
```python
from utils.logger import log_with_context

log_with_context(
    "info",
    f"Resultado obtido para jogo: {outcome} | {result_msg}",
    game_id=game.id,
    ext_id=game.ext_id,
    stage="fetch_result",
    status="success",
    extra_fields={"outcome": outcome, "hit": game.hit, "result_msg": result_msg}
)
```

## 📊 Benefícios

### 1. **Observabilidade Melhorada**
- ✅ Logs incluem contexto estruturado
- ✅ Fácil filtrar e buscar logs por campo
- ✅ Análise mais eficiente de logs

### 2. **Debug Mais Fácil**
- ✅ Contexto completo em cada log
- ✅ Identificação rápida de problemas
- ✅ Rastreabilidade de operações

### 3. **Análise de Performance**
- ✅ Duração de operações pode ser logada
- ✅ Identificação de gargalos
- ✅ Métricas de performance

### 4. **Integração com Ferramentas**
- ✅ Logs estruturados podem ser parseados facilmente
- ✅ Compatível com ELK, Grafana, etc
- ✅ Fácil extrair métricas

## 🧪 Como Funciona

### Exemplo de Uso

**Antes:**
```python
logger.info("Eventos extraídos: %d", len(events))
```

**Depois:**
```python
from utils.logger import log_with_context

log_with_context(
    "info",
    f"Eventos extraídos: {len(events)} eventos",
    url=url,
    stage="parse_events",
    status="success",
    extra_fields={"events_count": len(events), "method": "api"}
)
```

### Formato de Saída

**Antes:**
```
2025-11-04 14:30:00 | INFO | Eventos extraídos: 10
```

**Depois:**
```
2025-11-04 14:30:00 | INFO | Eventos extraídos: 10 eventos | url=https://betnacional.bet.br/events/1/0/7 | stage=parse_events | status=success | events_count=10 | method=api
```

### Campos Customizados

```python
log_with_context(
    "info",
    "Operação concluída",
    game_id=123,
    ext_id="456",
    duration_ms=150.5,
    extra_fields={
        "custom_field": "value",
        "another_field": 42
    }
)
```

**Saída:**
```
2025-11-04 14:30:00 | INFO | Operação concluída | another_field=42 | custom_field=value | duration_ms=150.5 | ext_id=456 | game_id=123
```

## 📈 Impacto Esperado

### Antes (Logs Simples)
```
2025-11-04 14:30:00 | INFO | Eventos extraídos: 10
```
❌ **Não sabemos:** De qual URL? Qual método? Qual etapa?

### Depois (Logs Estruturados)
```
2025-11-04 14:30:00 | INFO | Eventos extraídos: 10 eventos | url=https://betnacional.bet.br/events/1/0/7 | stage=parse_events | status=success | events_count=10 | method=api
```
✅ **Sabemos:** URL completa, etapa, status, método, contagem

**Benefícios:**
- ✅ **Filtragem eficiente** de logs por campo
- ✅ **Análise mais rápida** de problemas
- ✅ **Métricas extraíveis** automaticamente

## ⚙️ Configuração

### Usar Logging Estruturado

**Opção 1: Função Helper (Recomendado)**
```python
from utils.logger import log_with_context

log_with_context(
    "info",
    "Mensagem do log",
    game_id=123,
    ext_id="456",
    url="https://example.com",
    stage="processing",
    status="success"
)
```

**Opção 2: Logger Padrão com Extra (Compatível)**
```python
from utils.logger import logger

logger.info(
    "Mensagem do log",
    extra={
        "game_id": 123,
        "ext_id": "456",
        "url": "https://example.com",
        "stage": "processing",
        "status": "success"
    }
)
```

### Adicionar Campos Customizados

```python
log_with_context(
    "info",
    "Operação personalizada",
    game_id=123,
    extra_fields={
        "custom_metric": 42,
        "another_field": "value"
    }
)
```

## 📊 Estrutura de Logs

### Campos Padrão

| Campo | Tipo | Descrição |
|-------|------|-----------|
| `game_id` | int | ID do jogo no banco |
| `ext_id` | str | ID externo do jogo |
| `url` | str | URL relacionada |
| `duration_ms` | float | Duração em milissegundos |
| `status` | str | Status (started, success, failed, etc) |
| `stage` | str | Etapa do processo |
| `backend` | str | Backend usado (requests, playwright) |
| `attempt` | int | Número da tentativa |

### Campos de Extração

| Campo | Tipo | Descrição |
|-------|------|-----------|
| `sport_id` | int | ID do esporte |
| `category_id` | int | ID da categoria |
| `tournament_id` | int | ID do torneio |
| `events_count` | int | Número de eventos extraídos |
| `method` | str | Método usado (api, html) |

### Campos de Resultado

| Campo | Tipo | Descrição |
|-------|------|-----------|
| `outcome` | str | Resultado do jogo (home, draw, away) |
| `hit` | bool | Se acertou o palpite |
| `result_msg` | str | Mensagem do resultado |

## 🔄 Funcionamento

### Fluxo de Logging Estruturado

```
1. log_with_context() chamado
   ↓
2. Campos de contexto coletados
   ↓
3. Valores None removidos
   ↓
4. Log criado com extra={...}
   ↓
5. StructuredFormatter formata
   ↓
6. Contexto adicionado ao log
   ↓
7. Log escrito (arquivo + console)
```

### Compatibilidade

**Logs Antigos:**
- ✅ Continuam funcionando normalmente
- ✅ Sem contexto estruturado (comportamento padrão)

**Logs Novos:**
- ✅ Incluem contexto estruturado
- ✅ Compatíveis com logs antigos

## ✅ Status

**IMPLEMENTADO E PRONTO PARA USO**

O sistema agora:
- ✅ Tem logging estruturado implementado
- ✅ Função helper para facilitar uso
- ✅ Logs críticos atualizados com contexto
- ✅ Compatível com logs existentes

---

**Implementação concluída em:** 2025-11-04

**Arquivos criados/modificados:**
- `utils/logger.py` - StructuredFormatter e log_with_context()
- `scraping/fetchers.py` - Logs estruturados em fetch_events_from_link()
- `scraping/betnacional.py` - Logs estruturados em parsing
- `scheduler/jobs.py` - Logs estruturados em monitor_live_games_job()

