"""Scanner genérico de jogos para qualquer data."""
from __future__ import annotations
import asyncio
from datetime import datetime, timedelta
from typing import Any, Dict, List
import pytz
from sqlalchemy.exc import IntegrityError

from config.settings import (
    ZONE, HIGH_CONF_THRESHOLD, MIN_EV, MIN_PROB, WATCHLIST_DELTA, WATCHLIST_MIN_LEAD_MIN,
    get_all_betting_links, is_high_conf, was_high_conf_notified, mark_high_conf_notified,
    ONLY_HIGH_CONF_GAMES
)
from utils.logger import logger
from utils.stats import to_aware_utc, save_odd_history
from models.database import Game, SessionLocal
from scraping.fetchers import fetch_events_from_link
from scraping.betnacional import parse_local_datetime
from betting.decision import decide_bet, fetch_and_decide_picks, _is_total_goals_picks_enabled
from notifications.telegram import tg_send_message
from utils.formatters import fmt_pick_now, fmt_dawn_games_summary, fmt_today_games_summary
from watchlist.manager import wl_add
from scheduler.jobs import scheduler, fetch_events_smart


async def scan_games_for_date(
    date_offset: int = 0,
    send_summary: bool = False
) -> Dict[str, Any]:
    """
    Coleta e analisa jogos de uma data específica.
    
    Args:
        date_offset: 0 = hoje, 1 = amanhã, -1 = ontem, etc.
        send_summary: Se True, envia resumo via Telegram (usado para compatibilidade)
    
    Returns:
        Dict com estatísticas: {"analyzed": X, "selected": Y, "stored": Z}
    """
    stored_total = 0
    analyzed_total = 0
    chosen_view: List[Dict[str, Any]] = []
    
    analysis_date_local = datetime.now(ZONE).date() + timedelta(days=date_offset)
    date_str = "HOJE" if date_offset == 0 else "AMANHÃ" if date_offset == 1 else f"{date_offset:+d} dias"
    logger.info("📅 Iniciando varredura para %s (timezone %s): %s", date_str, ZONE, analysis_date_local.isoformat())
    
    backend_cfg = "playwright"
    
    with SessionLocal() as session:
        for url in get_all_betting_links():
            evs: List[Any] = []
            try:
                evs = await fetch_events_smart(url, backend_cfg)
            except Exception as e:
                logger.warning("Falha ao buscar %s: %s", url, e)
                continue
            
            analyzed_total += len(evs)
            
            for ev in evs:
                try:
                    start_utc = parse_local_datetime(getattr(ev, "start_local_str", ""))
                    if not start_utc:
                        continue
                    start_utc = to_aware_utc(start_utc)
                    
                    # Filtra apenas jogos da data alvo (no timezone local)
                    ev_date_local = start_utc.astimezone(ZONE).date()
                    if ev_date_local != analysis_date_local:
                        continue
                    
                    # Upsert do Game primeiro (sem campos de pick), depois roda decide_picks
                    # com fetch detalhado se ENABLE_TOTAL_GOALS_PICKS=true. Os campos legados
                    # de pick (g.pick, pick_prob, pick_ev, pick_reason, will_bet) serão
                    # preenchidos via mirror_match_result_to_game dentro de fetch_and_decide_picks.
                    g = session.query(Game).filter_by(ext_id=ev.ext_id, start_time=start_utc).one_or_none()
                    if g:
                        g.source_link = url
                        g.game_url = getattr(ev, "game_url", None) or g.game_url
                        g.competition = ev.competition or g.competition
                        g.team_home = ev.team_home or g.team_home
                        g.team_away = ev.team_away or g.team_away
                        g.odds_home = ev.odds_home
                        g.odds_draw = ev.odds_draw
                        g.odds_away = ev.odds_away
                        if g.status not in ("live", "ended"):
                            g.status = "live" if getattr(ev, "is_live", False) else "scheduled"
                    else:
                        g = Game(
                            ext_id=ev.ext_id,
                            source_link=url,
                            game_url=getattr(ev, "game_url", None),
                            competition=ev.competition,
                            country=getattr(ev, "country", None),
                            team_home=ev.team_home,
                            team_away=ev.team_away,
                            start_time=start_utc,
                            odds_home=ev.odds_home,
                            odds_draw=ev.odds_draw,
                            odds_away=ev.odds_away,
                            status="live" if getattr(ev, "is_live", False) else "scheduled",
                        )
                        session.add(g)
                        try:
                            session.flush()
                        except IntegrityError:
                            session.rollback()
                            g = session.query(Game).filter_by(ext_id=ev.ext_id, start_time=start_utc).one_or_none()
                            if not g:
                                continue
                            g.source_link = url
                            g.game_url = getattr(ev, "game_url", None) or g.game_url
                            g.competition = ev.competition or g.competition
                            g.country = getattr(ev, "country", None) or g.country
                            g.team_home = ev.team_home or g.team_home
                            g.team_away = ev.team_away or g.team_away
                            g.odds_home = ev.odds_home
                            g.odds_draw = ev.odds_draw
                            g.odds_away = ev.odds_away

                    # Decisão multi-market (1x2 sempre + total_goals atrás de feature flag)
                    picks_list = await fetch_and_decide_picks(
                        session, g, ev,
                        decision_source="scanner",
                        use_full_markets=_is_total_goals_picks_enabled(),
                    )
                    match_pick = next((p for p in picks_list if p.market == "match_result"), None)
                    will = bool(match_pick.will_bet) if match_pick else False
                    pick = match_pick.pick if match_pick else ""
                    pprob = float(match_pick.pick_prob or 0.0) if match_pick else 0.0
                    pev = float(match_pick.pick_ev or 0.0) if match_pick else 0.0
                    reason = match_pick.pick_reason if match_pick else ""

                    free_pass = is_high_conf(pprob)

                    # Se flag ONLY_HIGH_CONF_GAMES estiver ativa, apenas seleciona alta confiança
                    if ONLY_HIGH_CONF_GAMES:
                        should_save = free_pass  # Apenas alta confiança
                        if free_pass and not will:
                            reason = (reason or "Apenas alta confiança") + " | HIGH_CONF_ONLY"
                    else:
                        # Comportamento normal: seleciona se will=True ou alta confiança
                        should_save = will or free_pass

                    # Atualiza will_bet legado se foi selecionado (mantém True se já era True)
                    if should_save:
                        g.will_bet = True
                    elif g.will_bet is None:
                        g.will_bet = False
                    if reason:
                        g.pick_reason = reason
                    session.commit()
                    
                    # Se não foi selecionado, adiciona à watchlist se próximo do threshold
                    if not should_save:
                        # Watchlist: adiciona se estiver próximo do threshold
                        if (pev >= (MIN_EV - WATCHLIST_DELTA)) and (pprob >= (MIN_PROB - 0.05)):
                            minutes_until = int((start_utc - datetime.now(pytz.UTC)).total_seconds() / 60)
                            if minutes_until >= WATCHLIST_MIN_LEAD_MIN:
                                from utils.analytics_logger import log_watchlist_action
                                wl_add(session, ev.ext_id, url, start_utc)
                                log_watchlist_action(
                                    "add", ev.ext_id,
                                    f"Próximo do threshold (EV={pev:.3f}, prob={pprob:.3f})",
                                    metadata={"odds_home": ev.odds_home, "odds_draw": ev.odds_draw, "odds_away": ev.odds_away}
                                )
                                logger.info("👀 Adicionado à watchlist: %s vs %s", ev.team_home, ev.team_away)
                        # Jogo foi salvo mas não foi selecionado - não conta como "stored" para relatório
                        continue  # Pula processamento adicional se não foi selecionado
                    
                    # Jogo foi selecionado (will_bet=True) - processar normalmente
                    stored_total += 1
                    session.refresh(g)
                    
                    if free_pass or ((g.pick_prob or 0.0) >= HIGH_CONF_THRESHOLD):
                        try:
                            g.pick_reason = (g.pick_reason or "") + " HIGH_TRUST"
                            session.commit()
                        except Exception:
                            pass
                    
                    save_odd_history(session, g)
                    
                    g_start = to_aware_utc(g.start_time)
                    chosen_view.append({
                        "id": g.id,
                        "ext_id": g.ext_id,
                        "team_home": g.team_home,
                        "team_away": g.team_away,
                        "start_time": g_start,
                        "odds_home": float(g.odds_home or 0.0),
                        "odds_draw": float(g.odds_draw or 0.0),
                        "odds_away": float(g.odds_away or 0.0),
                        "pick": g.pick,
                        "pick_prob": float(g.pick_prob or 0.0),
                        "pick_ev": float(g.pick_ev or 0.0),
                    })
                    
                    logger.info(
                        "✅ SELECIONADO: %s vs %s | pick=%s | prob=%.1f%% | EV=%.1f%%",
                        g.team_home, g.team_away, g.pick, g.pick_prob * 100, g.pick_ev * 100
                    )
                    
                    # Envio per-pick: send_picks_for_game filtra picks individualmente
                    # (gate de high_conf agora aplica por pick, não por jogo inteiro).
                    try:
                        from notifications.telegram import send_picks_for_game
                        sent_count = send_picks_for_game(g, session)
                    except Exception as exc:
                        logger.exception("Falha em send_picks_for_game (scanner imediato) id=%s: %s", g.id, exc)
                        sent_count = 0

                    if sent_count > 0:
                        g.pick_reason = mark_high_conf_notified(g.pick_reason or "")
                        session.commit()
                        logger.info(f"✅ Palpite notificado para jogo {g.id} ({g.ext_id}) - {g.team_home} vs {g.team_away} — sent={sent_count}")
                    else:
                        from utils.analytics_logger import log_signal_suppression
                        log_signal_suppression(g.ext_id, "Nenhum pick passou o gate per-pick", g.pick_prob or 0.0, g.pick_ev or 0.0, game_id=g.id)
                        logger.debug(f"⏭️  Nenhum pick passou o gate (scanner imediato) para jogo {g.id}")
                    
                    # Agenda lembretes e watchers
                    from scheduler.jobs import _schedule_all_for_game
                    await _schedule_all_for_game(g)
                    
                except Exception:
                    session.rollback()
                    logger.exception("Erro ao processar evento %s vs %s", getattr(ev, "team_home", "?"), getattr(ev, "team_away", "?"))
            
            await asyncio.sleep(0.2)
    
    logger.info("🧾 Varredura concluída — analisados=%d | selecionados=%d | salvos=%d",
                analyzed_total, len(chosen_view), stored_total)
    
    return {
        "analyzed": analyzed_total,
        "selected": len(chosen_view),
        "stored": stored_total,
        "games": chosen_view
    }


async def send_dawn_games() -> bool:
    """
    Envia jogos da madrugada (00h-06h) do dia atual.
    Retorna True se enviou mensagem, False se não havia jogos.
    """
    today = datetime.now(ZONE).date()
    start_utc = ZONE.localize(datetime(today.year, today.month, today.day, 0, 0)).astimezone(pytz.UTC)
    end_utc = ZONE.localize(datetime(today.year, today.month, today.day, 6, 0)).astimezone(pytz.UTC)
    
    logger.info("🌙 Verificando jogos da madrugada (00:00-06:00)...")
    
    with SessionLocal() as session:
        games = session.query(Game).filter(
            Game.start_time >= start_utc,
            Game.start_time < end_utc,
            Game.will_bet.is_(True)
        ).order_by(Game.start_time).all()
        
        if not games:
            logger.info("⏭️  Nenhum jogo da madrugada encontrado. Mensagem não será enviada.")
            return False
        
        logger.info("✅ Encontrados %d jogos da madrugada. Enviando mensagem...", len(games))
        msg = fmt_dawn_games_summary(games, today)
        
        try:
            tg_send_message(msg, parse_mode="HTML", message_type="summary")
        except Exception:
            logger.exception("Falha ao enviar mensagem de jogos da madrugada")
            try:
                tg_send_message(msg, parse_mode=None, message_type="summary")
            except Exception:
                logger.exception("Falha ao enviar mensagem de jogos da madrugada (fallback)")
        
        return True


async def send_today_games() -> bool:
    """
    Envia jogos de hoje (06h-23h).
    Sempre envia mensagem, mesmo que vazia (para informar que não há jogos).
    """
    today = datetime.now(ZONE).date()
    start_utc = ZONE.localize(datetime(today.year, today.month, today.day, 6, 0)).astimezone(pytz.UTC)
    end_utc = ZONE.localize(datetime(today.year, today.month, today.day, 23, 59, 59)).astimezone(pytz.UTC)
    
    logger.info("🌅 Preparando resumo de jogos de hoje (06:00-23:59)...")
    
    with SessionLocal() as session:
        games = session.query(Game).filter(
            Game.start_time >= start_utc,
            Game.start_time <= end_utc,
            Game.will_bet.is_(True)
        ).order_by(Game.start_time).all()
        
        # Conta total analisado (para estatísticas)
        total_analyzed = session.query(Game).filter(
            Game.start_time >= ZONE.localize(datetime(today.year, today.month, today.day, 0, 0)).astimezone(pytz.UTC),
            Game.start_time <= end_utc
        ).count()
        
        logger.info("📊 Jogos de hoje: %d selecionados (de %d analisados)", len(games), total_analyzed)
        msg = fmt_today_games_summary(games, today, total_analyzed)
        
        try:
            tg_send_message(msg, parse_mode="HTML", message_type="summary")
        except Exception:
            logger.exception("Falha ao enviar mensagem de jogos de hoje")
            try:
                tg_send_message(msg, parse_mode=None, message_type="summary")
            except Exception:
                logger.exception("Falha ao enviar mensagem de jogos de hoje (fallback)")
        
        return True

