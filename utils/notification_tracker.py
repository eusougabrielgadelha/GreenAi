"""
Sistema de rastreamento de notificações no banco de dados.
Garante que jogos já notificados não sejam notificados novamente, mesmo após reiniciar o script.
"""
from datetime import datetime
from typing import Optional
import pytz
from models.database import Game, Pick, SessionLocal
from utils.logger import logger


def _is_pick(obj) -> bool:
    """Detecta se o objeto é um Pick (multi-market) vs Game (legacy)."""
    return isinstance(obj, Pick) or (hasattr(obj, "market") and hasattr(obj, "notified_at"))


def was_pick_notified(game: Game) -> bool:
    """
    Verifica se o palpite de um jogo já foi notificado.
    
    Args:
        game: Instância do Game
        
    Returns:
        True se já foi notificado, False caso contrário
    """
    return game.pick_notified_at is not None


def mark_pick_notified(obj, session=None):
    """
    Marca um pick/jogo como tendo sido notificado.

    Polimórfico:
      - Se `obj` é um Pick: seta `pick.notified_at = now(UTC)`. Se
        `pick.market == 'match_result'`, espelha em `game.pick_notified_at`
        pra retrocompat. Faz `session.flush()` (caller controla commit).
        Não retorna nada — segue contrato do PR.
      - Se `obj` é um Game (legacy): seta `game.pick_notified_at` e comita
        (preserva comportamento original dos callers existentes).

    Args:
        obj: Instância de Pick (novo) ou Game (legacy)
        session: Sessão do banco (opcional pro path Game, requerido pro Pick)
    """
    now_utc = datetime.now(pytz.UTC)

    # ---------- Path NOVO: Pick ----------
    if _is_pick(obj):
        pick = obj
        try:
            if pick.notified_at is not None:
                # Idempotência: já notificado, não faz nada
                return
            pick.notified_at = now_utc

            # Espelha em Game.pick_notified_at quando for match_result (retrocompat)
            if pick.market == "match_result":
                game = getattr(pick, "game", None)
                if game is not None and game.pick_notified_at is None:
                    game.pick_notified_at = now_utc

            if session is not None:
                session.flush()
            logger.debug(
                f"Pick {pick.id} (game_id={pick.game_id}, market={pick.market}) marcado como notificado em {now_utc}"
            )
            return
        except Exception as e:
            logger.exception(f"Erro ao marcar pick {getattr(pick, 'id', '?')} como notificado: {e}")
            return

    # ---------- Path LEGACY: Game ----------
    game = obj
    try:
        if game.pick_notified_at is not None:
            # Já foi notificado, não precisa fazer nada
            return True

        game.pick_notified_at = now_utc

        if session:
            session.commit()
        else:
            with SessionLocal() as sess:
                sess.add(game)
                sess.commit()

        logger.debug(f"Jogo {game.id} ({game.ext_id}) marcado como notificado em {game.pick_notified_at}")
        return True
    except Exception as e:
        logger.exception(f"Erro ao marcar jogo {game.id} como notificado: {e}")
        return False


def get_notified_games_for_date(date: datetime, session=None) -> list:
    """
    Busca todos os jogos que foram notificados em uma determinada data.
    
    Args:
        date: Data para buscar (timezone-aware)
        session: Sessão do banco (opcional)
        
    Returns:
        Lista de jogos que foram notificados na data
    """
    try:
        # Normalizar data para início e fim do dia
        date_start = date.replace(hour=0, minute=0, second=0, microsecond=0)
        date_end = date.replace(hour=23, minute=59, second=59, microsecond=999999)
        
        if session:
            games = session.query(Game).filter(
                Game.pick_notified_at >= date_start,
                Game.pick_notified_at <= date_end,
                Game.will_bet.is_(True)
            ).all()
            return games
        else:
            with SessionLocal() as sess:
                games = sess.query(Game).filter(
                    Game.pick_notified_at >= date_start,
                    Game.pick_notified_at <= date_end,
                    Game.will_bet.is_(True)
                ).all()
                return games
    except Exception as e:
        logger.exception(f"Erro ao buscar jogos notificados para data {date}: {e}")
        return []


def should_notify_pick(obj, check_high_conf: bool = True) -> tuple[bool, str]:
    """
    Decide se um pick/jogo deve ser notificado.

    Polimórfico:
      - Pick (novo): checa `will_bet=True`, `notified_at is None`, `outcome is None`.
        Não checa cooldown/horário — quem chama decide.
      - Game (legacy): mantém comportamento original (will_bet, pick, threshold).

    Args:
        obj: Pick ou Game
        check_high_conf: Aplica somente ao path Game (legacy)

    Returns:
        Tuple (should_notify: bool, reason: str)
    """
    # ---------- Path NOVO: Pick ----------
    if _is_pick(obj):
        pick = obj
        if not pick.will_bet:
            return False, "Pick não tem will_bet=True"
        if pick.notified_at is not None:
            return False, "Pick já foi notificado anteriormente"
        if pick.outcome is not None:
            return False, "Pick já tem outcome (jogo terminou)"
        if check_high_conf:
            from config.settings import HIGH_CONF_THRESHOLD
            if pick.pick_prob is None or pick.pick_prob < HIGH_CONF_THRESHOLD:
                return False, f"Probabilidade {pick.pick_prob} abaixo do threshold {HIGH_CONF_THRESHOLD}"
        return True, ""

    # ---------- Path LEGACY: Game ----------
    game = obj
    # 1. Verificar se já foi notificado
    if was_pick_notified(game):
        return False, "Já foi notificado anteriormente"

    # 2. Verificar se tem palpite
    if not game.pick:
        return False, "Jogo não tem palpite definido"

    # 3. Verificar se foi selecionado para aposta
    if not game.will_bet:
        return False, "Jogo não foi selecionado para aposta (will_bet=False)"

    # 4. Verificar alta confiança se solicitado
    if check_high_conf:
        from config.settings import HIGH_CONF_THRESHOLD
        if (game.pick_prob or 0.0) < HIGH_CONF_THRESHOLD:
            return False, f"Probabilidade abaixo do threshold ({game.pick_prob or 0.0:.3f} < {HIGH_CONF_THRESHOLD})"

    return True, "OK para notificar"


def get_notified_games_count(session=None) -> int:
    """
    Retorna o número total de jogos que foram notificados.
    
    Args:
        session: Sessão do banco (opcional)
        
    Returns:
        Número de jogos notificados
    """
    try:
        if session:
            count = session.query(Game).filter(Game.pick_notified_at.isnot(None)).count()
            return count
        else:
            with SessionLocal() as sess:
                count = sess.query(Game).filter(Game.pick_notified_at.isnot(None)).count()
                return count
    except Exception as e:
        logger.exception(f"Erro ao contar jogos notificados: {e}")
        return 0

