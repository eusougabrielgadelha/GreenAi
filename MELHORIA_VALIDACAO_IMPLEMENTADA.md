# ✅ Melhoria #5 Implementada: Validação de Dados

## 📋 O Que Foi Implementado

Implementada a **Melhoria #5** do documento `MELHORIAS_PRIORITARIAS.md`: **Validação de Dados**.

## 🔧 Mudanças Realizadas

### 1. **Criado Módulo de Validação**

**Arquivo:** `utils/validators.py` (NOVO)

**Funções de Validação:**

#### A. `validate_odds(odds_home, odds_draw, odds_away)`
Valida e normaliza odds de apostas.

**Validações:**
- ✅ Odds devem estar entre 1.0 e 100.0
- ✅ Odds não podem ser zero
- ✅ Todas as três odds devem estar presentes
- ✅ Valores devem ser numéricos

**Retorna:**
- `(odds_home, odds_draw, odds_away)` se válidas
- `(None, None, None)` se inválidas

#### B. `validate_event_data(event_id, home, away, odds_home, odds_draw, odds_away)`
Valida dados básicos de um evento.

**Validações:**
- ✅ `event_id` deve ser um inteiro positivo
- ✅ Nomes dos times devem ser strings não vazias
- ✅ Odds devem ser válidas (se fornecidas)

**Retorna:**
- `Dict` com dados validados se válido
- `None` se inválido

#### C. `validate_score(home_goals, away_goals)`
Valida placar de um jogo.

**Validações:**
- ✅ Gols devem ser inteiros >= 0
- ✅ Gols não podem ser absurdamente altos (> 50)

**Retorna:**
- `(home_goals, away_goals)` se válido
- `None` se inválido

#### D. `validate_tournament_data(tournament_id, tournament_name, ...)`
Valida dados de um campeonato/torneio.

**Validações:**
- ✅ `tournament_id` deve ser um inteiro positivo
- ✅ Nome do torneio deve ser string não vazia

#### E. `sanitize_string(s, max_length)`
Sanitiza strings removendo caracteres inválidos e limitando tamanho.

### 2. **Integrado Validação em Funções de Parsing**

**Arquivo:** `scraping/betnacional.py`

**Funções Atualizadas:**

#### A. `parse_events_from_api()`
- ✅ Valida odds antes de processar evento
- ✅ Valida dados do evento (event_id, home, away)
- ✅ Ignora eventos com dados inválidos
- ✅ Usa apenas dados validados

**Antes:**
```python
odds_home = odds.get('1')
odds_draw = odds.get('2')
odds_away = odds.get('3')

if not (odds_home and odds_draw and odds_away):
    continue
```

**Depois:**
```python
from utils.validators import validate_odds, validate_event_data

# Validar odds
home_odd, draw_odd, away_odd = validate_odds(odds_home, odds_draw, odds_away)
if not (home_odd and draw_odd and away_odd):
    logger.debug(f"Evento {event_id} ignorado: odds inválidas")
    continue

# Validar dados do evento
validated_event = validate_event_data(
    event_id=event_id,
    home=event_data.get('home', ''),
    away=event_data.get('away', ''),
    odds_home=home_odd,
    odds_draw=draw_odd,
    odds_away=away_odd
)

if not validated_event:
    logger.debug(f"Evento {event_id} ignorado: dados inválidos")
    continue

# Usar dados validados
validated_home = validated_event['home']
validated_away = validated_event['away']
validated_odds = validated_event['odds']
```

#### B. `parse_event_odds_from_api()`
- ✅ Valida range de odds (1.0 a 100.0) antes de adicionar
- ✅ Loga odds inválidas para debug

**Antes:**
```python
try:
    markets_dict[market_id]['odds'][outcome_id] = float(odd_value)
except (ValueError, TypeError):
    pass
```

**Depois:**
```python
try:
    odd_float = float(odd_value)
    # Validar range (1.0 a 100.0)
    if 1.0 <= odd_float <= 100.0:
        markets_dict[market_id]['odds'][outcome_id] = odd_float
    else:
        logger.debug(f"Odd {outcome_id} inválida (fora do range): {odd_float}")
except (ValueError, TypeError) as e:
    logger.debug(f"Erro ao converter odd {outcome_id}: {e}")
```

#### C. `scrape_game_result()`
- ✅ Valida placar antes de determinar resultado
- ✅ Ignora placares inválidos

**Antes:**
```python
home_goals = int(score_elements[0].get_text(strip=True))
away_goals = int(score_elements[1].get_text(strip=True))
```

**Depois:**
```python
from utils.validators import validate_score

home_goals_raw = score_elements[0].get_text(strip=True)
away_goals_raw = score_elements[1].get_text(strip=True)

validated_score = validate_score(home_goals_raw, away_goals_raw)
if validated_score:
    home_goals, away_goals = validated_score
    # Determinar resultado...
```

#### D. `scrape_live_game_data()`
- ✅ Valida placar antes de adicionar aos stats

## 📊 Benefícios

### 1. **Prevenção de Erros**
- ✅ Dados inválidos são detectados antes de usar
- ✅ Evita erros inesperados durante processamento
- ✅ Sistema mais robusto e confiável

### 2. **Melhor Qualidade de Dados**
- ✅ Apenas dados válidos são processados
- ✅ Odds fora do range são ignoradas
- ✅ Eventos com dados incompletos são filtrados

### 3. **Debug Mais Fácil**
- ✅ Logs informam quando dados inválidos são ignorados
- ✅ Facilita identificar problemas na API
- ✅ Ajuda a entender padrões de dados inválidos

### 4. **Manutenibilidade**
- ✅ Validação centralizada
- ✅ Fácil adicionar novas validações
- ✅ Consistência entre diferentes funções

## 🧪 Como Funciona

### Validação de Odds

```python
# Caso 1: Odds válidas
validate_odds(2.1, 3.4, 3.2)
# Retorna: (2.1, 3.4, 3.2)

# Caso 2: Odd fora do range
validate_odds(150.0, 3.4, 3.2)
# Retorna: (None, None, None)
# Log: "Odd home inválida (fora do range): 150.0"

# Caso 3: Odd zero
validate_odds(0, 3.4, 3.2)
# Retorna: (None, None, None)
# Log: "Odd home inválida (zero): 0"
```

### Validação de Evento

```python
# Caso 1: Evento válido
validate_event_data(
    event_id=12345,
    home="Flamengo",
    away="Palmeiras",
    odds_home=2.1,
    odds_draw=3.4,
    odds_away=3.2
)
# Retorna: {
#     'event_id': 12345,
#     'home': 'Flamengo',
#     'away': 'Palmeiras',
#     'odds': {'home': 2.1, 'draw': 3.4, 'away': 3.2}
# }

# Caso 2: Evento inválido (nome vazio)
validate_event_data(
    event_id=12345,
    home="",
    away="Palmeiras",
    odds_home=2.1,
    odds_draw=3.4,
    odds_away=3.2
)
# Retorna: None
# Log: "Nome do time da casa inválido: "
```

### Validação de Placar

```python
# Caso 1: Placar válido
validate_score(2, 1)
# Retorna: (2, 1)

# Caso 2: Placar inválido (valores negativos)
validate_score(-1, 0)
# Retorna: None
# Log: "Placar inválido (valores negativos): -1-0"

# Caso 3: Placar inválido (valores muito altos)
validate_score(100, 50)
# Retorna: None
# Log: "Placar inválido (valores muito altos): 100-50"
```

## 📈 Impacto Esperado

### Antes (Sem Validação)
```
API retorna: odds_home=150.0, odds_draw=3.4, odds_away=3.2
Sistema processa → Erro ao calcular EV → Sistema quebra ❌
```

### Depois (Com Validação)
```
API retorna: odds_home=150.0, odds_draw=3.4, odds_away=3.2
Sistema valida → Odds inválidas detectadas
Evento ignorado → Log: "Evento 12345 ignorado: odds inválidas"
Sistema continua normalmente ✅
```

**Benefícios:**
- ✅ **Redução de ~90%** em erros por dados inválidos (estimado)
- ✅ Sistema mais robusto e confiável
- ✅ Melhor qualidade de dados processados

## ⚙️ Configuração

### Ajustar Range de Odds

Por padrão, odds devem estar entre 1.0 e 100.0. Para alterar:

```python
# utils/validators.py
def validate_odds(odds_home, odds_draw, odds_away, min_odd=1.0, max_odd=100.0):
    if home < min_odd or home > max_odd:
        # ...
```

### Ajustar Limite de Gols

Por padrão, gols não podem ser > 50. Para alterar:

```python
# utils/validators.py
def validate_score(home_goals, away_goals, max_goals=50):
    if home > max_goals or away > max_goals:
        # ...
```

## 📊 Estrutura de Validação

### Validações Implementadas

1. **Odds:**
   - Range: 1.0 a 100.0
   - Não pode ser zero
   - Deve ser numérico

2. **Eventos:**
   - `event_id`: Inteiro positivo
   - `home`, `away`: Strings não vazias
   - Odds: Válidas (se fornecidas)

3. **Placar:**
   - Gols: Inteiros >= 0
   - Gols: <= 50 (limite razoável)

4. **Torneios:**
   - `tournament_id`: Inteiro positivo
   - `tournament_name`: String não vazia

5. **Strings:**
   - Sanitização e limite de tamanho

## 🔄 Funcionamento

### Fluxo de Validação

```
1. Dados recebidos da API
   ↓
2. Validação de odds
   ├─ Válidas → Continua
   └─ Inválidas → Ignora evento
   ↓
3. Validação de dados do evento
   ├─ Válidos → Continua
   └─ Inválidos → Ignora evento
   ↓
4. Processamento com dados validados
   ↓
5. Dados seguros para uso
```

## ✅ Status

**IMPLEMENTADO E PRONTO PARA USO**

O sistema agora:
- ✅ Valida todos os dados antes de usar
- ✅ Ignora dados inválidos automaticamente
- ✅ Loga informações sobre dados inválidos
- ✅ Previne erros inesperados

---

**Implementação concluída em:** 2025-11-04

**Arquivos criados/modificados:**
- `utils/validators.py` (NOVO) - Módulo de validação
- `scraping/betnacional.py` - Integração com validadores

