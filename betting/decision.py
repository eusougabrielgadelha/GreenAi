"""Lógica de decisão de apostas."""
from datetime import datetime, timedelta
import pytz
from models.database import SessionLocal, OddHistory
from config.settings import (
    MIN_EV, MIN_PROB, FAV_MODE, FAV_PROB_MIN, FAV_GAP_MIN, EV_TOL, FAV_IGNORE_EV,
    HIGH_ODD_MODE, HIGH_ODD_MIN, HIGH_ODD_MAX_PROB, HIGH_ODD_MIN_EV
)


def decide_bet(odds_home, odds_draw, odds_away, competition, teams, game_id=None):
    """
    Decisão de aposta com EV ajustado pelo movimento de odds.
    Se game_id for fornecido, consulta o histórico para calcular a variação.
    """
    MIN_ODD = 1.01
    
    names = ("home", "draw", "away")
    odds = (float(odds_home or 0.0), float(odds_draw or 0.0), float(odds_away or 0.0))
    avail = [(n, o) for n, o in zip(names, odds) if o >= MIN_ODD]
    if len(avail) < 2:
        return False, "", 0.0, 0.0, "Odds insuficientes (menos de 2 mercados)"

    inv = [(n, 1.0 / o) for n, o in avail]
    tot = sum(v for _, v in inv)
    if tot <= 0:
        return False, "", 0.0, 0.0, "Probabilidades inválidas"

    true = {n: v / tot for n, v in inv}  # prob. implícitas normalizadas
    odd_map = dict(avail)
    ev_map = {n: true[n] * odd_map[n] - 1.0 for n in true}

    # Calcula o EV Ajustado com base no movimento de odds
    adjusted_ev_map = ev_map.copy()
    if game_id:
        with SessionLocal() as session:
            # Busca as odds registradas 1 hora atrás
            one_hour_ago = datetime.now(pytz.UTC) - timedelta(hours=1)
            old_odd = session.query(OddHistory).filter(
                OddHistory.game_id == game_id,
                OddHistory.timestamp <= one_hour_ago
            ).order_by(OddHistory.timestamp.desc()).first()

            if old_odd:
                for market in ["home", "draw", "away"]:
                    current_odd = odd_map.get(market, 0.0)
                    old_odd_val = getattr(old_odd, f"odds_{market}", 0.0)
                    if old_odd_val > 0 and current_odd > 0:
                        # Calcula a variação percentual (negativa = odd caindo = bom)
                        variation = (current_odd - old_odd_val) / old_odd_val
                        # Ajusta o EV: se a odd caiu, aumenta o EV; se subiu, diminui.
                        adjustment = -variation * 0.5  # Fator de ajuste (configurável)
                        adjusted_ev_map[market] += adjustment

    # 1) Estratégia Padrão: Valor Esperado Positivo (Ajustado)
    pick_ev, best_ev = max(adjusted_ev_map.items(), key=lambda x: x[1])
    pprob_ev = true[pick_ev]
    if best_ev >= MIN_EV and pprob_ev >= MIN_PROB:
        reason = "EV positivo (ajustado por movimento de odds)"
        return True, pick_ev, pprob_ev, best_ev, reason

    # 2) Estratégia do Favorito "óbvio"
    if FAV_MODE == "on":
        probs_sorted = sorted(true.items(), key=lambda x: x[1], reverse=True)
        (pick_fav, p1), (_, p2) = probs_sorted[0], probs_sorted[1]
        ev_fav = adjusted_ev_map.get(pick_fav, 0.0)
        gap_ok = (p1 - p2) >= FAV_GAP_MIN
        prob_ok = p1 >= max(MIN_PROB, FAV_PROB_MIN, 0.40)
        ev_ok = (ev_fav >= EV_TOL) or FAV_IGNORE_EV
        if prob_ok and gap_ok and ev_ok:
            reason = "Favorito claro (probabilidade)" if FAV_IGNORE_EV else "Favorito claro (regra híbrida)"
            return True, pick_fav, p1, ev_fav, reason

    # 3) ESTRATÉGIA: Maior Potencial de Ganho (High Odds / High EV)
    if HIGH_ODD_MODE == "on":
        ev_sorted = sorted(adjusted_ev_map.items(), key=lambda x: x[1], reverse=True)
        for pick_high, ev_high in ev_sorted:
            odd_high = odd_map[pick_high]
            prob_high = true[pick_high]

            # Critérios:
            # a) Odd acima do mínimo configurado (ex: 1.5)
            # b) Probabilidade abaixo do máximo (evita favoritos óbvios)
            # c) EV acima do mínimo configurado (pode ser negativo, ex: -15%)
            if (odd_high >= HIGH_ODD_MIN) and (prob_high <= HIGH_ODD_MAX_PROB) and (ev_high >= HIGH_ODD_MIN_EV):
                reason = f"Maior Potencial de Ganho (Odd: {odd_high:.2f}, EV Ajustado: {ev_high*100:.1f}%)"
                return True, pick_high, prob_high, ev_high, reason

    # Camada de Filtro de Confiança (Reforçada)
    # Prioridade 1: Qualquer mercado com probabilidade > 50%
    if pprob_ev > 0.50:
        return True, pick_ev, pprob_ev, best_ev, "Favorito claro (probabilidade > 50%)"

    # Prioridade 2: Mercado com alta probabilidade (40%+), mesmo com EV negativo
    if pprob_ev >= 0.40:
        if best_ev >= -0.08:  # Aceita até -8% de EV
            return True, pick_ev, pprob_ev, best_ev, "Alta confiança (probabilidade > 40%)"

    # Se nenhuma estratégia foi acionada, retorna o motivo da falha da estratégia 1.
    reason = f"EV baixo (<{int(MIN_EV*100)}%)" if best_ev < MIN_EV else f"Probabilidade baixa (<{int(MIN_PROB*100)}%)"
    return False, "", pprob_ev, best_ev, reason


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

