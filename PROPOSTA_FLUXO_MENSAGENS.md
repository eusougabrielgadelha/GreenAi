# 🎯 Proposta: Fluxo Inteligente de Mensagens

## 📋 Visão Geral

Melhorar a experiência do usuário com mensagens mais organizadas e inteligentes, evitando spam de mensagens vazias.

## 🕐 Fluxo Proposto

### **Dia Anterior (22h) - Coleta de Dados**
```
22:00 → Scraping de TODOS os jogos de AMANHÃ (00h-23h)
      → Salva no banco (status: "scheduled")
      → NÃO envia mensagem ainda
```

### **Dia Seguinte - Envio Inteligente**

#### **1. Madrugada (00h ou 06h) - "Jogos da Madrugada"**
```
00:00 ou 06:00 → Verifica jogos salvos de 00h-06h
               → Se houver jogos selecionáveis (will_bet=True)
               → Envia: "🌙 JOGOS DA MADRUGADA"
               → Se NÃO houver → NÃO envia nada
```

#### **2. Manhã (06h) - "Jogos de Hoje"**
```
06:00 → Verifica jogos salvos de 06h-23h
      → Sempre envia (mesmo que vazio)
      → Envia: "🌅 JOGOS DE HOJE"
```

## 🏗️ Arquitetura Proposta

### 1. **Separar Coleta de Dados e Envio**

```
scanner/
├── __init__.py
└── game_scanner.py
    ├── scan_games_for_date()      # Coleta jogos (sem enviar)
    ├── send_dawn_games()          # Envia "Jogos da Madrugada" (só se houver)
    └── send_today_games()         # Envia "Jogos de Hoje" (sempre)
```

### 2. **Jobs Agendados**

```python
# scheduler/jobs.py

# 1. Coleta (dia anterior às 22h)
async def collect_tomorrow_games_job():
    """Coleta jogos de amanhã e salva no banco."""
    await scan_games_for_date(date_offset=1, send_summary=False)

# 2. Envio Madrugada (00h ou 06h)
async def send_dawn_games_job():
    """Envia jogos da madrugada (00h-06h) - só se houver."""
    sent = await send_dawn_games()
    if sent:
        logger.info("✅ Mensagem 'Jogos da Madrugada' enviada")
    else:
        logger.info("⏭️  Nenhum jogo da madrugada, mensagem não enviada")

# 3. Envio Manhã (06h)
async def send_today_games_job():
    """Envia jogos de hoje (06h-23h)."""
    await send_today_games()
```

## 📊 Estrutura das Mensagens

### Mensagem 1: "Jogos da Madrugada"
```
🌙 <b>JOGOS DA MADRUGADA</b>
<i>04 de Novembro de 2025</i>
━━━━━━━━━━━━━━━━━━━━

🎯 <b>PICKS DA MADRUGADA</b>

⚽ <b>Flamengo</b> vs <b>Palmeiras</b>
   🕐 02:30h | Pick: <b>Casa</b>
   📊 Prob: 65% | EV: +8.5%

⚽ <b>Corinthians</b> vs <b>São Paulo</b>
   🕐 04:00h | Pick: <b>Empate</b>
   📊 Prob: 52% | EV: +5.2%
```

### Mensagem 2: "Jogos de Hoje"
```
🌅 <b>JOGOS DE HOJE</b>
<i>04 de Novembro de 2025</i>
━━━━━━━━━━━━━━━━━━━━

📊 <b>RESUMO</b>
├ Total analisado: <b>45</b> jogos
└ Selecionados: <b>8</b> jogos

🎯 <b>PICKS DO DIA</b>

⚽ <b>Atletico-MG</b> vs <b>Internacional</b>
   🕐 16:00h | Pick: <b>Casa</b>
   📊 Prob: 68% | EV: +10.2%

⚽ <b>Grêmio</b> vs <b>Santos</b>
   🕐 18:00h | Pick: <b>Fora</b>
   📊 Prob: 55% | EV: +6.8%

[... mais jogos ...]
```

## 🔄 Fluxo Completo

### Exemplo Prático: Quinta-feira → Sexta-feira

```
Quinta-feira 22:00
├─ Job: collect_tomorrow_games_job()
├─ Faz scraping de sexta-feira (00h-23h)
├─ Analisa e salva todos os jogos no banco
└─ NÃO envia mensagem

Sexta-feira 00:00 (ou 06:00)
├─ Job: send_dawn_games_job()
├─ Busca jogos salvos de 00h-06h
├─ Se houver jogos com will_bet=True:
│  └─ Envia: "🌙 JOGOS DA MADRUGADA"
└─ Se NÃO houver:
   └─ NÃO envia nada (evita spam)

Sexta-feira 06:00
├─ Job: send_today_games_job()
├─ Busca jogos salvos de 06h-23h
└─ Envia: "🌅 JOGOS DE HOJE"
   (mesmo que vazio, informa que não há jogos)
```

## ✅ Vantagens

### 1. **Evita Spam**
- Não envia mensagem vazia de madrugada
- Usuário só recebe quando há algo relevante

### 2. **Organização Clara**
- Madrugada separada do resto do dia
- Facilita leitura e decisão rápida

### 3. **Antecedência**
- Jogos já coletados no dia anterior
- Envio rápido no dia seguinte (sem esperar scraping)

### 4. **Flexibilidade**
- Pode enviar madrugada às 00h ou 06h (configurável)
- Separação clara de responsabilidades

### 5. **Experiência do Usuário**
- Mensagens mais relevantes
- Menos poluição no chat
- Informação no momento certo

## 📝 Implementação

### Passo 1: Criar `scanner/game_scanner.py`

```python
async def scan_games_for_date(
    date_offset: int = 0,
    send_summary: bool = False  # NOVO: controla se envia
) -> Dict[str, Any]:
    """Coleta jogos de uma data e salva no banco."""
    # ... lógica de scraping e análise ...
    # Se send_summary=False, só salva, não envia
    return {"analyzed": X, "selected": Y}

async def send_dawn_games() -> bool:
    """Envia jogos da madrugada (00h-06h) - retorna True se enviou."""
    today = datetime.now(ZONE).date()
    start = ZONE.localize(datetime(today.year, today.month, today.day, 0, 0))
    end = ZONE.localize(datetime(today.year, today.month, today.day, 6, 0))
    
    games = session.query(Game).filter(
        Game.start_time >= start,
        Game.start_time < end,
        Game.will_bet.is_(True)
    ).all()
    
    if not games:
        return False  # Não enviou
    
    msg = fmt_dawn_games_summary(games)
    tg_send_message(msg)
    return True  # Enviou

async def send_today_games():
    """Envia jogos de hoje (06h-23h)."""
    # Similar, mas sempre envia (mesmo que vazio)
```

### Passo 2: Atualizar `scheduler/jobs.py`

```python
# Coleta (22h do dia anterior)
scheduler.add_job(
    collect_tomorrow_games_job,
    trigger=CronTrigger(hour=22, minute=0),
    id="collect_tomorrow"
)

# Envio Madrugada (00h ou 06h)
dawn_hour = int(os.getenv("DAWN_GAMES_HOUR", "6"))
scheduler.add_job(
    send_dawn_games_job,
    trigger=CronTrigger(hour=dawn_hour, minute=0),
    id="send_dawn"
)

# Envio Manhã (06h)
scheduler.add_job(
    send_today_games_job,
    trigger=CronTrigger(hour=6, minute=0),
    id="send_today"
)
```

### Passo 3: Criar Formatters

```python
# utils/formatters.py

def fmt_dawn_games_summary(games: List[Game]) -> str:
    """Formata mensagem de jogos da madrugada."""
    # ... implementação ...

def fmt_today_games_summary(games: List[Game], analyzed: int) -> str:
    """Formata mensagem de jogos de hoje."""
    # ... implementação similar ao fmt_morning_summary ...
```

## 🎯 Resultado Final

- ✅ **Coleta**: 22h do dia anterior (silenciosa)
- ✅ **Madrugada**: 00h ou 06h (só envia se houver)
- ✅ **Hoje**: 06h (sempre envia)
- ✅ **Zero spam**: Mensagens vazias não são enviadas
- ✅ **Organizado**: Separação clara madrugada/resto do dia

## 📊 Comparação: Antes vs Depois

### Antes
```
22:00 → Scraping + Envio imediato (pode ser vazio)
06:00 → Scraping + Envio (pode ser vazio)
       ❌ Mensagens vazias
       ❌ Duplicação de scraping
```

### Depois
```
22:00 → Scraping (silencioso, só salva)
00:00 → Envio madrugada (só se houver)
06:00 → Envio hoje (sempre)
       ✅ Sem mensagens vazias
       ✅ Scraping único
       ✅ Organizado
```



