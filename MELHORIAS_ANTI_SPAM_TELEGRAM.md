# 🚀 Melhorias Anti-Spam para Telegram

## 📋 Resumo

Implementadas melhorias abrangentes para reduzir spam no Telegram e melhorar a experiência do usuário.

---

## ✅ Melhorias Implementadas

### 1. **Sistema de Rate Limiting Global** 🎯

**Arquivo:** `utils/telegram_rate_limiter.py`

**Funcionalidades:**
- ✅ Limite de mensagens por minuto (padrão: 5 mensagens/min)
- ✅ Limite de mensagens por hora (padrão: 30 mensagens/hora)
- ✅ Intervalo mínimo entre mensagens (padrão: 10 segundos)
- ✅ Cooldown específico por tipo de mensagem:
  - `live_opportunity`: 8 minutos
  - `reminder`: 5 minutos
  - `watch_upgrade`: 3 minutos
  - `pick_now`: 2 minutos
  - `summary`: 30 minutos
  - `results_batch`: 5 minutos

**Como funciona:**
- Verifica limites antes de enviar cada mensagem
- Suprime mensagens que excederem os limites
- Registra estatísticas para monitoramento
- Persiste cooldowns no banco de dados (sobrevive a reinícios)

**Configuração (`.env`):**
```env
TELEGRAM_MAX_PER_MINUTE=5   # Máximo de mensagens por minuto
TELEGRAM_MAX_PER_HOUR=30    # Máximo de mensagens por hora
TELEGRAM_MIN_INTERVAL=10    # Intervalo mínimo entre mensagens (segundos)
```

---

### 2. **Integração com Sistema de Envio** 🔗

**Arquivo:** `notifications/telegram.py`

**Mudanças:**
- ✅ `tg_send_message()` agora verifica rate limiting antes de enviar
- ✅ Mensagens bloqueadas são registradas em analytics
- ✅ Parâmetro `skip_rate_limit` para mensagens críticas (opcional)

**Exemplo de uso:**
```python
# Mensagem normal (com rate limiting)
tg_send_message("Mensagem normal", message_type="pick_now")

# Mensagem crítica (sem rate limiting)
tg_send_message("ALERTA CRÍTICO!", message_type="alert", skip_rate_limit=True)
```

---

### 3. **Desativação de Mensagens "Busca Continua"** 🔇

**Arquivo:** `scheduler/jobs.py` (função `_handle_active_game`)

**Mudança:**
- ✅ Mensagem "🔄 BUSCA CONTINUADA" desativada
- ✅ Sistema só envia mensagens quando encontra oportunidades reais
- ✅ Reduz spam de atualizações desnecessárias

**Antes:**
- Enviava mensagem a cada hora quando não encontrava oportunidades
- Podia gerar muitas mensagens de "status"

**Depois:**
- Só envia quando encontra oportunidade válida
- Reduz significativamente o número de mensagens

---

### 4. **Sistema de Consolidação de Lembretes** 📦

**Arquivo:** `utils/reminder_consolidator.py`

**Funcionalidade:**
- ✅ Agrupa lembretes próximos no tempo (janela de 5 minutos)
- ✅ Envia mensagem consolidada quando há múltiplos jogos
- ✅ Mantém mensagem individual quando há apenas 1 jogo

**Exemplo:**
```
🔔 LEMBRETES (14:00)
━━━━━━━━━━━━━━━━━━━━━━

1. Napoli vs Eint. Frankfurt
   🕐 14:00h | Pick: Empate @ 23%

2. Real Madrid vs Sevilla
   🕐 14:03h | Pick: Real Madrid @ 62%

3. Corinthians vs Santos
   🕐 14:05h | Pick: Corinthians @ 54%
```

**Benefício:**
- Em vez de 3 mensagens separadas, envia 1 mensagem consolidada
- Melhora legibilidade e reduz spam

---

## 📊 Impacto Esperado

### Antes das Melhorias
```
❌ Múltiplas mensagens de "Busca Continua" por hora
❌ Lembretes individuais espalhados (spam)
❌ Sem controle de rate limiting
❌ Possível bloqueio do Telegram por excesso de mensagens
❌ Experiência do usuário comprometida
```

### Depois das Melhorias
```
✅ Rate limiting global (máx 5/min, 30/hora)
✅ Cooldown por tipo de mensagem
✅ Mensagens "Busca Continua" desativadas
✅ Lembretes consolidados quando próximos
✅ Experiência do usuário melhorada
✅ Menos risco de bloqueio do Telegram
```

---

## 🔧 Configuração

### Variáveis de Ambiente

Adicione ao seu `.env`:

```env
# Rate Limiting (opcional - padrões já configurados)
TELEGRAM_MAX_PER_MINUTE=5   # Máximo de mensagens por minuto
TELEGRAM_MAX_PER_HOUR=30    # Máximo de mensagens por hora
TELEGRAM_MIN_INTERVAL=10    # Intervalo mínimo entre mensagens (segundos)
```

### Ajuste de Limites

Se quiser limites mais restritivos:
```env
TELEGRAM_MAX_PER_MINUTE=3   # Apenas 3 mensagens por minuto
TELEGRAM_MAX_PER_HOUR=20    # Apenas 20 mensagens por hora
TELEGRAM_MIN_INTERVAL=15    # 15 segundos entre mensagens
```

Se quiser limites mais permissivos:
```env
TELEGRAM_MAX_PER_MINUTE=10  # Até 10 mensagens por minuto
TELEGRAM_MAX_PER_HOUR=50    # Até 50 mensagens por hora
TELEGRAM_MIN_INTERVAL=5     # 5 segundos entre mensagens
```

---

## 📈 Monitoramento

### Estatísticas do Rate Limiter

Você pode verificar estatísticas do rate limiter:

```python
from utils.telegram_rate_limiter import get_rate_limit_stats

stats = get_rate_limit_stats()
print(stats)
# {
#     'total_messages': 150,
#     'messages_last_minute': 2,
#     'messages_last_hour': 18,
#     'max_per_minute': 5,
#     'max_per_hour': 30,
#     'min_interval_seconds': 10,
#     'active_cooldowns': {
#         'live_opportunity': 3.5,  # 3.5 minutos restantes
#         'reminder': 1.2            # 1.2 minutos restantes
#     }
# }
```

### Logs

Mensagens suprimidas são registradas em logs:
```
⏸️ Mensagem suprimida (rate limit): pick_now - Aguarde 5.2s (intervalo mínimo entre mensagens)
```

---

## 🎯 Próximas Melhorias (Opcional)

### 1. Fila de Prioridade
- Implementar fila de mensagens com prioridades
- Mensagens importantes (resultados, alertas) têm prioridade
- Mensagens de status são postergadas quando há muitas pendentes

### 2. Consolidação de Resultados em Tempo Real
- Já existe consolidação em batch, mas pode ser melhorada
- Agrupar resultados por janela de tempo menor

### 3. Preferências do Usuário
- Permitir que usuário escolha quais tipos de mensagens quer receber
- Configurar limites por tipo de mensagem

---

## ✅ Checklist de Implementação

- [x] Sistema de rate limiting global
- [x] Integração com `tg_send_message`
- [x] Desativação de "Busca Continua"
- [x] Sistema de consolidação de lembretes
- [x] Cooldown por tipo de mensagem
- [x] Configuração via variáveis de ambiente
- [x] Persistência de cooldowns no banco
- [x] Logging e estatísticas
- [x] Documentação

---

## 🚀 Como Usar

1. **Configure variáveis de ambiente** (opcional, padrões já estão bons)
2. **Reinicie o sistema** para aplicar mudanças
3. **Monitore logs** para ver mensagens suprimidas
4. **Ajuste limites** se necessário baseado no uso

---

## 📝 Notas Técnicas

- Rate limiter usa `deque` para eficiência (O(1) para inserção/remoção)
- Cooldowns são persistidos no banco via `Stat` model
- Sistema de consolidação de lembretes pode ser expandido para outros tipos
- Rate limiting é aplicado automaticamente a todas as mensagens (exceto com `skip_rate_limit=True`)

---

**Data de Implementação:** 2025-01-11  
**Status:** ✅ Implementado e Testado

