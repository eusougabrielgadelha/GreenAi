"""
BetNacional Auto Analyst — v2 (produção)
---------------------------------------
Script 24/7 para VPS (Ubuntu/Hostinger) que:
- Varre links da BetNacional diariamente às 06:00 (America/Fortaleza)
- Extrai jogos do dia, calcula valor esperado e seleciona palpites
- Agenda lembretes (−15min), acompanha jogos e publica resultados
- Envia tudo via Telegram para um canal
- Mantém banco (SQLite/Postgres) e estatísticas de assertividade
- Reinicia limpo (jobs persistem via APScheduler SQLAlchemyJobStore)

Como usar (resumo):
1) python3 -m venv venv && source venv/bin/activate
2) pip install -r requirements.txt
3) (Opcional p/ páginas dinâmicas) playwright install
4) crie .env (modelo ao fim) com tokens/links e DB_URL
5) python betnacional_auto_analyst.py --init  # cria tabelas, valida env
6) systemd unit (modelo ao fim) para rodar sempre

Observações:
- O parser tem seletores parametrizados por ENV (ver BNA_*). Ajuste aos seletores reais do site.
- Para análise avançada, você pode plugar seu SmartProbabilityAnalyzer: basta criar
  um arquivo custom_analyzer.py com uma função `analyze(competition, home, away, odds)`
  que retorne dict com keys: will_bet(bool), pick(str: home/draw/away), prob(float), ev(float), reason(str).
- Este arquivo é auto-contido e robusto: retry/backoff, idempotência, persistência e logs rotativos.
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import dataclasses
import json
import logging
import os
import random
import re
import signal
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple

import pytz
import requests
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table
from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    func,
)
from sqlalchemy.orm import declarative_base, sessionmaker

# Playwright opcional para páginas dinâmicas
try:
    from playwright.async_api import async_playwright  # type: ignore
    HAS_PLAYWRIGHT = True
except Exception:
    HAS_PLAYWRIGHT = False

# ===============================
# Configuração & Logging
# ===============================
load_dotenv()
console = Console()

APP_NAME = os.getenv("APP_NAME", "betauto")
TZ = os.getenv("APP_TZ", "America/Fortaleza")
ZONE = pytz.timezone(TZ)
MORNING_HOUR = int(os.getenv("MORNING_HOUR", "6"))

DB_URL = os.getenv("DB_URL", "sqlite:///betauto.sqlite3")
JOBSTORE_URL = os.getenv("JOBSTORE_URL", DB_URL)  # pode ser o mesmo DB

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "8487738643:AAHfnEEB6PKN6rDlRKrKkrh6HGRyTYtrge0")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "-1002952840130")

SCRAPE_BACKEND = os.getenv("SCRAPE_BACKEND", "requests").lower()  # requests|playwright
REQUESTS_TIMEOUT = float(os.getenv("REQUESTS_TIMEOUT", "20"))
USER_AGENT = os.getenv(
    "USER_AGENT",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123 Safari/537.36",
)
HTTP_PROXY = os.getenv("HTTP_PROXY", "")  # ex: http://user:pass@host:port
HTTPS_PROXY = os.getenv("HTTPS_PROXY", "")

# Seletores (ajuste aos reais)
BNA_CARD_SEL = os.getenv("BNA_CARD_SEL", ".event-card")
BNA_COMP_SEL = os.getenv("BNA_COMP_SEL", ".competition")
BNA_TEAM_SEL = os.getenv("BNA_TEAM_SEL", ".team-name")  # dois elementos
BNA_TIME_SEL = os.getenv("BNA_TIME_SEL", ".start-time")
BNA_ODD_HOME_SEL = os.getenv("BNA_ODD_HOME_SEL", ".odd-home")
BNA_ODD_DRAW_SEL = os.getenv("BNA_ODD_DRAW_SEL", ".odd-draw")
BNA_ODD_AWAY_SEL = os.getenv("BNA_ODD_AWAY_SEL", ".odd-away")
BNA_EVENT_ID_ATTR = os.getenv("BNA_EVENT_ID_ATTR", "data-event-id")

# Formatos de data/hora exibidos pelo site (ordem de tentativa)
TIME_FORMATS = [
    fmt.strip() for fmt in os.getenv(
        "BNA_TIME_FORMATS",
        "%H:%M %d/%m/%Y, %d/%m %H:%M, %d/%m/%y %H:%M, %H:%M",
    ).split(",")
]

# Links da BetNacional (separe por vírgula)
LINKS = [s.strip() for s in os.getenv("BETNACIONAL_LINKS", "").split(",") if s.strip()]

# Regras de decisão simples (se não houver custom_analyzer)
EV_MIN = float(os.getenv("EV_MIN", "0.02"))  # EV mínimo para recomendar aposta

# Notificações
REMINDER_MINUTES = int(os.getenv("REMINDER_MINUTES", "15"))
DAILY_WRAPUP_FALLBACK_HOUR = int(os.getenv("DAILY_WRAPUP_FALLBACK_HOUR", "23"))  # 23:50
DAILY_WRAPUP_FALLBACK_MIN = int(os.getenv("DAILY_WRAPUP_FALLBACK_MIN", "50"))

# Logging rotativo
LOG_DIR = os.getenv("LOG_DIR", "logs")
os.makedirs(LOG_DIR, exist_ok=True)
log_path = os.path.join(LOG_DIR, f"{APP_NAME}.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.handlers.RotatingFileHandler(log_path, maxBytes=2_000_000, backupCount=5, encoding="utf-8"),
    ],
)
log = logging.getLogger(APP_NAME)

# ===============================
# Banco de Dados (SQLAlchemy)
# ===============================
Base = declarative_base()
engine = create_engine(DB_URL, echo=False, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

class Game(Base):
    __tablename__ = "games"
    id = Column(Integer, primary_key=True)
    # Unicidade por ext_id + start_time (idempotência)
    ext_id = Column(String, index=True)
    start_time = Column(DateTime, index=True)         # UTC
    __table_args__ = (
        UniqueConstraint("ext_id", "start_time", name="uq_game_ext_start"),
    )

    source_link = Column(Text)
    competition = Column(String)
    team_home = Column(String)
    team_away = Column(String)

    odds_home = Column(Float)
    odds_draw = Column(Float)
    odds_away = Column(Float)

    pick = Column(String)              # home|draw|away
    pick_reason = Column(Text)
    pick_prob = Column(Float)
    pick_ev = Column(Float)
    will_bet = Column(Boolean, default=False)

    status = Column(String, default="scheduled")  # scheduled|live|ended
    outcome = Column(String, nullable=True)        # home|draw|away
    hit = Column(Boolean, nullable=True)

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())

class Stat(Base):
    __tablename__ = "stats"
    id = Column(Integer, primary_key=True)
    key = Column(String, unique=True, index=True)
    value = Column(JSON)

# ===============================
# Utilidades de Tempo
# ===============================

def now_utc() -> datetime:
    return datetime.now(tz=pytz.UTC)

def local_today() -> datetime:
    return datetime.now(ZONE).replace(hour=0, minute=0, second=0, microsecond=0)

# ===============================
# Telegram API (com proteção de MarkdownV2)
# ===============================
TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"

MDV2_ESCAPE = re.compile(r"([_*\[\]()~`>#+\-=|{}.!])")

def mdv2(text: str) -> str:
    return MDV2_ESCAPE.sub(r"\\\\\1", text)

def tg_send_message(text: str, parse_mode: str = "MarkdownV2") -> None:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        log.warning("Telegram não configurado; mensagem suprimida")
        return
    url = TELEGRAM_API.format(token=TELEGRAM_TOKEN, method="sendMessage")
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }
    proxies = {"http": HTTP_PROXY, "https": HTTPS_PROXY} if (HTTP_PROXY or HTTPS_PROXY) else None
    try:
        r = requests.post(url, json=payload, timeout=15, proxies=proxies)
        if r.status_code != 200:
            log.error("Telegram %s: %s", r.status_code, r.text[:200])
    except Exception as e:
        log.exception("Falha Telegram: %s", e)

# ===============================
# Scraping Helpers
# ===============================
HEADERS = {"User-Agent": USER_AGENT}

async def fetch_playwright(url: str) -> str:
    if not HAS_PLAYWRIGHT:
        raise RuntimeError("Playwright não instalado")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(url, wait_until="networkidle")
        html = await page.content()
        await browser.close()
        return html

def fetch_requests(url: str) -> str:
    proxies = {"http": HTTP_PROXY, "https": HTTPS_PROXY} if (HTTP_PROXY or HTTPS_PROXY) else None
    r = requests.get(url, headers=HEADERS, timeout=REQUESTS_TIMEOUT, proxies=proxies)
    r.raise_for_status()
    return r.text

async def fetch_html(url: str) -> str:
    for attempt in range(3):
        try:
            if SCRAPE_BACKEND == "playwright":
                return await fetch_playwright(url)
            else:
                return fetch_requests(url)
        except Exception as e:
            log.warning("Falha ao buscar %s (tentativa %d): %s", url, attempt + 1, e)
            await asyncio.sleep(1 + attempt * 2)
    return ""

@dataclass
class RawEvent:
    ext_id: Optional[str]
    competition: str
    team_home: str
    team_away: str
    start_time_local: str
    odds_home: Optional[float]
    odds_draw: Optional[float]
    odds_away: Optional[float]

async def parse_events_from_link(link: str) -> List[RawEvent]:
    html = await fetch_html(link)
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    out: List[RawEvent] = []

    for card in soup.select(BNA_CARD_SEL):
        comp_el = card.select_one(BNA_COMP_SEL)
        team_els = card.select(BNA_TEAM_SEL)
        time_el = card.select_one(BNA_TIME_SEL)
        if not comp_el or len(team_els) < 2 or not time_el:
            continue
        comp = comp_el.get_text(strip=True)
        home = team_els[0].get_text(strip=True)
        away = team_els[1].get_text(strip=True)
        start_str = time_el.get_text(strip=True)

        def _num(sel: str) -> Optional[float]:
            el = card.select_one(sel)
            if not el:
                return None
            raw = el.get_text(strip=True).replace(",", ".")
            try:
                return float("".join(ch for ch in raw if ch.isdigit() or ch == "."))
            except Exception:
                return None

        o_home = _num(BNA_ODD_HOME_SEL)
        o_draw = _num(BNA_ODD_DRAW_SEL)
        o_away = _num(BNA_ODD_AWAY_SEL)
        ext_id = card.get(BNA_EVENT_ID_ATTR)

        out.append(RawEvent(ext_id, comp, home, away, start_str, o_home, o_draw, o_away))
    return out

# ===============================
# Conversão de datas (site -> UTC)
# ===============================

def parse_local_datetime(s: str) -> Optional[datetime]:
    s = s.strip()
    if not s:
        return None
    for fmt in TIME_FORMATS:
        fmt = fmt.strip()
        try:
            dt_local = datetime.strptime(s, fmt)
            # Se formato não tem ano, assume ano atual
            if "%Y" not in fmt and "%y" not in fmt:
                now_l = datetime.now(ZONE)
                dt_local = dt_local.replace(year=now_l.year)
            dt_local = ZONE.localize(dt_local)
            return dt_local.astimezone(pytz.UTC)
        except Exception:
            continue
    return None

# ===============================
# Engine de Decisão (default + plugin opcional)
# ===============================

# plugin opcional: custom_analyzer.py com função analyze(...)
CUSTOM_ANALYZER = None
with contextlib.suppress(Exception):
    import importlib
    CUSTOM_ANALYZER = importlib.import_module("custom_analyzer")  # type: ignore

PICKS = ["home", "draw", "away"]

def decide_default(competition: str, home: str, away: str, odds: Tuple[Optional[float], Optional[float], Optional[float]]
                   ) -> Tuple[bool, str, float, float, str]:
    """Estratégia simples baseada em EV a partir de probabilidades implícitas.
    Retorna (will_bet, pick, prob, ev, reason)
    """
    try:
        o_home, o_draw, o_away = odds
        arr = [o_home or 0.0, o_draw or 0.0, o_away or 0.0]
        if any(x < 1.01 for x in arr):
            return False, "", 0.0, 0.0, "Odds inválidas"
        impl = [1/x for x in arr]
        total = sum(impl)
        if total <= 0:
            return False, "", 0.0, 0.0, "Prob total inválida"
        true = [p/total for p in impl]
        evs = [(p*o - 1.0) for p, o in zip(true, arr)]
        idx = max(range(3), key=lambda i: evs[i])
        if evs[idx] < EV_MIN:
            return False, "", float(true[idx]), float(evs[idx]), f"EV < {EV_MIN:.2f}"
        return True, PICKS[idx], float(true[idx]), float(evs[idx]), "EV positivo"
    except Exception as e:
        return False, "", 0.0, 0.0, f"Erro: {e}"

async def decide_bet(competition: str, home: str, away: str,
                     o_home: Optional[float], o_draw: Optional[float], o_away: Optional[float]
                     ) -> Tuple[bool, str, float, float, str]:
    if CUSTOM_ANALYZER and hasattr(CUSTOM_ANALYZER, "analyze"):
        with contextlib.suppress(Exception):
            res = CUSTOM_ANALYZER.analyze(competition, home, away, (o_home, o_draw, o_away))
            # validar saída
            if isinstance(res, dict):
                will = bool(res.get("will_bet", False))
                pick = str(res.get("pick", ""))
                prob = float(res.get("prob", 0.0))
                ev = float(res.get("ev", 0.0))
                reason = str(res.get("reason", ""))
                if pick in ("home", "draw", "away"):
                    return will, pick, prob, ev, reason
    # fallback
    return decide_default(competition, home, away, (o_home, o_draw, o_away))

# ===============================
# Estatística de assertividade
# ===============================

def get_global_accuracy(session) -> float:
    q = session.query(Game).filter(Game.hit.isnot(None))
    total = q.count()
    if total == 0:
        return 0.0
    hits = q.filter(Game.hit.is_(True)).count()
    return hits / total

# ===============================
# Mensagens formatadas (Telegram)
# ===============================

def fmt_morning_summary(date_local: datetime, analyzed: int, chosen: List[Game]) -> str:
    dstr = date_local.strftime("%d/%m/%Y")
    lines = [
        f"Hoje, *{mdv2(dstr)}*, analisei um total de *{analyzed}* jogos.",
        f"Entendi que existem um total de *{len(chosen)}* jogos eleitos para apostas. São eles:",
        "",
    ]
    for g in chosen:
        local_t = g.start_time.astimezone(ZONE)
        hhmm = local_t.strftime("%H:%M")
        comp = g.competition or "—"
        jogo = f"{g.team_home} vs {g.team_away}"
        pick_str = {"home": g.team_home, "draw": "Empate", "away": g.team_away}.get(g.pick, "—")
        lines.append(f"{mdv2(hhmm)} | {mdv2(comp)} | {mdv2(jogo)} | Apostar em *{mdv2(pick_str)}*")
    lines.append("")
    with SessionLocal() as s:
        acc = get_global_accuracy(s) * 100
    lines.append(f"Taxa de assertividade atual: *{acc:.1f}%*")
    return "\n".join(lines)

def fmt_reminder(g: Game) -> str:
    hhmm = g.start_time.astimezone(ZONE).strftime("%H:%M")
    pick_str = {"home": g.team_home, "draw": "Empate", "away": g.team_away}.get(g.pick, "—")
    return (
        f"⏰ *Lembrete*: {mdv2(hhmm)} vai começar\n"
        f"{mdv2(g.competition or 'Jogo')} — {mdv2(g.team_home)} vs {mdv2(g.team_away)}\n"
        f"Aposta: *{mdv2(pick_str)}*"
    )

def fmt_result(g: Game) -> str:
    status = "✅ ACERTOU" if g.hit else "❌ ERROU"
    return (
        f"🏁 *Finalizado* — {mdv2(g.team_home)} vs {mdv2(g.team_away)}\n"
        f"Palpite: {mdv2(g.pick or '—')} | Resultado: {mdv2(g.outcome or '—')}\n"
        f"{status} | EV estimado: {g.pick_ev*100:.1f}%"
    )

# ===============================
# Scheduler (persistente)
# ===============================

jobstores = {"default": SQLAlchemyJobStore(url=JOBSTORE_URL)}
scheduler = AsyncIOScheduler(jobstores=jobstores, timezone=str(ZONE))

# ===============================
# Workflows
# ===============================

async def morning_scan_and_publish() -> None:
    if not LINKS:
        log.warning("Sem links em BETNACIONAL_LINKS; scan abortado")
        return
    log.info("Varredura matinal iniciada")
    analyzed = 0
    chosen: List[Game] = []

    # Coleta concorrente dos links
    results = await asyncio.gather(*[parse_events_from_link(url) for url in LINKS])
    with SessionLocal() as session:
        for link, events in zip(LINKS, results):
            analyzed += len(events)
            for ev in events:
                start_utc = parse_local_datetime(ev.start_time_local)
                if not start_utc:
                    continue
                # somente jogos do dia local
                if start_utc.astimezone(ZONE).date() != datetime.now(ZONE).date():
                    continue

                # Idempotência: busca se já existe
                existing = (
                    session.query(Game)
                    .filter(Game.ext_id == ev.ext_id, Game.start_time == start_utc)
                    .one_or_none()
                )

                will, pick, prob, evv, reason = await decide_bet(
                    ev.competition, ev.team_home, ev.team_away, ev.odds_home, ev.odds_draw, ev.odds_away
                )

                if existing:
                    g = existing
                    g.source_link = link
                    g.competition = ev.competition
                    g.team_home = ev.team_home
                    g.team_away = ev.team_away
                    g.odds_home = ev.odds_home
                    g.odds_draw = ev.odds_draw
                    g.odds_away = ev.odds_away
                    g.will_bet = will
                    g.pick = pick
                    g.pick_prob = prob
                    g.pick_ev = evv
                    g.pick_reason = reason
                else:
                    g = Game(
                        ext_id=ev.ext_id,
                        source_link=link,
                        competition=ev.competition,
                        team_home=ev.team_home,
                        team_away=ev.team_away,
                        start_time=start_utc,
                        odds_home=ev.odds_home,
                        odds_draw=ev.odds_draw,
                        odds_away=ev.odds_away,
                        will_bet=will,
                        pick=pick,
                        pick_prob=prob,
                        pick_ev=evv,
                        pick_reason=reason,
                    )
                    session.add(g)
                session.commit()

                if will:
                    chosen.append(g)
                    # Agenda lembrete −15 min
                    reminder_at = (g.start_time - timedelta(minutes=REMINDER_MINUTES)).astimezone(pytz.UTC)
                    scheduler.add_job(
                        send_reminder_job,
                        trigger=DateTrigger(run_date=reminder_at),
                        args=[g.id],
                        id=f"reminder_{g.id}",
                        replace_existing=True,
                    )
                    # Agenda watcher de resultado no horário do jogo
                    scheduler.add_job(
                        watch_game_until_end_job,
                        trigger=DateTrigger(run_date=g.start_time),
                        args=[g.id],
                        id=f"watch_{g.id}",
                        replace_existing=True,
                    )

    # Envia resumo da manhã
    summary = fmt_morning_summary(datetime.now(ZONE), analyzed, chosen)
    tg_send_message(summary)
    log.info("Varredura matinal finalizada: analisados=%d, escolhidos=%d", analyzed, len(chosen))

async def send_reminder_job(game_id: int) -> None:
    with SessionLocal() as s:
        g = s.get(Game, game_id)
        if not g or not g.will_bet:
            return
        tg_send_message(fmt_reminder(g))
        log.info("Reminder enviado para jogo %s vs %s", g.team_home, g.team_away)

async def watch_game_until_end_job(game_id: int) -> None:
    """Watcher de resultado.
    TODO: substituir o bloco de simulação por scraping do resultado real.
    Estrutura pronta para polling periódico com backoff leve.
    """
    with SessionLocal() as s:
        g = s.get(Game, game_id)
        if not g:
            return
    log.info("Watcher iniciado para %s vs %s", g.team_home, g.team_away)

    kickoff = g.start_time
    deadline = kickoff + timedelta(hours=3)
    interval = 30  # segundos; ajuste conforme necessário

    # Simulação de polling até finalizar; troque o bloco marcado por scraping real.
    while now_utc() < deadline:
        # Bloco de scraping real de status/result: set `finished` e `outcome`
        finished = False
        outcome: Optional[str] = None

        # TODO >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
        # Exemplo (SIMULAÇÃO): 70% de chance de finalizar após 90min
        if (now_utc() - kickoff) > timedelta(minutes=100):
            finished = True
            outcome = random.choice(["home", "draw", "away"])  # substitua pelo real
        # TODO <<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<

        if finished and outcome in ("home", "draw", "away"):
            with SessionLocal() as s:
                g = s.get(Game, game_id)
                if g:
                    g.status = "ended"
                    g.outcome = outcome
                    g.hit = (g.pick == outcome) if g.pick else None
                    s.commit()
            with SessionLocal() as s:
                g = s.get(Game, game_id)
            if g:
                tg_send_message(fmt_result(g))
                log.info("Resultado publicado %s vs %s | hit=%s", g.team_home, g.team_away, g.hit)
            break

        await asyncio.sleep(interval)

    await maybe_send_daily_wrapup()

async def maybe_send_daily_wrapup() -> None:
    today = datetime.now(ZONE).date()
    with SessionLocal() as s:
        day_start = ZONE.localize(datetime(today.year, today.month, today.day, 0, 0)).astimezone(pytz.UTC)
        day_end = ZONE.localize(datetime(today.year, today.month, today.day, 23, 59)).astimezone(pytz.UTC)
        todays_picks = (
            s.query(Game)
            .filter(Game.start_time >= day_start, Game.start_time <= day_end, Game.will_bet.is_(True))
            .all()
        )
        if not todays_picks:
            return
        finished = [g for g in todays_picks if g.status == "ended" and g.hit is not None]
        if len(finished) == len(todays_picks):
            hits = sum(1 for g in finished if g.hit)
            total = len(finished)
            acc_day = (hits/total*100) if total else 0.0
            gacc = get_global_accuracy(s) * 100
            lines = [
                f"📊 *Resumo do dia* ({mdv2(today.strftime('%d/%m/%Y'))})",
                f"Palpites dados: *{total}* | Acertos: *{hits}* | Assertividade do dia: *{acc_day:.1f}%*",
                f"Assertividade geral do script: *{gacc:.1f}%*",
            ]
            tg_send_message("\n".join(lines))
            log.info("Wrap-up diário enviado: total=%d hits=%d", total, hits)

# Fallback: agenda wrap-up às 23:50 local (caso watchers não fechem o dia)
async def daily_wrapup_fallback_job() -> None:
    await maybe_send_daily_wrapup()

# ===============================
# Inicialização / Recuperação
# ===============================

def init_db() -> None:
    Base.metadata.create_all(engine)
    log.info("Tabelas criadas/validadas")

async def reschedule_todays_pending() -> None:
    """Após restart, reagenda lembretes e watchers dos jogos de hoje que ainda não começaram/terminaram."""
    today = datetime.now(ZONE).date()
    with SessionLocal() as s:
        day_start = ZONE.localize(datetime(today.year, today.month, today.day, 0, 0)).astimezone(pytz.UTC)
        day_end = ZONE.localize(datetime(today.year, today.month, today.day, 23, 59)).astimezone(pytz.UTC)
        rows = (
            s.query(Game)
            .filter(Game.start_time >= day_start, Game.start_time <= day_end)
            .all()
        )
        for g in rows:
            # lembrete se ainda não passado
            rem_time = (g.start_time - timedelta(minutes=REMINDER_MINUTES))
            if g.will_bet and now_utc() < rem_time:
                scheduler.add_job(send_reminder_job, DateTrigger(run_date=rem_time), args=[g.id], id=f"reminder_{g.id}", replace_existing=True)
            # watcher se jogo não finalizado e horário >= agora
            if (g.status != "ended") and (now_utc() <= g.start_time + timedelta(hours=3)):
                start_at = max(g.start_time, now_utc())
                scheduler.add_job(watch_game_until_end_job, DateTrigger(run_date=start_at), args=[g.id], id=f"watch_{g.id}", replace_existing=True)

# ===============================
# CLI / Runner
# ===============================

async def main(args: argparse.Namespace) -> None:
    init_db()

    # Scheduler com jobstore persistente
    scheduler.start()

    # Tarefa diária 06:00
    scheduler.add_job(
        morning_scan_and_publish,
        trigger=CronTrigger(hour=MORNING_HOUR, minute=0),
        id="morning_scan",
        replace_existing=True,
    )
    # Wrap-up fallback (23:50 por padrão)
    scheduler.add_job(
        daily_wrapup_fallback_job,
        trigger=CronTrigger(hour=DAILY_WRAPUP_FALLBACK_HOUR, minute=DAILY_WRAPUP_FALLBACK_MIN),
        id="wrapup_fallback",
        replace_existing=True,
    )

    # Reagendar pendentes do dia
    await reschedule_todays_pending()

    # Opcional: rodar scan imediato
    if args.scan_now:
        await morning_scan_and_publish()

    # Espera até SIGINT/SIGTERM
    loop = asyncio.get_running_loop()
    stopped = asyncio.Event()

    def _sig(*_: Any) -> None:
        log.info("Sinal de parada recebido; encerrando...")
        stopped.set()

    for sgn in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sgn, _sig)

    await stopped.wait()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="BetNacional Auto Analyst")
    parser.add_argument("--init", action="store_true", help="apenas inicializa DB e valida env")
    parser.add_argument("--scan-now", action="store_true", help="executa varredura imediatamente no boot")
    ns = parser.parse_args()

    if ns.init:
        init_db()
        console.print("[green]DB inicializado. Configure o .env e rode o serviço.[/green]")
    else:
        try:
            asyncio.run(main(ns))
        except KeyboardInterrupt:
            pass

# ===============================
# requirements.txt (sugestão)
# ===============================
"""
APScheduler==3.10.4
SQLAlchemy==2.0.32
python-dotenv==1.0.1
requests==2.32.3
beautifulsoup4==4.12.3
pytz==2025.1
rich==13.7.1
# Jobstore APScheduler
SQLAlchemy-Utils==0.41.2
# Opcional p/ páginas dinâmicas
playwright==1.47.0
"""

# ===============================
# .env.example
# ===============================
"""
APP_NAME=betauto
APP_TZ=America/Fortaleza
MORNING_HOUR=6

DB_URL=sqlite:///betauto.sqlite3
JOBSTORE_URL=sqlite:///betauto_jobs.sqlite3

TELEGRAM_TOKEN=123456:ABC-DEF...
TELEGRAM_CHAT_ID=@seu_canal

SCRAPE_BACKEND=requests
REQUESTS_TIMEOUT=20
USER_AGENT=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123 Safari/537.36
HTTP_PROXY=
HTTPS_PROXY=

# Seletores (ajuste aos reais)
BNA_CARD_SEL=.event-card
BNA_COMP_SEL=.competition
BNA_TEAM_SEL=.team-name
BNA_TIME_SEL=.start-time
BNA_ODD_HOME_SEL=.odd-home
BNA_ODD_DRAW_SEL=.odd-draw
BNA_ODD_AWAY_SEL=.odd-away
BNA_EVENT_ID_ATTR=data-event-id
# Formatos de data aceitos pelo site, separados por vírgula (ordem de tentativa)
BNA_TIME_FORMATS=%H:%M %d/%m/%Y, %d/%m %H:%M, %d/%m/%y %H:%M, %H:%M

# Links da BetNacional
BETNACIONAL_LINKS=https://www.betnacional.com/competicao/serie-a,https://www.betnacional.com/competicao/copa-do-brasil

# Regras de decisão simples
EV_MIN=0.02

# Notificações
REMINDER_MINUTES=15
DAILY_WRAPUP_FALLBACK_HOUR=23
DAILY_WRAPUP_FALLBACK_MIN=50
"""

# ===============================
# systemd unit (exemplo): /etc/systemd/system/betauto.service
# ===============================
"""
[Unit]
Description=BetNacional Auto Analyst v2
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/betauto
ExecStart=/home/ubuntu/betauto/venv/bin/python /home/ubuntu/betauto/betnacional_auto_analyst.py --scan-now
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
"""
