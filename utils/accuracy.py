"""Agregação de assertividade por dimensão (país, liga, time, tipo de pick)."""
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import pytz
from sqlalchemy import and_

from models.database import Game


@dataclass
class DimensionStats:
    name: str
    total: int
    hits: int
    misses: int
    accuracy: float
    profit_units: float
    roi_pct: float
    avg_odd: float


def _base_filters(period_days: Optional[int], confidence_min: Optional[float]) -> list:
    """Monta filtros base comuns: pick e hit não-null, period_days e confidence_min."""
    filters = [Game.pick.isnot(None), Game.hit.isnot(None)]
    if period_days is not None:
        cutoff = datetime.now(pytz.UTC) - timedelta(days=period_days)
        filters.append(Game.start_time >= cutoff)
    if confidence_min is not None:
        filters.append(Game.pick_prob >= confidence_min)
    return filters


def _odd_for_pick(game: Game) -> float:
    """Retorna a odd correspondente ao pick do jogo."""
    if game.pick == "home":
        return float(game.odds_home or 0.0)
    if game.pick == "draw":
        return float(game.odds_draw or 0.0)
    if game.pick == "away":
        return float(game.odds_away or 0.0)
    return 0.0


def _build_stats(name: str, rows: List[Tuple[bool, float]]) -> DimensionStats:
    """Constrói DimensionStats a partir de lista de (hit, odd_picked)."""
    total = len(rows)
    if total == 0:
        return DimensionStats(name, 0, 0, 0, 0.0, 0.0, 0.0, 0.0)
    hits = sum(1 for hit, _ in rows if hit)
    misses = total - hits
    profit = sum((odd - 1.0) if hit else -1.0 for hit, odd in rows)
    avg_odd = sum(odd for _, odd in rows) / total
    accuracy = hits / total
    roi_pct = (profit / total) * 100.0
    return DimensionStats(
        name=name,
        total=total,
        hits=hits,
        misses=misses,
        accuracy=accuracy,
        profit_units=profit,
        roi_pct=roi_pct,
        avg_odd=avg_odd,
    )


def _fetch_games(
    session,
    period_days: Optional[int],
    confidence_min: Optional[float],
) -> List[Game]:
    """Busca jogos elegíveis (pick e hit não-null) aplicando filtros opcionais."""
    return (
        session.query(Game)
        .filter(and_(*_base_filters(period_days, confidence_min)))
        .all()
    )


def accuracy_by_country(
    session,
    period_days: Optional[int] = None,
    min_games: int = 1,
    confidence_min: Optional[float] = None,
) -> List[DimensionStats]:
    """Agrega jogos por country. Ordenado por profit_units DESC."""
    buckets: Dict[str, List[Tuple[bool, float]]] = {}
    for g in _fetch_games(session, period_days, confidence_min):
        key = g.country or "Desconhecido"
        buckets.setdefault(key, []).append((bool(g.hit), _odd_for_pick(g)))
    stats = [_build_stats(name, rows) for name, rows in buckets.items()]
    stats = [s for s in stats if s.total >= min_games]
    stats.sort(key=lambda s: s.profit_units, reverse=True)
    return stats


def accuracy_by_competition(
    session,
    period_days: Optional[int] = None,
    min_games: int = 1,
    confidence_min: Optional[float] = None,
) -> List[DimensionStats]:
    """Agrega por competition (liga). Ordenado por profit_units DESC."""
    buckets: Dict[str, List[Tuple[bool, float]]] = {}
    for g in _fetch_games(session, period_days, confidence_min):
        key = g.competition or "Desconhecida"
        buckets.setdefault(key, []).append((bool(g.hit), _odd_for_pick(g)))
    stats = [_build_stats(name, rows) for name, rows in buckets.items()]
    stats = [s for s in stats if s.total >= min_games]
    stats.sort(key=lambda s: s.profit_units, reverse=True)
    return stats


def accuracy_by_team(
    session,
    period_days: Optional[int] = None,
    min_games: int = 1,
    confidence_min: Optional[float] = None,
) -> List[DimensionStats]:
    """Agrega por time (home + away contam 1x cada). Ordenado por profit_units DESC."""
    buckets: Dict[str, List[Tuple[bool, float]]] = {}
    for g in _fetch_games(session, period_days, confidence_min):
        entry = (bool(g.hit), _odd_for_pick(g))
        if g.team_home:
            buckets.setdefault(g.team_home, []).append(entry)
        if g.team_away:
            buckets.setdefault(g.team_away, []).append(entry)
    stats = [_build_stats(name, rows) for name, rows in buckets.items()]
    stats = [s for s in stats if s.total >= min_games]
    stats.sort(key=lambda s: s.profit_units, reverse=True)
    return stats


def accuracy_by_pick_type(
    session,
    period_days: Optional[int] = None,
    confidence_min: Optional[float] = None,
) -> List[DimensionStats]:
    """Agrega por pick type (home/draw/away). Ordenado por pick_type alfabético."""
    buckets: Dict[str, List[Tuple[bool, float]]] = {"home": [], "draw": [], "away": []}
    for g in _fetch_games(session, period_days, confidence_min):
        if g.pick in buckets:
            buckets[g.pick].append((bool(g.hit), _odd_for_pick(g)))
    stats = [_build_stats(name, rows) for name, rows in buckets.items()]
    stats.sort(key=lambda s: s.name)
    return stats
