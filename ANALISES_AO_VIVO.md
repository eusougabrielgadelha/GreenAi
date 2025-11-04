# 📊 Análises Possíveis em Jogos Ao Vivo

## 🔍 Dados Disponíveis na Página do Jogo

Baseado no HTML fornecido (`58053101`), os seguintes dados podem ser extraídos:

### ✅ Atualmente Extraídos

1. **Estatísticas Básicas**
   - Placar atual (home_goals, away_goals)
   - Tempo de jogo (match_time)
   - Último evento (gol, cartão, etc.)

2. **Mercados de Apostas**
   - Resultado Final (Casa/Empate/Fora)
   - Ambos os Times Marcam (BTTS)
   - Total de Gols
   - Placar Exato
   - Escanteios
   - Cartões

### 🚀 Potencialmente Extraíveis (HTML)

Com base na estrutura do HTML, podemos tentar extrair:

1. **Estatísticas do Jogo**
   - Chutes (total, no gol, fora)
   - Posse de bola (%)
   - Cartões amarelos/vermelhos (por time)
   - Escanteios (por time)
   - Faltas cometidas
   - Finalizações perigosas
   - Gols esperados (xG)

2. **Análise de Momentum**
   - Últimos eventos (sequência de gols, cartões)
   - Padrão de criação de chances
   - Pressão no campo

3. **Comparação Temporal**
   - Movimento de odds (comparar com odds iniciais)
   - Mudanças de mercado ao longo do jogo

---

## 🎯 Sistema de Validação em Duas Etapas

### ETAPA 1: Encontrar Oportunidade
**Função:** `decide_live_bet_opportunity()`

**Critérios:**
- Odd mínima (`LIVE_MIN_ODD`)
- Edge mínimo (`LIVE_MIN_EDGE`)
- Score agregado (`LIVE_MIN_SCORE`)
- Respeita cooldown

**Oportunidades Detectadas:**
1. **BTTS NÃO** - 0-0 após 75 minutos
2. **Resultado Final** - Time vencendo por 1 gol após 85 minutos

### ETAPA 2: Validar Confiabilidade
**Função:** `validate_opportunity_reliability()`

**Fatores de Validação:**

#### 1. 📈 Movimento de Odds (0-30% confiança)
- Compara odd atual com odd inicial
- Se odd diminuiu → mais confiável
- Se odd aumentou >20% → pode rejeitar

#### 2. ⏱️ Contexto do Placar e Tempo (0-40% confiança)
- **BTTS NÃO**: Mais confiável quanto mais tempo passar sem gols
- **Resultado Final**: Mais confiável nos minutos finais com vantagem

#### 3. 🔄 Estabilidade da Oportunidade (0-15% confiança)
- Se a oportunidade persiste há vários minutos → mais estável
- Nova oportunidade requer mais validação

#### 4. 💰 Edge e Probabilidade (0-30% confiança)
- Edge alto (≥5%) → mais confiável
- Probabilidade muito alta (≥90%) → mais confiável

#### 5. 📝 Eventos Recentes (0-10% ou -5% confiança)
- Gol recente pode confirmar tendência
- Cartão recente pode indicar mudança de dinâmica

#### 6. 📊 Disponibilidade do Mercado (0-5% confiança)
- Mercado completo e disponível → confiança adicional

**Score Final:**
- Soma todos os fatores (máximo 1.0)
- Requer `LIVE_MIN_CONFIDENCE_SCORE` (padrão: 0.70) para aprovar
- Rejeições críticas podem descartar mesmo com score alto

---

## ⚙️ Configurações Disponíveis

No arquivo `.env`, você pode configurar:

```env
# Validação de Confiabilidade
LIVE_MIN_CONFIDENCE_SCORE=0.70  # Score mínimo para validar (0.0 a 1.0)
LIVE_REQUIRE_ODD_MOVEMENT=false  # Requer movimento de odds para validar
LIVE_REQUIRE_STATISTICS=false     # Requer estatísticas adicionais para validar

# Detecção de Oportunidades (já existentes)
LIVE_MIN_ODD=1.20
LIVE_MIN_EDGE=0.02
LIVE_MIN_SCORE=0.60
LIVE_COOLDOWN_MIN=8
LIVE_SAME_PICK_COOLDOWN_MIN=20
```

---

## 📊 Tipos de Análises Implementadas

### 1. **Análise de Movimento de Odds**
- Compara odds atuais com odds iniciais
- Detecta se o mercado está valorizando corretamente a situação
- Identifica oportunidades criadas por ajustes de odds

### 2. **Análise de Contexto Temporal**
- Avalia se o tempo do jogo favorece a oportunidade
- Considera o placar atual e a probabilidade de mudança
- Valida se há tempo suficiente para a aposta se concretizar

### 3. **Análise de Estabilidade**
- Verifica se a oportunidade persiste ao longo do tempo
- Oportunidades estáveis são mais confiáveis
- Detecta oportunidades "fugazes" que podem ser falsos sinais

### 4. **Análise de Edge e Probabilidade**
- Valida se o edge é realmente significativo
- Confirma se a probabilidade estimada é realista
- Combina múltiplos indicadores de valor

### 5. **Análise de Eventos**
- Considera eventos recentes do jogo
- Avalia se eventos favorecem ou prejudicam a oportunidade
- Detecta mudanças de dinâmica que podem invalidar a aposta

---

## 🎯 Fluxo Completo

```
1. Monitoramento detecta jogo ao vivo
   ↓
2. Extrai dados da página (placar, tempo, odds, mercados)
   ↓
3. ETAPA 1: decide_live_bet_opportunity()
   - Encontra oportunidades baseadas em regras
   - Calcula edge, probabilidade, score
   ↓
4. Se encontrou oportunidade:
   ↓
5. ETAPA 2: validate_opportunity_reliability()
   - Valida movimento de odds
   - Valida contexto do jogo
   - Valida estabilidade
   - Calcula score de confiança
   ↓
6. Se score >= MIN_CONFIDENCE_SCORE:
   ↓
7. Envia sinal validado via Telegram
   - Inclui score de confiança
   - Inclui fatores de validação
   ↓
8. Registra em analytics_events
```

---

## 🔮 Análises Futuras Possíveis

### 1. **Estatísticas Avançadas do Jogo**
- Chutes por time (total, no gol, fora)
- Posse de bola
- Finalizações perigosas
- xG (Expected Goals)

### 2. **Análise de Momentum**
- Sequência de eventos recentes
- Padrão de criação de chances
- Pressão no campo

### 3. **Análise de Histórico**
- Confrontos diretos anteriores
- Forma recente dos times
- Estatísticas em casa/fora

### 4. **Análise de Mercado**
- Comparação de odds entre casas
- Volume de apostas
- Mudanças súbitas de odds

### 5. **Análise de Contexto do Campeonato**
- Importância do jogo (rebaixamento, título, etc.)
- Motivação dos times
- Jogadores importantes em campo

---

## 📝 Exemplo de Validação

**Cenário:** BTTS NÃO aos 80 minutos, placar 0-0

**ETAPA 1 - Oportunidade Encontrada:**
- Odd: 1.45
- Probabilidade estimada: 0.92
- Edge: 0.33
- Score: 0.75 ✅

**ETAPA 2 - Validação:**
- Movimento de odds: +0.25 (odd diminuiu de 1.60 → 1.45)
- Contexto: +0.35 (80 minutos, 0-0)
- Estabilidade: +0.10 (oportunidade detectada há 5 minutos)
- Edge: +0.20 (edge alto)
- Eventos: +0.05 (sem eventos recentes)
- **Score Total: 0.95** ✅

**Resultado:** Oportunidade VALIDADA e sinal enviado com 95% de confiança.

