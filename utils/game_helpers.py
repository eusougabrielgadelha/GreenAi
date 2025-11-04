"""Funções auxiliares para gerenciamento de jogos."""
from typing import Any, Optional, TYPE_CHECKING
from sqlalchemy.exc import IntegrityError

if TYPE_CHECKING:
    from models.database import Game
else:
    # Importação real para uso em runtime (evita import circular)
    from models.database import Game

from config.settings import (
    is_high_conf as is_high_conf_config,
    was_high_conf_notified as was_high_conf_notified_config,
    mark_high_conf_notified as mark_high_conf_notified_config
)


def upsert_game_from_event(
    session,
    ev: Any,
    start_utc,
    url: str,
    pick: str,
    pprob: float,
    pev: float,
    reason: str,
    will: bool,
    status: str = "scheduled"
) -> Optional["Game"]:
    """
    Função helper para UPSERT de jogos.
    Retorna o Game criado/atualizado ou None em caso de erro.
    """
    g = session.query(Game).filter_by(ext_id=ev.ext_id, start_time=start_utc).one_or_none()
    
    if g:
        # Update existente
        g.source_link = url
        g.game_url = getattr(ev, "game_url", None) or g.game_url
        g.competition = ev.competition or g.competition
        g.team_home = ev.team_home or g.team_home
        g.team_away = ev.team_away or g.team_away
        g.odds_home = ev.odds_home
        g.odds_draw = ev.odds_draw
        g.odds_away = ev.odds_away
        g.pick = pick
        g.pick_prob = pprob
        g.pick_ev = pev
        g.pick_reason = reason
        g.will_bet = will
        # Preserva status existente se já for "live" ou "ended", senão usa o novo
        if g.status in ("live", "ended"):
            pass  # mantém
        else:
            g.status = status
        session.commit()
    else:
        # Create novo
        g = Game(
            ext_id=ev.ext_id,
            source_link=url,
            game_url=getattr(ev, "game_url", None),
            competition=ev.competition,
            team_home=ev.team_home,
            team_away=ev.team_away,
            start_time=start_utc,
            odds_home=ev.odds_home,
            odds_draw=ev.odds_draw,
            odds_away=ev.odds_away,
            pick=pick,
            pick_prob=pprob,
            pick_ev=pev,
            will_bet=will,
            pick_reason=reason,
            status=status,
        )
        session.add(g)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            # Retry: busca o que foi inserido por outra thread
            g = session.query(Game).filter_by(ext_id=ev.ext_id, start_time=start_utc).one_or_none()
            if g:
                g.source_link = url
                g.game_url = getattr(ev, "game_url", None) or g.game_url
                g.competition = ev.competition or g.competition
                g.team_home = ev.team_home or g.team_home
                g.team_away = ev.team_away or g.team_away
                g.odds_home = ev.odds_home
                g.odds_draw = ev.odds_draw
                g.odds_away = ev.odds_away
                g.pick = pick
                g.pick_prob = pprob
                g.pick_ev = pev
                g.pick_reason = reason
                g.will_bet = will
                if g.status in ("live", "ended"):
                    pass  # mantém
                else:
                    g.status = status
                session.commit()
            else:
                return None
    
    session.refresh(g)
    return g


def is_high_conf(game: Game) -> bool:
    """Alta confiança baseada em pick_prob (fallback para campos legados)."""
    val = (
        getattr(game, "pick_prob", None)
        or getattr(game, "pick_confidence", None)
        or getattr(game, "confidence", None)
        or 0.0
    )
    return is_high_conf_config(val)


def was_high_conf_notified(game: Game) -> bool:
    """Verifica se jogo já foi notificado."""
    return was_high_conf_notified_config(game.pick_reason or "")


def mark_high_conf_notified(game: Game) -> None:
    """Marca jogo como notificado."""
    game.pick_reason = mark_high_conf_notified_config(game.pick_reason or "")

