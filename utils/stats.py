"""Estatísticas e performance."""
from datetime import datetime, timedelta
from typing import Any, Dict
import pytz
from models.database import Game, SessionLocal
from config.settings import ZONE


def global_accuracy(session) -> float:
    """Calcula a taxa de acerto global."""
    total = session.query(Game).filter(Game.hit.isnot(None)).count()
    if total == 0:
        return 0.0
    hits = session.query(Game).filter(Game.hit.is_(True)).count()
    return hits / total


def get_weekly_stats(session) -> Dict[str, Any]:
    """Retorna estatísticas dos últimos 7 dias."""
    week_ago = datetime.now(pytz.UTC) - timedelta(days=7)
    games = session.query(Game).filter(
        Game.start_time >= week_ago,
        Game.hit.isnot(None)
    ).all()
    
    if not games:
        return {}
    
    hits = sum(1 for g in games if g.hit)
    total = len(games)
    return {
        'total': total,
        'hits': hits,
        'win_rate': (hits / total * 100) if total > 0 else 0,
        'roi': ((hits * 2 - total) / total * 100) if total > 0 else 0
    }


def get_monthly_stats(session) -> Dict[str, Any]:
    """Retorna estatísticas do mês atual."""
    now = datetime.now(ZONE)
    month_start = ZONE.localize(datetime(now.year, now.month, 1)).astimezone(pytz.UTC)
    games = session.query(Game).filter(
        Game.start_time >= month_start,
        Game.hit.isnot(None)
    ).all()
    
    if not games:
        return {}
    
    hits = sum(1 for g in games if g.hit)
    total = len(games)
    return {
        'total': total,
        'hits': hits,
        'win_rate': (hits / total * 100) if total > 0 else 0
    }


def to_aware_utc(dt: datetime | None) -> datetime | None:
    """Converte datetime para UTC aware."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return pytz.UTC.localize(dt)
    return dt.astimezone(pytz.UTC)


def get_lifetime_accuracy(session) -> Dict[str, Any]:
    """
    Calcula assertividade lifetime (histórico completo).
    Retorna estatísticas detalhadas de todos os tempos.
    """
    # Todos os jogos com resultado verificado
    all_games = session.query(Game).filter(
        Game.hit.isnot(None),
        Game.status == "ended"
    ).all()
    
    if not all_games:
        return {
            'total': 0,
            'hits': 0,
            'misses': 0,
            'accuracy': 0.0,
            'accuracy_percent': 0.0,
            'roi': 0.0
        }
    
    total = len(all_games)
    hits = sum(1 for g in all_games if g.hit is True)
    misses = total - hits
    accuracy = hits / total if total > 0 else 0.0
    
    # ROI estimado (assumindo aposta de 1 unidade por jogo)
    # ROI = (acertos * odd_media - total) / total
    total_odds = 0.0
    hits_with_odds = 0
    for g in all_games:
        if g.hit:
            pick_odd = None
            if g.pick == "home":
                pick_odd = g.odds_home
            elif g.pick == "draw":
                pick_odd = g.odds_draw
            elif g.pick == "away":
                pick_odd = g.odds_away
            
            if pick_odd:
                total_odds += pick_odd
                hits_with_odds += 1
    
    avg_odd = total_odds / hits_with_odds if hits_with_odds > 0 else 0.0
    roi = ((hits * avg_odd - total) / total * 100) if total > 0 and avg_odd > 0 else 0.0
    
    return {
        'total': total,
        'hits': hits,
        'misses': misses,
        'accuracy': accuracy,
        'accuracy_percent': accuracy * 100,
        'average_odd': avg_odd,
        'roi': roi
    }


def get_daily_summary(session, date_local: datetime = None) -> Dict[str, Any]:
    """
    Retorna resumo de todos os jogos finalizados de um dia específico.
    Se date_local não for fornecido, usa o dia atual.
    """
    if date_local is None:
        date_local = datetime.now(ZONE)
    
    day_start = ZONE.localize(datetime(date_local.year, date_local.month, date_local.day, 0, 0)).astimezone(pytz.UTC)
    day_end = ZONE.localize(datetime(date_local.year, date_local.month, date_local.day, 23, 59, 59)).astimezone(pytz.UTC)
    
    games = session.query(Game).filter(
        Game.start_time >= day_start,
        Game.start_time <= day_end,
        Game.status == "ended"
    ).order_by(Game.start_time).all()
    
    # Separa jogos com resultado verificado dos não verificados
    verified_games = [g for g in games if g.hit is not None]
    unverified_games = [g for g in games if g.hit is None]
    
    hits = sum(1 for g in verified_games if g.hit is True)
    misses = len(verified_games) - hits
    
    return {
        'date': date_local.date(),
        'total_games': len(games),
        'verified_games': len(verified_games),
        'unverified_games': len(unverified_games),
        'hits': hits,
        'misses': misses,
        'accuracy': (hits / len(verified_games) * 100) if verified_games else 0.0,
        'games': verified_games,
        'unverified': unverified_games
    }


def get_accuracy_by_confidence(session) -> Dict[str, Any]:
    """
    Calcula assertividade segmentada por nível de confiança.
    
    Retorna estatísticas separadas para:
    - Alta confiança (pick_prob >= 0.60)
    - Média confiança (0.40 <= pick_prob < 0.60)
    - Baixa confiança (pick_prob < 0.40)
    
    Returns:
        Dict com estatísticas por nível de confiança
    """
    from config.settings import HIGH_CONF_THRESHOLD
    
    # Todos os jogos com resultado verificado
    all_games = session.query(Game).filter(
        Game.hit.isnot(None),
        Game.status == "ended",
        Game.pick_prob.isnot(None)
    ).all()
    
    if not all_games:
        return {
            'high': {'total': 0, 'hits': 0, 'accuracy': 0.0, 'accuracy_percent': 0.0},
            'medium': {'total': 0, 'hits': 0, 'accuracy': 0.0, 'accuracy_percent': 0.0},
            'low': {'total': 0, 'hits': 0, 'accuracy': 0.0, 'accuracy_percent': 0.0}
        }
    
    # Separa por nível de confiança
    high_conf_games = []
    medium_conf_games = []
    low_conf_games = []
    
    for game in all_games:
        prob = game.pick_prob or 0.0
        if prob >= HIGH_CONF_THRESHOLD:
            high_conf_games.append(game)
        elif prob >= 0.40:
            medium_conf_games.append(game)
        else:
            low_conf_games.append(game)
    
    def calc_accuracy(games):
        if not games:
            return {'total': 0, 'hits': 0, 'accuracy': 0.0, 'accuracy_percent': 0.0}
        total = len(games)
        hits = sum(1 for g in games if g.hit is True)
        accuracy = hits / total if total > 0 else 0.0
        return {
            'total': total,
            'hits': hits,
            'misses': total - hits,
            'accuracy': accuracy,
            'accuracy_percent': accuracy * 100
        }
    
    return {
        'high': calc_accuracy(high_conf_games),
        'medium': calc_accuracy(medium_conf_games),
        'low': calc_accuracy(low_conf_games)
    }


def save_odd_history(session, game) -> bool:
    """Salva histórico de odds para um jogo."""
    from models.database import OddHistory
    from utils.logger import logger
    
    if not game or not game.id:
        return False
    
    try:
        odd_hist = OddHistory(
            game_id=game.id,
            ext_id=game.ext_id,
            odds_home=game.odds_home,
            odds_draw=game.odds_draw,
            odds_away=game.odds_away,
        )
        session.add(odd_hist)
        session.commit()
        return True
    except Exception as e:
        logger.warning(f"Falha ao salvar histórico de odds para jogo {game.id}: {e}")
        session.rollback()
        return False

