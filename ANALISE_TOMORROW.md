# 📊 Análise do Arquivo `tomorrow.py`

## 🎯 Propósito Principal

O arquivo `tomorrow.py` é uma **versão complementar** do sistema principal que analisa jogos de **AMANHÃ** ao invés de hoje.

## 🔍 Diferença Principal

### `main.py` (Sistema Principal)
- **Analisa**: Jogos de **HOJE** (dia atual)
- **Linha 58**: `analysis_date_local = datetime.now(ZONE).date()`
- **Função**: Varredura matinal dos jogos que acontecem no mesmo dia

### `tomorrow.py` (Sistema Complementar)
- **Analisa**: Jogos de **AMANHÃ** (próximo dia)
- **Linha 1672**: `analysis_date_local = (datetime.now(ZONE).date() + timedelta(days=1))`
- **Linha 1673**: `logger.info("📅 Dia analisado (timezone %s): %s (AMANHÃ)", ZONE, analysis_date_local.isoformat())`
- **Função**: Preparação antecipada dos jogos que acontecerão no dia seguinte

## 📋 Estrutura e Funcionalidades

### Componentes Principais

O `tomorrow.py` contém **TODAS** as mesmas funcionalidades do `main.py`, mas com a diferença temporal:

1. **Modelos de Banco de Dados**
   - `Game`, `Stat`, `LiveGameTracker`, `OddHistory`
   - Mesmos modelos do sistema principal

2. **Scraping**
   - `fetch_events_from_link()` - Busca eventos
   - `try_parse_events()` - Parseia HTML
   - `scrape_game_result()` - Busca resultados
   - `scrape_live_game_data()` - Dados ao vivo

3. **Lógica de Apostas**
   - `decide_bet()` - Decisão pré-jogo
   - `decide_live_bet_opportunity()` - Oportunidades ao vivo
   - `kelly_fraction()` - Critério de Kelly
   - `suggest_stake_and_return()` - Tamanho da aposta

4. **Jobs Agendados**
   - `morning_scan_and_publish()` - **Varredura matinal (AMANHÃ)**
   - `night_scan_for_early_games()` - Varredura noturna (jogos madrugada de amanhã)
   - `rescan_watchlist_job()` - Reescaneamento da watchlist
   - `hourly_rescan_job()` - Reavaliação horária
   - `monitor_live_games_job()` - Monitoramento ao vivo
   - `send_reminder_job()` - Envio de lembretes
   - `watch_game_until_end_job()` - Monitoramento até fim do jogo
   - `maybe_send_daily_wrapup()` - Resumo diário

5. **Formatação e Notificações**
   - `fmt_morning_summary()` - Resumo matinal
   - `fmt_result()` - Resultado do jogo
   - `fmt_pick_now()` - Palpite atual
   - `fmt_reminder()` - Lembrete
   - `fmt_watch_add()` - Adição à watchlist
   - `fmt_watch_upgrade()` - Atualização da watchlist
   - `fmt_live_bet_opportunity()` - Oportunidade ao vivo
   - `tg_send_message()` - Envio via Telegram

6. **Estatísticas**
   - `global_accuracy()` - Assertividade global
   - `get_weekly_stats()` - Estatísticas semanais
   - `get_monthly_stats()` - Estatísticas mensais

## 🔄 Casos de Uso

### Cenário 1: Preparação Antecipada
```
Hoje: 03/11/2025 (Quinta-feira)
main.py: Analisa jogos de 03/11/2025
tomorrow.py: Analisa jogos de 04/11/2025 (Sexta-feira)
```

### Cenário 2: Varredura Noturna
O `tomorrow.py` tem uma função especial `night_scan_for_early_games()` que:
- Procura jogos que começam na madrugada de amanhã (00:00 às 06:00)
- Prepara análise antecipada para jogos que começam muito cedo

**Linha 1889-1898**:
```python
tomorrow = datetime.now(ZONE).date() + timedelta(days=1)
start_window = ZONE.localize(datetime(tomorrow.year, tomorrow.month, tomorrow.day, 0, 0)).astimezone(pytz.UTC)
end_window   = ZONE.localize(datetime(tomorrow.year, tomorrow.month, tomorrow.day, 6, 0)).astimezone(pytz.UTC)
```

## 📊 Comparação Técnica

| Aspecto | `main.py` | `tomorrow.py` |
|---------|-----------|--------------|
| **Data de análise** | Hoje | Amanhã |
| **Linha de definição** | 58 | 1672 |
| **Tamanho** | 18.709 bytes | 113.008 bytes |
| **Estrutura** | Modular | Monolítico |
| **Status** | ✅ Ativo e modularizado | ⚠️ Pendente modularização |
| **Uso** | Produção diária | Preparação antecipada |

## 🎯 Vantagens do `tomorrow.py`

1. **Preparação Antecipada**: Analisa jogos com antecedência
2. **Jogos Madrugada**: Detecta jogos que começam muito cedo (00:00-06:00)
3. **Planejamento**: Permite planejar apostas do dia seguinte
4. **Flexibilidade**: Pode rodar em paralelo com `main.py`

## ⚠️ Problemas Atuais

1. **Código Duplicado**: 
   - Mesmo código do `main.py` (antes da modularização)
   - 113 KB de código monolítico
   - Não usa os módulos criados

2. **Manutenção Duplicada**: 
   - Qualquer correção precisa ser feita em dois lugares
   - Risco de inconsistências

3. **Não Modularizado**: 
   - Não aproveita a estrutura modular criada
   - Não compartilha código com `main.py`

## 💡 Recomendações

### Opção 1: Modularizar (Recomendado)
- Refatorar `tomorrow.py` para usar os módulos existentes
- Criar um parâmetro `analysis_date_offset` nos módulos
- Permitir que `main.py` e `tomorrow.py` compartilhem o mesmo código

### Opção 2: Integrar em `main.py`
- Adicionar flag `--tomorrow` ou variável de ambiente `ANALYSIS_DATE_OFFSET=1`
- Um único script que pode analisar hoje ou amanhã

### Opção 3: Manter Separado (Atual)
- Manter como está, mas modularizar para facilitar manutenção
- Reduzir duplicação de código

## 🔧 Exemplo de Modularização

```python
# Em scheduler/jobs.py
async def morning_scan_and_publish(date_offset: int = 0):
    """Varredura matinal.
    
    Args:
        date_offset: 0 = hoje, 1 = amanhã
    """
    analysis_date_local = datetime.now(ZONE).date() + timedelta(days=date_offset)
    # ... resto do código
```

```python
# Em main.py
async def main():
    await morning_scan_and_publish(date_offset=0)  # Hoje

# Em tomorrow.py (modularizado)
async def main():
    await morning_scan_and_publish(date_offset=1)  # Amanhã
```

## 📝 Conclusão

O `tomorrow.py` é um **script funcional e útil** que complementa o `main.py`, mas:
- ✅ **Funcionalidade**: É útil e tem propósito claro
- ⚠️ **Código**: Precisa ser modularizado para facilitar manutenção
- 🔄 **Recomendação**: Modularizar e integrar com a estrutura existente

**Status**: ⚠️ **Manter, mas modularizar**



