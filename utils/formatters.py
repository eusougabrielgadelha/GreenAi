"""Funções de formatação de mensagens."""
import html
import random
from datetime import datetime
from typing import Any, Dict, List
from models.database import Game, SessionLocal, CombinedBet
from config.settings import ZONE, HIGH_CONF_THRESHOLD
from utils.stats import global_accuracy, get_weekly_stats, to_aware_utc, get_lifetime_accuracy, get_daily_summary, get_accuracy_by_confidence


def h(b: str) -> str:
    """Helper para formatação HTML (bold)."""
    return f"<b>{b}</b>"


def esc(s: str) -> str:
    """Helper para escape HTML."""
    return html.escape(s or "")


def fmt_morning_summary(date_local: datetime, analyzed: int, chosen: List[Dict[str, Any]]) -> str:
    """Resumo matinal elegante e organizado"""
    dstr = date_local.strftime("%d/%m/%Y")
    day_name = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"][date_local.weekday()]
    
    # Cabeçalho
    msg = f"☀️ <b>BOM DIA!</b>\n"
    msg += f"<i>{day_name}, {dstr}</i>\n"
    msg += "━━━━━━━━━━━━━━━━━━━━\n\n"
    
    # Estatísticas do dia
    msg += f"📊 <b>RESUMO DA ANÁLISE</b>\n"
    msg += f"├ Jogos analisados: <b>{analyzed}</b>\n"
    msg += f"└ Jogos selecionados: <b>{len(chosen)}</b>\n\n"
    
    if chosen:
        # Agrupa por horário
        by_time = {}
        for g in chosen:
            time_str = g["start_time"].astimezone(ZONE).strftime("%H:%M")
            if time_str not in by_time:
                by_time[time_str] = []
            by_time[time_str].append(g)
        
        msg += f"🎯 <b>PICKS DO DIA</b>\n\n"
        
        for time_str in sorted(by_time.keys()):
            games = by_time[time_str]
            msg += f"🕐 <b>{time_str}h</b>\n"
            
            for g in games:
                pick_map = {"home": g.get('team_home'), "draw": "Empate", "away": g.get('team_away')}
                pick_str = pick_map.get(g.get("pick"), "—")
                
                # Formata com ícones baseados na probabilidade
                prob = g.get('pick_prob', 0)
                confidence = "🔥" if prob > 0.6 else "⭐" if prob > 0.4 else "💡"
                
                # Calcula a odd correta para o pick
                pick_odd = 0.0
                if g.get("pick") == "home":
                    pick_odd = g.get('odds_home', 0)
                elif g.get("pick") == "draw":
                    pick_odd = g.get('odds_draw', 0)
                elif g.get("pick") == "away":
                    pick_odd = g.get('odds_away', 0)
                
                odds_home = float(g.get('odds_home', 0) or 0.0)
                odds_away = float(g.get('odds_away', 0) or 0.0)
                msg += f"  {confidence} <b>{g.get('team_home')[:20]}</b> vs <b>{g.get('team_away')[:20]}</b>\n"
                msg += f"     → Odds: {odds_home:.2f} / {odds_away:.2f}\n"
                msg += f"     → {pick_str} @ {pick_odd:.2f} | Prob: {prob*100:.0f}% | EV: {g.get('pick_ev')*100:+.1f}%\n\n"
    else:
        msg += "ℹ️ <i>Nenhum jogo atende aos critérios hoje.</i>\n\n"
    
    # Rodapé com performance
    with SessionLocal() as s:
        acc = global_accuracy(s) * 100
        week_stats = get_weekly_stats(s)
    
    msg += "━━━━━━━━━━━━━━━━━━━━\n"
    msg += f"📈 <b>PERFORMANCE</b>\n"
    msg += f"├ Taxa geral: <b>{acc:.1f}%</b>\n"
    
    if week_stats:
        msg += f"├ Últimos 7 dias: <b>{week_stats['win_rate']:.1f}%</b>\n"
        msg += f"└ ROI semanal: <b>{week_stats['roi']:+.1f}%</b>\n"
    
    # Mensagem motivacional randômica
    motivational = random.choice([
        "💪 Disciplina sempre vence a sorte!",
        "🎯 Foco no processo, não no resultado.",
        "📚 Conhecimento é a melhor estratégia.",
        "⚖️ Equilíbrio e paciência são fundamentais.",
        "🌟 Consistência gera resultados."
    ])
    
    msg += f"\n<i>{motivational}</i>"
    
    return msg


def fmt_result(g: Game) -> str:
    """Formatação elegante para resultado final do jogo."""
    if g.hit is None:
        return "⚠️ <b>RESULTADO NÃO VERIFICADO</b>"

    emoji = "✅" if g.hit else "❌"
    status = "ACERTAMOS" if g.hit else "ERRAMOS"

    msg = f"{emoji} <b>RESULTADO - {status}</b>\n"
    msg += "━━━━━━━━━━━━━━━━━━━━\n\n"
    msg += f"⚽ <b>{g.team_home}</b> vs <b>{g.team_away}</b>\n\n"

    # Odds dos dois times
    odds_home = float(g.odds_home or 0.0)
    odds_away = float(g.odds_away or 0.0)
    odds_draw = float(g.odds_draw or 0.0)
    msg += f"💰 <b>ODDS</b>\n"
    msg += f"├ {g.team_home}: <b>{odds_home:.2f}</b>\n"
    msg += f"├ Empate: <b>{odds_draw:.2f}</b>\n"
    msg += f"└ {g.team_away}: <b>{odds_away:.2f}</b>\n\n"

    # Mapeia resultado para texto legível
    outcome_map = {"home": g.team_home, "draw": "Empate", "away": g.team_away}
    pick_map = {"home": g.team_home, "draw": "Empate", "away": g.team_away}

    msg += f"📊 <b>RESULTADO</b>\n"
    msg += f"├ Palpite: <b>{pick_map.get(g.pick, g.pick)}</b>\n"
    msg += f"├ Resultado: <b>{outcome_map.get(g.outcome, g.outcome or '—')}</b>\n"
    msg += f"└ EV estimado: {g.pick_ev*100:+.1f}%"

    return msg


def fmt_pick_now(g: Game) -> str:
    """Formatação elegante para novo pick"""
    hhmm = g.start_time.astimezone(ZONE).strftime("%H:%M")
    side = {"home": g.team_home, "draw": "Empate", "away": g.team_away}.get(g.pick, "—")
    
    # Calcula nível de confiança
    confidence_level = "ALTA" if g.pick_prob > 0.6 else "MÉDIA" if g.pick_prob > 0.4 else "PADRÃO"
    
    msg = f"🎯 <b>NOVA OPORTUNIDADE</b>\n"
    msg += "━━━━━━━━━━━━━━━━━━━━\n\n"
    
    msg += f"⚽ <b>JOGO</b>\n"
    msg += f"<b>{g.team_home}</b> vs <b>{g.team_away}</b>\n"
    msg += f"🕐 Início: {hhmm}h\n\n"
    
    # Odds dos dois times
    odds_home = float(g.odds_home or 0.0)
    odds_away = float(g.odds_away or 0.0)
    odds_draw = float(g.odds_draw or 0.0)
    msg += f"💰 <b>ODDS</b>\n"
    msg += f"├ {g.team_home}: <b>{odds_home:.2f}</b>\n"
    msg += f"├ Empate: <b>{odds_draw:.2f}</b>\n"
    msg += f"└ {g.team_away}: <b>{odds_away:.2f}</b>\n\n"
    
    msg += f"💡 <b>ANÁLISE</b>\n"
    msg += f"├ Aposta: <b>{side}</b>\n"
    
    # Calcula a odd correta baseada no pick
    pick_odd = 0.0
    if g.pick == "home":
        pick_odd = g.odds_home
    elif g.pick == "draw":
        pick_odd = g.odds_draw
    elif g.pick == "away":
        pick_odd = g.odds_away
        
    msg += f"├ Odd: <b>{pick_odd:.2f}</b>\n"
    msg += f"├ Probabilidade: <b>{g.pick_prob*100:.0f}%</b>\n"
    msg += f"├ Valor esperado: <b>{g.pick_ev*100:+.1f}%</b>\n"
    msg += f"└ Confiança: <b>{confidence_level}</b>\n"
    
    # Adiciona razão se não for genérica
    if g.pick_reason and g.pick_reason not in ["EV positivo", "Favorito claro"]:
        msg += f"\n💭 <i>{g.pick_reason}</i>\n"
    
    msg += "\n━━━━━━━━━━━━━━━━━━━━"
    
    return msg


def fmt_results_batch(games: List[Game], date_local: datetime = None) -> str:
    """Mensagem única (HTML) listando resultados de vários jogos (pick e resultado real)."""
    if date_local is None:
        date_local = datetime.now(ZONE)
    dstr = date_local.strftime("%d/%m/%Y")
    msg = f"📊 <b>RESULTADOS DAS APOSTAS</b>\n"
    msg += f"<i>{dstr}</i>\n"
    msg += "━━━━━━━━━━━━━━━━━━━━\n\n"
    total = len(games)
    hits = sum(1 for g in games if getattr(g, 'hit', None) is True)
    misses = sum(1 for g in games if getattr(g, 'hit', None) is False)
    acc = (hits / total * 100) if total else 0
    msg += f"📈 <b>RESUMO</b>\n"
    msg += f"├ Total: <b>{total}</b>\n"
    msg += f"├ ✅ Acertos: <b>{hits}</b>\n"
    msg += f"├ ❌ Erros: <b>{misses}</b>\n"
    msg += f"└ Assertividade: <b>{acc:.0f}%</b>\n\n"
    # Ordena por horário
    games_sorted = sorted(games, key=lambda g: g.start_time or datetime(1970,1,1))
    for idx, g in enumerate(games_sorted, 1):
        hhmm = (g.start_time.astimezone(ZONE).strftime("%H:%M") if g.start_time else "--:--")
        pick_map = {"home": g.team_home, "draw": "Empate", "away": g.team_away}
        pick_str = pick_map.get(g.pick, g.pick or "—")
        outcome_str = pick_map.get(g.outcome, g.outcome or "—")
        odd = 0.0
        if g.pick == "home":
            odd = float(g.odds_home or 0.0)
        elif g.pick == "draw":
            odd = float(g.odds_draw or 0.0)
        elif g.pick == "away":
            odd = float(g.odds_away or 0.0)
        status_emoji = "✅" if g.hit else ("❌" if g.hit is False else "ℹ️")
        status_text = "ACERTOU" if g.hit else ("ERROU" if g.hit is False else "SEM VERIFICAÇÃO")
        msg += f"{status_emoji} <b>{idx}.</b> <b>{esc(g.team_home)}</b> vs <b>{esc(g.team_away)}</b>\n"
        msg += f"   🕐 {hhmm}h | Pick: <b>{esc(pick_str)}</b> @ {odd:.2f}\n"
        msg += f"   📊 Resultado real: <b>{esc(outcome_str)}</b> | {status_text}\n\n"
    return msg


def fmt_reminder(g: Game) -> str:
    """Lembrete T-15 min antes do início do jogo."""
    hhmm = g.start_time.astimezone(ZONE).strftime("%H:%M")
    side = {"home": g.team_home, "draw": "Empate", "away": g.team_away}.get(g.pick, "—")

    # Odd correta do lado escolhido
    pick_odd = 0.0
    if g.pick == "home":
        pick_odd = g.odds_home or 0.0
    elif g.pick == "draw":
        pick_odd = g.odds_draw or 0.0
    elif g.pick == "away":
        pick_odd = g.odds_away or 0.0

    odds_home = float(g.odds_home or 0.0)
    odds_away = float(g.odds_away or 0.0)
    odds_draw = float(g.odds_draw or 0.0)
    
    return (
        "🔔 <b>Lembrete</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"⚽ <b>{esc(g.team_home)}</b> vs <b>{esc(g.team_away)}</b>\n"
        f"🕐 Início: {hhmm}h\n\n"
        f"💰 <b>ODDS</b>\n"
        f"├ {esc(g.team_home)}: <b>{odds_home:.2f}</b>\n"
        f"├ Empate: <b>{odds_draw:.2f}</b>\n"
        f"└ {esc(g.team_away)}: <b>{odds_away:.2f}</b>\n\n"
        f"🎯 Pick: <b>{esc(side)}</b> @ {pick_odd:.2f}\n"
        f"📈 Prob.: <b>{(g.pick_prob or 0)*100:.0f}%</b> | EV: <b>{(g.pick_ev or 0)*100:+.1f}%</b>"
    )


def fmt_watch_add(ev, ev_date_local: datetime, best_ev: float, pprob: float) -> str:
    """Formatação elegante para adição à watchlist"""
    hhmm = ev_date_local.strftime("%H:%M")
    
    # Odds dos dois times
    odds_home = float(getattr(ev, 'odds_home', 0) or 0.0)
    odds_away = float(getattr(ev, 'odds_away', 0) or 0.0)
    odds_draw = float(getattr(ev, 'odds_draw', 0) or 0.0)
    
    msg = f"👀 <b>ADICIONADO À WATCHLIST</b>\n"
    msg += "━━━━━━━━━━━━━━━━━━━━\n\n"
    msg += f"⚽ <b>{ev.team_home}</b> vs <b>{ev.team_away}</b>\n"
    msg += f"🕐 Início: {hhmm}h\n\n"
    msg += f"💰 <b>ODDS</b>\n"
    msg += f"├ {ev.team_home}: <b>{odds_home:.2f}</b>\n"
    msg += f"├ Empate: <b>{odds_draw:.2f}</b>\n"
    msg += f"└ {ev.team_away}: <b>{odds_away:.2f}</b>\n\n"
    msg += f"📊 <b>MÉTRICAS ATUAIS</b>\n"
    msg += f"├ EV: {best_ev*100:.1f}%\n"
    msg += f"├ Probabilidade: {pprob*100:.0f}%\n"
    msg += f"└ Status: Monitorando mudanças\n"
    msg += f"\n<i>Você será notificado se as odds melhorarem!</i>"
    
    return msg


def fmt_watch_upgrade(g: Game) -> str:
    """Formatação elegante para upgrade da watchlist"""
    hhmm = g.start_time.astimezone(ZONE).strftime("%H:%M")
    side = {"home": g.team_home, "draw": "Empate", "away": g.team_away}.get(g.pick, "—")
    
    msg = f"⬆️ <b>UPGRADE - WATCHLIST → PICK</b>\n"
    msg += "━━━━━━━━━━━━━━━━━━━━\n\n"
    msg += f"⚽ <b>{g.team_home}</b> vs <b>{g.team_away}</b>\n"
    msg += f"🕐 Início: {hhmm}h\n\n"
    
    # Odds dos dois times
    odds_home = float(g.odds_home or 0.0)
    odds_away = float(g.odds_away or 0.0)
    odds_draw = float(g.odds_draw or 0.0)
    msg += f"💰 <b>ODDS</b>\n"
    msg += f"├ {g.team_home}: <b>{odds_home:.2f}</b>\n"
    msg += f"├ Empate: <b>{odds_draw:.2f}</b>\n"
    msg += f"└ {g.team_away}: <b>{odds_away:.2f}</b>\n\n"
    
    # Calcula odd do pick
    pick_odd = 0.0
    if g.pick == "home":
        pick_odd = odds_home
    elif g.pick == "draw":
        pick_odd = odds_draw
    elif g.pick == "away":
        pick_odd = odds_away
    
    msg += f"✨ <b>ODDS MELHORARAM!</b>\n"
    msg += f"├ Nova aposta: <b>{side}</b> @ {pick_odd:.2f}\n"
    msg += f"├ Probabilidade: <b>{g.pick_prob*100:.0f}%</b>\n"
    msg += f"└ Valor esperado: <b>{g.pick_ev*100:+.1f}%</b>\n"
    msg += f"\n💚 <i>Agora atende aos critérios de aposta!</i>"
    
    return msg


def fmt_live_bet_opportunity(g: Game, opportunity: Dict[str, Any], stats: Dict[str, Any]) -> str:
    """Formatação para oportunidade de aposta ao vivo."""
    match_time = stats.get('match_time', '')
    urgency = "🔥🔥🔥" if any(x in match_time for x in ["85","86","87","88","89","90"]) else "🔥"

    pick_line = f"{opportunity.get('display_name')} • {opportunity['option']} @ {opportunity['odd']:.2f}"
    stake = opportunity.get("stake", 0.0)
    profit = opportunity.get("profit", 0.0)
    est_p = opportunity.get("p_est", 0.0)

    msg = (
        f"{urgency} <b>OPORTUNIDADE AO VIVO VALIDADA</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"⚽ <b>{g.team_home}</b> vs <b>{g.team_away}</b>\n"
        f"├ ⏱ {match_time} | Placar: {stats.get('score','—')}\n"
    )
    if 'last_event' in stats:
        msg += f"├ 📝 Último evento: {stats['last_event']}\n"
    
    # Mostra estatísticas adicionais se disponíveis
    shots_home = stats.get('shots_home')
    shots_away = stats.get('shots_away')
    possession_home = stats.get('possession_home')
    corners_home = stats.get('corners_home')
    corners_away = stats.get('corners_away')
    
    stats_line = []
    if shots_home is not None and shots_away is not None:
        stats_line.append(f"Chutes: {shots_home}-{shots_away}")
    if possession_home is not None:
        stats_line.append(f"Posse: {possession_home}%")
    if corners_home is not None and corners_away is not None:
        stats_line.append(f"Escanteios: {corners_home}-{corners_away}")
    
    if stats_line:
        msg += f"├ 📊 {' | '.join(stats_line)}\n"
    
    # Mostra score de confiança se disponível
    confidence_score = stats.get('confidence_score')
    if confidence_score is not None:
        confidence_emoji = "🔥" if confidence_score >= 0.80 else "⭐" if confidence_score >= 0.70 else "💡"
        msg += f"├ {confidence_emoji} Confiança: <b>{confidence_score*100:.0f}%</b>\n"
        validation_reason = stats.get('validation_reason', '')
        if validation_reason:
            # Mostra apenas os primeiros fatores de validação
            factors = validation_reason.split(' - ')[-1] if ' - ' in validation_reason else validation_reason
            if len(factors) > 60:
                factors = factors[:57] + "..."
            msg += f"└ ✓ {factors}\n\n"
        else:
            msg += "\n"

    msg += (
        f"💰 <b>APOSTA</b>\n"
        f"├ {pick_line}\n"
        f"├ Prob. estimada: <b>{est_p*100:.0f}%</b>\n"
        f"├ Aporte sugerido: <b>{stake:.2f}</b>\n"
        f"└ Lucro potencial: <b>{profit:.2f}</b>\n"
        "\n⚡ <i>Aja rápido — odds ao vivo mudam!</i>"
    )
    return msg


def fmt_dawn_games_summary(games: List[Game], date) -> str:
    """Formata mensagem de jogos da madrugada (00h-06h) do dia atual."""
    from datetime import date as date_type
    
    if isinstance(date, date_type):
        dstr = date.strftime("%d/%m/%Y")
        day_name = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"][date.weekday()]
    else:
        dstr = date.strftime("%d/%m/%Y")
        day_name = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"][date.weekday()]
    
    msg = "🌙 <b>JOGOS DA MADRUGADA</b>\n"
    msg += f"<i>{day_name}, {dstr}</i>\n"
    msg += "━━━━━━━━━━━━━━━━━━━━\n\n"
    
    msg += "🎯 <b>PICKS DA MADRUGADA</b>\n\n"
    
    # Ordena por horário
    games_sorted = sorted(games, key=lambda g: to_aware_utc(g.start_time).astimezone(ZONE))
    
    for g in games_sorted:
        hhmm = to_aware_utc(g.start_time).astimezone(ZONE).strftime("%H:%M")
        pick_map = {"home": g.team_home, "draw": "Empate", "away": g.team_away}
        pick_str = pick_map.get(g.pick, g.pick or "—")
        
        # Calcula odd correta
        if g.pick == "home":
            pick_odd = float(g.odds_home or 0.0)
        elif g.pick == "draw":
            pick_odd = float(g.odds_draw or 0.0)
        else:
            pick_odd = float(g.odds_away or 0.0)
        
        # Ícone de confiança
        prob = float(g.pick_prob or 0.0)
        confidence = "🔥" if prob > 0.6 else "⭐" if prob > 0.4 else "💡"
        
        odds_home = float(g.odds_home or 0.0)
        odds_away = float(g.odds_away or 0.0)
        msg += f"{confidence} <b>{esc(g.team_home)}</b> vs <b>{esc(g.team_away)}</b>\n"
        msg += f"   🕐 {hhmm}h | Odds: {odds_home:.2f} / {odds_away:.2f}\n"
        msg += f"   🎯 Pick: <b>{pick_str}</b> @ {pick_odd:.2f} | Prob: {prob*100:.0f}% | EV: {g.pick_ev*100:+.1f}%\n\n"
    
    return msg


def fmt_combined_bet(combined_bet: CombinedBet, games: List[Game]) -> str:
    """
    Formata mensagem de aposta combinada para Telegram.
    """
    bet_date_local = combined_bet.bet_date.astimezone(ZONE)
    date_str = bet_date_local.strftime("%d/%m/%Y")
    day_name = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"][bet_date_local.weekday()]
    
    msg = "🎯 <b>APOSTA COMBINADA - ALTA CONFIANÇA</b>\n"
    msg += f"<i>{day_name}, {date_str}</i>\n"
    msg += "━━━━━━━━━━━━━━━━━━━━\n\n"
    
    msg += f"📊 <b>RESUMO</b>\n"
    msg += f"├ Total de jogos: <b>{combined_bet.total_games}</b>\n"
    msg += f"├ Confiança média: <b>{combined_bet.avg_confidence*100:.0f}%</b>\n"
    msg += f"└ Odd combinada: <b>{combined_bet.combined_odd:.2f}</b>\n\n"
    
    msg += f"💰 <b>EXEMPLO DE APOSTA</b>\n"
    msg += f"├ Valor apostado: <b>R$ {combined_bet.example_stake:.2f}</b>\n"
    msg += f"└ Retorno potencial: <b>R$ {combined_bet.potential_return:.2f}</b>\n\n"
    
    msg += f"⚽ <b>JOGOS INCLUÍDOS</b>\n\n"
    
    # Ordena jogos por horário
    games_sorted = sorted(games, key=lambda g: g.start_time)
    
    # Exibir o nome do time escolhido ou 'Empate'
    pick_map = {"home": lambda g: g.team_home, "draw": lambda g: "Empate", "away": lambda g: g.team_away}
    
    for idx, game in enumerate(games_sorted, 1):
        game_local = game.start_time.astimezone(ZONE)
        date_short = game_local.strftime("%d/%m")
        hhmm = game_local.strftime("%H:%M")
        resolver = pick_map.get(game.pick)
        pick_str = resolver(game) if callable(resolver) else (game.pick or "—")

        # Determina odd do pick
        if game.pick == "home":
            pick_odd = float(game.odds_home or 0.0)
        elif game.pick == "draw":
            pick_odd = float(game.odds_draw or 0.0)
        else:
            pick_odd = float(game.odds_away or 0.0)

        # Ícone de confiança
        prob = float(game.pick_prob or 0.0)
        confidence_icon = "🔥" if prob >= HIGH_CONF_THRESHOLD else "⭐"

        msg += f"{confidence_icon} <b>{idx}.</b> {esc(game.team_home)} vs {esc(game.team_away)}\n"
        msg += f"   🗓 {date_short} 🕐 {hhmm} | Pick: <b>{pick_str}</b> @ {pick_odd:.2f}\n"
        msg += f"   📈 Prob: {prob*100:.0f}% | EV: {game.pick_ev*100:+.1f}%\n\n"
    
    msg += "━━━━━━━━━━━━━━━━━━━━\n"
    msg += "💡 <i>Esta aposta combina todos os jogos de alta confiança do dia.</i>\n"

    return msg


def fmt_combined_bet_result(bet: 'CombinedBet', session=None) -> str:
    """
    Mensagem HTML pro Telegram com resultado FINAL de uma múltipla.

    Estados:
      - status='won' → mensagem positiva, mostra lucro
      - status='lost' → mostra qual jogo errou
      - status='cancelled' → mostra jogo que cancelou (early-cancel)
    """
    def _fmt_brl(v: float) -> str:
        return f"R$ {v:.2f}".replace(".", ",")

    # Helper de moeda com sinal (lucro/perda)
    def _fmt_brl_signed(v: float) -> str:
        sign = "+" if v >= 0 else "-"
        return f"R$ {sign}{abs(v):.2f}".replace(".", ",")

    owns_session = False
    if session is None:
        session = SessionLocal()
        owns_session = True

    try:
        status = (bet.status or "").lower()
        status_map = {
            "won": ("✅🎉", "ACERTOU"),
            "lost": ("❌", "ERROU"),
            "cancelled": ("⏸️", "CANCELADA"),
        }
        status_emoji, status_label = status_map.get(status, ("⚠️", (status.upper() or "DESCONHECIDO")))

        # Buscar games associados
        game_ids = list(bet.game_ids or [])
        games = []
        if game_ids:
            games = session.query(Game).filter(Game.id.in_(game_ids)).all()

        # Manter ordem original do bet.game_ids
        games_by_id = {g.id: g for g in games}
        games_ordered = [games_by_id[gid] for gid in game_ids if gid in games_by_id]

        # Contagem de acertos sobre jogos verificados
        total_games = bet.total_games or len(game_ids) or 0
        hits = sum(1 for g in games_ordered if g.hit is True)

        # Métricas financeiras
        combined_odd = float(bet.combined_odd or 0.0)
        stake = float(bet.example_stake or 0.0)
        if status == "won":
            pnl_label = "Lucro"
            pnl_value = (combined_odd - 1.0) * stake
        elif status in ("lost", "cancelled"):
            pnl_label = "Perda"
            pnl_value = -stake
        else:
            pnl_label = "Resultado"
            pnl_value = 0.0

        # Cabeçalho
        msg = f"🎯 <b>RESULTADO DA MÚLTIPLA</b> {status_emoji}\n"
        msg += "━━━━━━━━━━━━━━━━━━━━\n\n"

        # Resumo
        msg += "📊 <b>RESUMO</b>\n"
        msg += f"├ Status: <b>{status_label}</b>\n"
        msg += f"├ Acertos: <b>{hits}/{total_games}</b>\n"
        msg += f"├ Odd combinada: <b>{combined_odd:.2f}</b>\n"
        msg += f"├ Aposta exemplo: <b>{_fmt_brl(stake)}</b>\n"
        msg += f"└ {pnl_label}: <b>{_fmt_brl_signed(pnl_value)}</b>\n\n"

        # Jogos
        msg += "⚽ <b>JOGOS</b>\n\n"

        outcome_dict = bet.outcome or {}
        pick_map_fn = {
            "home": lambda g: g.team_home,
            "draw": lambda g: "Empate",
            "away": lambda g: g.team_away,
        }

        # Iterar pareando picks/odds via índice (bet.picks/bet.odds são listas paralelas)
        picks_list = list(bet.picks or [])
        odds_list = list(bet.odds or [])

        for idx, gid in enumerate(game_ids, 0):
            g = games_by_id.get(gid)
            if g is None:
                # Jogo deletado/ausente — degrade gracioso
                pick_raw = picks_list[idx] if idx < len(picks_list) else "—"
                odd_val = float(odds_list[idx]) if idx < len(odds_list) and odds_list[idx] is not None else 0.0
                msg += f"⚠️ <b>{idx+1}.</b> Jogo indisponível\n"
                msg += f"   → Pick: <b>{esc(str(pick_raw))}</b> @ {odd_val:.2f}\n\n"
                continue

            team_home = esc(g.team_home or "—")
            team_away = esc(g.team_away or "—")

            # Resolver pick (preferir g.pick; fallback pra bet.picks[idx])
            pick_key = g.pick if g.pick in ("home", "draw", "away") else (
                picks_list[idx] if idx < len(picks_list) else None
            )
            pick_resolver = pick_map_fn.get(pick_key)
            pick_str = pick_resolver(g) if pick_resolver else (str(pick_key) if pick_key else "—")

            # Odd do pick: usar bet.odds[idx] se válida, senão derivar do game
            if idx < len(odds_list) and odds_list[idx] is not None:
                pick_odd = float(odds_list[idx])
            elif pick_key == "home":
                pick_odd = float(g.odds_home or 0.0)
            elif pick_key == "draw":
                pick_odd = float(g.odds_draw or 0.0)
            elif pick_key == "away":
                pick_odd = float(g.odds_away or 0.0)
            else:
                pick_odd = 0.0

            # Emoji individual
            if g.hit is True:
                game_emoji = "✅"
                game_status = "ACERTOU"
            elif g.hit is False:
                game_emoji = "❌"
                outcome_key = outcome_dict.get(str(g.id)) or g.outcome
                outcome_resolver = pick_map_fn.get(outcome_key)
                outcome_str = outcome_resolver(g) if outcome_resolver else (str(outcome_key) if outcome_key else "—")
                game_status = f"ERROU (Resultado: {esc(outcome_str)})"
            elif status == "cancelled":
                game_emoji = "⏸"
                game_status = "CANCELADA"
            else:
                game_emoji = "⏳"
                game_status = "PENDENTE"

            # Data e hora local do jogo
            if g.start_time is not None:
                try:
                    g_local = g.start_time.astimezone(ZONE)
                    datetime_short = g_local.strftime("%d/%m %H:%M")
                except (ValueError, AttributeError):
                    datetime_short = "—"
            else:
                datetime_short = "—"

            msg += f"{game_emoji} <b>{idx+1}.</b> {team_home} vs {team_away}\n"
            msg += f"   🗓 {datetime_short} | Pick: <b>{esc(pick_str)}</b> @ {pick_odd:.2f} → <b>{game_status}</b>\n\n"

        # Rodapé com data
        if bet.bet_date is not None:
            try:
                date_local = bet.bet_date.astimezone(ZONE)
            except (ValueError, AttributeError):
                date_local = bet.bet_date
            date_str = date_local.strftime("%d/%m/%Y")
        else:
            date_str = "—"

        msg += "━━━━━━━━━━━━━━━━━━━━\n"
        msg += f"📅 <i>Data: {date_str}</i>\n"

        return msg
    finally:
        if owns_session:
            session.close()


def fmt_today_games_summary(games: List[Game], date, analyzed: int) -> str:
    """Formata mensagem de jogos de hoje (06h-23h)."""
    from datetime import date as date_type
    
    if isinstance(date, date_type):
        dstr = date.strftime("%d/%m/%Y")
        day_name = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"][date.weekday()]
    else:
        dstr = date.strftime("%d/%m/%Y")
        day_name = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"][date.weekday()]
    
    msg = "🌅 <b>JOGOS DE HOJE</b>\n"
    msg += f"<i>{day_name}, {dstr}</i>\n"
    msg += "━━━━━━━━━━━━━━━━━━━━\n\n"
    
    msg += "📊 <b>RESUMO</b>\n"
    msg += f"├ Total analisado: <b>{analyzed}</b> jogos\n"
    msg += f"└ Selecionados: <b>{len(games)}</b> jogos\n\n"
    
    if games:
        msg += "🎯 <b>PICKS DO DIA</b>\n\n"
        
        # Agrupa por horário
        by_time = {}
        for g in games:
            time_str = to_aware_utc(g.start_time).astimezone(ZONE).strftime("%H:%M")
            if time_str not in by_time:
                by_time[time_str] = []
            by_time[time_str].append(g)
        
        for time_str in sorted(by_time.keys()):
            games_at_time = by_time[time_str]
            msg += f"🕐 <b>{time_str}h</b>\n"
            
            for g in games_at_time:
                pick_map = {"home": g.team_home, "draw": "Empate", "away": g.team_away}
                pick_str = pick_map.get(g.pick, g.pick or "—")
                
                # Calcula odd correta
                if g.pick == "home":
                    pick_odd = float(g.odds_home or 0.0)
                elif g.pick == "draw":
                    pick_odd = float(g.odds_draw or 0.0)
                else:
                    pick_odd = float(g.odds_away or 0.0)
                
                # Ícone de confiança
                prob = float(g.pick_prob or 0.0)
                confidence = "🔥" if prob > 0.6 else "⭐" if prob > 0.4 else "💡"
                
                odds_home = float(g.odds_home or 0.0)
                odds_away = float(g.odds_away or 0.0)
                msg += f"  {confidence} <b>{esc(g.team_home)}</b> vs <b>{esc(g.team_away)}</b>\n"
                msg += f"     → Odds: {odds_home:.2f} / {odds_away:.2f}\n"
                msg += f"     → {pick_str} @ {pick_odd:.2f} | Prob: {prob*100:.0f}% | EV: {g.pick_ev*100:+.1f}%\n\n"
    else:
        msg += "ℹ️ <i>Nenhum jogo atende aos critérios hoje.</i>\n\n"
    
    # Rodapé com performance
    with SessionLocal() as s:
        acc = global_accuracy(s) * 100
        week_stats = get_weekly_stats(s)
    
    msg += "━━━━━━━━━━━━━━━━━━━━\n"
    msg += f"📈 <b>PERFORMANCE</b>\n"
    msg += f"├ Taxa geral: <b>{acc:.1f}%</b>\n"
    
    if week_stats:
        msg += f"├ Últimos 7 dias: <b>{week_stats['win_rate']:.1f}%</b>\n"
        msg += f"└ ROI semanal: <b>{week_stats['roi']:+.1f}%</b>\n"
    
    # Mensagem motivacional
    motivational = random.choice([
        "💪 Disciplina sempre vence a sorte!",
        "🎯 Foco no processo, não no resultado.",
        "📚 Conhecimento é a melhor estratégia.",
        "⚖️ Equilíbrio e paciência são fundamentais.",
        "🌟 Consistência gera resultados."
    ])
    
    msg += f"\n<i>{motivational}</i>"
    
    return msg


def format_night_scan_summary(date: datetime, analyzed: int, games: List[Dict[str, Any]]) -> str:
    """Formata o resumo da varredura noturna (00:00–06:00 do dia seguinte, no fuso APP_TZ)."""
    msg = "🌙 <b>JOGOS DA MADRUGADA</b>\n"
    msg += f"<i>{date.strftime('%d/%m/%Y')} - 00:00 às 06:00</i>\n"
    msg += "━━━━━━━━━━━━━━━━━━━━\n\n"

    msg += "📊 <b>ANÁLISE NOTURNA</b>\n"
    msg += f"├ Jogos analisados: <b>{analyzed}</b>\n"
    msg += f"└ Jogos selecionados: <b>{len(games)}</b>\n\n"

    if games:
        msg += "🎯 <b>PICKS DA MADRUGADA</b>\n\n"
        # Ordena por horário local de início
        games_sorted = sorted(games, key=lambda x: to_aware_utc(x["start_time"]).astimezone(ZONE))
        for g in games_sorted:
            hhmm = to_aware_utc(g["start_time"]).astimezone(ZONE).strftime("%H:%M")
            pick_key = g.get("pick")
            pick_map = {"home": "Casa", "draw": "Empate", "away": "Fora"}
            pick_str = pick_map.get(pick_key, pick_key or "—")

            if pick_key == "home":
                odd = float(g.get("odds_home") or 0.0)
            elif pick_key == "draw":
                odd = float(g.get("odds_draw") or 0.0)
            else:
                odd = float(g.get("odds_away") or 0.0)

            msg += (
                f"🕐 <b>{hhmm}h</b>\n"
                f"  {esc(g.get('team_home'))} vs {esc(g.get('team_away'))}\n"
                f"  → {esc(pick_str)} @ {odd:.2f}\n"
                f"  → Prob.: {float(g.get('pick_prob') or 0)*100:.0f}% | EV: {float(g.get('pick_ev') or 0)*100:+.1f}%\n\n"
            )
    else:
        msg += "ℹ️ Nenhum pick para a janela 00:00–06:00.\n"

    return msg


def fmt_daily_summary(session, date_local: datetime = None) -> str:
    """
    Formata resumo diário completo com todos os jogos finalizados do dia.
    Inclui assertividade do dia e comparação com lifetime.
    """
    if date_local is None:
        date_local = datetime.now(ZONE)
    
    summary = get_daily_summary(session, date_local)
    lifetime = get_lifetime_accuracy(session)
    
    dstr = date_local.strftime("%d/%m/%Y")
    day_name = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"][date_local.weekday()]
    
    msg = f"📊 <b>RESUMO DO DIA</b>\n"
    msg += f"<i>{day_name}, {dstr}</i>\n"
    msg += "━━━━━━━━━━━━━━━━━━━━\n\n"
    
    # Estatísticas do dia
    msg += f"📈 <b>ESTATÍSTICAS DO DIA</b>\n"
    msg += f"├ Total de jogos: <b>{summary['total_games']}</b>\n"
    msg += f"├ Verificados: <b>{summary['verified_games']}</b>\n"
    
    if summary['unverified_games'] > 0:
        msg += f"├ Não verificados: <b>{summary['unverified_games']}</b>\n"
    
    msg += f"├ ✅ Acertos: <b>{summary['hits']}</b>\n"
    msg += f"├ ❌ Erros: <b>{summary['misses']}</b>\n"
    msg += f"└ Assertividade: <b>{summary['accuracy']:.1f}%</b>\n\n"
    
    # Lista de jogos do dia
    if summary['games']:
        msg += f"⚽ <b>JOGOS DO DIA</b>\n\n"
        for g in summary['games']:
            emoji = "✅" if g.hit else "❌"
            outcome_map = {"home": g.team_home, "draw": "Empate", "away": g.team_away}
            pick_map = {"home": g.team_home, "draw": "Empate", "away": g.team_away}
            
            hhmm = g.start_time.astimezone(ZONE).strftime("%H:%M")
            msg += f"{emoji} <b>{g.team_home}</b> vs <b>{g.team_away}</b>\n"
            msg += f"   🕐 {hhmm}h | Palpite: {pick_map.get(g.pick, g.pick)} | Resultado: {outcome_map.get(g.outcome, g.outcome or '—')}\n\n"
    
    # Comparação com lifetime
    if lifetime['total'] > 0:
        msg += "━━━━━━━━━━━━━━━━━━━━\n"
        msg += f"📊 <b>ASSERTIVIDADE LIFETIME</b>\n"
        msg += f"├ Total histórico: <b>{lifetime['total']}</b> jogos\n"
        msg += f"├ ✅ Acertos: <b>{lifetime['hits']}</b>\n"
        msg += f"├ ❌ Erros: <b>{lifetime['misses']}</b>\n"
        msg += f"├ Assertividade: <b>{lifetime['accuracy_percent']:.1f}%</b>\n"
        if lifetime['average_odd'] > 0:
            msg += f"├ Odd média: <b>{lifetime['average_odd']:.2f}</b>\n"
            msg += f"└ ROI estimado: <b>{lifetime['roi']:+.1f}%</b>\n\n"
        else:
            msg += f"└ ROI: <b>—</b>\n\n"
        
        # Assertividade por nível de confiança
        conf_stats = get_accuracy_by_confidence(session)
        msg += f"📊 <b>ASSERTIVIDADE POR CONFIANÇA</b>\n"
        
        if conf_stats['high']['total'] > 0:
            msg += f"├ 🔥 Alta (≥60%): <b>{conf_stats['high']['accuracy_percent']:.1f}%</b> "
            msg += f"({conf_stats['high']['hits']}/{conf_stats['high']['total']})\n"
        
        if conf_stats['medium']['total'] > 0:
            msg += f"├ ⭐ Média (40-60%): <b>{conf_stats['medium']['accuracy_percent']:.1f}%</b> "
            msg += f"({conf_stats['medium']['hits']}/{conf_stats['medium']['total']})\n"
        
        if conf_stats['low']['total'] > 0:
            msg += f"└ 💡 Baixa (<40%): <b>{conf_stats['low']['accuracy_percent']:.1f}%</b> "
            msg += f"({conf_stats['low']['hits']}/{conf_stats['low']['total']})\n"
        else:
            if conf_stats['high']['total'] > 0 or conf_stats['medium']['total'] > 0:
                msg += f"└ 💡 Baixa: <b>—</b> (sem dados)\n"
    
    # Mensagem motivacional
    if summary['accuracy'] >= 60:
        msg += "\n💪 <i>Excelente dia! Continue assim!</i>"
    elif summary['accuracy'] >= 50:
        msg += "\n👍 <i>Bom desempenho! Mantenha a consistência!</i>"
    else:
        msg += "\n📚 <i>Dia de aprendizado. Análise e ajuste!</i>"
    
    return msg


def fmt_lifetime_stats(session) -> str:
    """
    Formata estatísticas lifetime (histórico completo).
    """
    lifetime = get_lifetime_accuracy(session)
    
    msg = f"📊 <b>ESTATÍSTICAS LIFETIME</b>\n"
    msg += f"<i>Histórico Completo</i>\n"
    msg += "━━━━━━━━━━━━━━━━━━━━\n\n"
    
    if lifetime['total'] == 0:
        msg += "ℹ️ <i>Ainda não há jogos finalizados no histórico.</i>"
        return msg
    
    msg += f"📈 <b>PERFORMANCE GERAL</b>\n"
    msg += f"├ Total de jogos: <b>{lifetime['total']}</b>\n"
    msg += f"├ ✅ Acertos: <b>{lifetime['hits']}</b>\n"
    msg += f"├ ❌ Erros: <b>{lifetime['misses']}</b>\n"
    msg += f"├ Assertividade: <b>{lifetime['accuracy_percent']:.1f}%</b>\n"
    
    if lifetime['average_odd'] > 0:
        msg += f"├ Odd média (acertos): <b>{lifetime['average_odd']:.2f}</b>\n"
        msg += f"└ ROI estimado: <b>{lifetime['roi']:+.1f}%</b>\n\n"
    else:
        msg += f"└ ROI: <b>—</b>\n\n"
    
    # Assertividade por nível de confiança
    conf_stats = get_accuracy_by_confidence(session)
    msg += f"📊 <b>ASSERTIVIDADE POR CONFIANÇA</b>\n"
    
    if conf_stats['high']['total'] > 0:
        msg += f"├ 🔥 Alta (≥60%): <b>{conf_stats['high']['accuracy_percent']:.1f}%</b> "
        msg += f"({conf_stats['high']['hits']}/{conf_stats['high']['total']})\n"
    
    if conf_stats['medium']['total'] > 0:
        msg += f"├ ⭐ Média (40-60%): <b>{conf_stats['medium']['accuracy_percent']:.1f}%</b> "
        msg += f"({conf_stats['medium']['hits']}/{conf_stats['medium']['total']})\n"
    
    if conf_stats['low']['total'] > 0:
        msg += f"└ 💡 Baixa (<40%): <b>{conf_stats['low']['accuracy_percent']:.1f}%</b> "
        msg += f"({conf_stats['low']['hits']}/{conf_stats['low']['total']})\n\n"
    else:
        if conf_stats['high']['total'] > 0 or conf_stats['medium']['total'] > 0:
            msg += f"└ 💡 Baixa: <b>—</b> (sem dados)\n\n"
    
    # Interpretação do ROI
    if lifetime['roi'] > 0:
        msg += "💚 <i>ROI positivo! A estratégia está funcionando!</i>"
    elif lifetime['roi'] > -5:
        msg += "💛 <i>ROI próximo de zero. Ajustes podem melhorar.</i>"
    else:
        msg += "💡 <i>ROI negativo. Revisão da estratégia recomendada.</i>"
    
    return msg

