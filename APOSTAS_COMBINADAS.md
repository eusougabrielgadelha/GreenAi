# 🎯 Sistema de Apostas Combinadas

## 📋 Visão Geral

O sistema de apostas combinadas cria automaticamente uma aposta combinando **todos os jogos de alta confiança do dia** que estão marcados para aposta (`will_bet=True`).

## 🎯 Funcionalidades

### 1. **Identificação de Jogos de Alta Confiança**

O sistema identifica jogos de alta confiança com base nos seguintes critérios:
- `will_bet = True` (jogo marcado para aposta)
- `pick_prob >= HIGH_CONF_THRESHOLD` (padrão: 0.60 ou 60%)
- `pick` não nulo (tem um palpite definido)
- `status = "scheduled"` ou `"live"` (jogo ainda não terminou)

### 2. **Cálculo de Odd Combinada**

A odd combinada é calculada multiplicando todas as odds individuais dos jogos:

```
Odd Combinada = odd_jogo1 × odd_jogo2 × odd_jogo3 × ... × odd_jogoN
```

**Exemplo:**
- Jogo 1: 1.50 (Casa)
- Jogo 2: 2.00 (Empate)
- Jogo 3: 1.80 (Fora)
- **Odd Combinada = 1.50 × 2.00 × 1.80 = 5.40**

### 3. **Cálculo de Retorno Potencial**

O retorno potencial é calculado multiplicando a odd combinada pelo valor da aposta:

```
Retorno Potencial = Odd Combinada × Valor Aposta
```

**Exemplo com R$ 10:**
- Odd Combinada: 5.40
- Valor Aposta: R$ 10.00
- **Retorno Potencial = 5.40 × 10.00 = R$ 54.00**

### 4. **Taxa de Assertividade**

O sistema calcula a taxa de assertividade das apostas combinadas:

```
Taxa de Assertividade = (Apostas Ganhas / Total de Apostas) × 100%
```

**Exemplo:**
- Total de apostas: 30
- Apostas ganhas: 12
- **Taxa de Assertividade = (12/30) × 100% = 40%**

## 📊 Modelo de Banco de Dados

### Tabela: `combined_bets`

| Campo | Tipo | Descrição |
|-------|------|-----------|
| `id` | Integer | ID único da aposta combinada |
| `bet_date` | DateTime | Data da aposta (dia dos jogos) |
| `game_ids` | JSON | Lista de IDs dos jogos incluídos [1, 2, 3] |
| `picks` | JSON | Lista de picks correspondentes ["home", "draw", "away"] |
| `odds` | JSON | Lista de odds correspondentes [1.5, 2.0, 1.8] |
| `combined_odd` | Float | Odd combinada (multiplicação de todas) |
| `example_stake` | Float | Valor de exemplo da aposta (padrão R$ 10) |
| `potential_return` | Float | Retorno potencial (combined_odd × example_stake) |
| `avg_confidence` | Float | Média de confiança (pick_prob) dos jogos |
| `total_games` | Integer | Número de jogos na aposta |
| `sent_at` | DateTime | Quando foi enviada a notificação |
| `status` | String | pending \| completed \| won \| lost |
| `outcome` | JSON | Resultados dos jogos após finalização |
| `hit` | Boolean | True se acertou, False se errou, None se pendente |
| `created_at` | DateTime | Data de criação |
| `updated_at` | DateTime | Data de atualização |

## 🔄 Fluxo de Funcionamento

### 1. **Criação da Aposta Combinada**

```
1. Job executa diariamente às 08:00 (configurável via COMBINED_BET_HOUR)
   ↓
2. Busca jogos de alta confiança do dia
   ↓
3. Se houver jogos, cria aposta combinada no banco
   ↓
4. Calcula odd combinada e retorno potencial
   ↓
5. Envia notificação no Telegram
```

### 2. **Atualização de Resultados**

```
1. Jogo termina e resultado é obtido
   ↓
2. Sistema verifica se há apostas combinadas pendentes que incluem este jogo
   ↓
3. Se todos os jogos da aposta terminaram:
   - Verifica se todos os picks acertaram
   - Atualiza status (won/lost)
   - Atualiza campo hit (True/False)
```

## 📱 Formato da Mensagem

A mensagem enviada no Telegram inclui:

```
🎯 APOSTA COMBINADA - ALTA CONFIANÇA
[Data]

📊 RESUMO
├ Total de jogos: X
├ Confiança média: X%
└ Odd combinada: X.XX

💰 EXEMPLO DE APOSTA
├ Valor apostado: R$ 10.00
└ Retorno potencial: R$ XX.XX

⚽ JOGOS INCLUÍDOS
[Lista de todos os jogos com picks e odds]
```

## ⚙️ Configuração

### Variáveis de Ambiente

```env
# Horário de envio da aposta combinada (padrão: 8)
COMBINED_BET_HOUR=8

# Limiar de alta confiança (padrão: 0.60 ou 60%)
HIGH_CONF_THRESHOLD=0.60
```

## 📊 Funções Disponíveis

### `get_high_confidence_games_for_date(target_date, session)`
Busca todos os jogos de alta confiança do dia.

### `calculate_combined_odd(games)`
Calcula a odd combinada multiplicando todas as odds.

### `calculate_potential_return(combined_odd, stake=10.0)`
Calcula o retorno potencial.

### `calculate_avg_confidence(games)`
Calcula a média de confiança dos jogos.

### `create_combined_bet(games, bet_date, example_stake=10.0, session=None)`
Cria uma aposta combinada no banco de dados.

### `update_combined_bet_result(combined_bet, session)`
Atualiza o resultado da aposta combinada após os jogos terminarem.

### `calculate_combined_bets_accuracy(session, days=30)`
Calcula a taxa de assertividade das apostas combinadas.

## 📈 Estatísticas

O sistema mantém estatísticas de assertividade das apostas combinadas:

- **Total de apostas**: Número total de apostas combinadas finalizadas
- **Apostas ganhas**: Número de apostas que acertaram todos os picks
- **Apostas perdidas**: Número de apostas que erraram pelo menos um pick
- **Taxa de assertividade**: Percentual de acertos

## ✅ Benefícios

1. **Automação completa**: Sistema cria e envia automaticamente
2. **Rastreamento**: Todas as apostas são salvas no banco de dados
3. **Análise**: Taxa de assertividade calculada automaticamente
4. **Transparência**: Retorno potencial calculado e exibido
5. **Flexibilidade**: Configurável via variáveis de ambiente

## 🔍 Exemplo de Uso

### Consultar Apostas Combinadas

```python
from models.database import SessionLocal, CombinedBet
from betting.combined_bets import calculate_combined_bets_accuracy

with SessionLocal() as session:
    # Busca apostas combinadas
    bets = session.query(CombinedBet).filter(
        CombinedBet.status.in_(["won", "lost"])
    ).all()
    
    # Calcula taxa de assertividade
    stats = calculate_combined_bets_accuracy(session, days=30)
    print(f"Taxa de assertividade: {stats['accuracy']:.2f}%")
    print(f"Total: {stats['total']} | Ganhas: {stats['won']} | Perdidas: {stats['lost']}")
```

## 📝 Notas Importantes

1. **Aposta combinada só é criada se houver pelo menos 1 jogo de alta confiança**
2. **A odd combinada é calculada multiplicando todas as odds**
3. **O retorno potencial é apenas um exemplo (R$ 10 padrão)**
4. **A aposta combinada só é finalizada quando TODOS os jogos terminam**
5. **A aposta é considerada ganha apenas se TODOS os picks acertarem**

---

**Implementado em:** 2025-11-04

**Arquivos relacionados:**
- `betting/combined_bets.py` - Lógica de apostas combinadas
- `models/database.py` - Modelo `CombinedBet`
- `utils/formatters.py` - Formatação de mensagem `fmt_combined_bet()`
- `scheduler/jobs.py` - Job `send_combined_bet_job()`

