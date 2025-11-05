"""
Sistema de consolidação de lembretes próximos no tempo.
Agrupa lembretes que acontecem em janela curta de tempo para evitar spam.
"""
from datetime import datetime, timedelta
from typing import List, Dict, Any
import pytz
from models.database import Game, SessionLocal
from utils.logger import logger
from utils.formatters import fmt_reminder
from notifications.telegram import tg_send_message


def consolidate_reminders_job():
    """
    Job que consolida lembretes próximos no tempo.
    Busca jogos que têm lembretes agendados nos próximos minutos e agrupa.
    """
    from config.settings import START_ALERT_MIN, ZONE
    
    now_utc = datetime.now(pytz.UTC)
    window_minutes = 5  # Janela de 5 minutos para agrupar lembretes
    
    with SessionLocal() as session:
        # Busca jogos que têm lembretes agendados na próxima janela
        window_start = now_utc + timedelta(minutes=START_ALERT_MIN)
        window_end = window_start + timedelta(minutes=window_minutes)
        
        upcoming_games = (
            session.query(Game)
            .filter(
                Game.will_bet.is_(True),
                Game.status == "scheduled",
                Game.start_time >= window_start,
                Game.start_time <= window_end
            )
            .order_by(Game.start_time)
            .all()
        )
        
        if not upcoming_games:
            return
        
        # Agrupa jogos por intervalo de tempo (ex: todos os jogos entre 14:00-14:05)
        groups: Dict[str, List[Game]] = {}
        for game in upcoming_games:
            game_start_local = game.start_time.astimezone(ZONE)
            # Agrupa por intervalo de 5 minutos
            group_key = game_start_local.strftime("%H:%M")[:4] + "0"  # Ex: "14:00", "14:05"
            if group_key not in groups:
                groups[group_key] = []
            groups[group_key].append(game)
        
        # Envia mensagem consolidada para cada grupo
        for group_key, games in groups.items():
            if len(games) == 1:
                # Se só tem um jogo, envia lembrete individual normal
                game = games[0]
                tg_send_message(
                    fmt_reminder(game),
                    message_type="reminder",
                    game_id=game.id,
                    ext_id=game.ext_id
                )
                logger.info(f"🔔 Lembrete individual enviado para jogo {game.id}")
            else:
                # Se tem múltiplos jogos, consolida em uma mensagem
                send_consolidated_reminder(games, group_key)


def send_consolidated_reminder(games: List[Game], time_window: str):
    """
    Envia um lembrete consolidado para múltiplos jogos.
    
    Args:
        games: Lista de jogos para lembrar
        time_window: Janela de tempo (ex: "14:00")
    """
    from config.settings import ZONE
    
    if not games:
        return
    
    # Ordena por horário de início
    games_sorted = sorted(games, key=lambda g: g.start_time)
    
    # Monta mensagem consolidada
    lines = [
        f"🔔 <b>LEMBRETES ({time_window})</b>",
        f"━━━━━━━━━━━━━━━━━━━━━━",
        ""
    ]
    
    for i, game in enumerate(games_sorted, 1):
        game_start_local = game.start_time.astimezone(ZONE)
        time_str = game_start_local.strftime("%H:%M")
        
        pick_map = {
            "home": game.team_home,
            "draw": "Empate",
            "away": game.team_away
        }
        pick_str = pick_map.get(game.pick, game.pick or "—")
        
        lines.append(
            f"<b>{i}.</b> <b>{game.team_home}</b> vs <b>{game.team_away}</b>\n"
            f"   🕐 {time_str}h | Pick: <b>{pick_str}</b> @ {game.pick_prob * 100:.0f}%"
        )
        lines.append("")
    
    message = "\n".join(lines)
    
    # Usa game_id do primeiro jogo para rastreamento
    first_game = games_sorted[0]
    tg_send_message(
        message,
        parse_mode="HTML",
        message_type="reminder",
        game_id=first_game.id,
        ext_id=f"consolidated_{len(games)}"
    )
    
    logger.info(f"🔔 Lembrete consolidado enviado para {len(games)} jogos ({time_window})")

