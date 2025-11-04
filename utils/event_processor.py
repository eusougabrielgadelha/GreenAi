"""Processador genérico de eventos de jogos."""
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timedelta
import pytz

from config.settings import (
    ZONE, HIGH_CONF_THRESHOLD, MIN_EV, MIN_PROB,
    WATCHLIST_DELTA, WATCHLIST_MIN_LEAD_MIN
)
from utils.logger import logger
from utils.stats import to_aware_utc
from utils.game_helpers import upsert_game_from_event
from betting.decision import decide_bet
from watchlist.manager import wl_add
from notifications.telegram import tg_send_message
from utils.formatters import fmt_watch_add


def process_event_decision(
    ev: Any,
    start_utc: datetime,
    url: str,
    session
) -> Tuple[bool, Optional[Any], Optional[str], Optional[float], Optional[float], Optional[str], bool]:
    """
    Processa a decisão de aposta para um evento.
    
    Retorna: (will_bet, pick, pprob, pev, reason, free_pass)
    """
    # Decisão de aposta
    will, pick, pprob, pev, reason = decide_bet(
        ev.odds_home, ev.odds_draw, ev.odds_away,
        ev.competition, (ev.team_home, ev.team_away)
    )
    
    # 🚀 PASSE LIVRE: alta confiança ignora gates normais
    free_pass = (pprob or 0.0) >= HIGH_CONF_THRESHOLD
    if not will and free_pass:
        will = True
        reason = (reason or "Passe livre") + " | HIGH_TRUST"
    
    return will, pick, pprob, pev, reason, free_pass


def check_and_add_to_watchlist(
    ev: Any,
    start_utc: datetime,
    url: str,
    pev: float,
    pprob: float,
    reason: str,
    session,
    notify: bool = True
) -> bool:
    """
    Verifica se o evento deve ser adicionado à watchlist e adiciona se necessário.
    Retorna True se foi adicionado.
    """
    now_utc = datetime.now(pytz.UTC)
    lead_ok = (start_utc - now_utc) >= timedelta(minutes=WATCHLIST_MIN_LEAD_MIN)
    near_cut = (pev >= (MIN_EV - WATCHLIST_DELTA)) and (pev < MIN_EV)
    prob_ok = pprob >= MIN_PROB
    
    if lead_ok and near_cut and prob_ok and not getattr(ev, "is_live", False):
        added = wl_add(session, ev.ext_id, url, start_utc)
        if added:
            logger.info(
                "👀 Adicionado à WATCHLIST: %s vs %s | EV=%.3f | prob=%.3f | start=%s",
                ev.team_home, ev.team_away, pev, pprob, start_utc.isoformat()
            )
            if notify:
                tg_send_message(
                    fmt_watch_add(ev, start_utc.astimezone(ZONE), pev, pprob),
                    message_type="watchlist"
                )
            return True
    return False


def create_game_snapshot(g: Any) -> Dict[str, Any]:
    """Cria um snapshot leve de um Game para resumo."""
    g_start = to_aware_utc(g.start_time)
    return {
        "id": g.id,
        "ext_id": g.ext_id,
        "source_link": g.source_link,
        "competition": g.competition,
        "team_home": g.team_home,
        "team_away": g.team_away,
        "start_time": g_start,
        "odds_home": float(g.odds_home or 0.0),
        "odds_draw": float(g.odds_draw or 0.0),
        "odds_away": float(g.odds_away or 0.0),
        "pick": g.pick,
        "pick_prob": float(g.pick_prob or 0.0),
        "pick_ev": float(g.pick_ev or 0.0),
        "pick_reason": g.pick_reason,
        "will_bet": bool(g.will_bet),
        "status": g.status,
        "outcome": g.outcome,
        "hit": g.hit,
    }


def create_simple_game_snapshot(g: Any) -> Dict[str, Any]:
    """Cria um snapshot simples para resumos noturnos."""
    return {
        "id": g.id,
        "team_home": g.team_home,
        "team_away": g.team_away,
        "start_time": g.start_time,
        "pick": g.pick,
        "odds_home": float(g.odds_home or 0),
        "odds_draw": float(g.odds_draw or 0),
        "odds_away": float(g.odds_away or 0),
        "pick_prob": float(g.pick_prob or 0),
        "pick_ev": float(g.pick_ev or 0),
    }

