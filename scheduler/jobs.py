"""Jobs agendados do sistema."""
import os
import asyncio
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.date import DateTrigger
from sqlalchemy.exc import IntegrityError

from config.settings import (
    APP_TZ, MORNING_HOUR, WATCHLIST_RESCAN_MIN, ZONE,
    HIGH_CONF_THRESHOLD, MIN_EV, MIN_PROB, WATCHLIST_DELTA, WATCHLIST_MIN_LEAD_MIN,
    START_ALERT_MIN, LATE_WATCH_WINDOW_MIN, get_all_betting_links,
    is_high_conf, was_high_conf_notified, mark_high_conf_notified,
    ONLY_HIGH_CONF_GAMES,
    MONITOR_LIVE_INTERVAL_MIN, FLUSH_BUFFERS_INTERVAL_MIN,
    UPDATE_LIVE_STATUS_INTERVAL_MIN, FETCH_FINISHED_INTERVAL_MIN,
)
from utils.logger import logger
from utils.stats import to_aware_utc, save_odd_history
from utils.formatters import fmt_pick_now, fmt_watch_upgrade, fmt_live_bet_opportunity, format_night_scan_summary, fmt_combined_bet
from models.database import Game, LiveGameTracker, SessionLocal, CombinedBet
from scraping.fetchers import fetch_events_from_link, fetch_game_result, _fetch_requests_async, _fetch_with_playwright
from config.settings import HAS_PLAYWRIGHT
from scraping.betnacional import parse_local_datetime, scrape_live_game_data
from betting.decision import (
    decide_bet, decide_live_bet_opportunity,
    fetch_and_decide_picks, _is_total_goals_picks_enabled,
)
from notifications.telegram import tg_send_message
from watchlist.manager import wl_load, wl_save, wl_add, wl_remove

scheduler = AsyncIOScheduler(
    timezone=APP_TZ,
    job_defaults={
        "misfire_grace_time": 120,  # Aumentado para 2 minutos
        "coalesce": True,
        "max_instances": 1
    }
)


async def send_reminder_job(game_id: int):
    """Job de lembrete."""
    from utils.formatters import fmt_reminder
    
    with SessionLocal() as s:
        g = s.get(Game, game_id)
        if not g or not g.will_bet:
            return
        tg_send_message(fmt_reminder(g), message_type="reminder", game_id=g.id, ext_id=g.ext_id)
        logger.info("🔔 Lembrete enviado para jogo id=%s", game_id)


async def _schedule_all_for_game(g: Game):
    """Agenda lembrete T-15, alerta 'começa já já' e watcher."""
    
    try:
        now_utc = datetime.now(pytz.UTC)
        g_start = to_aware_utc(g.start_time)

        # Lembrete T-15
        reminder_at = (g_start - timedelta(minutes=START_ALERT_MIN))
        if reminder_at > now_utc:
            try:
                scheduler.add_job(
                    send_reminder_job,
                    trigger=DateTrigger(run_date=reminder_at),
                    args=[g.id],
                    id=f"rem_{g.id}",
                    replace_existing=True,
                )
            except Exception:
                logger.exception("Falha ao agendar lembrete do jogo id=%s", g.id)

        # Alerta "começa já já"
        if (now_utc >= reminder_at) and (now_utc < g_start):
            try:
                local_kick = g_start.astimezone(ZONE).strftime('%H:%M')
                tg_send_message(
                    f"🚨 <b>Começa já já</b> ({local_kick})\n"
                    f"{g.team_home} vs {g.team_away}\n"
                    f"Pick: <b>{g.pick.upper()}</b>",
                    parse_mode="HTML",
                    message_type="reminder",
                    game_id=g.id,
                    ext_id=g.ext_id
                )
            except Exception:
                logger.exception("Falha ao enviar alerta 'começa agora' id=%s", g.id)

        # Watcher
        if g_start > now_utc:
            try:
                scheduler.add_job(
                    watch_game_until_end_job,
                    trigger=DateTrigger(run_date=g_start),
                    args=[g.id],
                    id=f"watch_{g.id}",
                    replace_existing=True,
                )
            except Exception:
                logger.exception("Falha ao agendar watcher do jogo id=%s", g.id)
        else:
            limit_late = g_start + timedelta(minutes=LATE_WATCH_WINDOW_MIN)
            if now_utc < limit_late:
                try:
                    asyncio.create_task(watch_game_until_end_job(g.id))
                    logger.info("▶️ Watcher iniciado imediatamente (id=%s).", g.id)
                except Exception:
                    logger.exception("Falha ao iniciar watcher imediato id=%s", g.id)

    except Exception:
        logger.exception("Falha no agendamento do jogo id=%s", g.id)


async def night_scan_for_early_games():
    """Varredura noturna específica para jogos da madrugada (00:00 às 06:00)."""
    logger.info("🌙 Iniciando varredura noturna para jogos da madrugada...")

    # Janela: meia-noite → 06:00 do dia seguinte (no fuso APP_TZ), tudo convertido para UTC
    tomorrow = datetime.now(ZONE).date() + timedelta(days=1)
    start_window = ZONE.localize(datetime(tomorrow.year, tomorrow.month, tomorrow.day, 0, 0)).astimezone(pytz.UTC)
    end_window = ZONE.localize(datetime(tomorrow.year, tomorrow.month, tomorrow.day, 6, 0)).astimezone(pytz.UTC)

    stored_total = 0
    analyzed_total = 0
    early_games: List[Dict[str, Any]] = []

    backend_cfg = "playwright"
    logger.info(f"📅 Analisando jogos da madrugada de {tomorrow.strftime('%d/%m/%Y')} (00:00 às 06:00)")

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
                    # Parse e normalização do horário
                    start_utc = parse_local_datetime(getattr(ev, "start_local_str", ""))
                    if not start_utc:
                        continue
                    start_utc = to_aware_utc(start_utc)

                    # Filtro: apenas jogos entre 00:00 e 06:00 do dia seguinte
                    if not (start_window <= start_utc < end_window):
                        continue

                    # Upsert do Game primeiro (sem pick), depois decide_picks com fetch
                    # detalhado se feature flag ativa. mirror_match_result_to_game preenche
                    # os campos legados de pick no Game.
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
                            g.status = "scheduled"
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
                            status="scheduled",
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

                    # Decisão multi-market
                    picks_list = await fetch_and_decide_picks(
                        session, g, ev,
                        decision_source="night_scan",
                        use_full_markets=_is_total_goals_picks_enabled(),
                    )
                    match_pick = next((p for p in picks_list if p.market == "match_result"), None)
                    will = bool(match_pick.will_bet) if match_pick else False
                    pick = match_pick.pick if match_pick else ""
                    pprob = float(match_pick.pick_prob or 0.0) if match_pick else 0.0
                    pev = float(match_pick.pick_ev or 0.0) if match_pick else 0.0
                    reason = match_pick.pick_reason if match_pick else ""

                    # PASSE LIVRE: alta confiança entra mesmo sem will
                    free_pass = is_high_conf(pprob)

                    # Se flag ONLY_HIGH_CONF_GAMES estiver ativa, apenas seleciona alta confiança
                    if ONLY_HIGH_CONF_GAMES:
                        should_save = free_pass  # Apenas alta confiança
                        if free_pass and not will:
                            will = True
                            reason = (reason or "Apenas alta confiança") + " | HIGH_CONF_ONLY"
                    else:
                        # Comportamento normal
                        if not will and free_pass:
                            will = True
                            reason = (reason or "Passe livre") + " | HIGH_TRUST"
                        should_save = will  # Para madrugada, só salva se will=True (já inclui free_pass)

                    # Atualiza will_bet legado se foi selecionado
                    if should_save:
                        g.will_bet = True
                    elif g.will_bet is None:
                        g.will_bet = False
                    if reason:
                        g.pick_reason = reason
                    session.commit()
                    
                    if not should_save:
                        # Ainda assim, avaliar ADD na watchlist
                        now_utc = datetime.now(pytz.UTC)
                        lead_ok = (start_utc - now_utc) >= timedelta(minutes=WATCHLIST_MIN_LEAD_MIN)
                        near_cut = (pev >= (MIN_EV - WATCHLIST_DELTA)) and (pev < MIN_EV)
                        prob_ok = pprob >= MIN_PROB

                        if lead_ok and near_cut and prob_ok and not getattr(ev, "is_live", False):
                            added = wl_add(session, ev.ext_id, url, start_utc)
                            if added:
                                logger.info(
                                    "👀 Adicionado à WATCHLIST (madrugada): %s vs %s | EV=%.3f | prob=%.3f | start=%s",
                                    ev.team_home, ev.team_away, pev, pprob, start_utc.isoformat()
                                )
                        continue  # Pula processamento adicional se não foi selecionado
                    
                    # Jogo foi selecionado (will_bet=True) - processar normalmente
                    stored_total += 1
                    session.refresh(g)

                    # Marca tag se for alta confiança
                    if free_pass or ((g.pick_prob or 0.0) >= HIGH_CONF_THRESHOLD):
                        try:
                            g.pick_reason = (g.pick_reason or "") + " HIGH_TRUST"
                            session.commit()
                        except Exception:
                            session.rollback()

                    # Salva histórico de odds
                    save_odd_history(session, g)

                    # Adiciona para o resumo
                    early_games.append({
                        "id": g.id,
                        "team_home": g.team_home,
                        "team_away": g.team_away,
                        "start_time": g.start_time,
                        "pick": g.pick,
                        "odds_home": float(g.odds_home or 0),
                        "odds_draw": float(g.odds_draw or 0),
                        "odds_away": float(g.odds_away or 0),
                        "pick_prob": float(g.pick_prob or 0),
                        "pick_ev": float(g.pick_ev or 0),
                    })

                    logger.info(
                        "✅ MADRUGADA: %s vs %s | %s | pick=%s | início=%s",
                        g.team_home, g.team_away,
                        start_utc.astimezone(ZONE).strftime("%H:%M"),
                        g.pick,
                        getattr(ev, "start_local_str", "?")
                    )

                    # Envio per-pick: send_picks_for_game filtra picks individualmente
                    # (gate de high_conf agora aplica por pick, não por jogo inteiro).
                    try:
                        from notifications.telegram import send_picks_for_game
                        sent_count = send_picks_for_game(g, session)
                    except Exception as exc:
                        logger.exception("Falha em send_picks_for_game (madrugada) id=%s: %s", g.id, exc)
                        sent_count = 0

                    if sent_count > 0:
                        g.pick_reason = mark_high_conf_notified(g.pick_reason or "")
                        session.commit()
                        logger.info(f"✅ Palpite notificado (madrugada) para jogo {g.id} ({g.ext_id}) — sent={sent_count}")
                    else:
                        logger.debug(f"⏭️  Nenhum pick passou o gate (madrugada) para jogo {g.id}")

                    # Agendamentos
                    await _schedule_all_for_game(g)

                except Exception:
                    session.rollback()
                    logger.exception(
                        "Erro ao processar evento noturno %s vs %s (url=%s)",
                        getattr(ev, "team_home", "?"),
                        getattr(ev, "team_away", "?"),
                        url,
                    )

    # Resumo da varredura noturna
    if early_games:
        msg = format_night_scan_summary(tomorrow, analyzed_total, early_games)
        tg_send_message(msg, message_type="summary")

    logger.info("🌙 Varredura noturna concluída — analisados=%d | selecionados=%d",
                analyzed_total, len(early_games))


async def rescan_watchlist_job():
    """
    Rechecagem periódica da watchlist.
    Força o uso do Playwright para garantir que os jogos sejam carregados corretamente.
    Promove itens da watchlist a PICK quando cruzam os critérios.
    Alta confiança tem passe livre (entra mesmo sem cruzar EV/PROB).
    """
    logger.info("🔄 Rechecando WATCHLIST…")
    now_utc = datetime.now(pytz.UTC)

    with SessionLocal() as session:
        wl = wl_load(session)
        items = wl.get("items", [])
        if not items:
            logger.info("WATCHLIST vazia.")
            return

        # 1) Agrupa por link para baixar páginas uma vez só
        by_link: Dict[str, List[Dict[str, str]]] = {}
        for it in items:
            by_link.setdefault(it["link"], []).append(it)

        # 2) Para cada link, buscar eventos e indexar por ext_id
        page_cache: Dict[str, Dict[str, Any]] = {}
        for link, its in by_link.items():
            try:
                evs = await fetch_events_smart(link, "playwright")  # força playwright (com bypass API se ativo)
            except Exception as e:
                logger.warning("Falha ao buscar página da watchlist %s: %s", link, e)
                evs = []
            page_cache[link] = {e.ext_id: e for e in evs}

        # 3) Itera itens; remove passados; promove se cruzou o corte
        upgraded: List[str] = []
        removed_expired = 0

        # Usamos uma cópia para poder remover enquanto iteramos
        for it in list(items):
            ext_id = it["ext_id"]
            link = it["link"]
            try:
                start_utc = to_aware_utc(datetime.fromisoformat(it["start_time"]))
            except Exception:
                # Se a data estiver inválida, removemos o item
                removed_expired += wl_remove(session, lambda x, eid=ext_id: x["ext_id"] == eid)
                continue

            page = page_cache.get(link, {})
            ev = page.get(ext_id)

            # === Remoção: só expira se passou do horário; alta confiança fica até +6h ===
            if start_utc <= now_utc:
                # Precisa calcular a probabilidade primeiro
                ev_prob = None
                if ev:
                    _, _, ev_prob, _, _ = decide_bet(
                        ev.odds_home, ev.odds_draw, ev.odds_away, ev.competition, (ev.team_home, ev.team_away)
                    )
                high_conf = is_high_conf(ev_prob) if ev_prob else False
                if high_conf and now_utc <= (start_utc + timedelta(hours=6)):
                    logger.info("⏰ Mantido (HIGH_TRUST até +6h): %s (%s)", ext_id, it.get("start_time"))
                else:
                    removed_expired += wl_remove(
                        session,
                        lambda x, eid=ext_id, st=it["start_time"]: x["ext_id"] == eid and x["start_time"] == st
                    )
                continue

            if not ev:
                # evento sumiu da página; pode ser mudança de card/rota — mantemos temporariamente
                continue

            # Decisão preliminar (lightweight, sem DB writes) só pra decidir se promove.
            # Quando promove, refazemos com fetch_and_decide_picks pra persistir Pick e
            # opcionalmente analisar Over/Under.
            will, pick, pprob, pev, reason = decide_bet(
                ev.odds_home, ev.odds_draw, ev.odds_away, ev.competition, (ev.team_home, ev.team_away)
            )

            # PASSE LIVRE: alta confiança promove mesmo sem cruzar thresholds
            free_pass = is_high_conf(pprob)

            # Se flag ONLY_HIGH_CONF_GAMES estiver ativa, apenas promove alta confiança
            if ONLY_HIGH_CONF_GAMES:
                promote = free_pass  # Apenas alta confiança
            else:
                promote = free_pass or (will and (pprob >= MIN_PROB) and (pev >= MIN_EV))

            if promote:
                # Upsert do Game primeiro (sem pick), depois decide_picks com fetch detalhado.
                # mirror_match_result_to_game preenche os campos legados de pick no Game.
                g = session.query(Game).filter_by(ext_id=ext_id, start_time=start_utc).one_or_none()
                if g:
                    g.source_link = link
                    g.game_url = getattr(ev, "game_url", None) or g.game_url
                    g.competition = ev.competition or g.competition
                    g.team_home = ev.team_home or g.team_home
                    g.team_away = ev.team_away or g.team_away
                    g.odds_home = ev.odds_home
                    g.odds_draw = ev.odds_draw
                    g.odds_away = ev.odds_away
                    g.status = "scheduled"
                else:
                    g = Game(
                        ext_id=ext_id,
                        source_link=link,
                        game_url=getattr(ev, "game_url", None),
                        competition=ev.competition,
                        country=getattr(ev, "country", None),
                        team_home=ev.team_home,
                        team_away=ev.team_away,
                        start_time=start_utc,
                        odds_home=ev.odds_home,
                        odds_draw=ev.odds_draw,
                        odds_away=ev.odds_away,
                        status="scheduled",
                    )
                    session.add(g)
                    try:
                        session.flush()
                    except IntegrityError:
                        session.rollback()
                        g = session.query(Game).filter_by(ext_id=ext_id, start_time=start_utc).one_or_none()
                        if not g:
                            continue
                        g.source_link = link
                        g.game_url = getattr(ev, "game_url", None) or g.game_url
                        g.competition = ev.competition or g.competition
                        g.country = getattr(ev, "country", None) or g.country
                        g.team_home = ev.team_home or g.team_home
                        g.team_away = ev.team_away or g.team_away
                        g.odds_home = ev.odds_home
                        g.odds_draw = ev.odds_draw
                        g.odds_away = ev.odds_away
                        g.status = "scheduled"

                # Decisão multi-market com fetch (se feature flag ativa)
                picks_list = await fetch_and_decide_picks(
                    session, g, ev,
                    decision_source="watchlist_upgrade",
                    use_full_markets=_is_total_goals_picks_enabled(),
                )
                match_pick = next((p for p in picks_list if p.market == "match_result"), None)
                if match_pick is not None:
                    will = bool(match_pick.will_bet)
                    pick = match_pick.pick
                    pprob = float(match_pick.pick_prob or 0.0)
                    pev = float(match_pick.pick_ev or 0.0)
                    reason = match_pick.pick_reason or ""
                    free_pass = is_high_conf(pprob)

                # Marcadores legados: razão com tag de upgrade + will_bet=True
                if free_pass:
                    reason = (reason or "Upgrade watchlist") + " | HIGH_TRUST"
                else:
                    reason = "Upgrade watchlist"
                g.will_bet = True
                g.pick_reason = reason
                g.status = "scheduled"
                session.commit()

                # Salva histórico de odds quando promove
                save_odd_history(session, g)

                # NOTIFICAÇÃO — só envia se ALTA CONFIANÇA e sem duplicar (usando banco de dados)
                try:
                    from utils.notification_tracker import should_notify_pick, mark_pick_notified
                    
                    should_notify, reason = should_notify_pick(g, check_high_conf=True)
                    
                    if should_notify:
                        from utils.telegram_helpers import send_upgrade_with_buffer
                        send_upgrade_with_buffer(g)
                        # Marca como notificado no banco de dados (persiste após reiniciar)
                        mark_pick_notified(g, session)
                        # Mantém compatibilidade com sistema antigo (pick_reason)
                        g.pick_reason = mark_high_conf_notified(g.pick_reason or "")
                        session.commit()
                        logger.info(f"✅ Palpite notificado (watchlist upgrade) para jogo {g.id} ({g.ext_id})")
                    else:
                        logger.debug(f"⏭️  Palpite suprimido (watchlist upgrade) para jogo {g.id}: {reason}")
                except Exception:
                    logger.exception("Falha ao notificar upgrade watchlist id=%s", g.id)

                # Agendamentos
                try:
                    asyncio.create_task(_schedule_all_for_game(g))
                except Exception:
                    logger.exception("Falha ao agendar jobs para id=%s", g.id)

                # remover esse item da watchlist
                wl_remove(
                    session,
                    lambda x, eid=ext_id, st=it["start_time"]: x["ext_id"] == eid and x["start_time"] == st
                )
                upgraded.append(ext_id)

        if removed_expired:
            logger.info("🧹 WATCHLIST: %d itens expirados removidos.", removed_expired)
        
        if upgraded:
            logger.info("⬆️ WATCHLIST: promovidos %d itens: %s", len(upgraded), ", ".join(upgraded))
            # Faz flush dos buffers após upgrades para garantir envio rápido
            try:
                from utils.telegram_message_buffer import flush_all_buffers
                await flush_all_buffers()
            except Exception:
                pass  # Não falha o job se flush falhar
        else:
            logger.info("ℹ️ WATCHLIST: nenhuma promoção nesta passada.")


async def hourly_rescan_job():
    """
    Job executado a cada hora para reavaliar as odds dos jogos do dia.
    Dispara notificação apenas quando o jogo virar ALTA CONFIANÇA (e não repetir).
    """
    logger.info("🔄 Iniciando reavaliação horária dos jogos do dia.")
    now_utc = datetime.now(pytz.UTC)
    today = now_utc.astimezone(ZONE).date()

    with SessionLocal() as session:
        # Busca todos os jogos agendados para hoje que ainda não começaram
        day_start = ZONE.localize(datetime(today.year, today.month, today.day, 0, 0)).astimezone(pytz.UTC)
        day_end = ZONE.localize(datetime(today.year, today.month, today.day, 23, 59)).astimezone(pytz.UTC)

        games_to_rescan = (
            session.query(Game)
            .filter(
                Game.start_time >= day_start,
                Game.start_time <= day_end,
                Game.status == "scheduled",
                Game.start_time > now_utc  # Ainda não começou
            )
            .all()
        )

        for game in games_to_rescan:
            try:
                # Re-fetch da página do jogo
                html = await _fetch_requests_async(game.source_link)
                from scraping.betnacional import try_parse_events
                evs = try_parse_events(html, game.source_link)
                
                # Encontra o evento correspondente
                ev = None
                for e in evs:
                    if e.ext_id == game.ext_id:
                        ev = e
                        break
                
                if not ev:
                    continue

                # Captura prob anterior ANTES de fetch_and_decide_picks (que via mirror
                # pode atualizar game.pick_prob).
                prev_high = (game.pick_prob or 0.0) >= HIGH_CONF_THRESHOLD

                # Recalcula a decisão (multi-market) e persiste Pick row(s).
                # mirror_match_result_to_game preenche os campos legados de pick no Game.
                picks_list = await fetch_and_decide_picks(
                    session, game, ev,
                    decision_source="hourly_rescan",
                    use_full_markets=_is_total_goals_picks_enabled(),
                )
                match_pick = next((p for p in picks_list if p.market == "match_result"), None)
                will = bool(match_pick.will_bet) if match_pick else False
                pick = match_pick.pick if match_pick else ""
                pprob = float(match_pick.pick_prob or 0.0) if match_pick else 0.0
                pev = float(match_pick.pick_ev or 0.0) if match_pick else 0.0
                reason = match_pick.pick_reason if match_pick else ""

                new_high = (pprob or 0.0) >= HIGH_CONF_THRESHOLD

                # 1) Se virou ALTA CONFIANÇA agora (transição) e ainda não foi notificado -> dispara (usando banco de dados)
                from utils.notification_tracker import was_pick_notified
                if new_high and (not prev_high) and not was_pick_notified(game):
                    game.odds_home = ev.odds_home
                    game.odds_draw = ev.odds_draw
                    game.odds_away = ev.odds_away
                    game.pick = pick
                    game.pick_prob = pprob
                    game.pick_ev = pev
                    game.pick_reason = (reason or "Upgrade horário") + " | HIGH_TRUST"
                    session.commit()

                    # histórico antes da notificação
                    save_odd_history(session, game)

                    # notifica uma única vez (usando banco de dados)
                    try:
                        # Já verificamos acima que não foi notificado, então pode enviar
                        # Multi-pick: cobre match_result + total_goals quando houver.
                        try:
                            from notifications.telegram import send_picks_for_game
                            sent_count = send_picks_for_game(game, session)
                        except Exception:
                            sent_count = 0
                            logger.exception("Falha em send_picks_for_game (hourly transição) id=%s", game.id)

                        game.pick_reason = mark_high_conf_notified(game.pick_reason or "")
                        session.commit()
                        logger.info(f"✅ Palpite notificado (hourly rescan - transição alta confiança) para jogo {game.id} ({game.ext_id}) — sent={sent_count}")
                    except Exception:
                        logger.exception("Falha ao notificar alta confiança (hourly) id=%s", game.id)

                    # garante agendamentos/prioridade
                    try:
                        asyncio.create_task(_schedule_all_for_game(game))
                    except Exception:
                        logger.exception("Falha ao agendar jobs após alta confiança id=%s", game.id)

                    logger.info("🚀 Virou ALTA CONFIANÇA (id=%s) prob=%.3f", game.id, pprob)
                    continue  # já tratou este jogo

                # 2) Caso não tenha virado alta confiança: mantém seu critério original de upgrade por EV
                if will and pev > ((game.pick_ev or 0.0) + 0.05):
                    old_ev = game.pick_ev or 0.0
                    game.odds_home = ev.odds_home
                    game.odds_draw = ev.odds_draw
                    game.odds_away = ev.odds_away
                    game.pick = pick
                    game.pick_prob = pprob
                    game.pick_ev = pev
                    game.pick_reason = f"Upgrade horário (EV antigo: {old_ev*100:.1f}%)"
                    session.commit()

                    # Salva histórico
                    save_odd_history(session, game)

                    # Envio per-pick: send_picks_for_game filtra picks individualmente
                    # (gate de high_conf agora aplica por pick, não por jogo inteiro).
                    try:
                        from notifications.telegram import send_picks_for_game
                        sent_count = send_picks_for_game(game, session)
                    except Exception as exc:
                        logger.exception("Falha em send_picks_for_game (upgrade horário) id=%s: %s", game.id, exc)
                        sent_count = 0

                    if sent_count > 0:
                        game.pick_reason = mark_high_conf_notified(game.pick_reason or "")
                        session.commit()
                        asyncio.create_task(_schedule_all_for_game(game))
                        logger.info(f"✅ Palpite notificado (upgrade horário) para jogo {game.id} ({game.ext_id}) — sent={sent_count}")
                    else:
                        logger.info(
                            "📈 Jogo %s atualizado por EV, sem notificação (prob=%.3f; high_notified=%s)",
                            game.id, game.pick_prob or 0.0, was_high_conf_notified(game.pick_reason or "")
                        )

            except Exception as e:
                logger.exception(f"Erro ao reavaliar jogo {game.id}: {e}")

        session.commit()


async def update_games_to_live_status():
    """
    Atualiza status de jogos de 'scheduled' para 'live' quando o horário de início chegar.
    Executa a cada minuto para detectar jogos que acabaram de começar.
    """
    now_utc = datetime.now(pytz.UTC)
    
    with SessionLocal() as session:
        # Busca jogos que deveriam estar ao vivo (start_time <= now, mas ainda estão como scheduled)
        games_to_activate = (
            session.query(Game)
            .filter(
                Game.status == "scheduled",
                Game.will_bet.is_(True),
                Game.start_time <= now_utc,
                Game.start_time >= now_utc - timedelta(minutes=5)  # Janela de 5min para evitar reprocessar
            )
            .all()
        )
        
        for game in games_to_activate:
            game.status = "live"
            logger.info("▶️ Jogo %d (%s vs %s) iniciado - status atualizado para 'live'", 
                       game.id, game.team_home, game.team_away)
        
        if games_to_activate:
            session.commit()
            logger.info("✅ %d jogo(s) atualizado(s) para status 'live'", len(games_to_activate))


def _get_live_games_within_window(session, now_utc: datetime):
    """
    Busca jogos ao vivo que estão dentro da janela de tempo (2h30min após início).
    
    Args:
        session: Sessão do banco de dados
        now_utc: Timestamp atual em UTC
    
    Returns:
        Lista de jogos ao vivo ou lista vazia
    """
    # Verifica se há jogos pré-selecionados antes de iniciar monitoramento
    preselected_count = session.query(Game).filter(Game.will_bet.is_(True)).count()
    if preselected_count == 0:
        logger.debug("⏭️  Nenhum jogo pré-selecionado. Monitoramento ao vivo não executado.")
        return []
    
    # Busca apenas jogos que estão dentro do horário do jogo
    # Considera janela de 2h30min após o início (jogo normal + prorrogação)
    game_window_end = now_utc - timedelta(hours=2, minutes=30)
    
    # Usar eager loading para evitar N+1 queries
    from sqlalchemy.orm import joinedload
    
    live_games = (
        session.query(Game)
        .options(joinedload(Game.tracker))  # Carrega tracker junto com games
        .filter(
            Game.status == "live",
            Game.will_bet.is_(True),  # Só monitora jogos pré-selecionados
            Game.start_time >= game_window_end,  # Jogo começou há menos de 2h30min
            Game.start_time <= now_utc  # Jogo já começou
        )
        .all()
    )
    
    return live_games


def _ensure_tracker_exists(session, game: Game, now_utc: datetime) -> LiveGameTracker:
    """
    Garante que o tracker existe para um jogo, criando se necessário.
    
    Args:
        session: Sessão do banco de dados
        game: Jogo para o qual criar/obter tracker
        now_utc: Timestamp atual em UTC
    
    Returns:
        LiveGameTracker do jogo
    """
    tracker = game.tracker
    if not tracker:
        tracker = LiveGameTracker(
            game_id=game.id,
            ext_id=game.ext_id,
            last_analysis_time=now_utc - timedelta(minutes=5)
        )
        session.add(tracker)
        session.commit()

        # Envia mensagem de "Análise em Andamento"
        tg_send_message(
            f"🔍 <b>ANÁLISE AO VIVO INICIADA</b>\n"
            f"Estamos monitorando <b>{game.team_home} vs {game.team_away}</b> em busca de oportunidades de valor.\n"
            f"Você será notificado assim que uma aposta for validada.",
            message_type="live_opportunity",
            game_id=game.id,
            ext_id=game.ext_id
        )
        logger.info(f"🔍 Análise iniciada para jogo {game.id}: {game.team_home} vs {game.team_away}")
    
    return tracker


async def _update_game_tracker(tracker: LiveGameTracker, game: Game, now_utc: datetime):
    """
    Atualiza o tracker com os dados atuais do jogo.
    
    Args:
        tracker: Tracker do jogo
        game: Jogo sendo monitorado
        now_utc: Timestamp atual em UTC
    """
    # Scrapeia os dados atuais da página do jogo
    source_url = game.game_url or game.source_link
    
    # Tentar primeiro com requests (mais rápido), depois fallback para Playwright
    html = None
    try:
        html = await _fetch_requests_async(source_url, has_fallback=True)
    except Exception as e:
        logger.warning(f"Falha ao buscar HTML com requests para jogo {game.ext_id}: {e}. Tentando fallback Playwright...")
        if HAS_PLAYWRIGHT:
            try:
                html = await _fetch_with_playwright(source_url)
                logger.info(f"✅ Sucesso com fallback Playwright para jogo {game.ext_id}")
            except Exception as e2:
                logger.error(f"Falha também no fallback Playwright para jogo {game.ext_id}: {e2}")
                raise Exception(f"Falha ao buscar dados do jogo: requests ({e}) e playwright ({e2})")
        else:
            logger.error(f"Playwright não disponível, não há fallback para jogo {game.ext_id}")
            raise
    
    if html is None:
        raise Exception(f"Não foi possível obter HTML para jogo {game.ext_id}")
    
    live_data = scrape_live_game_data(html, game.ext_id, source_url=source_url)

    # Atualiza as estatísticas no tracker
    tracker.current_score = live_data["stats"].get("score")
    tracker.current_minute = live_data["stats"].get("match_time")
    tracker.stats_snapshot = live_data["stats"]  # Salva snapshot completo
    tracker.last_analysis_time = now_utc
    
    return live_data


def _is_game_finished(match_time: str) -> bool:
    """
    Verifica se um jogo terminou baseado no tempo do jogo.
    
    Args:
        match_time: String com tempo do jogo (ex: "45'", "FT", "90+")
    
    Returns:
        True se jogo terminou
    """
    if not match_time:
        return False
    
    match_time_upper = match_time.upper()
    game_finished_indicators = ["FT", "FINAL", "FIM", "TERMINADO", "ENDED", "90'", "90+"]
    return any(indicator in match_time_upper for indicator in game_finished_indicators)


async def _handle_finished_game(session, game: Game, tracker: LiveGameTracker, now_utc: datetime):
    """
    Processa um jogo que acabou de terminar.
    
    Args:
        session: Sessão do banco de dados
        game: Jogo terminado
        tracker: Tracker do jogo
        now_utc: Timestamp atual em UTC
    
    Returns:
        True se jogo foi processado com sucesso, False caso contrário
    """
    logger.info(f"🏁 Jogo {game.id} ({game.team_home} vs {game.team_away}) terminou detectado ao vivo. Buscando resultado...")
    
    # Marca como terminado
    game.status = "ended"
    session.commit()
    
    # Busca resultado final
    from scraping.fetchers import fetch_game_result
    from datetime import datetime
    import pytz
    result_data = await fetch_game_result(game.ext_id, game.game_url or game.source_link)
    
    if result_data:
        game.outcome = result_data.get("outcome")
        game.final_score_home = result_data.get("home_goals")
        game.final_score_away = result_data.get("away_goals")
        game.final_score = result_data.get("score")
        game.result_fetched_at = datetime.now(pytz.UTC)
        game.hit = (game.outcome == game.pick) if game.pick else None  # mirror legado pra match_result

        # Resolve TODOS os picks multi-mercado (match_result + total_goals quando houver)
        try:
            from betting.result_resolver import resolve_picks_for_game
            resolve_picks_for_game(session, game)
        except Exception as exc:
            logger.warning(f"Falha ao resolver picks pro game {game.id}: {exc}")

        result_msg = "✅ ACERTOU" if game.hit else "❌ ERROU" if game.hit is False else "⚠️ SEM PALPITE"
        score_str = f" ({game.final_score})" if game.final_score else ""
        from utils.logger import log_with_context
        log_with_context(
            "info",
            f"Resultado obtido para jogo: {game.outcome}{score_str} | {result_msg}",
            game_id=game.id,
            ext_id=game.ext_id,
            stage="fetch_result",
            status="success",
            extra_fields={"outcome": game.outcome, "score": game.final_score, "hit": game.hit, "result_msg": result_msg}
        )
        
        # Não enviar mensagem individual; envio será consolidado pelo job periódico
        
        # Atualiza resultado de apostas combinadas que incluíam este jogo
        try:
            from betting.combined_bets import update_combined_bet_result
            from utils.formatters import fmt_combined_bet_result
            # Busca apostas combinadas pendentes que incluem este jogo
            pending_bets = session.query(CombinedBet).filter(
                CombinedBet.status == "pending"
            ).all()

            for bet in pending_bets:
                if game.id in bet.game_ids:
                    result_status = update_combined_bet_result(bet, session)
                    if result_status in ("won", "lost"):
                        session.commit()
                        try:
                            msg = fmt_combined_bet_result(bet, session)
                            tg_send_message(msg, parse_mode="HTML", message_type="combined_result")
                            logger.info("📊 Resultado de múltipla #%s enviado: %s", bet.id, result_status)
                        except Exception:
                            logger.exception("Erro ao enviar notificação da múltipla #%s", bet.id)
        except Exception:
            logger.exception(f"Erro ao atualizar apostas combinadas após jogo {game.id}")
        
        # Tenta enviar resumo diário se todos os jogos do dia terminaram
        try:
            await maybe_send_daily_wrapup()
        except Exception:
            logger.exception(f"Erro ao verificar resumo diário após jogo {game.id}")
        
        session.commit()
        return True
    else:
        logger.warning(f"⚠️ Não foi possível obter resultado para jogo {game.id}, tentando novamente mais tarde")
        # Agenda watch_game_until_end_job para tentar novamente
        asyncio.create_task(watch_game_until_end_job(game.id))
        return False


async def _handle_active_game(session, game: Game, tracker: LiveGameTracker, live_data: Dict[str, Any], now_utc: datetime):
    """
    Processa um jogo que ainda está em andamento, procurando oportunidades de aposta.
    
    Args:
        session: Sessão do banco de dados
        game: Jogo em andamento
        tracker: Tracker do jogo
        live_data: Dados ao vivo do jogo
        now_utc: Timestamp atual em UTC
    """
    # ETAPA 1: Aplica a lógica de decisão para encontrar oportunidades
    opportunity = decide_live_bet_opportunity(live_data, game, tracker)
    
    # Registra análise de oportunidade (mesmo se não encontrou)
    from utils.analytics_logger import log_live_opportunity
    reason = "Oportunidade encontrada" if opportunity else "Nenhuma oportunidade encontrada"
    log_live_opportunity(game.id, game.ext_id, opportunity, reason=reason, metadata=live_data["stats"])

    # ETAPA 2: Se encontrou uma oportunidade, valida a confiabilidade
    if opportunity:
        from betting.live_validator import validate_opportunity_reliability
        
        is_reliable, confidence_score, validation_reason = validate_opportunity_reliability(
            opportunity, live_data, game, tracker
        )
        
        # Adiciona score de confiança à oportunidade
        opportunity["confidence_score"] = confidence_score
        opportunity["validation_reason"] = validation_reason
        
        # Se não passou na validação, registra e descarta
        if not is_reliable:
            log_live_opportunity(
                game.id, game.ext_id, opportunity,
                reason=f"Oportunidade rejeitada na validação: {validation_reason}",
                metadata={
                    **live_data["stats"],
                    "confidence_score": confidence_score,
                    "validation_reason": validation_reason
                }
            )
            logger.info(f"⚠️ Oportunidade rejeitada na validação (score: {confidence_score:.2f}): {validation_reason}")
            opportunity = None  # Descarta a oportunidade
        else:
            logger.info(f"✅ Oportunidade validada com confiança {confidence_score:.2f}: {validation_reason}")

    # ETAPA 3: Se houver uma oportunidade validada, envia o palpite
    if opportunity:
        # Prepara estatísticas com informações de validação
        stats_with_validation = {
            **live_data["stats"],
            "confidence_score": opportunity.get("confidence_score", 0.0),
            "validation_reason": opportunity.get("validation_reason", "")
        }
        
        # Envia mensagem de "Palpite Validado" usando buffer
        from utils.telegram_helpers import send_live_opportunity_with_buffer
        send_live_opportunity_with_buffer(game, opportunity, stats_with_validation)

        # Atualiza o tracker
        tracker.last_pick_sent = now_utc
        tracker.last_pick_key = opportunity.get("pick_key", "")
        cooldown_min = opportunity.get("cooldown_minutes", int(os.getenv("LIVE_COOLDOWN_MIN", "8")))
        tracker.cooldown_until = now_utc + timedelta(minutes=cooldown_min)
        tracker.notifications_sent = (tracker.notifications_sent or 0) + 1

        logger.info(f"✅ Oportunidade validada e enviada para jogo {game.id}: {opportunity['option']} @ {opportunity['odd']}")
    # else:
    #     # Mensagem "Busca Continua" DESATIVADA para evitar spam
    #     # Só envia oportunidades quando realmente encontradas
    #     pass


# Lock para prevenir execuções simultâneas do monitor_live_games_job
_monitor_live_games_lock = asyncio.Lock()

async def monitor_live_games_job():
    """
    Monitora jogos ao vivo em busca de oportunidades de aposta.
    Só monitora jogos que estão dentro do horário previsto (start_time até start_time + 2h30min).
    Só executa se houver jogos pré-selecionados (will_bet=True) no banco.

    Usa lock assíncrono para prevenir execuções simultâneas.
    """
    if os.getenv("ENABLE_LIVE_ANALYSIS", "false").lower() != "true":
        logger.debug("ENABLE_LIVE_ANALYSIS=false — monitor live desativado")
        return

    # Verificar se já está em execução
    if _monitor_live_games_lock.locked():
        logger.debug("Monitor de jogos ao vivo já em execução, pulando esta execução")
        return
    
    async with _monitor_live_games_lock:
        try:
            now_utc = datetime.now(pytz.UTC)

            with SessionLocal() as session:
                # Busca jogos ao vivo
                live_games = _get_live_games_within_window(session, now_utc)
                
                if not live_games:
                    logger.debug("⏭️  Nenhum jogo ao vivo dentro do horário previsto.")
                    return
                
                from utils.logger import log_with_context
                log_with_context(
                    "info",
                    f"Iniciando monitoramento de {len(live_games)} jogo(s) ao vivo",
                    stage="monitor_live_games",
                    status="started",
                    extra_fields={"games_count": len(live_games)}
                )

                for game in live_games:
                    try:
                        # 1. Garante que tracker existe
                        tracker = _ensure_tracker_exists(session, game, now_utc)
                        
                        # 2. Atualiza tracker com dados atuais
                        live_data = await _update_game_tracker(tracker, game, now_utc)
                        
                        # 3. Verifica se jogo terminou
                        if _is_game_finished(tracker.current_minute or "") and game.status == "live":
                            await _handle_finished_game(session, game, tracker, now_utc)
                            continue  # Pula para próximo jogo
                        
                        # 4. Processa jogo ativo
                        await _handle_active_game(session, game, tracker, live_data, now_utc)
                        session.commit()

                    except Exception as e:
                        logger.exception(f"Erro ao monitorar jogo ao vivo {game.id} ({game.ext_id}): {e}")

                from utils.logger import log_with_context
                log_with_context(
                    "info",
                    "Monitoramento de jogos ao vivo concluído",
                    stage="monitor_live_games",
                    status="completed"
                )
        except asyncio.CancelledError:
            logger.warning("Monitor de jogos ao vivo foi cancelado (CancelledError)")
            raise  # Re-raise para que o scheduler saiba que foi cancelado
        except Exception as e:
            logger.exception(f"Erro inesperado no monitor de jogos ao vivo: {e}")
            raise


async def send_daily_summary_job():
    """
    Job que envia resumo diário completo com todos os jogos finalizados do dia.
    Executa uma vez por dia (configurável via env).
    """
    logger.info("📊 Preparando resumo diário...")
    
    with SessionLocal() as session:
        from utils.formatters import fmt_daily_summary
        from datetime import datetime
        
        # Resumo do dia atual
        summary_msg = fmt_daily_summary(session, datetime.now(ZONE))
        tg_send_message(summary_msg, message_type="summary")
        
        logger.info("📊 Resumo diário enviado com sucesso.")


async def generate_daily_analytics_report_job():
    """
    Job que gera e envia o relatório de analytics do dia anterior.
    Executa antes do ciclo reiniciar (5 minutos antes da varredura matinal).
    """
    from utils.analytics_report import generate_and_save_daily_report
    from datetime import datetime, timedelta
    
    # Gera relatório do dia anterior
    yesterday = (datetime.now(ZONE) - timedelta(days=1)).date()
    logger.info("📊 Gerando relatório de analytics para %s...", yesterday.strftime("%d/%m/%Y"))
    
    try:
        report = await asyncio.to_thread(generate_and_save_daily_report, yesterday)
        
        # Envia via Telegram (opcional, pode ser muito longo)
        # Se quiser enviar, descomente as linhas abaixo
        # from notifications.telegram import tg_send_message
        # tg_send_message(f"<pre>{report}</pre>", parse_mode="HTML", message_type="analytics_report")
        
        logger.info("✅ Relatório de analytics gerado com sucesso para %s", yesterday.strftime("%d/%m/%Y"))
    except Exception as e:
        logger.exception("Erro ao gerar relatório de analytics: %s", e)


async def collect_tomorrow_games_job():
    """Coleta jogos de amanhã e salva no banco (sem enviar mensagem)."""
    from scanner.game_scanner import scan_games_for_date
    
    logger.info("📥 Iniciando coleta de jogos de AMANHÃ...")
    result = await scan_games_for_date(date_offset=1, send_summary=False)
    logger.info("✅ Coleta concluída: %d analisados, %d selecionados", result["analyzed"], result["selected"])


async def send_dawn_games_job():
    """Envia jogos da madrugada (00h-06h) - só se houver jogos selecionáveis."""
    from scanner.game_scanner import send_dawn_games
    
    sent = await send_dawn_games()
    if sent:
        logger.info("✅ Mensagem 'Jogos da Madrugada' enviada com sucesso")
    else:
        logger.info("⏭️  Nenhum jogo da madrugada encontrado. Mensagem não enviada.")


async def send_combined_bet_job():
    """
    Job que envia aposta combinada com todos os jogos de alta confiança do dia.
    Executa diariamente às 08:00 para enviar a aposta combinada do dia.
    """
    from betting.combined_bets import (
        select_games_for_combined_bet,
        create_combined_bet,
        calculate_combined_odd,
        calculate_potential_return,
        calculate_avg_confidence
    )

    now_utc = datetime.now(pytz.UTC)
    today_utc = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)

    with SessionLocal() as session:
        # Seleção inteligente: max 10, min 3, diversificação por liga/time, exclui draws,
        # ranking por pick_prob, valida min_combined_odd. Tudo configurável via env.
        games = select_games_for_combined_bet(session, date_filter=today_utc)

        if not games:
            logger.info("📊 Nenhuma múltipla criada hoje (sem jogos elegíveis após filtros).")
            return
        
        # Cria aposta combinada
        combined_bet = create_combined_bet(
            games=games,
            bet_date=today_utc,
            example_stake=10.0,
            session=session
        )
        
        if not combined_bet:
            logger.error("❌ Erro ao criar aposta combinada.")
            return
        
        # Formata e envia mensagem
        message = fmt_combined_bet(combined_bet, games)
        
        # Envia notificação
        tg_send_message(
            message,
            message_type="combined_bet",
            game_id=None,  # Não é um jogo específico
            ext_id=f"combined_{combined_bet.id}"
        )
        
        # Atualiza sent_at
        combined_bet.sent_at = now_utc
        session.commit()
        
        logger.info(f"✅ Aposta combinada enviada: {len(games)} jogos, odd {combined_bet.combined_odd:.2f}, retorno R$ {combined_bet.potential_return:.2f}")


async def send_today_games_job():
    """Envia jogos de hoje (06h-23h)."""
    from scanner.game_scanner import send_today_games
    
    await send_today_games()
    logger.info("✅ Mensagem 'Jogos de Hoje' enviada com sucesso")


async def morning_scan_and_publish():
    """
    Varredura matinal completa:
    1. Analisa todas as oportunidades em todos os campeonatos
    2. Decide quais jogos serão monitorados ao vivo
    3. NÃO envia resumos aqui - isso é feito em horários específicos:
       - Jogos da madrugada: 23h
       - Jogos de hoje: 06h
    """
    from scanner.game_scanner import scan_games_for_date
    
    logger.info("🌅 Iniciando varredura matinal completa...")
    
    # Analisa todas as oportunidades de hoje
    result = await scan_games_for_date(date_offset=0, send_summary=False)
    logger.info("✅ Varredura concluída: %d analisados, %d selecionados", result["analyzed"], result["selected"])
    
    # Marca jogos selecionados para monitoramento ao vivo quando iniciarem
    with SessionLocal() as session:
        selected_games = (
            session.query(Game)
            .filter(
                Game.will_bet.is_(True),
                Game.status == "scheduled"
            )
            .all()
        )
        
        # Garante que os jogos têm game_url para monitoramento ao vivo
        for game in selected_games:
            if not game.game_url and game.source_link:
                # Tenta construir game_url a partir do source_link
                from urllib.parse import urljoin
                if game.ext_id:
                    game.game_url = f"https://betnacional.bet.br/event/1/0/{game.ext_id}"
                    session.commit()
        
        logger.info("📋 %d jogo(s) pré-selecionado(s) preparado(s) para monitoramento ao vivo", len(selected_games))
    
    logger.info("✅ Varredura matinal concluída.")


async def watch_game_until_end_job(game_id: int):
    """
    Monitora um jogo específico até que ele termine, verificando o resultado.
    Tenta atualizar o status do jogo e notificar o resultado.
    """
    if os.getenv("ENABLE_LIVE_ANALYSIS", "false").lower() != "true":
        logger.debug("ENABLE_LIVE_ANALYSIS=false — watch_game_until_end_job(%s) desativado", game_id)
        return

    logger.info("👀 Iniciando monitoramento do jogo id=%s até o fim...", game_id)
    
    with SessionLocal() as session:
        game = session.query(Game).filter_by(id=game_id).one_or_none()
        if not game:
            logger.warning("⚠️ Jogo id=%s não encontrado. Encerrando monitoramento.", game_id)
            return
        
        # Verifica se o jogo já terminou
        if game.status == "ended" and game.outcome:
            logger.info("✅ Jogo id=%s já finalizado. Resultado: %s", game_id, game.outcome)
            return
        
        # Tenta obter o resultado
        try:
            from datetime import datetime
            import pytz
            result_data = await fetch_game_result(game.ext_id, game.game_url or game.source_link)
            
            if result_data:
                game.outcome = result_data.get("outcome")
                game.final_score_home = result_data.get("home_goals")
                game.final_score_away = result_data.get("away_goals")
                game.final_score = result_data.get("score")
                game.result_fetched_at = datetime.now(pytz.UTC)
                game.status = "ended"
                game.hit = (game.outcome == game.pick) if game.pick else None  # mirror legado pra match_result

                # Resolve TODOS os picks multi-mercado (match_result + total_goals quando houver)
                try:
                    from betting.result_resolver import resolve_picks_for_game
                    resolve_picks_for_game(session, game)
                except Exception as exc:
                    logger.warning(f"Falha ao resolver picks pro game {game.id}: {exc}")

                result_msg = "✅ ACERTOU" if game.hit else "❌ ERROU" if game.hit is False else "⚠️ SEM PALPITE"
                score_str = f" ({game.final_score})" if game.final_score else ""
                logger.info("🏁 Resultado obtido para jogo id=%s: %s%s | %s", game_id, game.outcome, score_str, result_msg)
                
                # Não enviar mensagem individual; envio será consolidado pelo job periódico
                
                session.commit()
                
                # Tenta enviar resumo diário se todos os jogos do dia terminaram
                try:
                    await maybe_send_daily_wrapup()
                except Exception:
                    logger.exception("Erro ao verificar resumo diário após jogo id=%s", game_id)
            else:
                logger.warning("⚠️ Não foi possível obter resultado para jogo id=%s. Tentando novamente mais tarde...", game_id)
                # Agenda nova tentativa em alguns minutos
                import asyncio
                await asyncio.sleep(300)  # 5 minutos
                await watch_game_until_end_job(game_id)
        except Exception as e:
            logger.exception("Erro ao monitorar jogo id=%s: %s", game_id, e)


async def maybe_send_daily_wrapup():
    """
    Verifica se todos os jogos do dia terminaram e envia resumo se sim.
    Chamada após cada jogo terminar para tentar enviar o wrap-up.
    Usa Stat para evitar envios duplicados.
    """
    from models.database import Stat
    
    today = datetime.now(ZONE).date()
    today_str = today.isoformat()
    summary_sent_key = f"daily_summary_sent_{today_str}"
    
    with SessionLocal() as session:
        # Verifica se já foi enviado hoje
        from watchlist.manager import stat_get, stat_set
        already_sent = stat_get(session, summary_sent_key, False)
        if already_sent:
            return  # Já foi enviado hoje
        
        day_start = ZONE.localize(datetime(today.year, today.month, today.day, 0, 0)).astimezone(pytz.UTC)
        day_end = ZONE.localize(datetime(today.year, today.month, today.day, 23, 59, 59)).astimezone(pytz.UTC)
        
        # Busca todos os jogos do dia que tiveram palpite (will_bet=True)
        todays_games = (
            session.query(Game)
            .filter(
                Game.start_time >= day_start,
                Game.start_time <= day_end,
                Game.will_bet.is_(True)
            )
            .all()
        )
        
        if not todays_games:
            return
        
        # Verifica quantos terminaram e têm resultado
        finished = [g for g in todays_games if g.status == "ended" and g.hit is not None]
        
        # Se todos os jogos do dia terminaram E todos têm resultado verificado
        if len(finished) == len(todays_games) and len(finished) > 0:
            # Marca como enviado ANTES de enviar (evita duplicação em caso de erro)
            stat_set(session, summary_sent_key, True)
            session.commit()
            
            # Envia resumo completo usando o novo formatter
            from utils.formatters import fmt_daily_summary
            summary_msg = fmt_daily_summary(session, datetime.now(ZONE))
            tg_send_message(summary_msg)
            
            hits = sum(1 for g in finished if g.hit)
            total = len(finished)
            logger.info(f"📊 Wrap-up do dia enviado | total={total} hits={hits} acc={hits/total*100:.1f}%")


async def cleanup_result_cache_job():
    """
    Job periódico para limpar entradas expiradas do cache de resultados.
    Executa a cada hora para manter o cache limpo.
    """
    from utils.cache import result_cache
    
    try:
        removed = result_cache.clear_expired()
        stats = result_cache.get_stats()
        
        if removed > 0:
            logger.info(f"🧹 Cache limpo: {removed} entradas expiradas removidas. "
                       f"Cache atual: {stats['size']} entradas | "
                       f"Hit rate: {stats['hit_rate']:.1f}%")
        else:
            logger.debug(f"🧹 Verificação de cache: nenhuma entrada expirada. "
                        f"Cache atual: {stats['size']} entradas | "
                        f"Hit rate: {stats['hit_rate']:.1f}%")
    except Exception as e:
        logger.exception(f"Erro ao limpar cache de resultados: {e}")


async def health_check_job():
    """
    Job periódico para verificar a saúde do sistema e enviar alertas.
    Executa a cada 30 minutos para monitorar componentes críticos.
    """
    from utils.health_check import system_health
    
    try:
        logger.debug("🏥 Executando health checks do sistema...")
        results = system_health.check_and_alert()
        
        # Log resumo do status
        if results["overall"]:
            logger.debug("✅ Sistema saudável: todos os componentes funcionando")
        else:
            unhealthy = []
            if not results["api"]["healthy"]:
                unhealthy.append("API")
            if not results["database"]["healthy"]:
                unhealthy.append("Banco")
            if not results["telegram"]["healthy"]:
                unhealthy.append("Telegram")
            
            logger.warning(f"⚠️ Sistema com problemas: {', '.join(unhealthy)}")
        
        # Log detalhado apenas em modo debug
        logger.debug(f"Status detalhado: {system_health.get_status_summary()}")
        
    except Exception as e:
        logger.exception(f"Erro ao executar health checks: {e}")


async def flush_message_buffers_job():
    """
    Job periódico para fazer flush dos buffers de mensagens.
    Garante que mensagens consolidadas sejam enviadas mesmo se buffer não encher.
    """
    try:
        from utils.telegram_message_buffer import flush_all_buffers
        await flush_all_buffers()
        logger.debug("📦 Buffers de mensagens verificados e flushados se necessário")
    except Exception as e:
        logger.exception(f"Erro ao fazer flush dos buffers: {e}")


async def fetch_finished_games_results_job():
    """
    Job periódico que busca resultados de jogos finalizados que ainda não têm resultado.
    Garante que mesmo após reiniciar o script, os resultados sejam buscados eventualmente.
    """
    from datetime import datetime, timedelta
    import pytz
    from models.database import SessionLocal, Game
    from scraping.fetchers import fetch_game_result
    from utils.formatters import fmt_result
    from notifications.telegram import tg_send_message
    
    def _normalize_datetime_to_utc(dt: datetime) -> datetime:
        """
        Normaliza um datetime para UTC (offset-aware).
        
        Se o datetime já for offset-aware, retorna convertido para UTC.
        Se for offset-naive, assume que está em UTC e adiciona timezone UTC.
        """
        if dt is None:
            return None
        if dt.tzinfo is None:
            # Offset-naive: assume UTC
            return pytz.UTC.localize(dt)
        # Offset-aware: converte para UTC
        return dt.astimezone(pytz.UTC)
    
    now_utc = datetime.now(pytz.UTC)
    
    try:
        with SessionLocal() as session:
            # Buscar jogos que terminaram mas não têm resultado
            # IMPORTANTE: Verificar se o jogo já aconteceu (data/hora) antes de buscar resultado
            # Busca jogos que terminaram há mais de 30 minutos e nas últimas 48 horas
            finished_no_result = (
                session.query(Game)
                .filter(
                    Game.status.in_(["live", "ended", "scheduled"]),  # Incluir scheduled também
                    Game.will_bet.is_(True),
                    Game.outcome.is_(None),  # Não tem resultado
                    Game.start_time >= now_utc - timedelta(days=2),  # Últimas 48 horas
                    Game.start_time <= now_utc - timedelta(minutes=30)  # Terminou há mais de 30min (já aconteceu)
                )
                .all()
            )
            
            if not finished_no_result:
                logger.debug("✅ Nenhum jogo finalizado sem resultado para buscar")
                return
            
            logger.info(f"🔍 Buscando resultados para {len(finished_no_result)} jogo(s) finalizado(s) sem resultado")
            
            results_batch = []
            for game in finished_no_result:
                try:
                    # Verificar se o jogo já aconteceu (comparando data/hora)
                    # Se start_time está no passado (há mais de 30 minutos), o jogo já aconteceu
                    # Normalizar start_time para UTC (offset-aware)
                    game_start_utc = _normalize_datetime_to_utc(game.start_time)
                    time_since_start = now_utc - game_start_utc
                    game_duration_minutes = 105  # Duração típica de um jogo de futebol (90min + 15min de acréscimo)
                    
                    # Verificar se já passou tempo suficiente para o jogo ter terminado
                    if time_since_start.total_seconds() / 60 < game_duration_minutes:
                        # Jogo ainda pode estar em andamento, pular
                        logger.debug(f"⏳ Jogo {game.id} ainda pode estar em andamento (iniciou há {int(time_since_start.total_seconds() / 60)} minutos)")
                        continue
                    
                    logger.info(f"🔎 Buscando resultado para jogo {game.id} ({game.ext_id}) - {game.team_home} vs {game.team_away} (iniciou há {int(time_since_start.total_seconds() / 60)} minutos)")
                    
                    # Atualizar status para "ended" se ainda não estiver
                    if game.status != "ended":
                        game.status = "ended"
                        logger.debug(f"📝 Status do jogo {game.id} atualizado para 'ended'")
                    
                    from datetime import datetime
                    import pytz
                    result_data = await fetch_game_result(game.ext_id, game.game_url or game.source_link)
                    
                    if result_data:
                        game.outcome = result_data.get("outcome")
                        game.final_score_home = result_data.get("home_goals")
                        game.final_score_away = result_data.get("away_goals")
                        game.final_score = result_data.get("score")
                        game.result_fetched_at = datetime.now(pytz.UTC)
                        game.status = "ended"
                        game.hit = (game.outcome == game.pick) if game.pick else None  # mirror legado pra match_result

                        # Resolve TODOS os picks multi-mercado (match_result + total_goals quando houver)
                        try:
                            from betting.result_resolver import resolve_picks_for_game
                            resolve_picks_for_game(session, game)
                        except Exception as exc:
                            logger.warning(f"Falha ao resolver picks pro game {game.id}: {exc}")

                        result_msg = "✅ ACERTOU" if game.hit else "❌ ERROU" if game.hit is False else "⚠️ SEM PALPITE"
                        score_str = f" ({game.final_score})" if game.final_score else ""
                        logger.info(f"✅ Resultado obtido para jogo {game.id}: {game.outcome}{score_str} | {result_msg}")
                        
                        # Acumula resultados desta execução para envio em lote
                        if 'results_batch' not in locals():
                            results_batch = []
                        results_batch.append(game)
                        
                        # Atualiza resultado de apostas combinadas
                        try:
                            from betting.combined_bets import update_combined_bet_result
                            from utils.formatters import fmt_combined_bet_result
                            pending_bets = session.query(CombinedBet).filter(
                                CombinedBet.status == "pending"
                            ).all()

                            for bet in pending_bets:
                                if game.id in bet.game_ids:
                                    result_status = update_combined_bet_result(bet, session)
                                    if result_status in ("won", "lost"):
                                        session.commit()
                                        try:
                                            msg = fmt_combined_bet_result(bet, session)
                                            tg_send_message(msg, parse_mode="HTML", message_type="combined_result")
                                            logger.info("📊 Resultado de múltipla #%s enviado: %s", bet.id, result_status)
                                        except Exception:
                                            logger.exception("Erro ao enviar notificação da múltipla #%s", bet.id)
                        except Exception:
                            logger.exception(f"Erro ao atualizar apostas combinadas após jogo {game.id}")
                        
                        session.commit()
                        logger.info(f"✅ Resultado do jogo {game.id} salvo (notificação em lote)")
                    else:
                        logger.debug(f"⚠️  Não foi possível obter resultado para jogo {game.id} ainda (tentará novamente)")
                except Exception as e:
                    logger.exception(f"Erro ao buscar resultado para jogo {game.id}: {e}")

            # Após processar o bloco, se houver jogos com resultado, enviar mensagem única
            try:
                if results_batch:
                    from utils.formatters import fmt_results_batch
                    from notifications.telegram import tg_send_message
                    msg = fmt_results_batch(results_batch)
                    tg_send_message(msg)  # HTML por padrão
            except Exception:
                logger.exception("Erro ao enviar mensagem em lote de resultados")
                    
    except Exception as e:
        logger.exception(f"Erro ao executar job de busca de resultados: {e}")


def setup_scheduler():
    """
    Registra todos os jobs no AsyncIOScheduler.
    """
    
    # --- Relatório de Analytics (antes do ciclo reiniciar) ---
    # Executa 5 minutos antes da varredura matinal
    if MORNING_HOUR >= 1:
        report_hour = MORNING_HOUR
        report_minute = 55  # 5 minutos antes
    else:
        report_hour = 23
        report_minute = 55
    
    scheduler.add_job(
        generate_daily_analytics_report_job,
        trigger=CronTrigger(hour=report_hour, minute=report_minute),
        id="daily_analytics_report",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=300,
    )
    logger.info("📊 Relatório de analytics agendado para %02d:%02d (antes do ciclo)", report_hour, report_minute)
    
    # --- Varredura matinal (diária) ---
    scheduler.add_job(
        morning_scan_and_publish,
        trigger=CronTrigger(hour=MORNING_HOUR, minute=0),
        id="morning_scan",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=300,
    )

    # --- Varredura noturna opcional ---
    if os.getenv("ENABLE_NIGHT_SCAN", "false").lower() == "true":
        night_hour = int(os.getenv("NIGHT_SCAN_HOUR", "22"))
        scheduler.add_job(
            night_scan_for_early_games,
            trigger=CronTrigger(hour=night_hour, minute=0),
            id="night_scan",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            misfire_grace_time=300,
        )
        logger.info("🌙 Varredura noturna ativada às %02d:00.", night_hour)

    # --- Rechecagem periódica da watchlist ---
    scheduler.add_job(
        rescan_watchlist_job,
        trigger=IntervalTrigger(minutes=WATCHLIST_RESCAN_MIN),
        id="watchlist_rescan",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=60,
    )
    
    # --- Limpeza periódica do cache de resultados ---
    scheduler.add_job(
        cleanup_result_cache_job,
        trigger=IntervalTrigger(hours=1),  # A cada 1 hora
        id="cache_cleanup",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=300,
    )
    logger.info("🧹 Limpeza de cache de resultados agendada a cada 1 hora")

    # --- Renovação de cookies BN a cada 3 horas (margem antes do TTL=4h) ---
    scheduler.add_job(
        refresh_bn_cookies_job,
        'interval',
        hours=3,
        id='refresh_bn_cookies',
        replace_existing=True,
        next_run_time=datetime.now(pytz.UTC) + timedelta(seconds=10),
    )
    logger.info("🍪 Renovação de cookies BN agendada a cada 3h (primeira run em ~10s)")

    # --- Health checks do sistema (DESATIVADO) ---
    # scheduler.add_job(
    #     health_check_job,
    #     trigger=IntervalTrigger(minutes=30),  # A cada 30 minutos
    #     id="health_check",
    #     replace_existing=True,
    #     coalesce=True,
    #     max_instances=1,
    #     misfire_grace_time=300,
    # )
    # logger.info("🏥 Health checks do sistema agendados a cada 30 minutos")
    
    # --- Busca periódica de resultados de jogos finalizados ---
    scheduler.add_job(
        fetch_finished_games_results_job,
        trigger=IntervalTrigger(minutes=FETCH_FINISHED_INTERVAL_MIN),
        id="fetch_finished_results",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=300,
    )
    logger.info("🔍 Busca de resultados de jogos finalizados agendada a cada %d minutos", FETCH_FINISHED_INTERVAL_MIN)

    # --- Flush periódico de buffers de mensagens ---
    scheduler.add_job(
        flush_message_buffers_job,
        trigger=IntervalTrigger(minutes=FLUSH_BUFFERS_INTERVAL_MIN),
        id="flush_message_buffers",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=60,
    )
    logger.info("📦 Flush de buffers de mensagens agendado a cada %d minutos", FLUSH_BUFFERS_INTERVAL_MIN)
    
    # --- Reavaliação horária dos jogos do dia ---
    scheduler.add_job(
        hourly_rescan_job,
        trigger=IntervalTrigger(hours=1),
        id="hourly_rescan",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=120,
    )

    # --- Atualização de status de jogos para 'live' ---
    scheduler.add_job(
        update_games_to_live_status,
        trigger=IntervalTrigger(minutes=UPDATE_LIVE_STATUS_INTERVAL_MIN),
        id="update_games_to_live",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=60,
    )

    # --- Monitoramento de jogos ao vivo (condicional) ---
    if os.getenv("ENABLE_LIVE_ANALYSIS", "false").lower() == "true":
        scheduler.add_job(
            monitor_live_games_job,
            trigger=IntervalTrigger(minutes=MONITOR_LIVE_INTERVAL_MIN),
            id="monitor_live_games",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            misfire_grace_time=60,
        )
        logger.info("📡 Monitor de jogos ao vivo agendado a cada %d minutos", MONITOR_LIVE_INTERVAL_MIN)
    else:
        logger.info("🚫 Monitor de jogos ao vivo DESATIVADO (ENABLE_LIVE_ANALYSIS=false)")

    # --- Coleta de jogos de amanhã (22h do dia anterior) ---
    collect_tomorrow_hour = int(os.getenv("COLLECT_TOMORROW_HOUR", "22"))
    scheduler.add_job(
        collect_tomorrow_games_job,
        trigger=CronTrigger(hour=collect_tomorrow_hour, minute=0),
        id="collect_tomorrow",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=300,
    )
    logger.info("📥 Coleta de jogos de amanhã agendada para %02d:00", collect_tomorrow_hour)

    # --- Envio de jogos da madrugada (23h do dia anterior) ---
    dawn_hour = int(os.getenv("DAWN_GAMES_HOUR", "23"))
    scheduler.add_job(
        send_dawn_games_job,
        trigger=CronTrigger(hour=dawn_hour, minute=0),
        id="send_dawn",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=300,
    )
    logger.info("🌙 Envio de jogos da madrugada agendado para %02d:00", dawn_hour)

    # --- Envio de jogos de hoje (06h) ---
    send_today_hour = int(os.getenv("SEND_TODAY_HOUR", "6"))
    scheduler.add_job(
        send_today_games_job,
        trigger=CronTrigger(hour=send_today_hour, minute=0),
        id="send_today",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=300,
    )
    logger.info("🌅 Envio de jogos de hoje agendado para %02d:00", send_today_hour)

    # --- Envio de aposta combinada (08h) ---
    combined_bet_hour = int(os.getenv("COMBINED_BET_HOUR", "8"))
    scheduler.add_job(
        send_combined_bet_job,
        trigger=CronTrigger(hour=combined_bet_hour, minute=0),
        id="send_combined_bet",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=300,
    )
    logger.info("🎯 Envio de aposta combinada agendado para %02d:00", combined_bet_hour)

    # --- Resumo diário (opcional, via env) ---
    daily_summary_hour = os.getenv("DAILY_SUMMARY_HOUR", "")
    if daily_summary_hour:
        try:
            summary_hour = int(daily_summary_hour)
            scheduler.add_job(
                send_daily_summary_job,
                trigger=CronTrigger(hour=summary_hour, minute=0),
                id="daily_summary",
                replace_existing=True,
                coalesce=True,
                max_instances=1,
                misfire_grace_time=300,
            )
            logger.info("📊 Resumo diário agendado para %02d:00", summary_hour)
        except ValueError:
            logger.warning("DAILY_SUMMARY_HOUR inválido, ignorando resumo diário agendado")

    # Inicia o scheduler
    scheduler.start()

    # Log amigável do que ficou ativo
    collect_tomorrow_hour = int(os.getenv("COLLECT_TOMORROW_HOUR", "22"))
    dawn_hour = int(os.getenv("DAWN_GAMES_HOUR", "6"))
    send_today_hour = int(os.getenv("SEND_TODAY_HOUR", "6"))
    
    base_msg = f"✅ Scheduler ON — Coleta: {collect_tomorrow_hour:02d}:00 | Madrugada: {dawn_hour:02d}:00 | Hoje: {send_today_hour:02d}:00 ({APP_TZ})"
    base_msg += (
        f" | watchlist ~{WATCHLIST_RESCAN_MIN}min"
        f" | reavaliação horária"
        f" | ao vivo cada 1min"
    )
    logger.info(base_msg)


# ============================================================
# BN cookie refresh + smart fetch routing (API JSON / Playwright)
# ============================================================

async def refresh_bn_cookies_job():
    """
    Job periódico que renova cookies BetNacional via Playwright.
    Roda a cada BN_COOKIE_TTL_HOURS - 1 (margem de segurança).
    Também roda ao iniciar (chamado em main.py via on_startup hook).

    Skip se BetNacional não é fallback ativo (USE_BETNACIONAL_FALLBACK=false).
    """
    try:
        from config.settings import USE_BETNACIONAL_FALLBACK
    except Exception:
        USE_BETNACIONAL_FALLBACK = False
    if not USE_BETNACIONAL_FALLBACK:
        logger.debug("BN fallback OFF — pulando refresh de cookies")
        return

    try:
        from utils.bn_cookie_manager import refresh_cookies_async, is_expired
        forced = is_expired()
        cookies = await refresh_cookies_async(force=forced)
        if cookies:
            logger.info(f"🍪 Cookies BN renovados: {len(cookies)} cookies")
        else:
            logger.warning("🍪 Falha ao renovar cookies BN (refresh retornou vazio)")
    except Exception as exc:
        logger.exception(f"refresh_bn_cookies_job falhou: {exc}")


async def fetch_events_smart(
    url: str,
    backend: str = "playwright",
    tournament_id_hint: Optional[int] = None,
) -> list:
    """
    Roteamento inteligente de fetch:
    0. Se USE_BETANO_AS_PRIMARY=true: tenta Betano primeiro.
       - Se Betano retornar eventos: retorna direto.
       - Se Betano falhar/vazio E USE_BETNACIONAL_FALLBACK=false: retorna [].
       - Se Betano falhar/vazio E USE_BETNACIONAL_FALLBACK=true: cai pro BetNacional.
    1. Se USE_API_JSON_FETCH=true E cookies disponíveis: tenta via API
       a) Se tournament_id_hint vier: usa esse
       b) Senão: extrai do URL (regex /events/{sport}/{cat}/{tour})
       c) Se retornar [], cai pro fallback
    2. Fallback: fetch_events_from_link(url, backend) (Playwright/HTML).
    """
    import re

    # ─── 0) Caminho primário: Betano ───────────────────────────────────────
    try:
        from config.settings import USE_BETANO_AS_PRIMARY, USE_BETNACIONAL_FALLBACK
    except Exception:
        USE_BETANO_AS_PRIMARY = False
        USE_BETNACIONAL_FALLBACK = False

    if USE_BETANO_AS_PRIMARY:
        try:
            from scraping.betano import fetch_events_via_betano_api
            events = await fetch_events_via_betano_api(source_link=url)
            if events:
                logger.info(
                    f"✅ Betano fetch OK ({len(events)} eventos) | url={url}"
                )
                return events
            logger.warning(f"⚠️ Betano fetch retornou 0 eventos | url={url}")
        except ImportError as exc:
            logger.warning(
                f"Módulo betano indisponível ({exc}) — caindo pro fallback se disponível"
            )
        except Exception as exc:
            logger.exception(f"Betano fetch falhou: {exc}")

        # Se Betano falhou/vazio e fallback BetNacional não habilitado, retorna []
        if not USE_BETNACIONAL_FALLBACK:
            logger.warning(
                "USE_BETNACIONAL_FALLBACK=false — não tentando BetNacional"
            )
            return []

    # ─── 1) Caminho atual: BetNacional via API JSON ────────────────────────
    use_api = os.getenv("USE_API_JSON_FETCH", "false").lower() == "true"

    if use_api:
        try:
            from utils.bn_cookie_manager import get_cookies
            cookies = get_cookies()
        except Exception:
            cookies = {}

        if cookies:
            sport_id, category_id, tournament_id = 1, 0, tournament_id_hint or 0
            m = re.search(r'/events/(\d+)/(\d+)/(\d+)', url)
            if m and tournament_id_hint is None:
                sport_id = int(m.group(1))
                category_id = int(m.group(2))
                tournament_id = int(m.group(3))

            try:
                from scraping.fetchers import fetch_events_via_api
                events = await fetch_events_via_api(
                    sport_id=sport_id,
                    category_id=category_id,
                    tournament_id=tournament_id,
                )
                if events:
                    logger.info(
                        f"✅ API fetch OK ({len(events)} eventos) — "
                        f"sport={sport_id} cat={category_id} tour={tournament_id}"
                    )
                    return events
                logger.warning("⚠️ API fetch retornou [] — caindo pro fallback HTML")
            except ImportError:
                logger.warning("fetch_events_via_api ainda não disponível — fallback HTML")
            except Exception as exc:
                logger.exception(f"API fetch erro inesperado, fallback: {exc}")
        else:
            logger.warning("USE_API_JSON_FETCH=true mas cookies indisponíveis — fallback")

    return await fetch_events_from_link(url, backend)
