"""
Sistema de recuperação de jogos pendentes ao reiniciar o script.
Garante que jogos que estavam sendo monitorados continuem sendo processados após reiniciar.
"""
from datetime import datetime, timedelta
from typing import List, Dict, Any
import pytz
from models.database import Game, SessionLocal
from utils.logger import logger
from scraping.fetchers import fetch_game_result
from scheduler.jobs import (
    _schedule_all_for_game, 
    _ensure_tracker_exists, 
    _update_game_tracker,
    _is_game_finished,
    _handle_finished_game
)


async def recover_pending_games():
    """
    Recupera e continua o processamento de jogos pendentes após reiniciar o script.
    
    Processa:
    1. Jogos ao vivo (status='live') que ainda não têm resultado
    2. Jogos agendados (status='scheduled') com will_bet=True que precisam ser monitorados
    3. Jogos que terminaram (status='ended') mas não têm resultado ainda
    """
    now_utc = datetime.now(pytz.UTC)
    
    with SessionLocal() as session:
        # 1. Buscar jogos ao vivo que ainda não têm resultado
        live_games = (
            session.query(Game)
            .filter(
                Game.status == "live",
                Game.will_bet.is_(True),
                Game.outcome.is_(None),  # Ainda não tem resultado
                Game.start_time >= now_utc - timedelta(hours=3)  # Dentro de 3 horas
            )
            .all()
        )
        
        if live_games:
            logger.info(f"🔄 Recuperando {len(live_games)} jogo(s) ao vivo pendente(s)")
            for game in live_games:
                try:
                    # Garantir que tracker existe
                    tracker = _ensure_tracker_exists(session, game, now_utc)
                    # Atualizar tracker com dados atuais
                    await _update_game_tracker(tracker, game, now_utc)
                    # Verificar se jogo já terminou
                    if _is_game_finished(tracker.current_minute or "") and game.status == "live":
                        await _handle_finished_game(session, game, tracker, now_utc)
                    else:
                        # Garantir que está sendo monitorado
                        logger.info(f"✅ Jogo ao vivo recuperado: {game.id} ({game.ext_id}) - {game.team_home} vs {game.team_away}")
                except Exception as e:
                    logger.exception(f"Erro ao recuperar jogo ao vivo {game.id}: {e}")
        
        # 2. Buscar jogos agendados que precisam ser monitorados
        scheduled_games = (
            session.query(Game)
            .filter(
                Game.status == "scheduled",
                Game.will_bet.is_(True),
                Game.start_time >= now_utc - timedelta(hours=1),  # Próximas 24 horas
                Game.start_time <= now_utc + timedelta(hours=24)
            )
            .all()
        )
        
        if scheduled_games:
            logger.info(f"🔄 Recuperando {len(scheduled_games)} jogo(s) agendado(s) para monitoramento")
            for game in scheduled_games:
                try:
                    # Verificar se já começou
                    if game.start_time <= now_utc:
                        game.status = "live"
                        logger.info(f"▶️  Jogo {game.id} ({game.ext_id}) atualizado para 'live' - {game.team_home} vs {game.team_away}")
                        # Garantir tracker
                        tracker = _ensure_tracker_exists(session, game, now_utc)
                        await _update_game_tracker(tracker, game, now_utc)
                    else:
                        # Ainda agendado - garantir que está agendado para monitoramento
                        logger.info(f"📅 Jogo agendado recuperado: {game.id} ({game.ext_id}) - {game.team_home} vs {game.team_away} às {game.start_time}")
                        # Re-agendar jobs para o jogo
                        await _schedule_all_for_game(game)
                    session.commit()
                except Exception as e:
                    logger.exception(f"Erro ao recuperar jogo agendado {game.id}: {e}")
        
        # 3. Buscar jogos que terminaram mas não têm resultado
        finished_no_result = (
            session.query(Game)
            .filter(
                Game.status.in_(["live", "ended"]),
                Game.will_bet.is_(True),
                Game.outcome.is_(None),  # Não tem resultado
                Game.start_time >= now_utc - timedelta(days=1),  # Últimas 24 horas
                Game.start_time <= now_utc - timedelta(minutes=90)  # Terminou há mais de 90min (tempo suficiente para ter resultado)
            )
            .all()
        )
        
        if finished_no_result:
            logger.info(f"🔍 Buscando resultados finais para {len(finished_no_result)} jogo(s) que terminaram sem resultado")
            for game in finished_no_result:
                try:
                    logger.info(f"🔎 Buscando resultado final para jogo {game.id} ({game.ext_id}) - {game.team_home} vs {game.team_away}")
                    outcome = await fetch_game_result(game.ext_id, game.game_url or game.source_link)
                    if outcome:
                        game.outcome = outcome
                        game.status = "ended"
                        game.hit = (outcome == game.pick) if game.pick else None
                        result_msg = "✅ ACERTOU" if game.hit else "❌ ERROU" if game.hit is False else "⚠️ SEM PALPITE"
                        logger.info(f"✅ Resultado obtido para jogo {game.id}: {outcome} | {result_msg}")
                        
                        # Envia notificação de resultado
                        from utils.formatters import fmt_result
                        from notifications.telegram import tg_send_message
                        tg_send_message(fmt_result(game), message_type="result", game_id=game.id, ext_id=game.ext_id)
                        
                        session.commit()
                    else:
                        logger.warning(f"⚠️  Não foi possível obter resultado para jogo {game.id} ainda")
                except Exception as e:
                    logger.exception(f"Erro ao buscar resultado final para jogo {game.id}: {e}")
        
        # Resumo
        total_recovered = len(live_games) + len(scheduled_games) + len(finished_no_result)
        if total_recovered > 0:
            logger.info(f"✅ Recuperação concluída: {total_recovered} jogo(s) recuperado(s) ({len(live_games)} ao vivo, {len(scheduled_games)} agendados, {len(finished_no_result)} sem resultado)")
        else:
            logger.info("✅ Nenhum jogo pendente para recuperar")


def get_pending_games_summary() -> Dict[str, Any]:
    """
    Retorna um resumo dos jogos pendentes no banco de dados.
    
    Returns:
        Dict com contagem de jogos por status
    """
    now_utc = datetime.now(pytz.UTC)
    
    with SessionLocal() as session:
        live_count = session.query(Game).filter(
            Game.status == "live",
            Game.will_bet.is_(True),
            Game.outcome.is_(None)
        ).count()
        
        scheduled_count = session.query(Game).filter(
            Game.status == "scheduled",
            Game.will_bet.is_(True),
            Game.start_time >= now_utc - timedelta(hours=1),
            Game.start_time <= now_utc + timedelta(hours=24)
        ).count()
        
        finished_no_result_count = session.query(Game).filter(
            Game.status.in_(["live", "ended"]),
            Game.will_bet.is_(True),
            Game.outcome.is_(None),
            Game.start_time >= now_utc - timedelta(days=1),
            Game.start_time <= now_utc - timedelta(minutes=90)
        ).count()
        
        return {
            "live_pending": live_count,
            "scheduled_pending": scheduled_count,
            "finished_no_result": finished_no_result_count,
            "total_pending": live_count + scheduled_count + finished_no_result_count
        }

