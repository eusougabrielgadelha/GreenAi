# 📊 Assertividade por Nível de Confiança

## 📋 Resumo

Implementada funcionalidade para calcular e exibir assertividade segmentada por nível de confiança (Alta, Média, Baixa).

---

## ✅ Funcionalidades Implementadas

### 1. **Nova Função: `get_accuracy_by_confidence()`**

**Arquivo:** `utils/stats.py`

**Segmentação:**
- 🔥 **Alta Confiança**: `pick_prob >= 0.60` (60% ou mais)
- ⭐ **Média Confiança**: `0.40 <= pick_prob < 0.60` (40% a 59%)
- 💡 **Baixa Confiança**: `pick_prob < 0.40` (menos de 40%)

**Retorna:**
```python
{
    'high': {
        'total': 45,
        'hits': 32,
        'misses': 13,
        'accuracy': 0.711,
        'accuracy_percent': 71.1
    },
    'medium': {
        'total': 28,
        'hits': 15,
        'misses': 13,
        'accuracy': 0.536,
        'accuracy_percent': 53.6
    },
    'low': {
        'total': 12,
        'hits': 4,
        'misses': 8,
        'accuracy': 0.333,
        'accuracy_percent': 33.3
    }
}
```

---

### 2. **Integração em Resumos Diários**

**Arquivo:** `utils/formatters.py` - função `fmt_daily_summary()`

**Exemplo de mensagem:**

```
📊 RESUMO DO DIA
Segunda, 05/11/2025
━━━━━━━━━━━━━━━━━━━━

📈 ESTATÍSTICAS DO DIA
├ Total de jogos: 8
├ Verificados: 8
├ ✅ Acertos: 5
├ ❌ Erros: 3
└ Assertividade: 62.5%

⚽ JOGOS DO DIA
[... lista de jogos ...]

━━━━━━━━━━━━━━━━━━━━
📊 ASSERTIVIDADE LIFETIME
├ Total histórico: 150 jogos
├ ✅ Acertos: 95
├ ❌ Erros: 55
├ Assertividade: 63.3%
├ Odd média: 2.15
└ ROI estimado: +35.2%

📊 ASSERTIVIDADE POR CONFIANÇA
├ 🔥 Alta (≥60%): 71.1% (32/45)
├ ⭐ Média (40-60%): 53.6% (15/28)
└ 💡 Baixa (<40%): 33.3% (4/12)

💪 Excelente dia! Continue assim!
```

---

### 3. **Integração em Estatísticas Lifetime**

**Arquivo:** `utils/formatters.py` - função `fmt_lifetime_stats()`

**Exemplo de mensagem:**

```
📊 ESTATÍSTICAS LIFETIME
Histórico Completo
━━━━━━━━━━━━━━━━━━━━

📈 PERFORMANCE GERAL
├ Total de jogos: 150
├ ✅ Acertos: 95
├ ❌ Erros: 55
├ Assertividade: 63.3%
├ Odd média (acertos): 2.15
└ ROI estimado: +35.2%

📊 ASSERTIVIDADE POR CONFIANÇA
├ 🔥 Alta (≥60%): 71.1% (32/45)
├ ⭐ Média (40-60%): 53.6% (15/28)
└ 💡 Baixa (<40%): 33.3% (4/12)

💚 ROI positivo! A estratégia está funcionando!
```

---

### 4. **Integração no Terminal**

**Arquivo:** `read_db.py` - função `show_accuracy_stats()`

**Exemplo de saída:**

```
ESTATISTICAS DE ACERTO
   Taxa geral: 63.33% (95/150)

   Por nível de confiança:
   • 🔥 Alta (≥60%): 71.11% (32/45)
   • ⭐ Média (40-60%): 53.57% (15/28)
   • 💡 Baixa (<40%): 33.33% (4/12)

   Por tipo de pick:
   • draw: 45.00% (9/20)
   • home: 68.75% (55/80)
   • away: 62.00% (31/50)
```

---

## 🎯 Casos de Uso

### 1. **Análise de Performance**
Identificar em qual nível de confiança o sistema performa melhor:
- Se alta confiança tem assertividade > 70% → focar em alta confiança
- Se média confiança tem assertividade > 60% → pode ser interessante
- Se baixa confiança tem assertividade < 40% → evitar

### 2. **Ajuste de Estratégia**
- Se alta confiança está performando bem → aumentar `HIGH_CONF_THRESHOLD`
- Se média confiança está performando mal → aumentar critérios mínimos
- Se baixa confiança está performando bem → considerar estratégias diferentes

### 3. **Validação de Modelo**
- Verificar se a confiança calculada corresponde à assertividade real
- Alta confiança deve ter assertividade proporcionalmente maior
- Identificar overconfidence ou underconfidence

---

## 📊 Interpretação dos Resultados

### Cenário Ideal
```
🔥 Alta (≥60%): 75%+ assertividade
⭐ Média (40-60%): 55-65% assertividade
💡 Baixa (<40%): 40-50% assertividade
```
**Interpretação:** Sistema está bem calibrado, confiança corresponde à realidade.

### Cenário de Overconfidence
```
🔥 Alta (≥60%): 50% assertividade
⭐ Média (40-60%): 40% assertividade
💡 Baixa (<40%): 30% assertividade
```
**Interpretação:** Sistema superestima confiança, ajustar cálculo de probabilidade.

### Cenário de Underconfidence
```
🔥 Alta (≥60%): 90% assertividade
⭐ Média (40-60%): 70% assertividade
💡 Baixa (<40%): 60% assertividade
```
**Interpretação:** Sistema subestima confiança, pode ser mais agressivo.

---

## 🔧 Como Usar

### Via Telegram (Resumo Diário)
- Estatísticas aparecem automaticamente no resumo diário
- Incluídas em `fmt_daily_summary()` e `fmt_lifetime_stats()`

### Via Terminal
```bash
python read_db.py accuracy
```

### Via Código Python
```python
from models.database import SessionLocal
from utils.stats import get_accuracy_by_confidence

with SessionLocal() as session:
    stats = get_accuracy_by_confidence(session)
    
    print(f"Alta confiança: {stats['high']['accuracy_percent']:.1f}%")
    print(f"Média confiança: {stats['medium']['accuracy_percent']:.1f}%")
    print(f"Baixa confiança: {stats['low']['accuracy_percent']:.1f}%")
```

---

## 📈 Impacto Esperado

### Antes
- Apenas assertividade geral
- Não sabia se alta confiança realmente performava melhor
- Difícil validar se o modelo está bem calibrado

### Depois
- Assertividade segmentada por confiança
- Identifica qual nível performa melhor
- Valida se confiança corresponde à realidade
- Permite ajustes estratégicos baseados em dados

---

**Data de Implementação:** 2025-01-11  
**Status:** ✅ Implementado e Testado

