# ✅ Como o Sistema Verifica se os Sinais Foram Corretos

## 📋 Visão Geral

O sistema verifica automaticamente se os sinais (palpites/apostas) foram corretos após cada jogo terminar, comparando o **resultado real** com o **palpite feito**.

## 🔄 Fluxo Completo de Verificação

### 1. **Monitoramento do Jogo**

O sistema monitora jogos em tempo real através do job `monitor_live_games_job()`:

```python
# scheduler/jobs.py, linha 636
async def monitor_live_games_job():
    # Monitora jogos ao vivo
    # Verifica quando o jogo termina
    # Busca o resultado automaticamente
```

### 2. **Detecção de Fim do Jogo**

Quando o sistema detecta que um jogo terminou (status mudou de "live" para "ended"):

```python
# scheduler/jobs.py, linha 717-721
if game.status == "ended":
    # Busca o resultado do jogo
    outcome = await fetch_game_result(game.ext_id, game.game_url or game.source_link)
```

### 3. **Busca do Resultado**

A função `fetch_game_result()` busca o resultado da página do jogo:

```python
# scraping/fetchers.py, linha 146
async def fetch_game_result(ext_id: str, source_link: str) -> Optional[str]:
    """
    Busca o resultado de um jogo específico.
    Retorna: "home", "draw", ou "away"
    """
    html = await _fetch_requests_async(source_link)
    return scrape_game_result(html, ext_id)
```

### 4. **Extração do Resultado**

A função `scrape_game_result()` extrai o resultado do HTML usando múltiplas estratégias:

```python
# scraping/betnacional.py, linha 657
def scrape_game_result(html: str, ext_id: str) -> Optional[str]:
    """
    Tenta extrair o resultado final (home/draw/away) da página HTML.
    
    Estratégias:
    1. Procura por texto "Vencedor" / "Winner"
    2. Procura por classes CSS comuns (.winner, .vencedor)
    3. Retorna None se não encontrar
    """
```

**Estratégias de Extração:**
- ✅ **Estratégia 1**: Procura por texto "Vencedor" ou "Winner" e verifica se está associado a "Casa", "Fora" ou "Empate"
- ✅ **Estratégia 2**: Procura por classes CSS como `.winner`, `.vencedor`, `[class*="winner"]`
- ⚠️ **Estratégia 3**: Se não encontrar, retorna `None` (tentará novamente mais tarde)

### 5. **Comparação com o Palpite**

Após obter o resultado, o sistema compara com o palpite:

```python
# scheduler/jobs.py, linha 724-725
if outcome:
    game.outcome = outcome  # Salva o resultado real
    game.hit = (outcome == game.pick) if game.pick else None  # Compara
```

**Lógica de Comparação:**
- `game.hit = True` → ✅ **ACERTOU** (outcome == pick)
- `game.hit = False` → ❌ **ERROU** (outcome != pick)
- `game.hit = None` → ⚠️ **SEM PALPITE** (não havia palpite)

### 6. **Notificação do Resultado**

O sistema envia uma notificação automática via Telegram:

```python
# scheduler/jobs.py, linha 730-731
from utils.formatters import fmt_result
tg_send_message(fmt_result(game), message_type="result", ...)
```

**Mensagem enviada inclui:**
- ✅/❌ Se acertou ou errou
- ⚽ Times e placar
- 💰 Odds usadas
- 📊 Palpite vs Resultado
- 📈 EV estimado

### 7. **Tentativas de Rebusca**

Se o resultado não for encontrado imediatamente:

```python
# scheduler/jobs.py, linha 738-741
else:
    # Agenda nova tentativa
    asyncio.create_task(watch_game_until_end_job(game.id))
```

A função `watch_game_until_end_job()` tenta novamente a cada 5 minutos até obter o resultado.

## 📊 Estatísticas Calculadas

O sistema calcula automaticamente:

### 1. **Assertividade Lifetime**

```python
# utils/stats.py, linha 69
def get_lifetime_accuracy(session) -> Dict[str, Any]:
    """
    Calcula assertividade de todos os jogos com resultado verificado.
    """
    all_games = session.query(Game).filter(
        Game.hit.isnot(None),  # Jogos com resultado verificado
        Game.status == "ended"
    ).all()
    
    hits = sum(1 for g in all_games if g.hit is True)
    accuracy = hits / total * 100
```

**Retorna:**
- Total de jogos verificados
- Quantidade de acertos
- Quantidade de erros
- Percentual de assertividade
- ROI estimado

### 2. **Resumo Diário**

Quando todos os jogos do dia terminam:

```python
# scheduler/jobs.py, linha 995
async def maybe_send_daily_wrapup():
    """
    Verifica se todos os jogos do dia terminaram e envia resumo.
    """
    # Verifica quantos terminaram
    finished = [g for g in todays_games if g.status == "ended" and g.hit is not None]
    
    # Se todos terminaram, envia resumo
    if len(finished) == len(todays_games):
        summary_msg = fmt_daily_summary(session, datetime.now(ZONE))
        tg_send_message(summary_msg)
```

## 🗄️ Armazenamento no Banco de Dados

### Campos Importantes na Tabela `Game`:

```python
# models/database.py, linha 13
class Game(Base):
    # ... outros campos ...
    pick = Column(String)        # home|draw|away (palpite)
    outcome = Column(String)    # home|draw|away (resultado real)
    hit = Column(Boolean)       # True=acertou, False=errou, None=sem palpite
    status = Column(String)     # scheduled|live|ended
```

## 📱 Notificações Enviadas

### 1. **Notificação Individual** (após cada jogo)

```
✅ RESULTADO - ACERTAMOS
━━━━━━━━━━━━━━━━━━━━

⚽ Flamengo vs Palmeiras

💰 ODDS
├ Flamengo: 2.10
├ Empate: 3.40
└ Palmeiras: 3.20

📊 RESULTADO
├ Palpite: Flamengo
├ Resultado: Flamengo
└ EV estimado: +5.2%
```

### 2. **Resumo Diário** (quando todos terminam)

Mostra estatísticas do dia:
- Total de jogos
- Acertos vs Erros
- Assertividade do dia
- ROI estimado

## ⚠️ Limitações Atuais

### 1. **Extração do Resultado**

O método atual de extração do resultado é limitado:
- Depende de encontrar texto "Vencedor" no HTML
- Pode falhar se a estrutura HTML mudar
- Retorna `None` se não encontrar (requer nova tentativa)

### 2. **Melhorias Possíveis**

1. **Usar API XHR** para buscar resultado (se disponível)
2. **Extrair do placar final** (se disponível no HTML)
3. **Verificar múltiplas fontes** (HTML + API)
4. **Melhorar estratégias de busca** no HTML

## 🔧 Como Melhorar a Verificação

### Opção 1: Usar API XHR (Recomendado)

Se a API da BetNacional expõe resultado final, podemos usar:

```python
def fetch_result_from_api(event_id: int) -> Optional[str]:
    """
    Busca resultado via API XHR.
    """
    # Chamar API: /api/event-odds/{event_id}
    # Extrair resultado do JSON
    # Retornar "home", "draw", ou "away"
```

### Opção 2: Melhorar Extração HTML

Adicionar mais estratégias:

```python
def scrape_game_result(html: str, ext_id: str) -> Optional[str]:
    # Estratégia 1: Texto "Vencedor" (atual)
    # Estratégia 2: Classes CSS (atual)
    # Estratégia 3: Extrair do placar final
    # Estratégia 4: Buscar em elementos de resultado
    # Estratégia 5: Verificar status do jogo na API
```

### Opção 3: Fallback para Múltiplas Fontes

```python
async def fetch_game_result(ext_id: str, source_link: str) -> Optional[str]:
    # Tentar 1: API XHR
    # Tentar 2: HTML scraping melhorado
    # Tentar 3: Extrair do placar
    # Retornar o primeiro que funcionar
```

## 📈 Métricas de Sucesso

O sistema rastreia automaticamente:

- ✅ **Assertividade**: Percentual de acertos
- ✅ **ROI**: Retorno sobre investimento estimado
- ✅ **Estatísticas por dia**: Resumo diário
- ✅ **Estatísticas lifetime**: Histórico completo

## 🎯 Conclusão

O sistema **verifica automaticamente** se os sinais foram corretos:

1. ✅ Monitora jogos até o fim
2. ✅ Busca resultado automaticamente
3. ✅ Compara com o palpite
4. ✅ Salva no banco de dados
5. ✅ Notifica via Telegram
6. ✅ Calcula estatísticas

**A única limitação atual é a extração do resultado do HTML**, que pode ser melhorada usando a API XHR ou melhorando as estratégias de scraping.

