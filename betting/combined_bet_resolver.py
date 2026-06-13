"""Resolver de máquina de estados de combined_bets.

Resolve combinadas em status='pending' aplicando regras:

| Condição                                          | Transição          | resolution_reason            |
|---------------------------------------------------|--------------------|------------------------------|
| ≥1 pick com outcome != pick                       | pending → lost     | early_miss:game_id=X          |
| Todos picks com outcome == pick                   | pending → won      | all_resolved                  |
| Algum pick sem outcome E idade < TTL              | mantém pending     | —                             |
| Algum pick sem outcome E idade ≥ TTL              | pending → unresolved | ttl_exceeded:games=[...]    |

Estados won/lost/unresolved são TERMINAIS — idempotente: chamadas
subsequentes ignoram esses casos.

Aplica-se a `market='match_result'` (1x2). Handicap asiático já tem
resolver próprio com early-cancel (não tocar).

Uso:
    from betting.combined_bet_resolver import resolve_pending_combined_bets
    with SessionLocal() as session:
        stats = resolve_pending_combined_bets(session)
        # stats = {"won": 1, "lost": 3, "unresolved": 2, "still_pending": 4}
"""
import json
import os
from datetime import datetime, timedelta
from typing import Dict, Optional

import pytz
from sqlalchemy.orm import Session

from models.database import CombinedBet, Game
from utils.logger import logger


# TTL configurável (default 48h). Combinadas pending mais velhas que isso
# com algum jogo sem outcome viram 'unresolved' — saem das métricas
# strict mas continuam visíveis no health check.
RESOLVE_TTL_HOURS = int(os.getenv("COMBINED_BET_RESOLVE_TTL_HOURS", "48"))


def _game_pick_to_outcome_value(pick_value: str) -> Optional[str]:
    """Picks salvos em combined_bets.picks são NOMES dos times (ou 'Empate').
    Mas Game.pick guarda 'home'/'draw'/'away'. Pra comparar com Game.outcome,
    usamos Game.pick (canônico). picks JSON da combined_bet serve só pro display.
    """
    return pick_value  # não precisa transformar — usamos Game.pick direto


def _evaluate_combined_bet(
    bet: CombinedBet,
    games_by_id: Dict[int, Game],
    now_utc: datetime,
) -> Optional[Dict]:
    """Avalia uma combined_bet. Retorna dict de transição ou None se mantém pending."""
    game_ids = bet.game_ids or []
    if not game_ids:
        return {
            "status": "unresolved",
            "hit": None,
            "outcome": {},
            "resolution_reason": "empty_game_ids",
        }

    outcomes_map: Dict[str, str] = {}
    pending_games: list = []
    miss_game_id: Optional[int] = None

    for gid in game_ids:
        g = games_by_id.get(int(gid))
        if g is None:
            pending_games.append(int(gid))
            continue

        # Game.outcome é 'home'|'draw'|'away'|None. Game.pick é o lado que o sistema apostou.
        if g.outcome is None:
            pending_games.append(int(gid))
            continue

        outcomes_map[str(gid)] = g.outcome

        # Comparação: o pick canônico (home/draw/away) tem que casar com o outcome
        if g.pick is None:
            # Game sem pick canônico — não dá pra avaliar essa entrada
            pending_games.append(int(gid))
            continue

        if g.outcome != g.pick:
            # Achou um miss — pode early-resolve como lost
            miss_game_id = int(gid)
            break

    if miss_game_id is not None:
        return {
            "status": "lost",
            "hit": False,
            "outcome": outcomes_map,
            "resolution_reason": f"early_miss:game_id={miss_game_id}",
        }

    if pending_games:
        # Sem miss confirmado, mas tem jogo(s) sem outcome — checa TTL
        bet_date = bet.bet_date
        if bet_date is not None and bet_date.tzinfo is None:
            bet_date = pytz.UTC.localize(bet_date)
        age_hours = (now_utc - bet_date).total_seconds() / 3600 if bet_date else 0
        if age_hours >= RESOLVE_TTL_HOURS:
            return {
                "status": "unresolved",
                "hit": None,
                "outcome": outcomes_map,
                "resolution_reason": f"ttl_exceeded:games={pending_games}",
            }
        return None  # ainda dentro da janela — mantém pending

    # Sem miss + sem pending → todos hit
    return {
        "status": "won",
        "hit": True,
        "outcome": outcomes_map,
        "resolution_reason": "all_resolved",
    }


def resolve_pending_combined_bets(session: Session) -> Dict[str, int]:
    """Resolve todas as combined_bets de market='match_result' em status='pending'.

    Idempotente: só age em status='pending'. Estados won/lost/unresolved são terminais.

    Retorna dict com contagens:
        {"won": int, "lost": int, "unresolved": int, "still_pending": int, "skipped": int}
    """
    now_utc = datetime.now(pytz.UTC)
    stats = {"won": 0, "lost": 0, "unresolved": 0, "still_pending": 0, "skipped": 0}

    pending_bets = session.query(CombinedBet).filter(
        CombinedBet.status == "pending",
        CombinedBet.market == "match_result",
    ).all()

    if not pending_bets:
        return stats

    # Carrega todos os games envolvidos numa só query
    all_game_ids = set()
    for bet in pending_bets:
        for gid in (bet.game_ids or []):
            try:
                all_game_ids.add(int(gid))
            except (TypeError, ValueError):
                continue

    if not all_game_ids:
        return stats

    games = session.query(Game).filter(Game.id.in_(all_game_ids)).all()
    games_by_id = {g.id: g for g in games}

    for bet in pending_bets:
        try:
            transition = _evaluate_combined_bet(bet, games_by_id, now_utc)
            if transition is None:
                stats["still_pending"] += 1
                continue

            bet.status = transition["status"]
            bet.hit = transition["hit"]
            bet.outcome = transition["outcome"]
            bet.resolution_reason = transition["resolution_reason"]
            bet.resolved_at = now_utc
            stats[transition["status"]] += 1

            logger.info(
                "🎯 combined_bet #%d → %s (%s)",
                bet.id, transition["status"], transition["resolution_reason"],
            )
        except Exception:
            logger.exception("Falha ao resolver combined_bet #%d", bet.id)
            stats["skipped"] += 1

    try:
        session.commit()
    except Exception:
        logger.exception("Falha no commit do resolver de combined_bets")
        session.rollback()
        return stats

    if any(stats[k] > 0 for k in ("won", "lost", "unresolved")):
        logger.info(
            "✅ Resolver combined_bets: won=%d lost=%d unresolved=%d still_pending=%d skipped=%d",
            stats["won"], stats["lost"], stats["unresolved"],
            stats["still_pending"], stats["skipped"],
        )

    return stats
