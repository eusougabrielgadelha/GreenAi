# Guia de Leitura do Banco de Dados

Este guia mostra como consultar e ler dados do banco de dados SQLite (`betauto.sqlite3`).

## Estrutura do Banco

O banco usa **SQLite** e está localizado em `betauto.sqlite3` (ou conforme `DB_URL` no `.env`).

### Tabelas Principais

1. **`games`** - Jogos escaneados e analisados
2. **`live_game_trackers`** - Rastreamento de jogos ao vivo
3. **`odd_history`** - Histórico de odds dos jogos
4. **`analytics_events`** - Eventos de analytics
5. **`combined_bets`** - Apostas combinadas
6. **`stats`** - Estatísticas gerais do sistema

---

## Como Usar o SessionLocal

O padrão é usar `SessionLocal()` como context manager:

```python
from models.database import SessionLocal, Game, LiveGameTracker, OddHistory

# Método 1: Usando context manager (recomendado)
with SessionLocal() as session:
    games = session.query(Game).all()
    # session é fechada automaticamente ao sair do bloco

# Método 2: Gerenciamento manual
session = SessionLocal()
try:
    games = session.query(Game).all()
finally:
    session.close()
```

---

## Exemplos Práticos de Consultas

### 1. Buscar Todos os Jogos

```python
from models.database import SessionLocal, Game

with SessionLocal() as session:
    # Todos os jogos
    all_games = session.query(Game).all()
    
    for game in all_games:
        print(f"ID: {game.id}, {game.team_home} vs {game.team_away}")
        print(f"Status: {game.status}, Pick: {game.pick}")
        print(f"Hit: {game.hit}, Outcome: {game.outcome}")
        print("---")
```

### 2. Filtrar Jogos por Status

```python
from models.database import SessionLocal, Game

with SessionLocal() as session:
    # Jogos agendados
    scheduled = session.query(Game).filter(Game.status == "scheduled").all()
    
    # Jogos ao vivo
    live = session.query(Game).filter(Game.status == "live").all()
    
    # Jogos finalizados
    ended = session.query(Game).filter(Game.status == "ended").all()
```

### 3. Jogos Selecionados para Aposta

```python
from models.database import SessionLocal, Game

with SessionLocal() as session:
    # Apenas jogos que foram selecionados para apostar
    selected = session.query(Game).filter(Game.will_bet == True).all()
    
    # Jogos selecionados com alta confiança
    high_conf = session.query(Game).filter(
        Game.will_bet == True,
        Game.pick_prob >= 0.60
    ).all()
```

### 4. Buscar por Data de Início

```python
from models.database import SessionLocal, Game
from datetime import datetime, timedelta
import pytz

with SessionLocal() as session:
    # Jogos de hoje
    today = datetime.now(pytz.UTC).replace(hour=0, minute=0, second=0)
    tomorrow = today + timedelta(days=1)
    
    games_today = session.query(Game).filter(
        Game.start_time >= today,
        Game.start_time < tomorrow
    ).all()
    
    # Jogos dos últimos 7 dias
    week_ago = datetime.now(pytz.UTC) - timedelta(days=7)
    recent_games = session.query(Game).filter(
        Game.start_time >= week_ago
    ).order_by(Game.start_time.desc()).all()
```

### 5. Estatísticas de Acertos

```python
from models.database import SessionLocal, Game
from sqlalchemy import func

with SessionLocal() as session:
    # Total de jogos finalizados
    total = session.query(Game).filter(
        Game.status == "ended",
        Game.hit.isnot(None)
    ).count()
    
    # Jogos que acertaram
    hits = session.query(Game).filter(
        Game.status == "ended",
        Game.hit == True
    ).count()
    
    # Taxa de acerto
    accuracy = (hits / total * 100) if total > 0 else 0
    print(f"Taxa de acerto: {accuracy:.2f}% ({hits}/{total})")
    
    # Agrupar por pick
    stats = session.query(
        Game.pick,
        func.count(Game.id).label('total'),
        func.sum(func.cast(Game.hit, Integer)).label('hits')
    ).filter(
        Game.status == "ended",
        Game.hit.isnot(None)
    ).group_by(Game.pick).all()
    
    for pick, total, hits_count in stats:
        acc = (hits_count / total * 100) if total > 0 else 0
        print(f"{pick}: {acc:.2f}% ({hits_count}/{total})")
```

### 6. Jogos com Notificações Enviadas

```python
from models.database import SessionLocal, Game
from datetime import datetime, timedelta

with SessionLocal() as session:
    # Jogos notificados hoje
    today = datetime.now(pytz.UTC).replace(hour=0, minute=0, second=0)
    
    notified_today = session.query(Game).filter(
        Game.pick_notified_at >= today,
        Game.pick_notified_at.isnot(None)
    ).all()
    
    # Jogos notificados mas ainda não finalizados
    pending_notified = session.query(Game).filter(
        Game.pick_notified_at.isnot(None),
        Game.status.in_(["scheduled", "live"])
    ).all()
```

### 7. Buscar Jogo por ID Externo

```python
from models.database import SessionLocal, Game

with SessionLocal() as session:
    ext_id = "63369819"
    
    # Buscar por ext_id
    game = session.query(Game).filter(Game.ext_id == ext_id).first()
    
    if game:
        print(f"Jogo encontrado: {game.team_home} vs {game.team_away}")
        print(f"Status: {game.status}")
        print(f"Pick: {game.pick} (prob: {game.pick_prob})")
    else:
        print("Jogo não encontrado")
```

### 8. Tracker de Jogo ao Vivo

```python
from models.database import SessionLocal, LiveGameTracker, Game

with SessionLocal() as session:
    # Buscar tracker com dados do jogo
    trackers = session.query(LiveGameTracker).join(Game).all()
    
    for tracker in trackers:
        game = tracker.game
        print(f"Jogo: {game.team_home} vs {game.team_away}")
        print(f"Status: {game.status}")
        print(f"Placar: {tracker.current_score}")
        print(f"Minuto: {tracker.current_minute}")
        print(f"Última análise: {tracker.last_analysis_time}")
        print(f"Notificações enviadas: {tracker.notifications_sent}")
        print("---")
```

### 9. Histórico de Odds

```python
from models.database import SessionLocal, OddHistory, Game

with SessionLocal() as session:
    # Buscar histórico de odds de um jogo específico
    game_id = 123
    history = session.query(OddHistory).filter(
        OddHistory.game_id == game_id
    ).order_by(OddHistory.timestamp).all()
    
    for entry in history:
        print(f"Timestamp: {entry.timestamp}")
        print(f"Odds: {entry.odds_home} / {entry.odds_draw} / {entry.odds_away}")
        print("---")
```

### 10. Consultas com Relacionamentos

```python
from models.database import SessionLocal, Game, LiveGameTracker

with SessionLocal() as session:
    # Jogos ao vivo com tracker
    live_with_tracker = session.query(Game).filter(
        Game.status == "live"
    ).join(LiveGameTracker).all()
    
    for game in live_with_tracker:
        tracker = game.tracker
        print(f"{game.team_home} vs {game.team_away}")
        if tracker:
            print(f"Placar: {tracker.current_score}")
            print(f"Minuto: {tracker.current_minute}")
```

### 11. Buscar Jogos por Competição

```python
from models.database import SessionLocal, Game

with SessionLocal() as session:
    # Jogos de uma competição específica
    competition = "Premier League"
    games = session.query(Game).filter(
        Game.competition == competition
    ).order_by(Game.start_time).all()
```

### 12. Usar SQL Direto (Raw SQL)

```python
from models.database import SessionLocal, text

with SessionLocal() as session:
    # Query SQL direta
    result = session.execute(text("""
        SELECT 
            team_home, 
            team_away, 
            pick, 
            hit,
            pick_prob
        FROM games
        WHERE status = 'ended'
        AND hit IS NOT NULL
        ORDER BY start_time DESC
        LIMIT 10
    """))
    
    for row in result:
        print(f"{row.team_home} vs {row.team_away}: {row.pick} (prob: {row.pick_prob}) - {'✓' if row.hit else '✗'}")
```

### 13. Exportar Dados para CSV

```python
import csv
from models.database import SessionLocal, Game

with SessionLocal() as session:
    games = session.query(Game).filter(
        Game.status == "ended",
        Game.hit.isnot(None)
    ).all()
    
    with open('games_export.csv', 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([
            'ID', 'Time Casa', 'Time Fora', 'Competição', 
            'Data/Hora', 'Pick', 'Prob', 'EV', 'Hit', 'Outcome'
        ])
        
        for game in games:
            writer.writerow([
                game.id,
                game.team_home,
                game.team_away,
                game.competition,
                game.start_time,
                game.pick,
                game.pick_prob,
                game.pick_ev,
                game.hit,
                game.outcome
            ])
```

---

## Script de Exemplo Completo

Crie um arquivo `read_db_example.py`:

```python
"""Exemplo de leitura do banco de dados."""
from models.database import SessionLocal, Game, LiveGameTracker
from datetime import datetime, timedelta
import pytz

def print_games_summary():
    """Mostra resumo geral dos jogos."""
    with SessionLocal() as session:
        total = session.query(Game).count()
        scheduled = session.query(Game).filter(Game.status == "scheduled").count()
        live = session.query(Game).filter(Game.status == "live").count()
        ended = session.query(Game).filter(Game.status == "ended").count()
        selected = session.query(Game).filter(Game.will_bet == True).count()
        
        print("=== RESUMO DO BANCO DE DADOS ===")
        print(f"Total de jogos: {total}")
        print(f"Agendados: {scheduled}")
        print(f"Ao vivo: {live}")
        print(f"Finalizados: {ended}")
        print(f"Selecionados para apostar: {selected}")
        print()

def print_recent_games(limit=10):
    """Mostra jogos recentes."""
    with SessionLocal() as session:
        games = session.query(Game).order_by(
            Game.start_time.desc()
        ).limit(limit).all()
        
        print(f"=== ÚLTIMOS {limit} JOGOS ===")
        for game in games:
            status_emoji = {
                "scheduled": "⏰",
                "live": "🔴",
                "ended": "✅"
            }.get(game.status, "❓")
            
            print(f"{status_emoji} {game.team_home} vs {game.team_away}")
            print(f"   {game.competition} - {game.start_time}")
            if game.pick:
                print(f"   Pick: {game.pick} (prob: {game.pick_prob:.2%}, EV: {game.pick_ev:.3f})")
            if game.hit is not None:
                print(f"   Resultado: {'✓ ACERTOU' if game.hit else '✗ ERROU'} ({game.outcome})")
            print()

def print_accuracy_stats():
    """Mostra estatísticas de acerto."""
    with SessionLocal() as session:
        ended_with_result = session.query(Game).filter(
            Game.status == "ended",
            Game.hit.isnot(None)
        ).all()
        
        if not ended_with_result:
            print("Nenhum jogo finalizado com resultado ainda.")
            return
        
        total = len(ended_with_result)
        hits = sum(1 for g in ended_with_result if g.hit)
        accuracy = (hits / total * 100) if total > 0 else 0
        
        print("=== ESTATÍSTICAS DE ACERTO ===")
        print(f"Taxa de acerto: {accuracy:.2f}% ({hits}/{total})")
        print()

if __name__ == "__main__":
    print_games_summary()
    print_recent_games(5)
    print_accuracy_stats()
```

Execute:

```bash
python read_db_example.py
```

---

## Ferramentas Úteis

### Usando SQLite CLI

Você também pode usar o SQLite diretamente:

```bash
# Windows
sqlite3 betauto.sqlite3

# Linux/Mac
sqlite3 betauto.sqlite3
```

Exemplos de queries SQL:

```sql
-- Ver todos os jogos
SELECT id, team_home, team_away, status, pick, hit FROM games;

-- Jogos ao vivo
SELECT * FROM games WHERE status = 'live';

-- Taxa de acerto
SELECT 
    COUNT(*) as total,
    SUM(CASE WHEN hit = 1 THEN 1 ELSE 0 END) as hits,
    ROUND(SUM(CASE WHEN hit = 1 THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2) as accuracy
FROM games 
WHERE status = 'ended' AND hit IS NOT NULL;
```

---

## Dicas Importantes

1. **Sempre feche a sessão**: Use `with SessionLocal()` ou `session.close()`
2. **Filtros eficientes**: Use índices (status, will_bet, ext_id, start_time)
3. **Ordem**: Use `.order_by()` para ordenar resultados
4. **Limite**: Use `.limit()` para evitar carregar muitos dados
5. **Timezone**: Todos os timestamps estão em UTC no banco

---

## Campos Importantes da Tabela `games`

- `id`: ID único do jogo
- `ext_id`: ID externo do jogo (da API/site)
- `team_home` / `team_away`: Times
- `start_time`: Data/hora de início (UTC)
- `status`: `scheduled` | `live` | `ended`
- `pick`: `home` | `draw` | `away`
- `pick_prob`: Probabilidade do palpite (0.0 a 1.0)
- `pick_ev`: Expected Value do palpite
- `will_bet`: `True` se foi selecionado para apostar
- `outcome`: Resultado final (`home` | `draw` | `away`)
- `hit`: `True` se acertou, `False` se errou, `None` se ainda não finalizou
- `pick_notified_at`: Quando foi enviada a notificação do palpite

