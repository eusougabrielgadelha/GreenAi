"""Resolve outcome and hit for all picks of a finished game."""
import math
from datetime import datetime
from typing import List, Optional
import pytz
from models.database import Game, Pick


def resolve_handicap_asian(pick, home_goals: int, away_goals: int) -> dict:
    """
    Resolve handicap asiático dado um pick e o placar final.

    Args:
        pick: instância de Pick com market='handicap_asian', line=float, pick=str ('home'|'away')
        home_goals: int — gols home
        away_goals: int — gols away

    Returns:
        dict: {'outcome': 'win'|'lose'|'push'|'half_win'|'half_lose'|'void',
               'hit': True|False|None,
               'payout': float}

        payout em unidades de stake:
          1.0    = ganhou stake × odd (resultado normal de win)
          0.0    = perdeu
          1/odd  = push (devolveu stake)
        Em quarter line: média entre as duas metades.
    """
    line = getattr(pick, "line", None)
    side = getattr(pick, "pick", None)

    if line is None or side not in ("home", "away"):
        return {"outcome": "void", "hit": None, "payout": 0.0}

    line = float(line)
    # diff: a partir do lado apostado
    diff = (home_goals - away_goals) if side == "home" else (away_goals - home_goals)
    adjusted = diff + line

    # Quarter line (.25, .75): split em 2 metades
    line_x2 = line * 2.0
    if abs(line_x2 - round(line_x2)) > 1e-9:
        line_low = math.floor(line_x2) / 2.0
        line_high = math.ceil(line_x2) / 2.0

        class _PseudoPick:
            def __init__(self, ln, sd, odd):
                self.line = ln
                self.pick = sd
                self.market = "handicap_asian"
                self.pick_odd = odd

        odd_attr = getattr(pick, "pick_odd", None) or 1.0
        r1 = resolve_handicap_asian(_PseudoPick(line_low, side, odd_attr), home_goals, away_goals)
        r2 = resolve_handicap_asian(_PseudoPick(line_high, side, odd_attr), home_goals, away_goals)
        avg_payout = (r1["payout"] + r2["payout"]) / 2.0

        if avg_payout > 1.0 + 1e-9:
            outcome = "half_win"
            hit = True
        elif avg_payout < 1.0 - 1e-9:
            if avg_payout > 1e-9:
                outcome = "half_lose"
                hit = False
            else:
                outcome = "lose"
                hit = False
        else:
            outcome = "push"
            hit = None
        return {"outcome": outcome, "hit": hit, "payout": avg_payout}

    # Linha .5 ou .0 (inteira)
    if adjusted > 1e-9:
        return {"outcome": "win", "hit": True, "payout": 1.0}
    elif adjusted < -1e-9:
        return {"outcome": "lose", "hit": False, "payout": 0.0}
    else:
        odd_val = float(getattr(pick, "pick_odd", None) or 1.0)
        if odd_val <= 0:
            odd_val = 1.0
        return {"outcome": "push", "hit": None, "payout": 1.0 / odd_val}


def resolve_picks_for_game(session, game: Game) -> List[Pick]:
    """Resolve outcome/hit for every Pick attached to a finished Game.

    Returns [] if final scores are missing. Flushes session at the end
    (caller decides when to commit).
    """
    if game.final_score_home is None or game.final_score_away is None:
        return []

    home = int(game.final_score_home)
    away = int(game.final_score_away)
    total = home + away

    # Infer 1x2 outcome from scores if not already set on game
    if game.outcome:
        inferred_outcome = game.outcome
    else:
        if home > away:
            inferred_outcome = "home"
        elif away > home:
            inferred_outcome = "away"
        else:
            inferred_outcome = "draw"

    now = datetime.now(pytz.UTC)
    resolved: List[Pick] = []

    for pick in game.picks:
        if pick.market == "match_result":
            pick.outcome = inferred_outcome
            pick.hit = (pick.outcome == pick.pick) if pick.pick else None

        elif pick.market == "total_goals":
            if pick.line is None:
                pick.outcome = None
                pick.hit = None
            else:
                line = float(pick.line)
                # Integer line (.0) can push (void); fractional line (.5) cannot
                if abs(line - round(line)) < 1e-9:
                    line_int = int(round(line))
                    if total == line_int:
                        pick.outcome = "void"
                        pick.hit = None
                    elif total > line_int:
                        pick.outcome = "over"
                        pick.hit = (pick.pick == "over")
                    else:
                        pick.outcome = "under"
                        pick.hit = (pick.pick == "under")
                else:
                    if total > line:
                        pick.outcome = "over"
                        pick.hit = (pick.pick == "over")
                    else:
                        pick.outcome = "under"
                        pick.hit = (pick.pick == "under")

        elif pick.market == "handicap_asian":
            if pick.line is None or pick.pick not in ("home", "away"):
                pick.outcome = "void"
                pick.hit = None
            else:
                res = resolve_handicap_asian(pick, home, away)
                pick.outcome = res["outcome"]
                pick.hit = res["hit"]

        else:
            # Unknown market: skip without marking verified
            continue

        pick.result_verified_at = now
        resolved.append(pick)

    session.flush()
    return resolved


def get_match_result_pick(game: Game) -> Optional[Pick]:
    """Return the match_result Pick of a Game (or None)."""
    for p in game.picks:
        if p.market == "match_result":
            return p
    return None
