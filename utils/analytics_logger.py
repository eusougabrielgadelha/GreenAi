"""Sistema de log estruturado para analytics do sistema."""
from datetime import datetime
from typing import Any, Dict, Optional
import pytz
from models.database import SessionLocal, AnalyticsEvent
from utils.logger import logger


def log_event(
    event_type: str,
    event_category: str,
    event_data: Optional[Dict[str, Any]] = None,
    game_id: Optional[int] = None,
    ext_id: Optional[str] = None,
    source_link: Optional[str] = None,
    success: bool = True,
    reason: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> None:
    """
    Registra um evento de analytics no banco de dados.
    
    Args:
        event_type: Tipo do evento (extraction, calculation, decision, telegram_send, etc)
        event_category: Categoria do evento (scraping, betting, notification, etc)
        event_data: Dados estruturados do evento
        game_id: ID do jogo relacionado (opcional)
        ext_id: ID externo do jogo (opcional)
        source_link: Link da fonte (opcional)
        success: Se o evento foi bem-sucedido
        reason: Motivo da ação (ex: por que foi suprimido ou enviado)
        metadata: Metadados adicionais
    """
    try:
        with SessionLocal() as session:
            event = AnalyticsEvent(
                event_type=event_type,
                event_category=event_category,
                timestamp=datetime.now(pytz.UTC),
                game_id=game_id,
                ext_id=ext_id,
                source_link=source_link,
                event_data=event_data or {},
                success=success,
                reason=reason,
                event_metadata=metadata or {}  # Renomeado de 'metadata' para evitar conflito com SQLAlchemy
            )
            session.add(event)
            session.commit()
    except Exception as e:
        logger.exception("Erro ao registrar evento de analytics: %s", e)


def log_extraction(
    url: str,
    events_count: int,
    backend: str,
    success: bool = True,
    error: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> None:
    """Registra uma extração de dados."""
    log_event(
        event_type="extraction",
        event_category="scraping",
        event_data={
            "url": url,
            "events_count": events_count,
            "backend": backend
        },
        source_link=url,
        success=success,
        reason=error,
        metadata=metadata
    )


def log_calculation(
    ext_id: Optional[str],
    odds_home: float,
    odds_draw: float,
    odds_away: float,
    pick: str,
    pick_prob: float,
    pick_ev: float,
    strategy: str,
    game_id: Optional[int] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> None:
    """Registra um cálculo de decisão."""
    log_event(
        event_type="calculation",
        event_category="betting",
        event_data={
            "odds_home": odds_home,
            "odds_draw": odds_draw,
            "odds_away": odds_away,
            "pick": pick,
            "pick_prob": pick_prob,
            "pick_ev": pick_ev,
            "strategy": strategy
        },
        game_id=game_id,
        ext_id=ext_id,
        success=True,
        metadata=metadata
    )


def log_decision(
    ext_id: Optional[str],
    will_bet: bool,
    pick: str,
    pick_prob: float,
    pick_ev: float,
    reason: str,
    game_id: Optional[int] = None,
    suppressed: bool = False,
    suppression_reason: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> None:
    """Registra uma decisão de aposta."""
    log_event(
        event_type="decision",
        event_category="betting",
        event_data={
            "will_bet": will_bet,
            "pick": pick,
            "pick_prob": pick_prob,
            "pick_ev": pick_ev
        },
        game_id=game_id,
        ext_id=ext_id,
        success=will_bet,
        reason=suppression_reason if suppressed else reason,
        metadata={
            **(metadata or {}),
            "suppressed": suppressed,
            "decision_reason": reason
        }
    )


def log_telegram_send(
    message_type: str,
    game_id: Optional[int] = None,
    ext_id: Optional[str] = None,
    success: bool = True,
    error: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> None:
    """Registra o envio de uma mensagem via Telegram."""
    log_event(
        event_type="telegram_send",
        event_category="notification",
        event_data={
            "message_type": message_type
        },
        game_id=game_id,
        ext_id=ext_id,
        success=success,
        reason=error,
        metadata=metadata
    )


def log_signal_suppression(
    ext_id: Optional[str],
    reason: str,
    pick_prob: float,
    pick_ev: float,
    game_id: Optional[int] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> None:
    """Registra a supressão de um sinal."""
    log_event(
        event_type="signal_suppression",
        event_category="betting",
        event_data={
            "pick_prob": pick_prob,
            "pick_ev": pick_ev
        },
        game_id=game_id,
        ext_id=ext_id,
        success=False,
        reason=reason,
        metadata=metadata
    )


def log_signal_sent(
    ext_id: Optional[str],
    reason: str,
    pick: str,
    pick_prob: float,
    pick_ev: float,
    game_id: Optional[int] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> None:
    """Registra o envio de um sinal."""
    log_event(
        event_type="signal_sent",
        event_category="betting",
        event_data={
            "pick": pick,
            "pick_prob": pick_prob,
            "pick_ev": pick_ev
        },
        game_id=game_id,
        ext_id=ext_id,
        success=True,
        reason=reason,
        metadata=metadata
    )


def log_watchlist_action(
    action: str,  # add, remove, upgrade
    ext_id: str,
    reason: str,
    metadata: Optional[Dict[str, Any]] = None
) -> None:
    """Registra uma ação na watchlist."""
    log_event(
        event_type="watchlist_action",
        event_category="betting",
        event_data={
            "action": action
        },
        ext_id=ext_id,
        success=True,
        reason=reason,
        metadata=metadata
    )


def log_live_opportunity(
    game_id: int,
    ext_id: str,
    opportunity: Optional[Dict[str, Any]],
    reason: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> None:
    """Registra uma análise de oportunidade ao vivo."""
    log_event(
        event_type="live_opportunity",
        event_category="betting",
        event_data=opportunity or {},
        game_id=game_id,
        ext_id=ext_id,
        success=opportunity is not None,
        reason=reason,
        metadata=metadata
    )

