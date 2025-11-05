"""Funções auxiliares para Telegram."""
from notifications.telegram import tg_send_message
from utils.formatters import fmt_pick_now, fmt_watch_upgrade
from models.database import Game
from typing import Optional, Dict, Any


def send_pick_with_buffer(game: Game) -> bool:
    """
    Envia pick usando buffer de consolidação.
    
    Args:
        game: Instância do Game
        
    Returns:
        True se foi adicionado ao buffer, False se foi enviado imediatamente
    """
    from utils.telegram_message_buffer import add_to_buffer
    
    message = fmt_pick_now(game)
    buffered = add_to_buffer(
        message_type="pick_now",
        content=message,
        game_id=game.id,
        ext_id=game.ext_id,
        metadata={"team_home": game.team_home, "team_away": game.team_away}
    )
    
    if not buffered:
        # Buffer não está ativo ou não aceitou, enviar imediatamente
        tg_send_message(message, message_type="pick_now", game_id=game.id, ext_id=game.ext_id)
        return False
    
    return True


def send_upgrade_with_buffer(game: Game) -> bool:
    """
    Envia upgrade da watchlist usando buffer de consolidação.
    
    Args:
        game: Instância do Game
        
    Returns:
        True se foi adicionado ao buffer, False se foi enviado imediatamente
    """
    from utils.telegram_message_buffer import add_to_buffer
    
    message = fmt_watch_upgrade(game)
    buffered = add_to_buffer(
        message_type="watch_upgrade",
        content=message,
        game_id=game.id,
        ext_id=game.ext_id,
        metadata={"team_home": game.team_home, "team_away": game.team_away}
    )
    
    if not buffered:
        # Buffer não está ativo ou não aceitou, enviar imediatamente
        tg_send_message(message, message_type="watch_upgrade", game_id=game.id, ext_id=game.ext_id)
        return False
    
    return True


def send_live_opportunity_with_buffer(game: Game, opportunity: Dict[str, Any], stats: Dict[str, Any]) -> bool:
    """
    Envia oportunidade ao vivo usando buffer de consolidação.
    
    Args:
        game: Instância do Game
        opportunity: Dicionário com dados da oportunidade
        stats: Dicionário com estatísticas do jogo
        
    Returns:
        True se foi adicionado ao buffer, False se foi enviado imediatamente
    """
    from utils.telegram_message_buffer import add_to_buffer
    from utils.formatters import fmt_live_bet_opportunity
    
    message = fmt_live_bet_opportunity(game, opportunity, stats)
    buffered = add_to_buffer(
        message_type="live_opportunity",
        content=message,
        game_id=game.id,
        ext_id=game.ext_id,
        metadata={
            "opportunity": opportunity,
            "stats": stats,
            "team_home": game.team_home,
            "team_away": game.team_away
        }
    )
    
    if not buffered:
        # Buffer não está ativo ou não aceitou, enviar imediatamente
        from notifications.telegram import tg_send_message
        tg_send_message(message, message_type="live_opportunity", game_id=game.id, ext_id=game.ext_id)
        return False
    
    return True


def send_summary_safe(text: str, message_type: str = "summary") -> None:
    """
    Envia mensagem de resumo com fallback para diferentes formatos.
    Tenta HTML primeiro, depois texto simples.
    """
    try:
        tg_send_message(text, parse_mode="HTML", message_type=message_type)
        return
    except Exception:
        from utils.logger import logger
        logger.exception("Falha com HTML; tentando sem parse_mode…")
    try:
        tg_send_message(text, parse_mode=None, message_type=message_type)
    except TypeError:
        try:
            tg_send_message(text, message_type=message_type)
        except Exception:
            logger.exception("Falha ao enviar resumo ao Telegram (fallback simples).")
    except Exception:
        logger.exception("Falha ao enviar resumo ao Telegram (fallback simples).")
