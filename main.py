from __future__ import annotations
import asyncio
import os
import signal
# Removido: random - não utilizado
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
import pytz
# Removido: imports do scheduler - usar de scheduler/jobs.py
# Removido: IntegrityError - usar de utils/game_helpers
from utils.logger import logger

# ================================
# Imports de módulos do sistema
# ================================
from scraping.fetchers import (
    fetch_events_from_link, fetch_game_result,
    fetch_requests, _fetch_requests_async
)
from scraping.betnacional import (
    scrape_live_game_data, parse_local_datetime
)
from betting.decision import decide_bet, decide_live_bet_opportunity
from utils.formatters import (
    fmt_morning_summary, fmt_result, fmt_pick_now, fmt_reminder,
    fmt_watch_add, fmt_watch_upgrade, fmt_live_bet_opportunity,
    fmt_dawn_games_summary, fmt_today_games_summary, format_night_scan_summary
)
from utils.stats import global_accuracy, to_aware_utc, save_odd_history
from utils.game_helpers import (
    upsert_game_from_event,
    is_high_conf, was_high_conf_notified, mark_high_conf_notified
)
from utils.telegram_helpers import send_summary_safe
from utils.event_processor import (
    process_event_decision, check_and_add_to_watchlist,
    create_game_snapshot, create_simple_game_snapshot
)
from watchlist.manager import wl_load, wl_save, wl_add, wl_remove

# ================================
# Config - Importa de config.settings
# ================================
from config.settings import (
    APP_TZ, ZONE, MORNING_HOUR, DB_URL, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID,
    SCRAPE_BACKEND, REQUESTS_TIMEOUT, USER_AGENT, HIGH_CONF_THRESHOLD,
    HIGH_CONF_SENT_MARK, EXTRA_LINKS, LOG_DIR, START_ALERT_MIN,
    LATE_WATCH_WINDOW_MIN, WATCHLIST_DELTA, WATCHLIST_MIN_LEAD_MIN,
    WATCHLIST_RESCAN_MIN, MIN_EV, MIN_PROB, get_all_betting_links
)

# Removido: logger duplicado - usar de utils.logger

# ================================
# DB - Importa dos modelos
# ================================
from models.database import Game, LiveGameTracker, SessionLocal


# ================================
# Telegram - Importa do módulo de notificações
# ================================
from notifications.telegram import tg_send_message

# ================================
# Scheduler - Importa de scheduler/jobs.py
# ================================
from scheduler.jobs import scheduler, setup_scheduler

# ================================
# Jobs - Todos movidos para scheduler/jobs.py
# ================================
# Removido: todos os jobs foram movidos para scheduler/jobs.py para evitar dependência circular

# ================================
# Runner
# ================================
async def main():
    setup_scheduler()
    # dispara uma varredura no boot para testar
    from scheduler.jobs import morning_scan_and_publish
    await morning_scan_and_publish()
    loop = asyncio.get_running_loop()
    stop = asyncio.Event()
    def _sig(*_):
        logger.info("Sinal de parada recebido; encerrando…")
        stop.set()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _sig)
        except NotImplementedError:
            pass
    await stop.wait()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
