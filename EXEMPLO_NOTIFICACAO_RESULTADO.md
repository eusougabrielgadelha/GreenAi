# 📱 Exemplo de Notificação de Resultado

## ✅ Sim, o Sistema Envia Automaticamente!

Quando um jogo termina, o sistema **automaticamente**:
1. ✅ Busca o resultado final
2. ✅ Compara com o palpite
3. ✅ Envia notificação no Telegram

## 📱 Exemplo de Mensagem Enviada

### Se o Sinal ACERTOU:

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

### Se o Sinal ERROU:

```
❌ RESULTADO - ERRAMOS
━━━━━━━━━━━━━━━━━━━━

⚽ Flamengo vs Palmeiras

💰 ODDS
├ Flamengo: 2.10
├ Empate: 3.40
└ Palmeiras: 3.20

📊 RESULTADO
├ Palpite: Flamengo
├ Resultado: Palmeiras
└ EV estimado: +5.2%
```

## 🔄 Quando é Enviado?

A notificação é enviada **automaticamente** quando:

1. **O jogo termina** (status muda para "ended")
2. **O sistema consegue obter o resultado** (via API ou HTML scraping)
3. **A comparação é feita** (`game.hit = (outcome == game.pick)`)

## 📍 Onde Isso Acontece no Código?

### 1. Monitoramento de Jogos ao Vivo

```python
# scheduler/jobs.py, linha 720-731
if game.status == "ended":
    # Busca resultado final
    outcome = await fetch_game_result(game.ext_id, game.game_url or game.source_link)
    
    if outcome:
        game.outcome = outcome
        game.hit = (outcome == game.pick) if game.pick else None
        
        # ✅ ENVIA NOTIFICAÇÃO DE RESULTADO
        from utils.formatters import fmt_result
        tg_send_message(fmt_result(game), message_type="result", ...)
```

### 2. Monitoramento Específico (se não conseguir na primeira vez)

```python
# scheduler/jobs.py, linha 959-976
async def watch_game_until_end_job(game_id: int):
    # Tenta obter o resultado
    outcome = await fetch_game_result(...)
    
    if outcome:
        game.outcome = outcome
        game.hit = (outcome == game.pick) if game.pick else None
        
        # ✅ ENVIA NOTIFICAÇÃO DE RESULTADO
        from utils.formatters import fmt_result
        tg_send_message(fmt_result(game), message_type="result", ...)
```

## 📊 Informações na Notificação

A mensagem contém:

1. **✅/❌ Status**: Se acertou ou errou
2. **⚽ Jogo**: Times que jogaram
3. **💰 Odds**: Odds de casa, empate e fora
4. **📊 Comparação**:
   - Palpite que foi feito
   - Resultado real do jogo
   - EV (Expected Value) estimado

## 🔄 Resumo Diário

Além da notificação individual, quando **todos os jogos do dia terminam**, o sistema também envia um **resumo diário** com:

- Total de jogos do dia
- Quantidade de acertos
- Quantidade de erros
- Assertividade do dia
- ROI estimado

## ⚙️ Configuração

Não é necessário configurar nada! O envio é **automático** e acontece sempre que:

- Um jogo termina
- O resultado é obtido com sucesso
- Existe um palpite (`game.pick`) para comparar

## 🎯 Garantias

✅ **Sempre envia** quando o jogo termina e o resultado é obtido
✅ **Formatação clara** mostrando se acertou ou errou
✅ **Todas as informações** relevantes (odds, palpite, resultado)
✅ **Automático** - não precisa fazer nada manualmente

## 📝 Notas Importantes

1. **Se o resultado não for encontrado imediatamente**: O sistema tenta novamente a cada 5 minutos até conseguir
2. **Se não houver palpite**: A mensagem mostra "⚠️ SEM PALPITE" mas ainda envia a notificação
3. **Múltiplas tentativas**: Se a primeira tentativa falhar, o sistema agenda nova tentativa automaticamente

## ✅ Conclusão

**SIM, o sistema envia automaticamente o resultado do sinal quando o jogo termina!**

Você receberá uma notificação clara mostrando:
- ✅ Se acertou
- ❌ Se errou
- Todas as informações do jogo e do palpite

