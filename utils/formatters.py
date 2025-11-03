"""Funções de formatação de mensagens."""
import html
import random
from datetime import datetime
from typing import Any, Dict, List
from models.database import Game, SessionLocal
from config.settings import ZONE
from utils.stats import global_accuracy, get_weekly_stats, to_aware_utc, get_lifetime_accuracy, get_daily_summary
from notifications.telegram import h


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
                
                msg += f"  {confidence} <b>{g.get('team_home')[:20]}</b> vs <b>{g.get('team_away')[:20]}</b>\n"
                msg += f"     → {pick_str} @ {pick_odd:.2f}\n"
                msg += f"     → Prob: {prob*100:.0f}% | EV: {g.get('pick_ev')*100:+.1f}%\n\n"
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
    msg += f"⚽ <b>{g.team_home}</b> vs <b>{g.team_away}</b>\n"

    # Mapeia resultado para texto legível
    outcome_map = {"home": g.team_home, "draw": "Empate", "away": g.team_away}
    pick_map = {"home": g.team_home, "draw": "Empate", "away": g.team_away}

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

    return (
        "🔔 <b>Lembrete</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"⚽ <b>{esc(g.team_home)}</b> vs <b>{esc(g.team_away)}</b>\n"
        f"🕐 Início: {hhmm}h\n"
        f"🎯 Pick: <b>{esc(side)}</b> @ {pick_odd:.2f}\n"
        f"📈 Prob.: <b>{(g.pick_prob or 0)*100:.0f}%</b> | EV: <b>{(g.pick_ev or 0)*100:+.1f}%</b>"
    )


def fmt_watch_add(ev, ev_date_local: datetime, best_ev: float, pprob: float) -> str:
    """Formatação elegante para adição à watchlist"""
    hhmm = ev_date_local.strftime("%H:%M")
    
    msg = f"👀 <b>ADICIONADO À WATCHLIST</b>\n"
    msg += "━━━━━━━━━━━━━━━━━━━━\n\n"
    msg += f"⚽ <b>{ev.team_home}</b> vs <b>{ev.team_away}</b>\n"
    msg += f"🕐 Início: {hhmm}h\n\n"
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
    msg += f"✨ <b>ODDS MELHORARAM!</b>\n"
    msg += f"├ Nova aposta: <b>{side}</b>\n"
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
        f"{urgency} <b>OPORTUNIDADE AO VIVO</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"⚽ <b>{g.team_home}</b> vs <b>{g.team_away}</b>\n"
        f"├ ⏱ {match_time} | Placar: {stats.get('score','—')}\n"
    )
    if 'last_event' in stats:
        msg += f"├ 📝 Último evento: {stats['last_event']}\n"

    msg += (
        f"\n💰 <b>APOSTA</b>\n"
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
        
        msg += f"{confidence} <b>{esc(g.team_home)}</b> vs <b>{esc(g.team_away)}</b>\n"
        msg += f"   🕐 {hhmm}h | Pick: <b>{pick_str}</b> @ {pick_odd:.2f}\n"
        msg += f"   📊 Prob: {prob*100:.0f}% | EV: {g.pick_ev*100:+.1f}%\n\n"
    
    return msg


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
                
                msg += f"  {confidence} <b>{esc(g.team_home)}</b> vs <b>{esc(g.team_away)}</b>\n"
                msg += f"     → {pick_str} @ {pick_odd:.2f}\n"
                msg += f"     → Prob: {prob*100:.0f}% | EV: {g.pick_ev*100:+.1f}%\n\n"
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
            msg += f"└ ROI estimado: <b>{lifetime['roi']:+.1f}%</b>\n"
        else:
            msg += f"└ ROI: <b>—</b>\n"
    
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
    
    # Interpretação do ROI
    if lifetime['roi'] > 0:
        msg += "💚 <i>ROI positivo! A estratégia está funcionando!</i>"
    elif lifetime['roi'] > -5:
        msg += "💛 <i>ROI próximo de zero. Ajustes podem melhorar.</i>"
    else:
        msg += "💡 <i>ROI negativo. Revisão da estratégia recomendada.</i>"
    
    return msg

