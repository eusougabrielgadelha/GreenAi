"""Resolve outcome and hit for all picks of a finished game."""
from datetime import datetime
from typing import List, Optional
import pytz
from models.database import Game, Pick


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
