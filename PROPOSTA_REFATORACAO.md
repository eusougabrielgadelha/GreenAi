# 🎯 Proposta de Refatoração - Análise de Jogos de Amanhã

## 📋 Situação Atual

### Problemas Identificados
1. **Duplicação de Código**: `tomorrow.py` tem 113 KB duplicando funcionalidades do `main.py`
2. **Manutenção Dupla**: Qualquer correção precisa ser feita em dois lugares
3. **Responsabilidades Mistas**: `tomorrow.py` contém TUDO (scraping, cálculo, monitoramento, etc.)
4. **Nome Inadequado**: "tomorrow.py" não é descritivo

## 💡 Proposta: Modularização Completa

### Arquitetura Proposta

```
scanner/
├── __init__.py
└── game_scanner.py    # Função genérica de scan (data como parâmetro)

main.py                 # Roda scan de HOJE (00h-23h)
scan_tomorrow.py        # Roda scan de AMANHÃ (00h-23h) - MUITO SIMPLES
```

### Responsabilidades Separadas

| Componente | Responsabilidade | Localização |
|------------|------------------|-------------|
| **Buscar/Scraping** | Buscar eventos dos sites | `scraping/` ✅ |
| **Análise/Cálculo** | Decisão de apostas, EV, probabilidades | `betting/` ✅ |
| **Monitoramento** | Acompanhar jogos ao vivo | `live/` + `scheduler/jobs.py` ✅ |
| **Agendamento** | Jobs agendados | `scheduler/jobs.py` ✅ |
| **Scan de Hoje** | Analisar jogos de HOJE | `main.py` (chama scanner) |
| **Scan de Amanhã** | Analisar jogos de AMANHÃ | `scan_tomorrow.py` (chama scanner) |

## 🏗️ Estrutura Detalhada

### 1. Criar `scanner/game_scanner.py`

```python
"""Scanner genérico de jogos para qualquer data."""
async def scan_games_for_date(
    date_offset: int = 0,  # 0 = hoje, 1 = amanhã
    send_summary: bool = True
) -> Dict[str, Any]:
    """
    Analisa jogos de uma data específica.
    
    Args:
        date_offset: 0 = hoje, 1 = amanhã, -1 = ontem, etc.
        send_summary: Se deve enviar resumo via Telegram
    
    Returns:
        Dict com estatísticas da análise
    """
    analysis_date_local = datetime.now(ZONE).date() + timedelta(days=date_offset)
    
    # TODO: Mover lógica de morning_scan_and_publish() para cá
    # (usar os módulos existentes: scraping, betting, etc.)
```

### 2. Refatorar `main.py`

```python
# main.py
from scanner.game_scanner import scan_games_for_date

async def morning_scan_and_publish():
    """Varredura matinal - jogos de HOJE."""
    return await scan_games_for_date(date_offset=0, send_summary=True)
```

### 3. Criar `scan_tomorrow.py` (MUITO SIMPLES)

```python
"""Scanner de jogos de AMANHÃ."""
import asyncio
from scanner.game_scanner import scan_games_for_date
from utils.logger import logger

async def main():
    """Analisa jogos de amanhã (00h-23h)."""
    logger.info("📅 Iniciando análise de jogos de AMANHÃ...")
    result = await scan_games_for_date(date_offset=1, send_summary=True)
    logger.info(f"✅ Análise concluída: {result['analyzed']} jogos analisados, {result['selected']} selecionados")

if __name__ == "__main__":
    asyncio.run(main())
```

### 4. Atualizar `scheduler/jobs.py`

```python
# Job para scan de amanhã (opcional, rodar às 22h por exemplo)
async def scan_tomorrow_job():
    """Job que analisa jogos de amanhã."""
    from scanner.game_scanner import scan_games_for_date
    await scan_games_for_date(date_offset=1, send_summary=True)

# No setup_scheduler():
if os.getenv("ENABLE_TOMORROW_SCAN", "false").lower() == "true":
    tomorrow_hour = int(os.getenv("TOMORROW_SCAN_HOUR", "22"))
    scheduler.add_job(
        scan_tomorrow_job,
        trigger=CronTrigger(hour=tomorrow_hour, minute=0),
        id="tomorrow_scan",
        replace_existing=True,
    )
```

## ✅ Vantagens da Proposta

### 1. **Zero Duplicação**
- Uma única função `scan_games_for_date()` com parâmetro `date_offset`
- Todo código compartilhado via módulos existentes

### 2. **Responsabilidades Claras**
- `scanner/` → Apenas busca e análise de jogos
- `betting/` → Apenas cálculos e decisões
- `live/` → Apenas monitoramento ao vivo
- `scheduler/` → Apenas agendamento

### 3. **Flexibilidade**
- Pode rodar scan de hoje ou amanhã via parâmetro
- Pode criar scans para outros dias facilmente
- Pode rodar manualmente (`python scan_tomorrow.py`) ou via scheduler

### 4. **Manutenção Simples**
- Uma correção no `scanner/game_scanner.py` afeta ambos
- Testes mais fáceis (testar função genérica)

### 5. **Nomes Descritivos**
- `scan_tomorrow.py` → Claro que é scan de amanhã
- `scanner/game_scanner.py` → Claro que é scanner genérico

## 🔄 Fluxo de Execução

### Cenário 1: Scan de Hoje (Automático)
```
06:00 → scheduler chama morning_scan_and_publish()
      → chama scan_games_for_date(date_offset=0)
      → analisa jogos de HOJE (00h-23h)
      → envia resumo
```

### Cenário 2: Scan de Amanhã (Automático)
```
22:00 → scheduler chama scan_tomorrow_job()
      → chama scan_games_for_date(date_offset=1)
      → analisa jogos de AMANHÃ (00h-23h)
      → envia resumo
```

### Cenário 3: Scan Manual de Amanhã
```bash
python scan_tomorrow.py
```

## 📊 Comparação: Antes vs Depois

### Antes
```
main.py (18 KB)        → Scan de hoje
tomorrow.py (113 KB)   → Scan de amanhã + TUDO duplicado
                        ❌ 113 KB de código duplicado
```

### Depois
```
main.py (18 KB)        → Scan de hoje (chama scanner)
scan_tomorrow.py (2 KB) → Scan de amanhã (chama scanner)
scanner/game_scanner.py → Função genérica (compartilhada)
                        ✅ Zero duplicação
                        ✅ 111 KB economizados
```

## 🎯 Recomendação Final

**MODULARIZAR** é a melhor opção porque:

1. ✅ **Elimina 100% da duplicação** (111 KB economizados)
2. ✅ **Mantém responsabilidades separadas** (cada módulo faz uma coisa)
3. ✅ **Facilita manutenção** (um lugar para corrigir)
4. ✅ **Flexível** (pode rodar manual ou automático)
5. ✅ **Escalável** (fácil adicionar scan de outros dias)
6. ✅ **Testável** (função genérica fácil de testar)

**NÃO integrar no `main.py`** porque:
- ❌ Misturaria responsabilidades (hoje + amanhã no mesmo arquivo)
- ❌ Dificultaria manutenção (lógica condicional complexa)
- ❌ Não permitiria rodar scans independentes

## 📝 Próximos Passos

1. Criar `scanner/__init__.py`
2. Criar `scanner/game_scanner.py` com função genérica
3. Mover lógica de `morning_scan_and_publish()` para `scan_games_for_date()`
4. Refatorar `main.py` para usar `scan_games_for_date(date_offset=0)`
5. Criar `scan_tomorrow.py` simples que chama `scan_games_for_date(date_offset=1)`
6. Adicionar job opcional no scheduler para scan de amanhã
7. Deletar `tomorrow.py` (não será mais necessário)

## 🚀 Resultado Esperado

- ✅ `scan_tomorrow.py` com ~20 linhas (só chama função)
- ✅ `scanner/game_scanner.py` com ~200 linhas (lógica compartilhada)
- ✅ Zero duplicação de código
- ✅ Responsabilidades claras
- ✅ Fácil manutenção e testes



