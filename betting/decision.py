"""Lógica de decisão de apostas."""
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, List, Optional
import pytz
from models.database import SessionLocal, OddHistory, Pick
from config.settings import (
    MIN_EV, MIN_PROB, FAV_MODE, FAV_PROB_MIN, FAV_GAP_MIN, EV_TOL, FAV_IGNORE_EV,
    HIGH_ODD_MODE, HIGH_ODD_MIN, HIGH_ODD_MAX_PROB, HIGH_ODD_MIN_EV
)


_TOTAL_GOALS_LINE_RE = re.compile(r'^(Mais|Menos)\s+de\s+(\d+(?:\.\d+)?)$', re.IGNORECASE)


def _normalize_odd_value(val) -> float:
    """Aceita float direto ou dict {'odd': float, ...}. Retorna 0.0 se inválido."""
    if isinstance(val, (int, float)):
        try:
            return float(val)
        except Exception:
            return 0.0
    if isinstance(val, dict):
        try:
            return float(val.get("odd", 0.0) or 0.0)
        except Exception:
            return 0.0
    return 0.0


def _extract_total_goals_lines(market_dict: dict) -> dict:
    """
    Extrai linhas completas (com Mais E Menos) do mercado total_goals.
    Retorna: {0.5: {"over": 1.02, "under": 10.0}, 1.5: {...}, ...}
    Descarta linhas com par incompleto (só Mais ou só Menos).
    Normaliza valor das options (aceita float direto OU dict {"odd": float}).
    Aceita 'Mais de X.X' / 'Menos de X.X' (case-insensitive, com tolerância de espaços).
    Se o mercado for None ou options vazio, retorna {}.
    """
    if not market_dict or not isinstance(market_dict, dict):
        return {}
    options = market_dict.get("options") or {}
    if not isinstance(options, dict) or not options:
        return {}

    partial: dict = {}
    for key, raw_val in options.items():
        if not isinstance(key, str):
            continue
        m = _TOTAL_GOALS_LINE_RE.match(key.strip())
        if not m:
            continue
        side_raw = m.group(1).lower()
        try:
            line = float(m.group(2))
        except Exception:
            continue
        odd = _normalize_odd_value(raw_val)
        if odd <= 0:
            continue
        side = "over" if side_raw == "mais" else "under"
        partial.setdefault(line, {})[side] = odd

    return {line: sides for line, sides in partial.items() if "over" in sides and "under" in sides}


@dataclass
class PickResult:
    market: str
    line: Optional[float] = None
    will_bet: bool = False
    pick: str = ""
    pick_prob: float = 0.0
    pick_ev: float = 0.0
    pick_odd: float = 0.0
    reason: str = ""
    metadata: dict = field(default_factory=dict)


def decide_match_result(
    odds_home: float,
    odds_draw: float,
    odds_away: float,
    *,
    game_id: Optional[int] = None,
    competition: Optional[str] = None,
    teams: Optional[tuple] = None,
) -> PickResult:
    """
    Decisão de aposta no mercado Resultado Final (1x2) com EV ajustado por movimento de odds.
    """
    from utils.analytics_logger import log_calculation, log_decision, log_signal_suppression, log_signal_sent

    MIN_ODD = 1.01

    names = ("home", "draw", "away")
    odds = (float(odds_home or 0.0), float(odds_draw or 0.0), float(odds_away or 0.0))
    avail = [(n, o) for n, o in zip(names, odds) if o >= MIN_ODD]
    if len(avail) < 2:
        reason = "Odds insuficientes (menos de 2 mercados)"
        log_decision(None, False, "", 0.0, 0.0, reason, game_id=game_id, suppressed=True, suppression_reason=reason)
        return PickResult(
            market="match_result",
            line=None,
            will_bet=False,
            pick="",
            pick_prob=0.0,
            pick_ev=0.0,
            pick_odd=0.0,
            reason=reason,
            metadata={"strategy": None, "failure": "insufficient_odds"},
        )

    inv = [(n, 1.0 / o) for n, o in avail]
    tot = sum(v for _, v in inv)
    if tot <= 0:
        reason = "Probabilidades inválidas"
        log_decision(None, False, "", 0.0, 0.0, reason, game_id=game_id, suppressed=True, suppression_reason=reason)
        return PickResult(
            market="match_result",
            line=None,
            will_bet=False,
            pick="",
            pick_prob=0.0,
            pick_ev=0.0,
            pick_odd=0.0,
            reason=reason,
            metadata={"strategy": None, "failure": "invalid_probabilities"},
        )

    true = {n: v / tot for n, v in inv}
    odd_map = dict(avail)
    ev_map = {n: true[n] * odd_map[n] - 1.0 for n in true}

    adjusted_ev_map = ev_map.copy()
    odd_movement_used = False
    if game_id:
        with SessionLocal() as session:
            one_hour_ago = datetime.now(pytz.UTC) - timedelta(hours=1)
            old_odd = session.query(OddHistory).filter(
                OddHistory.game_id == game_id,
                OddHistory.timestamp <= one_hour_ago
            ).order_by(OddHistory.timestamp.desc()).first()

            if old_odd:
                odd_movement_used = True
                for market in ["home", "draw", "away"]:
                    current_odd = odd_map.get(market, 0.0)
                    old_odd_val = getattr(old_odd, f"odds_{market}", 0.0)
                    if old_odd_val > 0 and current_odd > 0:
                        variation = (current_odd - old_odd_val) / old_odd_val
                        adjustment = -variation * 0.5
                        adjusted_ev_map[market] += adjustment

    alternatives = {
        n: {
            "prob": true[n],
            "ev": adjusted_ev_map[n],
            "odd": odd_map[n],
        }
        for n in true
    }

    # 1) EV positivo ajustado
    pick_ev, best_ev = max(adjusted_ev_map.items(), key=lambda x: x[1])
    pprob_ev = true[pick_ev]
    ev_original_best = ev_map[pick_ev]

    log_calculation(
        None, odds[0], odds[1], odds[2], pick_ev, pprob_ev, best_ev,
        strategy="EV positivo (ajustado)",
        game_id=game_id,
        metadata={"competition": competition, "teams": teams}
    )

    if best_ev >= MIN_EV and pprob_ev >= MIN_PROB:
        reason = "EV positivo (ajustado por movimento de odds)"
        log_decision(None, True, pick_ev, pprob_ev, best_ev, reason, game_id=game_id)
        log_signal_sent(None, reason, pick_ev, pprob_ev, best_ev, game_id=game_id)
        return PickResult(
            market="match_result",
            line=None,
            will_bet=True,
            pick=pick_ev,
            pick_prob=pprob_ev,
            pick_ev=best_ev,
            pick_odd=odd_map[pick_ev],
            reason=reason,
            metadata={
                "strategy": "ev_positive_adjusted",
                "ev_original": ev_original_best,
                "ev_adjusted": best_ev,
                "odd_movement_used": odd_movement_used,
                "alternatives": alternatives,
            },
        )

    # 2) Favorito claro
    if FAV_MODE == "on":
        probs_sorted = sorted(true.items(), key=lambda x: x[1], reverse=True)
        (pick_fav, p1), (_, p2) = probs_sorted[0], probs_sorted[1]
        ev_fav = adjusted_ev_map.get(pick_fav, 0.0)
        gap_ok = (p1 - p2) >= FAV_GAP_MIN
        prob_ok = p1 >= max(MIN_PROB, FAV_PROB_MIN, 0.40)
        ev_ok = (ev_fav >= EV_TOL) or FAV_IGNORE_EV
        if prob_ok and gap_ok and ev_ok:
            reason = "Favorito claro (probabilidade)" if FAV_IGNORE_EV else "Favorito claro (regra híbrida)"
            log_decision(None, True, pick_fav, p1, ev_fav, reason, game_id=game_id)
            log_signal_sent(None, reason, pick_fav, p1, ev_fav, game_id=game_id)
            return PickResult(
                market="match_result",
                line=None,
                will_bet=True,
                pick=pick_fav,
                pick_prob=p1,
                pick_ev=ev_fav,
                pick_odd=odd_map[pick_fav],
                reason=reason,
                metadata={
                    "strategy": "favorito_claro",
                    "ev_original": ev_map.get(pick_fav, 0.0),
                    "ev_adjusted": ev_fav,
                    "odd_movement_used": odd_movement_used,
                    "alternatives": alternatives,
                },
            )

    # 3) High Odd
    if HIGH_ODD_MODE == "on":
        ev_sorted = sorted(adjusted_ev_map.items(), key=lambda x: x[1], reverse=True)
        for pick_high, ev_high in ev_sorted:
            odd_high = odd_map[pick_high]
            prob_high = true[pick_high]

            if (odd_high >= HIGH_ODD_MIN) and (prob_high <= HIGH_ODD_MAX_PROB) and (ev_high >= HIGH_ODD_MIN_EV):
                reason = f"Maior Potencial de Ganho (Odd: {odd_high:.2f}, EV Ajustado: {ev_high*100:.1f}%)"
                log_decision(None, True, pick_high, prob_high, ev_high, reason, game_id=game_id)
                log_signal_sent(None, reason, pick_high, prob_high, ev_high, game_id=game_id)
                return PickResult(
                    market="match_result",
                    line=None,
                    will_bet=True,
                    pick=pick_high,
                    pick_prob=prob_high,
                    pick_ev=ev_high,
                    pick_odd=odd_high,
                    reason=reason,
                    metadata={
                        "strategy": "high_odd",
                        "ev_original": ev_map.get(pick_high, 0.0),
                        "ev_adjusted": ev_high,
                        "odd_movement_used": odd_movement_used,
                        "alternatives": alternatives,
                    },
                )

    # 4) Prob > 50%
    if pprob_ev > 0.50:
        reason = "Favorito claro (probabilidade > 50%)"
        log_decision(None, True, pick_ev, pprob_ev, best_ev, reason, game_id=game_id)
        log_signal_sent(None, reason, pick_ev, pprob_ev, best_ev, game_id=game_id)
        return PickResult(
            market="match_result",
            line=None,
            will_bet=True,
            pick=pick_ev,
            pick_prob=pprob_ev,
            pick_ev=best_ev,
            pick_odd=odd_map[pick_ev],
            reason=reason,
            metadata={
                "strategy": "prob_gt_50",
                "ev_original": ev_original_best,
                "ev_adjusted": best_ev,
                "odd_movement_used": odd_movement_used,
                "alternatives": alternatives,
            },
        )

    # 5) Prob >= 40% com EV >= -8%
    if pprob_ev >= 0.40:
        if best_ev >= -0.08:
            reason = "Alta confiança (probabilidade > 40%)"
            log_decision(None, True, pick_ev, pprob_ev, best_ev, reason, game_id=game_id)
            log_signal_sent(None, reason, pick_ev, pprob_ev, best_ev, game_id=game_id)
            return PickResult(
                market="match_result",
                line=None,
                will_bet=True,
                pick=pick_ev,
                pick_prob=pprob_ev,
                pick_ev=best_ev,
                pick_odd=odd_map[pick_ev],
                reason=reason,
                metadata={
                    "strategy": "prob_gte_40",
                    "ev_original": ev_original_best,
                    "ev_adjusted": best_ev,
                    "odd_movement_used": odd_movement_used,
                    "alternatives": alternatives,
                },
            )

    # Fallback: nenhuma estratégia acionada — reason vem da falha da estratégia 1
    reason = f"EV baixo (<{int(MIN_EV*100)}%)" if best_ev < MIN_EV else f"Probabilidade baixa (<{int(MIN_PROB*100)}%)"
    log_decision(None, False, "", pprob_ev, best_ev, reason, game_id=game_id, suppressed=True, suppression_reason=reason)
    log_signal_suppression(None, reason, pprob_ev, best_ev, game_id=game_id)
    return PickResult(
        market="match_result",
        line=None,
        will_bet=False,
        pick="",
        pick_prob=pprob_ev,
        pick_ev=best_ev,
        pick_odd=odd_map[pick_ev],
        reason=reason,
        metadata={
            "strategy": None,
            "ev_original": ev_original_best,
            "ev_adjusted": best_ev,
            "odd_movement_used": odd_movement_used,
            "alternatives": alternatives,
            "almost_pick": pick_ev,
        },
    )


def decide_bet(odds_home, odds_draw, odds_away, competition, teams, game_id=None):
    """DEPRECATED: usar decide_match_result. Mantido por compatibilidade temporária."""
    r = decide_match_result(
        odds_home, odds_draw, odds_away,
        game_id=game_id, competition=competition, teams=teams,
    )
    return r.will_bet, r.pick, r.pick_prob, r.pick_ev, r.reason


def decide_live_bet_opportunity(live_data, game, tracker):
    """
    Retorna uma oportunidade apenas se:
      - odd >= LIVE_MIN_ODD
      - 'edge' >= LIVE_MIN_EDGE (acima do break-even)
      - score agregado >= LIVE_MIN_SCORE
      - respeita cooldown geral do jogo e cooldown específico para mesma pick
    """
    import os
    from models.database import Game, LiveGameTracker
    from betting.kelly import suggest_stake_and_return
    
    stats = live_data.get("stats", {})
    markets = live_data.get("markets", {})
    match_time = stats.get("match_time", "") or ""

    # Cooldown geral do jogo
    now = datetime.now(pytz.UTC)
    cooldown_until = tracker.cooldown_until
    if cooldown_until and now < cooldown_until:
        return None

    LIVE_MIN_ODD = float(os.getenv("LIVE_MIN_ODD", "1.20"))
    LIVE_MIN_EDGE = float(os.getenv("LIVE_MIN_EDGE", "0.02"))
    LIVE_MIN_SCORE = float(os.getenv("LIVE_MIN_SCORE", "0.60"))
    SAME_PICK_CD_MIN = int(os.getenv("LIVE_SAME_PICK_COOLDOWN_MIN", "20"))
    COOLDOWN_MIN = int(os.getenv("LIVE_COOLDOWN_MIN", "8"))

    candidates = []

    # REGRA 1: BTTS NÃO 0-0 >= 75'
    try:
        home_goals = int(stats.get("home_goals", 0))
        away_goals = int(stats.get("away_goals", 0))
    except Exception:
        home_goals = away_goals = 0

    if home_goals == 0 and away_goals == 0:
        if any(x in match_time for x in ["75","76","77","78","79","80","81","82","83","84","85","86","87","88","89","90"]):
            btts = markets.get("btts", {}).get("options", {})
            odd = float(btts.get("Não", 0.0) or 0.0)
            if odd >= LIVE_MIN_ODD:
                brk = 1.0 / odd
                bonus = 0.03 if "85" in match_time or "86" in match_time or "87" in match_time or "88" in match_time or "89" in match_time or "90" in match_time else 0.02
                p_est = min(0.95, brk + bonus)
                edge = p_est * odd - 1.0
                score = 0.4 + 0.3 + min(0.3, max(0.0, edge))
                candidates.append({
                    "market_key": "btts",
                    "display_name": "Ambos os Times Marcam",
                    "option": "Não",
                    "odd": odd,
                    "p_est": p_est,
                    "edge": edge,
                    "score": score,
                    "cooldown_minutes": COOLDOWN_MIN
                })

    # REGRA 2: Resultado Final — time vencendo por 1 gol aos 85+'
    if abs(home_goals - away_goals) == 1 and any(x in match_time for x in ["85","86","87","88","89","90"]):
        leader = "Casa" if home_goals > away_goals else "Fora"
        result_market = markets.get("match_result", {}).get("options", {})
        odd = float(result_market.get(leader, 0.0) or 0.0)
        if odd >= LIVE_MIN_ODD:
            brk = 1.0 / odd
            p_est = min(0.98, brk + 0.03)
            edge = p_est * odd - 1.0
            score = 0.35 + 0.25 + min(0.4, max(0.0, edge))
            candidates.append({
                "market_key": "match_result",
                "display_name": "Resultado Final",
                "option": leader,
                "odd": odd,
                "p_est": p_est,
                "edge": edge,
                "score": score,
                "cooldown_minutes": max(COOLDOWN_MIN, 12)
            })

    if not candidates:
        return None

    # Escolhe melhor por score
    cand = max(candidates, key=lambda c: c["score"])

    # Filtros finais
    if cand["edge"] < LIVE_MIN_EDGE or cand["score"] < LIVE_MIN_SCORE:
        return None

    # Dedupe: não repetir mesma pick (mercado+opção) dentro do SAME_PICK_CD_MIN
    pick_key = f"{cand['market_key']}|{cand['option']}"
    if tracker.last_pick_key == pick_key and tracker.last_pick_sent:
        if (now - tracker.last_pick_sent).total_seconds() < SAME_PICK_CD_MIN * 60:
            return None

    # Sugerir stake/retorno
    bankroll = float(os.getenv("BANKROLL", "1000"))
    kfrac = float(os.getenv("KELLY_FRACTION", "0.25"))
    stake, profit = suggest_stake_and_return(cand["p_est"], cand["odd"], bankroll, kfrac)
    
    cand["stake"] = stake
    cand["profit"] = profit
    cand["pick_key"] = pick_key

    return cand


def decide_total_goals(
    total_goals_market: dict,
    *,
    game_id: Optional[int] = None,
    competition: Optional[str] = None,
    teams: Optional[tuple] = None,
    lines: tuple = (0.5, 1.5, 2.5, 3.5),
) -> Optional["PickResult"]:
    """
    Decisão de aposta no mercado Total de Gols (Over/Under).

    Para cada linha em `lines` que tem par completo (Mais E Menos),
    normaliza odds, calcula prob implícita sem vig e EV.
    Aplica a cascata de estratégias do match_result, adaptada pra 2-vias.
    NÃO faz ajuste por movimento de odds nesta versão.
    """
    from utils.analytics_logger import (
        log_calculation, log_decision, log_signal_suppression, log_signal_sent
    )

    available = _extract_total_goals_lines(total_goals_market or {})
    if not available:
        return None

    # Filtra linhas pedidas e mantém só as com par completo
    filtered = {ln: sides for ln, sides in available.items() if ln in lines}
    if not filtered:
        return None

    # Calcula prob/ev por (linha, lado)
    per_line: dict = {}
    candidates: list = []  # (line, side, prob, ev, odd)
    for line, sides in filtered.items():
        odd_over = sides["over"]
        odd_under = sides["under"]
        inv_over = 1.0 / odd_over if odd_over > 0 else 0.0
        inv_under = 1.0 / odd_under if odd_under > 0 else 0.0
        tot = inv_over + inv_under
        if tot <= 0:
            continue
        prob_over = inv_over / tot
        prob_under = inv_under / tot
        ev_over = prob_over * odd_over - 1.0
        ev_under = prob_under * odd_under - 1.0
        per_line[line] = {
            "over": {"prob": prob_over, "ev": ev_over, "odd": odd_over},
            "under": {"prob": prob_under, "ev": ev_under, "odd": odd_under},
        }
        candidates.append((line, "over", prob_over, ev_over, odd_over))
        candidates.append((line, "under", prob_under, ev_under, odd_under))

    if not candidates:
        return None

    alternatives = {f"{ln}": sides_data for ln, sides_data in per_line.items()}

    # Melhor (linha, lado) por EV
    best = max(candidates, key=lambda c: c[3])
    best_line, best_side, best_prob, best_ev, best_odd = best

    # "outro" lado dentro da mesma linha (pra checagem favorito_claro)
    other_side = "under" if best_side == "over" else "over"
    other_data = per_line[best_line][other_side]
    other_prob = other_data["prob"]
    other_ev = other_data["ev"]
    other_odd = other_data["odd"]

    log_metadata = {
        "competition": competition,
        "teams": teams,
        "market": "total_goals",
        "line": best_line,
    }

    log_calculation(
        None, best_odd, 0.0, 0.0, best_side, best_prob, best_ev,
        strategy="EV positivo total_goals",
        game_id=game_id,
        metadata=log_metadata,
    )

    def _build_result(strategy: str, reason: str, line: float, side: str,
                      prob: float, ev: float, odd: float, will_bet: bool = True) -> PickResult:
        return PickResult(
            market="total_goals",
            line=line,
            will_bet=will_bet,
            pick=side,
            pick_prob=prob,
            pick_ev=ev,
            pick_odd=odd,
            reason=reason,
            metadata={
                "market": "total_goals",
                "line": line,
                "strategy": strategy,
                "ev_original": ev,
                "ev_adjusted": ev,
                "odd_movement_used": False,
                "alternatives": alternatives,
            },
        )

    # 1) EV positivo
    if best_ev >= MIN_EV and best_prob >= MIN_PROB:
        reason = f"EV positivo total_goals (linha {best_line})"
        log_decision(
            None, True, best_side, best_prob, best_ev, reason,
            game_id=game_id,
            metadata={"market": "total_goals", "line": best_line, "strategy": "ev_positive"},
        )
        log_signal_sent(
            None, reason, best_side, best_prob, best_ev,
            game_id=game_id,
            metadata={"market": "total_goals", "line": best_line},
        )
        return _build_result("ev_positive", reason, best_line, best_side,
                             best_prob, best_ev, best_odd)

    # 2) Favorito Claro (mesma linha)
    if FAV_MODE == "on":
        if best_prob >= other_prob:
            p_best, p_other = best_prob, other_prob
            ev_fav = best_ev
            fav_side, fav_prob, fav_odd = best_side, best_prob, best_odd
        else:
            p_best, p_other = other_prob, best_prob
            ev_fav = other_ev
            fav_side, fav_prob, fav_odd = other_side, other_prob, other_odd

        prob_ok = p_best >= max(MIN_PROB, FAV_PROB_MIN, 0.40)
        gap_ok = (p_best - p_other) >= FAV_GAP_MIN
        ev_ok = (ev_fav >= EV_TOL) or FAV_IGNORE_EV

        if prob_ok and gap_ok and ev_ok:
            reason = f"Favorito claro total_goals (linha {best_line})"
            log_decision(
                None, True, fav_side, fav_prob, ev_fav, reason,
                game_id=game_id,
                metadata={"market": "total_goals", "line": best_line, "strategy": "favorito_claro"},
            )
            log_signal_sent(
                None, reason, fav_side, fav_prob, ev_fav,
                game_id=game_id,
                metadata={"market": "total_goals", "line": best_line},
            )
            return _build_result("favorito_claro", reason, best_line, fav_side,
                                 fav_prob, ev_fav, fav_odd)

    # 3) High Odd — itera todas as (linha, lado) por EV desc
    if HIGH_ODD_MODE == "on":
        ev_sorted = sorted(candidates, key=lambda c: c[3], reverse=True)
        for line_h, side_h, prob_h, ev_h, odd_h in ev_sorted:
            if (odd_h >= HIGH_ODD_MIN) and (prob_h <= HIGH_ODD_MAX_PROB) and (ev_h >= HIGH_ODD_MIN_EV):
                reason = (
                    f"Maior Potencial de Ganho total_goals "
                    f"(Odd: {odd_h:.2f}, EV: {ev_h*100:.1f}%, linha {line_h})"
                )
                log_decision(
                    None, True, side_h, prob_h, ev_h, reason,
                    game_id=game_id,
                    metadata={"market": "total_goals", "line": line_h, "strategy": "high_odd"},
                )
                log_signal_sent(
                    None, reason, side_h, prob_h, ev_h,
                    game_id=game_id,
                    metadata={"market": "total_goals", "line": line_h},
                )
                return _build_result("high_odd", reason, line_h, side_h,
                                     prob_h, ev_h, odd_h)

    # 4) Prob > 50% (na (linha,lado) de maior EV)
    if best_prob > 0.50:
        reason = "Favorito claro total_goals (probabilidade > 50%)"
        log_decision(
            None, True, best_side, best_prob, best_ev, reason,
            game_id=game_id,
            metadata={"market": "total_goals", "line": best_line, "strategy": "prob_gt_50"},
        )
        log_signal_sent(
            None, reason, best_side, best_prob, best_ev,
            game_id=game_id,
            metadata={"market": "total_goals", "line": best_line},
        )
        return _build_result("prob_gt_50", reason, best_line, best_side,
                             best_prob, best_ev, best_odd)

    # 5) Prob >= 40% com EV >= -8%
    if best_prob >= 0.40 and best_ev >= -0.08:
        reason = "Alta confiança total_goals (probabilidade > 40%)"
        log_decision(
            None, True, best_side, best_prob, best_ev, reason,
            game_id=game_id,
            metadata={"market": "total_goals", "line": best_line, "strategy": "prob_gte_40"},
        )
        log_signal_sent(
            None, reason, best_side, best_prob, best_ev,
            game_id=game_id,
            metadata={"market": "total_goals", "line": best_line},
        )
        return _build_result("prob_gte_40", reason, best_line, best_side,
                             best_prob, best_ev, best_odd)

    # Nenhuma estratégia acionou
    reason = "EV/prob baixos em todas as linhas"
    log_decision(
        None, False, "", best_prob, best_ev, reason,
        game_id=game_id, suppressed=True, suppression_reason=reason,
        metadata={"market": "total_goals", "line": best_line, "strategy": None},
    )
    log_signal_suppression(
        None, reason, best_prob, best_ev,
        game_id=game_id,
        metadata={"market": "total_goals", "line": best_line},
    )
    return PickResult(
        market="total_goals",
        line=best_line,
        will_bet=False,
        pick="",
        pick_prob=best_prob,
        pick_ev=best_ev,
        pick_odd=best_odd,
        reason=reason,
        metadata={
            "market": "total_goals",
            "line": best_line,
            "strategy": None,
            "ev_original": best_ev,
            "ev_adjusted": best_ev,
            "odd_movement_used": False,
            "alternatives": alternatives,
            "almost_pick": best_side,
        },
    )


def decide_handicap_asian(
    markets: dict,
    *,
    game_id: Optional[int] = None,
    competition: Optional[str] = None,
    teams: Optional[tuple] = None,
    enable_observation_mode: bool = True,
) -> Optional["PickResult"]:
    """
    Decide aposta em Handicap Asiático.

    Estratégia:
    1. Calibra (λ_home, λ_away) via Poisson usando markets['match_result'] + markets['total_goals'].
    2. Para cada linha de handicap em markets['handicap_asian']['options']:
       - Calcula probabilidade real via prob_handicap_asian (modelo)
       - Compara com odd ofertada → calcula EV
    3. Filtra apenas linhas .5 (sem push) — descarta .0 e .25/.75
       pra evitar edge cases de push.
    4. Escolhe a (linha, lado) de MAIOR EV.
    5. Aplica gate MIN_EV / MIN_PROB.

    Em modo observação: will_bet=False mesmo se pick válido (não notifica),
    mas guarda metadata pra análise posterior.

    Args:
        markets: dict com 'match_result', 'total_goals', e (opcional) 'handicap_asian'
        enable_observation_mode: se True, picks gerados mas not bet (fase validação)

    Returns:
        PickResult com market='handicap_asian', line=<linha>, pick='home'|'away' ou
        None se mercado handicap não disponível.
    """
    handicap_market = markets.get("handicap_asian") if isinstance(markets, dict) else None
    if not handicap_market or not isinstance(handicap_market, dict):
        return None
    options = handicap_market.get("options") or {}
    if not isinstance(options, dict) or not options:
        return None

    # Imports lazy
    from betting.poisson import calibrate_from_markets, prob_handicap_asian

    lambdas = calibrate_from_markets(markets)
    if not lambdas:
        return None
    lam_h, lam_a = lambdas

    # Padrão: "Casa -1.5", "Fora +0.5", "Home -1", "Away +0.5", etc.
    pattern = re.compile(r'^(Casa|Fora|Home|Away)\s*([+-]?\d+(?:\.\d+)?)$', re.IGNORECASE)

    candidates = []
    for option_name, raw_odd in options.items():
        if not isinstance(option_name, str):
            continue
        m = pattern.match(option_name.strip())
        if not m:
            continue
        side_raw = m.group(1).lower()
        try:
            line = float(m.group(2))
        except (TypeError, ValueError):
            continue

        # Normaliza side
        if side_raw in ("casa", "home"):
            side = "home"
        elif side_raw in ("fora", "away"):
            side = "away"
        else:
            continue

        # Aceita SOMENTE linhas .5 puras (sem .0 nem quarter .25/.75)
        # line*2 deve ser inteiro ímpar → abs(line) - floor(abs(line)) == 0.5
        line_x2 = line * 2.0
        if abs(line_x2 - round(line_x2)) > 1e-9:
            # Quarter line — descarta
            continue
        # Agora line*2 é inteiro. Se também for inteiro puro (line.0), descarta.
        if abs(line - round(line)) < 1e-9:
            continue
        # Confirma que é .5
        if abs(abs(line) - int(abs(line)) - 0.5) > 1e-9:
            continue

        odd_val = _normalize_odd_value(raw_odd)
        if odd_val < 1.01:
            continue

        # Calcula prob via Poisson
        try:
            hcp_probs = prob_handicap_asian(lam_h, lam_a, side, line)
        except Exception:
            continue
        prob_win = hcp_probs.get("win", 0.0) if isinstance(hcp_probs, dict) else 0.0
        if prob_win <= 0:
            continue

        ev = prob_win * odd_val - 1.0
        candidates.append({
            "side": side,
            "line": line,
            "odd": odd_val,
            "prob": prob_win,
            "ev": ev,
            "option_name": option_name,
        })

    if not candidates:
        return None

    # Escolhe maior EV
    best = max(candidates, key=lambda c: c["ev"])

    # Gate: only will_bet=True se EV >= MIN_EV E prob >= MIN_PROB
    will_bet = False
    reason = (
        f"Handicap asiático sem sinal (line={best['line']}, "
        f"EV={best['ev']:.2%}, prob={best['prob']:.2%})"
    )

    if best["ev"] >= MIN_EV and best["prob"] >= MIN_PROB:
        if enable_observation_mode:
            # Modo observação: NÃO notifica (will_bet=False), mas guarda metadata
            will_bet = False
            reason = (
                f"Handicap asiático em observação (line={best['line']}, "
                f"EV={best['ev']:.2%}, prob={best['prob']:.2%})"
            )
        else:
            will_bet = True
            reason = (
                f"Handicap asiático: line={best['line']}, "
                f"EV={best['ev']:.2%}, prob={best['prob']:.2%}"
            )

    return PickResult(
        market="handicap_asian",
        line=best["line"],
        will_bet=will_bet,
        pick=best["side"],
        pick_prob=best["prob"],
        pick_ev=best["ev"],
        pick_odd=best["odd"],
        reason=reason,
        metadata={
            "market": "handicap_asian",
            "lam_home": lam_h,
            "lam_away": lam_a,
            "option_name": best["option_name"],
            "all_candidates": candidates[:10],  # max 10 candidatos pra debug
            "observation_mode": enable_observation_mode,
            "strategy": "poisson_ev",
        },
    )


def decide_picks(
    game_data: dict,
    *,
    game_id: Optional[int] = None,
    competition: Optional[str] = None,
    teams: Optional[tuple] = None,
) -> List[PickResult]:
    """
    Orquestrador. Roda decide_match_result sempre e, se feature flag
    ENABLE_TOTAL_GOALS_PICKS=true, também roda decide_total_goals.
    Também roda decide_handicap_asian se markets['handicap_asian'] existir
    (default em modo observação — picks gerados mas not bet).
    Retorna lista de PickResult (1+ elementos, sem None).
    """
    results: List[PickResult] = []

    markets = (game_data or {}).get("markets", {}) or {}

    # 1) match_result (sempre)
    mr = markets.get("match_result", {}) if isinstance(markets, dict) else {}
    opts = mr.get("options", {}) if isinstance(mr, dict) else {}
    odds_home = _normalize_odd_value(opts.get("Casa", 0.0))
    odds_draw = _normalize_odd_value(opts.get("Empate", 0.0))
    odds_away = _normalize_odd_value(opts.get("Fora", 0.0))

    mr_result = decide_match_result(
        odds_home, odds_draw, odds_away,
        game_id=game_id, competition=competition, teams=teams,
    )
    if mr_result is not None:
        results.append(mr_result)

    # 2) total_goals (atrás de feature flag)
    enable_tg = os.getenv("ENABLE_TOTAL_GOALS_PICKS", "false").lower() == "true"
    if enable_tg:
        tg_market = markets.get("total_goals") if isinstance(markets, dict) else None
        if tg_market:
            tg_result = decide_total_goals(
                tg_market,
                game_id=game_id, competition=competition, teams=teams,
            )
            if tg_result is not None:
                results.append(tg_result)

    # 3) handicap_asian (modo observação por padrão)
    enable_obs = os.getenv("HANDICAP_ASIAN_OBSERVATION_MODE", "true").lower() == "true"
    try:
        hcp_pick = decide_handicap_asian(
            markets,
            game_id=game_id,
            competition=competition,
            teams=teams,
            enable_observation_mode=enable_obs,
        )
        if hcp_pick is not None:
            results.append(hcp_pick)
    except Exception as exc:
        from utils.logger import logger
        logger.warning(f"decide_handicap_asian falhou: {exc}")

    return results


# ============================================================
# Persistência de Picks (multi-market)
# ============================================================

def _is_total_goals_picks_enabled() -> bool:
    """Lê env flag a cada chamada — não cacheia, pra reagir a mudanças sem restart."""
    return os.getenv("ENABLE_TOTAL_GOALS_PICKS", "false").lower() == "true"


def upsert_pick(session, game_id: int, pick_result: "PickResult", decision_source: str) -> "Pick":
    """
    Upsert idempotente de Pick na tabela picks.
    Chave única: (game_id, market, line) — UniqueConstraint do schema.

    Comportamento:
      - Se já existe Pick(game_id, market, line) e ainda NÃO tem outcome resolvido
        (outcome is None), atualiza com os campos novos do pick_result.
      - Se já existe Pick e outcome JÁ está resolvido, NÃO sobrescreve (o jogo já
        terminou — não faz sentido revisar).
      - Se não existe, cria.

    NÃO commita — só flush. Quem chama controla a transação.
    Retorna o Pick (novo ou atualizado).
    """
    existing = (
        session.query(Pick)
        .filter_by(game_id=game_id, market=pick_result.market, line=pick_result.line)
        .one_or_none()
    )

    if existing is not None:
        # Se já resolvido (jogo terminou), preserva — não revisa pick após resultado.
        if existing.outcome is not None:
            return existing
        existing.pick = pick_result.pick or existing.pick
        existing.pick_prob = pick_result.pick_prob
        existing.pick_ev = pick_result.pick_ev
        existing.pick_odd = pick_result.pick_odd
        existing.pick_reason = pick_result.reason
        existing.will_bet = bool(pick_result.will_bet)
        existing.decision_source = decision_source
        existing.decision_metadata = pick_result.metadata
        try:
            session.flush()
        except Exception:
            session.rollback()
            raise
        return existing

    new_pick = Pick(
        game_id=game_id,
        market=pick_result.market,
        line=pick_result.line,
        pick=pick_result.pick or "",
        pick_prob=pick_result.pick_prob,
        pick_ev=pick_result.pick_ev,
        pick_odd=pick_result.pick_odd,
        pick_reason=pick_result.reason,
        will_bet=bool(pick_result.will_bet),
        decision_source=decision_source,
        decision_metadata=pick_result.metadata,
    )
    session.add(new_pick)
    try:
        session.flush()
    except Exception:
        session.rollback()
        raise
    return new_pick


def mirror_match_result_to_game(game, match_pick: "Pick") -> None:
    """
    Mantém os campos legados de Game sincronizados com o Pick de match_result
    pra retrocompat. NÃO commita.

    Atualiza Game.pick, pick_prob, pick_ev, pick_reason, will_bet apenas se
    Game.outcome ainda for None (jogo não terminou).
    """
    if game is None or match_pick is None:
        return
    if getattr(game, "outcome", None) is not None:
        # Jogo já terminou — não sobrescreve histórico.
        return
    game.pick = match_pick.pick or ""
    game.pick_prob = match_pick.pick_prob
    game.pick_ev = match_pick.pick_ev
    game.pick_reason = match_pick.pick_reason
    # will_bet legado: mantém True se já era True (preserva sinalização anterior)
    if match_pick.will_bet:
        game.will_bet = True


def _ev_get(ev_or_dict: Any, attr: str, default: Any = None) -> Any:
    """Acessa campo de objeto (getattr) ou dict (.get) de forma uniforme."""
    if isinstance(ev_or_dict, dict):
        return ev_or_dict.get(attr, default)
    return getattr(ev_or_dict, attr, default)


async def fetch_and_decide_picks(
    session,
    game,
    ev_or_dict,
    decision_source: str,
    use_full_markets: bool,
) -> List["Pick"]:
    """
    Orquestra fetch + decisão + persistência multi-market.

    Fluxo:
      1) Garante que game.id existe (flush se necessário).
      2) Se use_full_markets=True: tenta fetch_game_full_markets(ext_id, game_url).
         Se retornou markets relevantes, usa pra decide_picks.
      3) Senão (ou fetch falhou): monta game_data minimal só com odds 1x2.
      4) Pra cada PickResult: upsert_pick. Se for match_result, mirror_match_result_to_game.
      5) Retorna lista de Pick(s) atualizados.

    NÃO commita — quem chama controla a transação (geralmente comita o Game logo após).
    """
    from utils.logger import logger as _logger

    # 1) Garante game.id válido
    if getattr(game, "id", None) is None:
        try:
            session.add(game)
            session.flush()
        except Exception:
            _logger.exception("Falha ao flushar Game novo antes de decide_picks")
            raise

    ext_id = _ev_get(ev_or_dict, "ext_id")
    game_url = _ev_get(ev_or_dict, "game_url")
    competition = _ev_get(ev_or_dict, "competition")
    team_home = _ev_get(ev_or_dict, "team_home")
    team_away = _ev_get(ev_or_dict, "team_away")
    odds_home = _ev_get(ev_or_dict, "odds_home", 0.0) or 0.0
    odds_draw = _ev_get(ev_or_dict, "odds_draw", 0.0) or 0.0
    odds_away = _ev_get(ev_or_dict, "odds_away", 0.0) or 0.0
    teams = (team_home, team_away)

    game_data: dict = {}

    # 2) Fetch detalhado se habilitado
    if use_full_markets and ext_id:
        try:
            from scraping.fetchers import fetch_game_full_markets
            fetched = await fetch_game_full_markets(str(ext_id), game_url)
            if isinstance(fetched, dict):
                markets = fetched.get("markets") or {}
                if isinstance(markets, dict) and markets:
                    game_data = fetched
        except Exception:
            _logger.exception(
                "fetch_game_full_markets falhou pra ext_id=%s — caindo pra modo minimal",
                ext_id,
            )

    # 3) Fallback / modo minimal: monta game_data só com 1x2 do digest
    if not game_data or not (game_data.get("markets") or {}).get("match_result"):
        game_data = {
            "markets": {
                "match_result": {
                    "options": {
                        "Casa": float(odds_home or 0.0),
                        "Empate": float(odds_draw or 0.0),
                        "Fora": float(odds_away or 0.0),
                    }
                }
            }
        }

    # 4) Decisão multi-market
    pick_results = decide_picks(
        game_data,
        game_id=game.id,
        competition=competition,
        teams=teams,
    )

    # 4.1) Enrichment seletivo: handicap asiático SÓ pra jogos de alta confiança
    # Custa ~10s/jogo via Playwright. Só vale pra candidatos top.
    # Pré-condição: pick de match_result com prob >= HIGH_CONF_THRESHOLD
    _hcp_already_decided = any(pr.market == "handicap_asian" for pr in pick_results)
    if not _hcp_already_decided and ext_id and game_url:
        try:
            from config.settings import HIGH_CONF_THRESHOLD
            mr_pick = next((pr for pr in pick_results if pr.market == "match_result"), None)
            if mr_pick and (mr_pick.pick_prob or 0) >= HIGH_CONF_THRESHOLD:
                from scraping.betano import fetch_event_handicap_asian
                hcp_market = await fetch_event_handicap_asian(str(ext_id), game_url)
                if hcp_market and hcp_market.get("options"):
                    # Injeta no game_data e re-roda só o handicap
                    enriched_markets = dict(game_data.get("markets") or {})
                    enriched_markets["handicap_asian"] = hcp_market
                    enriched = {"stats": game_data.get("stats", {}), "markets": enriched_markets}
                    enriched_picks = decide_picks(
                        enriched,
                        game_id=game.id,
                        competition=competition,
                        teams=teams,
                    )
                    # Pega só o pick de handicap (já temos os outros)
                    hcp_pick = next(
                        (p for p in enriched_picks if p.market == "handicap_asian"),
                        None,
                    )
                    if hcp_pick:
                        pick_results.append(hcp_pick)
                        _logger.info(
                            "🎯 Enrichment handicap pra %s: %s @ %.2f (prob=%.0f%%, EV=%+.1f%%)",
                            teams, hcp_pick.pick, hcp_pick.pick_odd or 0,
                            (hcp_pick.pick_prob or 0) * 100,
                            (hcp_pick.pick_ev or 0) * 100,
                        )
        except Exception:
            _logger.exception("Enrichment handicap falhou pra ext_id=%s", ext_id)

    # 5) Persistência
    persisted: List["Pick"] = []
    for pr in pick_results:
        try:
            pick_row = upsert_pick(session, game.id, pr, decision_source)
        except Exception:
            _logger.exception(
                "Falha ao upsert_pick game_id=%s market=%s line=%s",
                game.id, pr.market, pr.line,
            )
            continue
        persisted.append(pick_row)

        if pr.market == "match_result":
            try:
                mirror_match_result_to_game(game, pick_row)
            except Exception:
                _logger.exception(
                    "Falha ao espelhar match_result no Game id=%s", game.id
                )

    # Log informativo quando flag ativa e total_goals gerou pick
    if use_full_markets:
        tg_pick = next((p for p in persisted if p.market == "total_goals"), None)
        if tg_pick is not None:
            try:
                _logger.info(
                    "🎯 Pick total_goals persistido: game_id=%s linha=%s lado=%s prob=%.3f ev=%.3f",
                    game.id, tg_pick.line, tg_pick.pick,
                    float(tg_pick.pick_prob or 0.0), float(tg_pick.pick_ev or 0.0),
                )
            except Exception:
                pass

    return persisted

