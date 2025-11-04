"""Jobs agendados do sistema."""
import os
import asyncio
from datetime import datetime, timedelta
from typing import Any, Dict, List
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
    is_high_conf, was_high_conf_notified, mark_high_conf_notified
)
from utils.logger import logger
from utils.stats import to_aware_utc, save_odd_history
from utils.formatters import fmt_pick_now, fmt_watch_upgrade, fmt_live_bet_opportunity, format_night_scan_summary
from models.database import Game, LiveGameTracker, SessionLocal
from scraping.fetchers import fetch_events_from_link, fetch_game_result, _fetch_requests_async
from scraping.betnacional import parse_local_datetime, scrape_live_game_data
from betting.decision import decide_bet, decide_live_bet_opportunity
from notifications.telegram import tg_send_message
from watchlist.manager import wl_load, wl_save, wl_add, wl_remove

scheduler = AsyncIOScheduler(
    timezone=APP_TZ,
    job_defaults={
        "misfire_grace_time": 60,
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
                evs = await fetch_events_from_link(url, backend_cfg)
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

                    # Decisão
                    will, pick, pprob, pev, reason = decide_bet(
                        ev.odds_home, ev.odds_draw, ev.odds_away, ev.competition, (ev.team_home, ev.team_away)
                    )

                    # PASSE LIVRE: alta confiança entra mesmo sem will
                    free_pass = is_high_conf(pprob)
                    if not will and free_pass:
                        will = True
                        reason = (reason or "Passe livre") + " | HIGH_TRUST"

                    if not will:
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
                        continue

                    # UPSERT seguro
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
                        g.pick = pick
                        g.pick_prob = pprob
                        g.pick_ev = pev
                        g.pick_reason = reason
                        g.will_bet = will
                        g.status = "scheduled"
                        session.commit()
                    else:
                        g = Game(
                            ext_id=ev.ext_id,
                            source_link=url,
                            game_url=getattr(ev, "game_url", None),
                            competition=ev.competition,
                            team_home=ev.team_home,
                            team_away=ev.team_away,
                            start_time=start_utc,
                            odds_home=ev.odds_home,
                            odds_draw=ev.odds_draw,
                            odds_away=ev.odds_away,
                            pick=pick,
                            pick_prob=pprob,
                            pick_ev=pev,
                            will_bet=will,
                            pick_reason=reason,
                            status="scheduled",
                        )
                        session.add(g)
                        try:
                            session.commit()
                        except IntegrityError:
                            session.rollback()
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
                                g.pick = pick
                                g.pick_prob = pprob
                                g.pick_ev = pev
                                g.pick_reason = reason
                                g.will_bet = will
                                g.status = "scheduled"
                                session.commit()

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

                    # Envio do pick — SOMENTE se alta confiança e sem duplicar
                    try:
                        if (g.pick_prob or 0.0) >= HIGH_CONF_THRESHOLD and not was_high_conf_notified(g.pick_reason or ""):
                            tg_send_message(fmt_pick_now(g), message_type="pick_now", game_id=g.id, ext_id=g.ext_id)
                            g.pick_reason = mark_high_conf_notified(g.pick_reason or "")
                            session.commit()
                    except Exception:
                        logger.exception("Falha ao enviar pick noturno id=%s", g.id)

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
                evs = await fetch_events_from_link(link, "playwright")  # força playwright
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

            # recalcular decisão
            will, pick, pprob, pev, reason = decide_bet(
                ev.odds_home, ev.odds_draw, ev.odds_away, ev.competition, (ev.team_home, ev.team_away)
            )

            # PASSE LIVRE: alta confiança promove mesmo sem cruzar thresholds
            free_pass = is_high_conf(pprob)
            promote = free_pass or (will and (pprob >= MIN_PROB) and (pev >= MIN_EV))

            if promote:
                # UPSERT seguro
                if free_pass:
                    reason = (reason or "Upgrade watchlist") + " | HIGH_TRUST"
                else:
                    reason = "Upgrade watchlist"

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
                    g.pick = pick
                    g.pick_prob = pprob
                    g.pick_ev = pev
                    g.will_bet = True
                    g.pick_reason = reason
                    g.status = "scheduled"
                    session.commit()
                else:
                    g = Game(
                        ext_id=ext_id,
                        source_link=link,
                        game_url=getattr(ev, "game_url", None),
                        competition=ev.competition,
                        team_home=ev.team_home,
                        team_away=ev.team_away,
                        start_time=start_utc,
                        odds_home=ev.odds_home,
                        odds_draw=ev.odds_draw,
                        odds_away=ev.odds_away,
                        pick=pick,
                        pick_prob=pprob,
                        pick_ev=pev,
                        will_bet=True,
                        pick_reason=reason,
                        status="scheduled",
                    )
                    session.add(g)
                    try:
                        session.commit()
                    except IntegrityError:
                        session.rollback()
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
                            g.pick = pick
                            g.pick_prob = pprob
                            g.pick_ev = pev
                            g.will_bet = True
                            g.pick_reason = reason
                            g.status = "scheduled"
                            session.commit()

                session.refresh(g)

                # Salva histórico de odds quando promove
                save_odd_history(session, g)

                # NOTIFICAÇÃO — só envia se ALTA CONFIANÇA e sem duplicar
                try:
                    if (g.pick_prob or 0.0) >= HIGH_CONF_THRESHOLD and not was_high_conf_notified(g.pick_reason or ""):
                        tg_send_message(fmt_watch_upgrade(g), message_type="watch_upgrade", game_id=g.id, ext_id=g.ext_id)
                        g.pick_reason = mark_high_conf_notified(g.pick_reason or "")
                        session.commit()
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

                # Recalcula a decisão
                will, pick, pprob, pev, reason = decide_bet(
                    ev.odds_home, ev.odds_draw, ev.odds_away,
                    game.competition, (game.team_home, game.team_away),
                    game_id=game.id,
                )

                prev_high = (game.pick_prob or 0.0) >= HIGH_CONF_THRESHOLD
                new_high = (pprob or 0.0) >= HIGH_CONF_THRESHOLD

                # 1) Se virou ALTA CONFIANÇA agora (transição) e ainda não foi notificado -> dispara
                if new_high and (not prev_high) and not was_high_conf_notified(game.pick_reason or ""):
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

                    # notifica uma única vez
                    try:
                        tg_send_message(fmt_pick_now(game), message_type="pick_now", game_id=game.id, ext_id=game.ext_id)
                        game.pick_reason = mark_high_conf_notified(game.pick_reason or "")
                        session.commit()
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

                    # Não notificar upgrades "médios": só notificamos se for alta confiança e ainda não notificado
                    if (game.pick_prob or 0.0) >= HIGH_CONF_THRESHOLD and not was_high_conf_notified(game.pick_reason or ""):
                        try:
                            tg_send_message(fmt_pick_now(game), message_type="pick_now", game_id=game.id, ext_id=game.ext_id)
                            game.pick_reason = mark_high_conf_notified(game.pick_reason or "")
                            session.commit()
                            asyncio.create_task(_schedule_all_for_game(game))
                        except Exception:
                            logger.exception("Falha ao notificar upgrade (alta confiança) id=%s", game.id)
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


async def monitor_live_games_job():
    """
    Monitora jogos ao vivo em busca de oportunidades de aposta.
    Só monitora jogos que estão dentro do horário previsto (start_time até start_time + 2h30min).
    Só executa se houver jogos pré-selecionados (will_bet=True) no banco.
    """
    now_utc = datetime.now(pytz.UTC)

    with SessionLocal() as session:
        # 1. Verifica se há jogos pré-selecionados antes de iniciar monitoramento
        preselected_count = session.query(Game).filter(Game.will_bet.is_(True)).count()
        if preselected_count == 0:
            logger.debug("⏭️  Nenhum jogo pré-selecionado. Monitoramento ao vivo não executado.")
            return
        
        # 2. Busca apenas jogos que estão dentro do horário do jogo
        # Considera janela de 2h30min após o início (jogo normal + prorrogação)
        game_window_end = now_utc - timedelta(hours=2, minutes=30)
        
        live_games = (
            session.query(Game)
            .filter(
                Game.status == "live",
                Game.will_bet.is_(True),  # Só monitora jogos pré-selecionados
                Game.start_time >= game_window_end,  # Jogo começou há menos de 2h30min
                Game.start_time <= now_utc  # Jogo já começou
            )
            .all()
        )
        
        if not live_games:
            logger.debug("⏭️  Nenhum jogo ao vivo dentro do horário previsto.")
            return
        
        logger.info("⚽ Iniciando monitoramento de %d jogo(s) ao vivo...", len(live_games))

        for game in live_games:
            try:
                # 1. Busca ou cria o tracker
                tracker = session.query(LiveGameTracker).filter_by(game_id=game.id).one_or_none()
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

                # 2. Scrapeia os dados atuais da página do jogo
                html = await _fetch_requests_async(game.game_url or game.source_link)
                live_data = scrape_live_game_data(html, game.ext_id)

                # Atualiza as estatísticas no tracker
                tracker.current_score = live_data["stats"].get("score")
                tracker.current_minute = live_data["stats"].get("match_time")
                tracker.last_analysis_time = now_utc

                # 2.5. Verifica se o jogo terminou (detecção automática)
                match_time = tracker.current_minute or ""
                match_time_upper = match_time.upper()
                game_finished_indicators = ["FT", "FINAL", "FIM", "TERMINADO", "ENDED", "90'", "90+"]
                is_finished = any(indicator in match_time_upper for indicator in game_finished_indicators)
                
                if is_finished and game.status == "live":
                    logger.info(f"🏁 Jogo {game.id} ({game.team_home} vs {game.team_away}) terminou detectado ao vivo. Buscando resultado...")
                    # Marca como terminado e busca resultado imediatamente
                    game.status = "ended"
                    session.commit()
                    
                    # Busca resultado final
                    from scraping.fetchers import fetch_game_result
                    outcome = await fetch_game_result(game.ext_id, game.game_url or game.source_link)
                    
                    if outcome:
                        game.outcome = outcome
                        game.hit = (outcome == game.pick) if game.pick else None
                        result_msg = "✅ ACERTOU" if game.hit else "❌ ERROU" if game.hit is False else "⚠️ SEM PALPITE"
                        logger.info(f"🏁 Resultado obtido para jogo {game.id}: {outcome} | {result_msg}")
                        
                        # Envia notificação de resultado
                        from utils.formatters import fmt_result
                        tg_send_message(fmt_result(game), message_type="result", game_id=game.id, ext_id=game.ext_id)
                        
                        # Tenta enviar resumo diário se todos os jogos do dia terminaram
                        try:
                            await maybe_send_daily_wrapup()
                        except Exception:
                            logger.exception(f"Erro ao verificar resumo diário após jogo {game.id}")
                    else:
                        logger.warning(f"⚠️ Não foi possível obter resultado para jogo {game.id}, tentando novamente mais tarde")
                        # Agenda watch_game_until_end_job para tentar novamente
                        asyncio.create_task(watch_game_until_end_job(game.id))
                    
                    session.commit()
                    continue  # Pula para próximo jogo

                # 3. ETAPA 1: Aplica a lógica de decisão para encontrar oportunidades (só se o jogo ainda está rolando)
                opportunity = decide_live_bet_opportunity(live_data, game, tracker)
                
                # Registra análise de oportunidade (mesmo se não encontrou)
                from utils.analytics_logger import log_live_opportunity
                reason = "Oportunidade encontrada" if opportunity else "Nenhuma oportunidade encontrada"
                log_live_opportunity(game.id, game.ext_id, opportunity, reason=reason, metadata=live_data["stats"])

                # 4. ETAPA 2: Se encontrou uma oportunidade, valida a confiabilidade
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

                # 5. Se houver uma oportunidade validada, envia o palpite
                if opportunity:
                    # Prepara estatísticas com informações de validação
                    stats_with_validation = {
                        **live_data["stats"],
                        "confidence_score": opportunity.get("confidence_score", 0.0),
                        "validation_reason": opportunity.get("validation_reason", "")
                    }
                    
                    # Envia mensagem de "Palpite Validado"
                    message = fmt_live_bet_opportunity(game, opportunity, stats_with_validation)
                    tg_send_message(message, message_type="live_opportunity", game_id=game.id, ext_id=game.ext_id)

                    # Atualiza o tracker
                    tracker.last_pick_sent = now_utc
                    tracker.last_pick_key = opportunity.get("pick_key", "")
                    cooldown_min = opportunity.get("cooldown_minutes", int(os.getenv("LIVE_COOLDOWN_MIN", "8")))
                    tracker.cooldown_until = now_utc + timedelta(minutes=cooldown_min)
                    tracker.notifications_sent = (tracker.notifications_sent or 0) + 1

                    logger.info(f"✅ Oportunidade validada e enviada para jogo {game.id}: {opportunity['option']} @ {opportunity['odd']}")
                else:
                    # Envia mensagem de "Busca Continua" (opcional, para não spam)
                    # Só envia a mensagem se passou muito tempo desde a última.
                    if (now_utc - tracker.last_analysis_time).total_seconds() > 3600:  # 1 hora
                        tg_send_message(
                            f"🔄 <b>BUSCA CONTINUADA</b>\n"
                            f"Ainda não encontramos uma oportunidade de valor em <b>{game.team_home} vs {game.team_away}</b>.\n"
                            f"Continuaremos monitorando.",
                            message_type="live_opportunity",
                            game_id=game.id,
                            ext_id=game.ext_id
                        )
                        tracker.last_analysis_time = now_utc  # Atualiza para evitar spam
                        session.commit()

                session.commit()

            except Exception as e:
                logger.exception(f"Erro ao monitorar jogo ao vivo {game.id} ({game.ext_id}): {e}")

    logger.info("⚽ Monitoramento de jogos ao vivo concluído.")


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
            outcome = await fetch_game_result(game.ext_id, game.game_url or game.source_link)
            
            if outcome:
                game.outcome = outcome
                game.status = "ended"
                game.hit = (outcome == game.pick) if game.pick else None
                
                result_msg = "✅ ACERTOU" if game.hit else "❌ ERROU" if game.hit is False else "⚠️ SEM PALPITE"
                logger.info("🏁 Resultado obtido para jogo id=%s: %s | %s", game_id, outcome, result_msg)
                
                # Envia notificação de resultado
                from utils.formatters import fmt_result
                tg_send_message(
                    fmt_result(game),
                    message_type="result",
                    game_id=game.id,
                    ext_id=game.ext_id
                )
                
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
        trigger=IntervalTrigger(minutes=1),
        id="update_games_to_live",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=60,
    )
    
    # --- Monitoramento de jogos ao vivo ---
    scheduler.add_job(
        monitor_live_games_job,
        trigger=IntervalTrigger(minutes=1),
        id="monitor_live_games",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=60,
    )

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
