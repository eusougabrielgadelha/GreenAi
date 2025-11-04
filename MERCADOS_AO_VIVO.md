# 📊 Mercados de Apostas ao Vivo - Suportados

## 🎯 Mercados Implementados

O sistema agora suporta a extração dos seguintes mercados de apostas para jogos ao vivo:

### 1. ✅ Resultado Final (1x2)
- **Chave:** `match_result`
- **Market ID:** `1`
- **Opções:** Casa, Empate, Fora
- **Status:** ✅ Implementado

### 2. ✅ Placar Exato / Gols Exatos
- **Chave:** `correct_score`
- **Market ID:** Detectado dinamicamente (geralmente `2` ou `3`)
- **Formato de Outcome IDs:** `"0-0"`, `"1-0"`, `"0-1"`, `"2-1"`, etc.
- **Normalização:** Formato `"0x0"` é convertido para `"0-0"`
- **Status:** ✅ Implementado

### 3. ✅ Handicap Asiático
- **Chave:** `asian_handicap`
- **Market ID:** Detectado dinamicamente (geralmente `4` ou `5`)
- **Formato de Outcome IDs:** 
  - `"H1"`, `"H2"`, `"H-1"`, `"H-2"` (Handicap numérico)
  - `"H0.5"`, `"H-0.5"` (Handicap com meio)
  - `"AH1"`, `"AH2"` (Asian Handicap alternativo)
- **Status:** ✅ Implementado

### 4. ✅ Outros Mercados
- **Chave:** `market_{market_id}` (genérico)
- **Status:** ✅ Processamento genérico para mercados não identificados

---

## 🔍 Como Funciona

### Via API XHR (Prioritário)

A função `parse_event_odds_from_api()` identifica automaticamente os mercados pelos `outcome_ids`:

1. **Placar Exato:** Detecta padrões como `"0-0"`, `"1-0"`, `"2-1"`, etc.
2. **Handicap Asiático:** Detecta padrões como `"H1"`, `"AH2"`, `"H-0.5"`, etc.
3. **Outros:** Armazena como mercado genérico com `market_id`

### Via HTML Scraping (Fallback)

A função `scrape_live_game_data()` extrai mercados do HTML usando o mapeamento:

```python
market_name_map = {
    "Resultado Final": "match_result",
    "Placar Exato": "correct_score",
    "Gols Exatos": "correct_score",  # Sinônimo
    "Handicap Asiático": "asian_handicap",
    "Handicap": "asian_handicap",  # Forma abreviada
    # ... outros mercados
}
```

---

## 📝 Estrutura de Dados

### Formato de Retorno

```python
{
    "stats": {
        "event_id": 64743690,
        "home": "Time Casa",
        "away": "Time Fora",
        # ... outras estatísticas
    },
    "markets": {
        "match_result": {
            "display_name": "Resultado Final",
            "options": {
                "Casa": 2.50,
                "Empate": 3.20,
                "Fora": 2.80
            }
        },
        "correct_score": {
            "display_name": "Placar Exato",
            "options": {
                "0-0": 12.00,
                "1-0": 8.50,
                "0-1": 9.00,
                "1-1": 6.50,
                "2-1": 9.50
            },
            "market_id": 2
        },
        "asian_handicap": {
            "display_name": "Handicap Asiático",
            "options": {
                "H1": 1.85,
                "H-1": 1.95,
                "H0.5": 1.90
            },
            "market_id": 4
        }
    }
}
```

---

## 🚀 Uso no Sistema

### Exemplo de Extração

```python
from scraping.betnacional import scrape_live_game_data

# Via HTML
html = fetch_html_from_url("https://betnacional.bet.br/event/1/1/64743690")
data = scrape_live_game_data(html, ext_id="64743690", source_url="...")

# Verificar mercados disponíveis
if "correct_score" in data["markets"]:
    placar_opcoes = data["markets"]["correct_score"]["options"]
    print(f"Placares disponíveis: {list(placar_opcoes.keys())}")

if "asian_handicap" in data["markets"]:
    handicap_opcoes = data["markets"]["asian_handicap"]["options"]
    print(f"Handicaps disponíveis: {list(handicap_opcoes.keys())}")
```

### Exemplo de Decisão de Aposta

```python
from betting.decision import decide_live_bet_opportunity

# Verificar oportunidade em Placar Exato
if "correct_score" in live_data["markets"]:
    # Analisar odds de placares específicos
    # Ex: "1-0" com odd alta após 60 minutos
    pass

# Verificar oportunidade em Handicap Asiático
if "asian_handicap" in live_data["markets"]:
    # Analisar movimento de odds de handicap
    # Ex: H-1 com odd favorável após time marcar
    pass
```

---

## 🔧 Detalhes Técnicos

### Identificação de Placar Exato

```python
# Padrão regex para detectar placares
score_pattern = re.compile(r'^\d+[-x]\d+$', re.IGNORECASE)

# Exemplos válidos:
# "0-0" ✅
# "1-0" ✅
# "2-1" ✅
# "0x0" ✅ (normalizado para "0-0")
```

### Identificação de Handicap Asiático

```python
# Padrão regex para detectar handicaps
handicap_pattern = re.compile(r'^H[-]?[\d.]+$|^AH[-]?[\d.]+$', re.IGNORECASE)

# Exemplos válidos:
# "H1" ✅
# "H-1" ✅
# "H0.5" ✅
# "AH2" ✅
```

---

## 📊 Próximos Passos

### Melhorias Futuras

1. **Análise de Oportunidades:**
   - Implementar lógica de decisão para Placar Exato
   - Implementar lógica de decisão para Handicap Asiático

2. **Validação de Confiabilidade:**
   - Adicionar fatores de validação específicos para cada mercado
   - Considerar contexto do jogo (placar atual, tempo, etc.)

3. **Notificações:**
   - Formatar mensagens específicas para cada tipo de mercado
   - Incluir odds e contexto do mercado

---

## ✅ Status de Implementação

| Mercado | API XHR | HTML Scraping | Decisão | Validação |
|---------|---------|---------------|---------|-----------|
| Resultado Final | ✅ | ✅ | ✅ | ✅ |
| Placar Exato | ✅ | ✅ | ⏳ | ⏳ |
| Handicap Asiático | ✅ | ✅ | ⏳ | ⏳ |
| Outros Mercados | ✅ | ⏳ | ⏳ | ⏳ |

**Legenda:**
- ✅ Implementado
- ⏳ Pendente
- ❌ Não suportado

