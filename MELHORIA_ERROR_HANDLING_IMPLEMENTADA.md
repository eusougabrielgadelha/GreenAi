# ✅ Melhoria #4 Implementada: Tratamento de Erros Melhorado

## 📋 O Que Foi Implementado

Implementada a **Melhoria #4** do documento `MELHORIAS_PRIORITARIAS.md`: **Melhorar Tratamento de Erros**.

## 🔧 Mudanças Realizadas

### 1. **Criado Módulo de Tratamento de Erros**

**Arquivo:** `utils/error_handler.py` (NOVO)

**Função Principal `log_error_with_context()`:**
- ✅ Loga erros com contexto detalhado
- ✅ Inclui tipo de erro, mensagem e traceback completo
- ✅ Suporta diferentes níveis (error, warning, critical)
- ✅ Opção de re-levantar exceção após logar

**Funcionalidades:**
```python
def log_error_with_context(
    error: Exception,
    context: Optional[Dict[str, Any]] = None,
    level: str = "error",
    reraise: bool = False
) -> None
```

**Contexto Incluído:**
- Tipo de erro (`error_type`)
- Mensagem de erro (`error_message`)
- Traceback completo (`traceback`)
- Contexto customizado (url, ext_id, stage, etc)

**Funções Auxiliares:**
- `safe_execute()` - Executa função sync com tratamento de erro
- `safe_execute_async()` - Executa função async com tratamento de erro
- `@with_error_context()` - Decorator para adicionar contexto automaticamente

### 2. **Integrado em Funções Críticas de Scraping**

**Arquivo:** `scraping/fetchers.py`

**Funções Atualizadas:**
- ✅ `fetch_events_from_link()` - Erros de API XHR com contexto
- ✅ `_fetch_requests_async()` - Erros de requisição HTTP com contexto
- ✅ `fetch_game_result()` - Erros de busca de resultado com contexto

**Antes:**
```python
except Exception as e:
    error_msg = str(e)[:500]
    logger.warning("Erro ao buscar via API XHR: %s", error_msg)
```

**Depois:**
```python
except Exception as e:
    from utils.error_handler import log_error_with_context
    log_error_with_context(
        e,
        context={
            "url": url,
            "sport_id": sport_id,
            "category_id": category_id,
            "tournament_id": tournament_id,
            "stage": "api_xhr"
        },
        level="warning",
        reraise=False
    )
```

**Arquivo:** `scraping/betnacional.py`

**Funções Atualizadas:**
- ✅ `fetch_events_from_api()` - Erros de API com contexto
- ✅ `fetch_event_odds_from_api()` - Erros de odds com contexto
- ✅ `parse_local_datetime()` - Logs de debug para erros de parsing

### 3. **Contexto Adicionado aos Logs**

**Informações Agora Incluídas:**
- ✅ URL sendo processada
- ✅ IDs relevantes (sport_id, category_id, tournament_id, event_id, ext_id)
- ✅ Stage/etapa onde ocorreu o erro
- ✅ Backend usado (se aplicável)
- ✅ Número de tentativa (se aplicável)
- ✅ Traceback completo (em nível debug)

**Exemplo de Log Melhorado:**
```
2025-11-04 14:30:00 | ERROR | Erro: HTTPError | Contexto: url=https://betnacional.bet.br/events/1/0/7, sport_id=1, category_id=0, tournament_id=7, stage=api_xhr
2025-11-04 14:30:00 | DEBUG | Traceback completo:
  File "scraping/betnacional.py", line 97, in fetch_events_from_api
    response.raise_for_status()
  ...
```

## 📊 Benefícios

### 1. **Debug Mais Fácil**
- ✅ Contexto completo em todos os erros
- ✅ Traceback completo disponível
- ✅ Identificação rápida de onde ocorreu o erro

### 2. **Melhor Rastreabilidade**
- ✅ Cada erro tem contexto suficiente para entender o problema
- ✅ URLs, IDs e parâmetros são logados
- ✅ Stage/etapa onde ocorreu o erro é identificado

### 3. **Logs Mais Informativos**
- ✅ Não mais erros silenciosos
- ✅ Informações relevantes sempre presentes
- ✅ Facilita troubleshooting

### 4. **Manutenibilidade**
- ✅ Código centralizado para tratamento de erros
- ✅ Consistência entre diferentes funções
- ✅ Fácil adicionar mais contexto no futuro

## 🧪 Como Funciona

### Exemplo de Uso Direto

```python
from utils.error_handler import log_error_with_context

try:
    result = await fetch_data(url)
except Exception as e:
    log_error_with_context(
        e,
        context={
            "url": url,
            "ext_id": ext_id,
            "stage": "data_fetch"
        },
        level="error",
        reraise=False
    )
```

### Exemplo com Decorator

```python
from utils.error_handler import with_error_context

@with_error_context(module="scraping", component="fetcher")
async def fetch_data(url: str):
    # código que pode falhar
    pass
```

### Exemplo com Safe Execute

```python
from utils.error_handler import safe_execute_async

result = await safe_execute_async(
    fetch_data,
    url,
    context={"url": url},
    default_return=None
)
```

## 📈 Impacto Esperado

### Antes (Erros Sem Contexto)
```
2025-11-04 14:30:00 | WARNING | Erro ao buscar via API XHR: 403 Forbidden
```
❌ **Não sabemos:** Qual URL? Quais parâmetros? Onde exatamente falhou?

### Depois (Erros Com Contexto)
```
2025-11-04 14:30:00 | WARNING | Erro: HTTPError | Contexto: url=https://betnacional.bet.br/events/1/0/7, sport_id=1, category_id=0, tournament_id=7, stage=api_xhr
2025-11-04 14:30:00 | DEBUG | Traceback completo:
  File "scraping/betnacional.py", line 97, in fetch_events_from_api
    response = requests.get(api_url, params=params, headers=headers, timeout=20)
  ...
```
✅ **Sabemos:** URL completa, todos os parâmetros, onde falhou, traceback completo

## ⚙️ Configuração

### Níveis de Log

- **error**: Para erros críticos que precisam atenção
- **warning**: Para erros que têm fallback (ex: API → HTML)
- **critical**: Para erros que podem parar o sistema

### Re-levantar Exceção

```python
# Não re-levantar (padrão para fallbacks)
log_error_with_context(e, context={...}, reraise=False)

# Re-levantar (para erros críticos)
log_error_with_context(e, context={...}, reraise=True)
```

## 📊 Estrutura de Contexto

**Contexto Padrão Incluído:**
- `error_type`: Tipo da exceção (ex: "HTTPError", "ValueError")
- `error_message`: Mensagem do erro (limitado a 500 chars)
- `traceback`: Traceback completo

**Contexto Customizado (exemplos):**
- `url`: URL sendo processada
- `ext_id`: ID externo do jogo
- `sport_id`, `category_id`, `tournament_id`: IDs do campeonato
- `event_id`: ID do evento
- `stage`: Etapa onde ocorreu (ex: "api_xhr", "html_scraping")
- `backend`: Backend usado (ex: "playwright", "requests")
- `attempt`: Número da tentativa

## 🔄 Funcionamento

### Fluxo de Tratamento de Erro

```
1. Erro ocorre
   ↓
2. log_error_with_context() é chamado
   ↓
3. Extrai informações do erro
   - Tipo de erro
   - Mensagem
   - Traceback
   ↓
4. Combina com contexto fornecido
   ↓
5. Loga com nível apropriado
   ↓
6. Loga traceback completo (se error/critical)
   ↓
7. Re-levanta se solicitado (reraise=True)
```

## ✅ Status

**IMPLEMENTADO E PRONTO PARA USO**

O sistema agora:
- ✅ Loga todos os erros com contexto detalhado
- ✅ Inclui traceback completo quando necessário
- ✅ Identifica claramente onde ocorreu o erro
- ✅ Facilita debug e troubleshooting

---

**Implementação concluída em:** 2025-11-04

**Arquivos criados/modificados:**
- `utils/error_handler.py` (NOVO) - Módulo de tratamento de erros
- `scraping/fetchers.py` - Integração com error handler
- `scraping/betnacional.py` - Integração com error handler

