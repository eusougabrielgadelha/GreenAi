"""Cálculo de Kelly e gerenciamento de stake."""
from typing import Tuple


def kelly_fraction(p: float, odd: float) -> float:
    """
    Kelly puro: f* = (bp - q)/b, onde b=odd-1, q=1-p.
    Retorna 0 se não houver edge.
    """
    if odd is None or odd <= 1.0 or p is None or p <= 0 or p >= 1:
        return 0.0
    b = odd - 1.0
    q = 1.0 - p
    f = (b * p - q) / b
    return max(0.0, f)


def suggest_stake_and_return(p: float, odd: float, bankroll: float, kelly_frac: float) -> Tuple[float, float]:
    """
    Aplica Kelly fracionado: stake = bankroll * kelly_fraction(p, odd) * kelly_frac
    Retorna (stake, lucro_potencial)
    """
    f_star = kelly_fraction(p, odd)
    stake = bankroll * f_star * max(0.0, min(1.0, kelly_frac))
    stake = round(stake, 2)
    potential_profit = round(stake * (odd - 1.0), 2)
    return stake, potential_profit

