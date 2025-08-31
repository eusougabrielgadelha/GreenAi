# main.py
from __future__ import annotations

import asyncio
import os
import re
import signal
import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import pytz
import json
import logging
from logging.handlers import RotatingFileHandler

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from types import SimpleNamespace as NS

from sqlalchemy import (
    create_engine, Column, Integer, String, Float, Text, DateTime, Boolean, JSON, func, UniqueConstraint
)
from sqlalchemy.orm import declarative_base, sessionmaker
    # noqa: E402
from sqlalchemy.exc import IntegrityError

# ================================
# Playwright (opcional)
# ================================
HAS_PLAYWRIGHT = False
try:
    from playwright.async_api import async_playwright
    HAS_PLAYWRIGHT = True
except Exception:
    HAS_PLAYWRIGHT = False

# ================================
# Config
# ================================
load_dotenv()

APP_TZ = os.getenv("APP_TZ", "America/Fortaleza")
ZONE = pytz.timezone(APP_TZ)

MORNING_HOUR = int(os.getenv("MORNING_HOUR", "6"))

DB_URL = os.getenv("DB_URL", "sqlite:///betauto.sqlite3")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

SCRAPE_BACKEND = os.getenv("SCRAPE_BACKEND", "requests").lower()  # requests | playwright | auto
REQUESTS_TIMEOUT = float(os.getenv("REQUESTS_TIMEOUT", "20"))
USER_AGENT = os.getenv(
    "USER_AGENT",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123 Safari/537.36"
)

# Se desejar complementar via .env:
# BETNACIONAL_LINKS=https://betnacional.bet.br/events/1/0/7,https://...
EXTRA_LINKS = [s.strip() for s in os.getenv("BETNACIONAL_LINKS", "").split(",") if s.strip()]

LOG_DIR = os.getenv("LOG_DIR", "logs")
os.makedirs(LOG_DIR, exist_ok=True)

# ================================
# Logger (stdout + arquivo)
# ================================
logger = logging.getLogger("betauto")
logger.setLevel(logging.INFO)

_fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")

h_file = RotatingFileHandler(os.path.join(LOG_DIR, "betauto.log"), maxBytes=2_000_000, backupCount=5, encoding="utf-8")
h_file.setFormatter(_fmt)
h_file.setLevel(logging.INFO)

h_out = logging.StreamHandler()
h_out.setFormatter(_fmt)
h_out.setLevel(logging.INFO)

if not logger.handlers:
    logger.addHandler(h_file)
    logger.addHandler(h_out)

# ================================
# DB
# ================================
Base = declarative_base()
engine = create_engine(DB_URL, echo=False, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

class Game(Base):
    __tablename__ = "games"
    id = Column(Integer, primary_key=True)
    ext_id = Column(String, index=True)
    source_link = Column(Text)
    competition = Column(String)
    team_home = Column(String)
    team_away = Column(String)
    start_time = Column(DateTime, index=True)    # UTC
    odds_home = Column(Float)
    odds_draw = Column(Float)
    odds_away = Column(Float)
    pick = Column(String)                        # home|draw|away
    pick_reason = Column(Text)
    pick_prob = Column(Float)
    pick_ev = Column(Float)
    will_bet = Column(Boolean, default=False)
    status = Column(String, default="scheduled") # scheduled|live|ended
    outcome = Column(String, nullable=True)      # home|draw|away
    hit = Column(Boolean, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("ext_id", "start_time", name="uq_game_extid_start"),
    )

class Stat(Base):
    __tablename__ = "stats"
    id = Column(Integer, primary_key=True)
    key = Column(String, unique=True, index=True)
    value = Column(JSON)

Base.metadata.create_all(engine)

# ================================
# Telegram
# ================================
def tg_send_message(text: str, parse_mode: Optional[str] = "HTML") -> None:
    """Usa HTML por padrão; omite parse_mode se None para evitar 400."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Telegram não configurado (TOKEN/CHAT_ID ausentes).")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "disable_web_page_preview": True,
    }
    if parse_mode:  # só inclui quando tem valor válido
        payload["parse_mode"] = parse_mode

    try:
        r = requests.post(url, json=payload, timeout=15)
        if r.status_code != 200:
            logger.error("Telegram %s: %s", r.status_code, r.text[:300])
    except Exception as e:
        logger.exception("Erro Telegram: %s", e)

def h(b: str) -> str:
    return f"<b>{b}</b>"

# ================================
# Scraper helpers
# ================================
HEADERS = {"User-Agent": USER_AGENT}

async def fetch_playwright(url: str) -> str:
    if not HAS_PLAYWRIGHT:
        raise RuntimeError("Playwright não disponível.")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(user_agent=USER_AGENT)
        await page.goto(url, wait_until="networkidle", timeout=60_000)
        html = await page.content()
        await browser.close()
        return html

def fetch_requests(url: str) -> str:
    r = requests.get(url, headers=HEADERS, timeout=REQUESTS_TIMEOUT)
    r.raise_for_status()
    return r.text

def num_from_text(s: str) -> Optional[float]:
    if not s:
        return None
    s = s.replace(",", ".")
    s = "".join(ch for ch in s if ch.isdigit() or ch == ".")
    try:
        v = float(s)
        return v if v >= 1.01 else None
    except:
        return None

def parse_local_datetime(s: str) -> Optional[datetime]:
    if not s:
        return None
    s = s.strip()

    # 1) tentar ISO-8601 (com Z ou offset)
    try:
        s_iso = s.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s_iso)
        if dt.tzinfo is None:
            dt_local = ZONE.localize(dt)
            return dt_local.astimezone(pytz.UTC)
        return dt.astimezone(pytz.UTC)
    except Exception:
        pass

    # 2) formatos legados
    fmts = [
        "%H:%M %d/%m/%Y", "%H:%M %d/%m/%y",
        "%d/%m/%Y %H:%M", "%d/%m/%y %H:%M",
        "%d/%m %H:%M", "%H:%M",
    ]
    for fmt in fmts:
        try:
            dt = datetime.strptime(s, fmt)
            if "%Y" not in fmt and "%y" not in fmt:
                nowl = datetime.now(ZONE)
                dt = dt.replace(year=nowl.year)
            if fmt == "%H:%M":
                nowl = datetime.now(ZONE)
                dt = dt.replace(day=nowl.day, month=nowl.month, year=nowl.year)
            dt_local = ZONE.localize(dt)
            return dt_local.astimezone(pytz.UTC)
        except Exception:
            continue
    return None


@dataclass
class EventRow:
    competition: str
    team_home: str
    team_away: str
    start_local_str: str
    odds_home: Optional[float]
    odds_draw: Optional[float]
    odds_away: Optional[float]
    ext_id: Optional[str] = None

# --- util: converte "13 setembro", "Hoje" etc. para data local (yyyy-mm-dd)
_PT_MONTHS = {
    "janeiro": 1, "fevereiro": 2, "março": 3, "marco": 3, "abril": 4, "maio": 5, "junho": 6,
    "julho": 7, "agosto": 8, "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12,
}
def _date_from_header_text(txt: str) -> Optional[datetime]:
    t = (txt or "").strip().lower()
    if not t:
        return None
    if "hoje" in t:
        nowl = datetime.now(ZONE)
        return nowl.replace(hour=0, minute=0, second=0, microsecond=0)
    # opcional: amanhã/ontem (se a casa usar)
    if "amanhã" in t or "amanha" in t:
        nowl = datetime.now(ZONE) + timedelta(days=1)
        return nowl.replace(hour=0, minute=0, second=0, microsecond=0)
    if "ontem" in t:
        nowl = datetime.now(ZONE) - timedelta(days=1)
        return nowl.replace(hour=0, minute=0, second=0, microsecond=0)

    m = re.search(r"(\d{1,2})\s+([a-zç]+)", t)
    if m:
        day = int(m.group(1))
        mon_name = m.group(2)
        mon = _PT_MONTHS.get(mon_name, None)
        if mon:
            nowl = datetime.now(ZONE)
            dt = nowl.replace(month=mon, day=day, hour=0, minute=0, second=0, microsecond=0)
            return dt
    return None

def try_parse_events(html: str, url: str):
    """
    Parser adaptado ao HTML do Betnacional (com data-testid='odd-<id>_1_<col>_').
    Agora identifica o cabeçalho de data (“Hoje”, “13 setembro”, etc.) anterior a cada card
    e compõe o start_local_str com data completa, evitando “pegar” jogos de outras datas como se fossem de hoje.
    """
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select('[data-testid="preMatchOdds"]')
    evs = []

    def _num(txt: str):
        if not txt:
            return None
        txt = txt.strip().replace(",", ".")
        m = re.search(r"\d+(?:\.\d+)?", txt)
        return float(m.group(0)) if m else None

    for card in cards:
        # 1) identificar cabeçalho de data mais próximo acima
        hdr = card.find_previous(
            "div",
            class_=lambda c: c and "text-odds-subheader-text" in c
        )
        header_text = hdr.get_text(strip=True) if hdr else ""
        header_date = _date_from_header_text(header_text)  # datetime local com 00:00

        # 2) extrair identificadores e nomes
        a = card.select_one('a[href*="/event/"]')
        if not a:
            continue
        href = a.get("href", "")
        m = re.search(r"/event/\d+/\d+/(\d+)", href)
        ext_id = m.group(1) if m else ""

        title = a.get_text(" ", strip=True)
        team_home, team_away = "", ""
        if " x " in title:
            team_home, team_away = [p.strip() for p in title.split(" x ", 1)]
        else:
            names = [s.get_text(strip=True) for s in a.select("span.text-ellipsis")]
            if len(names) >= 2:
                team_home, team_away = names[0], names[1]

        # 3) hora local (ex.: 20:30). Se houver cabeçalho de data, montamos "HH:MM dd/mm/YYYY"
        t = card.select_one(".text-text-light-secondary")
        hour_local = t.get_text(strip=True) if t else ""
        start_local_str = hour_local

        if hour_local and header_date:
            dd = f"{header_date.day:02d}"
            mm = f"{header_date.month:02d}"
            yyyy = header_date.year
            start_local_str = f"{hour_local} {dd}/{mm}/{yyyy}"

        # 4) odds
        def pick_cell(i: int):
            if ext_id:
                c = card.select_one(f"[data-testid='odd-{ext_id}_1_{i}_']")
                if c:
                    return _num(c.get_text(" ", strip=True))
            return None

        odd_home = pick_cell(1)
        odd_draw = pick_cell(2)
        odd_away = pick_cell(3)

        if odd_home is None or odd_draw is None or odd_away is None:
            cells = card.select("[data-testid^='odd-'][data-testid$='_']")
            if ext_id:
                cells = [c for c in cells if c.get("data-testid", "").startswith(f"odd-{ext_id}_1_")]
            def col_index(c):
                mm = re.search(r"_1_(\d)_", c.get("data-testid", ""))
                return int(mm.group(1)) if mm else 99
            cells = sorted(cells, key=col_index)
            vals = [_num(c.get_text(" ", strip=True)) for c in cells[:3]]
            if len(vals) >= 3:
                odd_home, odd_draw, odd_away = vals

        evs.append(NS(
            ext_id=ext_id,
            source_link=url,
            competition="",  # se precisar, complemente
            team_home=team_home,
            team_away=team_away,
            start_local_str=start_local_str,  # agora com a data correta para o card
            odds_home=odd_home,
            odds_draw=odd_draw,
            odds_away=odd_away,
        ))

    return evs

async def fetch_events_from_link(url: str, backend: str):
    """
    Baixa a página (via requests ou playwright) e parseia os eventos.
    """
    backend_sel = backend
    if backend_sel == "auto":
        backend_sel = "playwright"  # escolha padrão

    logger.info("🔎 Varredura iniciada para %s — backend=%s", url, backend_sel)

    try:
        if backend_sel == "playwright":
            html = await _fetch_with_playwright(url)
            evs = try_parse_events(html, url)
        else:
            r = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
            r.raise_for_status()
            evs = try_parse_events(r.text, url)

        logger.info("🧮  → eventos extraídos: %d", len(evs))
        return evs

    except Exception as e:
        logger.warning("Falha ao buscar %s com %s: %s", url, backend_sel, e)
        return []

async def _fetch_with_playwright(url: str) -> str:
    """
    Renderiza a página com Playwright e retorna o HTML.
    """
    if not HAS_PLAYWRIGHT:
        raise RuntimeError("Playwright não disponível no ambiente.")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0",
            locale="pt-BR",
        )
        page = await context.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_selector('[data-testid="preMatchOdds"]', timeout=15000)
            html = await page.content()
            return html
        finally:
            await context.close()
            await browser.close()

# ================================
# Regras simples de decisão
# ================================
def decide_bet(odds_home, odds_draw, odds_away, competition, teams):
    # parâmetros ajustáveis
    MIN_ODD = 1.01
    MIN_EV = float(os.getenv("MIN_EV", "0.02"))
    MIN_PROB = float(os.getenv("MIN_PROB", "0.25"))
    FAV_MODE = os.getenv("FAV_MODE", "on").lower()      # on|off
    FAV_PROB_MIN = float(os.getenv("FAV_PROB_MIN", "0.70"))
    FAV_GAP_MIN = float(os.getenv("FAV_GAP_MIN", "0.18"))
    EV_TOL = float(os.getenv("EV_TOL", "-0.03"))
    # por padrão aceitamos favorito com EV negativo leve
    FAV_IGNORE_EV = os.getenv("FAV_IGNORE_EV", "on").lower() == "on"

    names = ("home", "draw", "away")
    odds = (float(odds_home or 0.0), float(odds_draw or 0.0), float(odds_away or 0.0))
    avail = [(n, o) for n, o in zip(names, odds) if o >= MIN_ODD]
    if len(avail) < 2:
        return False, "", 0.0, 0.0, "Odds insuficientes (menos de 2 mercados)"

    inv = [(n, 1.0 / o) for n, o in avail]
    tot = sum(v for _, v in inv)
    if tot <= 0:
        return False, "", 0.0, 0.0, "Probabilidades inválidas"

    true = {n: v / tot for n, v in inv}                 # prob. implícitas normalizadas
    odd_map = dict(avail)
    ev_map = {n: true[n] * odd_map[n] - 1.0 for n in true}

    # 1) Valor puro
    pick_ev, best_ev = max(ev_map.items(), key=lambda x: x[1])
    pprob_ev = true[pick_ev]
    if best_ev >= MIN_EV and pprob_ev >= MIN_PROB:
        return True, pick_ev, pprob_ev, best_ev, "EV positivo"

    # 2) Favorito “óbvio” (probabilidade)
    if FAV_MODE == "on":
        probs_sorted = sorted(true.items(), key=lambda x: x[1], reverse=True)
        (pick_fav, p1), (_, p2) = probs_sorted[0], probs_sorted[1]
        ev_fav = ev_map.get(pick_fav, 0.0)
        gap_ok = (p1 - p2) >= FAV_GAP_MIN
        prob_ok = p1 >= max(MIN_PROB, FAV_PROB_MIN, 0.40)
        ev_ok = (ev_fav >= EV_TOL) or FAV_IGNORE_EV

        if prob_ok and gap_ok and ev_ok:
            reason = "Favorito claro (probabilidade)" if FAV_IGNORE_EV else "Favorito claro (regra híbrida)"
            return True, pick_fav, p1, ev_fav, reason

    reason = f"EV baixo (<{int(MIN_EV*100)}%)" if best_ev < MIN_EV else f"Probabilidade baixa (<{int(MIN_PROB*100)}%)"
    return False, "", pprob_ev, best_ev, reason

# ================================
# Links monitorados
# ================================
class BetAuto:
    def __init__(self):
        self.betting_links = {
            "UEFA Champions League": {"pais": "Europa", "campeonato": "UEFA Champions League", "link": "https://betnacional.bet.br/events/1/0/7"},
            "Espanha - LaLiga": {"pais": "Espanha", "campeonato": "LaLiga", "link": "https://betnacional.bet.br/events/1/0/8"},
            "Inglaterra - Premier League": {"pais": "Inglaterra", "campeonato": "Premier League", "link": "https://betnacional.bet.br/events/1/0/17"},
            "Brasil - Paulista": {"pais": "Brasil", "campeonato": "Paulista", "link": "https://betnacional.bet.br/events/1/0/15644"},
            "França - Ligue 1": {"pais": "França", "campeonato": "Ligue 1", "link": "https://betnacional.bet.br/events/1/0/34"},
            "Itália - Série A": {"pais": "Itália", "campeonato": "Série A", "link": "https://betnacional.bet.br/events/1/0/23"},
            "Alemanha - Bundesliga": {"pais": "Alemanha", "campeonato": "Bundesliga", "link": "https://betnacional.bet.br/events/1/0/38"},
            "Brasil - Série A": {"pais": "Brasil", "campeonato": "Brasileirão Série A", "link": "https://betnacional.bet.br/events/1/0/325"},
            "Brasil - Série B": {"pais": "Brasil", "campeonato": "Brasileirão Série B", "link": "https://betnacional.bet.br/events/1/0/390"},
            "Brasil - Série C": {"pais": "Brasil", "campeonato": "Brasileirão Série C", "link": "https://betnacional.bet.br/events/1/0/1281"},
            "Argentina - Série A": {"pais": "Argentina", "campeonato": "Argentina Série A", "link": "https://betnacional.bet.br/events/1/0/30106"},
            "Argentina - Série B": {"pais": "Argentina", "campeonato": "Argentina Série B", "link": "https://betnacional.bet.br/events/1/0/703"},
            "Estados Unidos - Major League Soccer": {"pais": "Estados Unidos", "campeonato": "Major League Soccer", "link": "https://betnacional.bet.br/events/1/0/242"},
        }

    def all_links(self) -> List[str]:
        base = [cfg["link"] for cfg in self.betting_links.values() if "link" in cfg]
        base.extend(EXTRA_LINKS)
        seen, out = set(), []
        for u in base:
            if u not in seen:
                out.append(u); seen.add(u)
        return out

# ================================
# Helpers de assertividade & mensagens
# ================================
def global_accuracy(session) -> float:
    total = session.query(Game).filter(Game.hit.isnot(None)).count()
    if total == 0:
        return 0.0
    hits = session.query(Game).filter(Game.hit.is_(True)).count()
    return hits / total

def fmt_morning_summary(date_local: datetime, analyzed: int, chosen: List[Game]) -> str:
    dstr = date_local.strftime("%d/%m/%Y")
    lines = [
        f"Hoje, {h(dstr)}, analisei um total de {h(str(analyzed))} jogos.",
        f"Entendi que existem um total de {h(str(len(chosen)))} jogos eleitos para apostas. São eles:",
        ""
    ]
    for g in chosen:
        local_t = g.start_time.astimezone(ZONE).strftime("%H:%M")
        comp = g.competition or "—"
        jogo = f"{g.team_home} vs {g.team_away}"
        pick_str = {"home": g.team_home, "draw": "Empate", "away": g.team_away}.get(g.pick, "—")
        lines.append(f"{local_t} | {comp} | {jogo} | Apostar em {h(pick_str)}")
    lines.append("")
    with SessionLocal() as s:
        acc = global_accuracy(s) * 100
    lines.append(f"Taxa de assertividade atual: {h(f'{acc:.1f}%')}")
    return "\n".join(lines)

def fmt_reminder(g: Game) -> str:
    hhmm = g.start_time.astimezone(ZONE).strftime("%H:%M")
    pick_str = {"home": g.team_home, "draw": "Empate", "away": g.team_away}.get(g.pick, "—")
    return (
        f"⏰ {h('Lembrete')}: {hhmm} vai começar\n"
        f"{g.competition or 'Jogo'} — {g.team_home} vs {g.team_away}\n"
        f"Aposta: {h(pick_str)}"
    )

def fmt_result(g: Game) -> str:
    status = "✅ ACERTOU" if g.hit else "❌ ERROU"
    return (
        f"🏁 {h('Finalizado')} — {g.team_home} vs {g.team_away}\n"
        f"Palpite: {g.pick} | Resultado: {g.outcome or '—'}\n"
        f"{status} | EV estimado: {g.pick_ev*100:.1f}%"
    )

def fmt_pick_now(g: Game) -> str:
    """Mensagem imediata por pick selecionado."""
    hhmm = g.start_time.astimezone(ZONE).strftime("%H:%M")
    side = {"home": g.team_home, "draw": "Empate", "away": g.team_away}.get(g.pick, "—")
    return (
        f"🎯 {h('Sinal de Aposta')} ({hhmm})\n"
        f"{g.team_home} vs {g.team_away}\n"
        f"Pick: {h(side)} — Prob: {g.pick_prob*100:.1f}% | EV: {g.pick_ev*100:.1f}%\n"
        f"Odds: {g.odds_home:.2f}/{g.odds_draw:.2f}/{g.odds_away:.2f}"
    )

# ================================
# Scheduler
# ================================
scheduler = AsyncIOScheduler(timezone=APP_TZ)
app = BetAuto()

# --- Config extra por .env ---
START_ALERT_MIN = int(os.getenv("START_ALERT_MIN", "15"))           # janela para alerta "começa agora"
LATE_WATCH_WINDOW_MIN = int(os.getenv("LATE_WATCH_WINDOW_MIN", "130"))  # watcher tardio (até 2h10 após o início)

# --- Helper: garantir sempre datetime aware em UTC ---
def to_aware_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return pytz.UTC.localize(dt)
    return dt.astimezone(pytz.UTC)


async def morning_scan_and_publish():
    logger.info("🌅 Iniciando varredura matinal...")
    stored_total = 0
    analyzed_total = 0

    # Resumo usa snapshots leves (dict) para evitar DetachedInstanceError
    chosen_view: List[Dict[str, Any]] = []
    # Guardamos o Game também para envio imediato do sinal, se precisar
    chosen_db: List[Game] = []

    def _send_summary_safe(text: str) -> None:
        try:
            tg_send_message(text, parse_mode="HTML")
            return
        except Exception:
            logger.exception("Falha com HTML; tentando sem parse_mode…")
        try:
            tg_send_message(text, parse_mode=None)
        except TypeError:
            try:
                tg_send_message(text)
            except Exception:
                logger.exception("Falha ao enviar resumo ao Telegram (fallback simples).")
        except Exception:
            logger.exception("Falha ao enviar resumo ao Telegram (fallback simples).")

    backend_cfg = SCRAPE_BACKEND if SCRAPE_BACKEND in ("requests", "playwright", "auto") else "requests"
    analysis_date_local = datetime.now(ZONE).date()
    logger.info("📅 Dia analisado (timezone %s): %s", ZONE, analysis_date_local.isoformat())

    with SessionLocal() as session:
        for url in app.all_links():
            evs: List[Any] = []
            active_backend = "requests" if backend_cfg in ("requests", "auto") else "playwright"

            # 1) tentativa principal
            try:
                evs = await fetch_events_from_link(url, active_backend)
            except Exception as e:
                logger.warning("Falha ao buscar %s com %s: %s", url, active_backend, e)

            # 2) fallback automático
            if backend_cfg == "auto" and not evs:
                try:
                    logger.info("🔁 Fallback para playwright em %s", url)
                    evs = await fetch_events_from_link(url, "playwright")
                    active_backend = "playwright"
                except Exception as e:
                    logger.warning("Fallback playwright também falhou em %s: %s", url, e)

            analyzed_total += len(evs)

            for ev in evs:
                try:
                    # ---- horário do evento -> UTC aware
                    start_utc = parse_local_datetime(getattr(ev, "start_local_str", ""))
                    if not start_utc:
                        logger.info("Ignorado: data inválida | %s vs %s | raw='%s'",
                                    getattr(ev, "team_home", "?"),
                                    getattr(ev, "team_away", "?"),
                                    getattr(ev, "start_local_str", ""))
                        continue

                    # normaliza qualquer datetime para UTC aware
                    start_utc = to_aware_utc(start_utc)

                    # ---- filtra SOMENTE jogos do dia analisado (timezone local do app)
                    event_date_local = start_utc.astimezone(ZONE).date()
                    if event_date_local != analysis_date_local:
                        logger.info("⏭️ Fora do dia analisado | %s vs %s | início='%s' (dia=%s) | url=%s",
                                    getattr(ev, "team_home", "?"),
                                    getattr(ev, "team_away", "?"),
                                    getattr(ev, "start_local_str", ""),
                                    event_date_local.isoformat(),
                                    url)
                        continue

                    # ---- decisão de aposta
                    will, pick, pprob, pev, reason = decide_bet(
                        ev.odds_home, ev.odds_draw, ev.odds_away, ev.competition, (ev.team_home, ev.team_away)
                    )
                    if not will:
                        logger.info(
                            "DESCARTADO: %s vs %s | motivo=%s | odds=(%.2f,%.2f,%.2f) | prob=%.1f%% | EV=%.1f%% | início='%s' | url=%s",
                            ev.team_home, ev.team_away, reason,
                            float(ev.odds_home or 0), float(ev.odds_draw or 0), float(ev.odds_away or 0),
                            pprob * 100, pev * 100, ev.start_local_str, url
                        )
                        continue

                    # ---- UPSERT (evita UNIQUE constraint em ext_id+start_time)
                    g = session.query(Game).filter_by(ext_id=ev.ext_id, start_time=start_utc).one_or_none()
                    if g:
                        g.source_link = url
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
                        session.commit()
                    else:
                        g = Game(
                            ext_id=ev.ext_id,
                            source_link=url,
                            competition=ev.competition,
                            team_home=ev.team_home,
                            team_away=ev.team_away,
                            start_time=start_utc,  # UTC aware
                            odds_home=ev.odds_home,
                            odds_draw=ev.odds_draw,
                            odds_away=ev.odds_away,
                            pick=pick,
                            pick_prob=pprob,
                            pick_ev=pev,
                            will_bet=will,
                            pick_reason=reason,
                        )
                        session.add(g)
                        try:
                            session.commit()
                        except IntegrityError:
                            session.rollback()
                            g = session.query(Game).filter_by(ext_id=ev.ext_id, start_time=start_utc).one_or_none()
                            if g:
                                g.source_link = url
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
                                session.commit()
                            else:
                                raise

                    stored_total += 1
                    session.refresh(g)  # garante id e campos atualizados

                    # Snapshot leve para resumo
                    chosen_db.append(g)
                    g_start = to_aware_utc(g.start_time)
                    chosen_view.append({
                        "id": g.id,
                        "ext_id": g.ext_id,
                        "source_link": g.source_link,
                        "competition": g.competition,
                        "team_home": g.team_home,
                        "team_away": g.team_away,
                        "start_time": g_start,
                        "odds_home": float(g.odds_home or 0.0),
                        "odds_draw": float(g.odds_draw or 0.0),
                        "odds_away": float(g.odds_away or 0.0),
                        "pick": g.pick,
                        "pick_prob": float(g.pick_prob or 0.0),
                        "pick_ev": float(g.pick_ev or 0.0),
                        "pick_reason": g.pick_reason,
                        "will_bet": bool(g.will_bet),
                        "status": g.status,
                        "outcome": g.outcome,
                        "hit": g.hit,
                    })

                    logger.info(
                        "✅ SELECIONADO: %s vs %s | pick=%s | prob=%.1f%% | EV=%.1f%% | odds=(%.2f,%.2f,%.2f) | início=%s | url=%s",
                        g.team_home, g.team_away, g.pick, g.pick_prob * 100, g.pick_ev * 100,
                        float(g.odds_home or 0), float(g.odds_draw or 0), float(g.odds_away or 0),
                        ev.start_local_str, url
                    )

                    # ---- Envio imediato do sinal
                    try:
                        tg_send_message(fmt_pick_now(g))
                    except Exception:
                        logger.exception("Falha ao enviar sinal imediato do jogo id=%s", g.id)

                    # ---- Agendamentos (tudo em UTC aware)
                    try:
                        now_utc = datetime.now(pytz.UTC)

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
                        else:
                            delta_min = int((now_utc - reminder_at).total_seconds() // 60)
                            logger.info("⏩ Lembrete não agendado (horário já passou) id=%s (dif=%d min)", g.id, delta_min)

                        # Alerta “começa já já” se entre T-15 e o apito inicial
                        if (now_utc >= reminder_at) and (now_utc < g_start):
                            try:
                                local_kick = g_start.astimezone(ZONE).strftime('%H:%M')
                                tg_send_message(
                                    f"🚨 <b>Começa já já</b> ({local_kick})\n"
                                    f"{g.team_home} vs {g.team_away}\n"
                                    f"Pick: <b>{g.pick.upper()}</b>",
                                    parse_mode="HTML"
                                )
                            except Exception:
                                logger.exception("Falha ao enviar alerta 'começa agora' id=%s", g.id)

                        # Watcher normal (futuro) ou tardio (até X min após início)
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
                                # Inicia watcher imediatamente (sem scheduler)
                                try:
                                    asyncio.create_task(watch_game_until_end_job(g.id))
                                    atraso = int((now_utc - g_start).total_seconds() // 60)
                                    logger.info("▶️ Watcher iniciado imediatamente (id=%s, atraso=%d min).", g.id, atraso)
                                except Exception:
                                    logger.exception("Falha ao iniciar watcher imediato id=%s", g.id)
                            else:
                                atraso = int((now_utc - g_start).total_seconds() // 60)
                                logger.info("⏹️ Watcher não criado: jogo iniciou há %d min (> %d) id=%s.",
                                            atraso, LATE_WATCH_WINDOW_MIN, g.id)

                    except Exception:
                        logger.exception("Falha no fluxo de agendamento para jogo id=%s", g.id)

                except Exception:
                    session.rollback()
                    logger.exception(
                        "Erro ao processar evento %s vs %s (url=%s)",
                        getattr(ev, "team_home", "?"),
                        getattr(ev, "team_away", "?"),
                        url,
                    )

            await asyncio.sleep(0.2)  # respiro entre páginas

    # Resumo só com os jogos de hoje (já filtrados)
    msg = fmt_morning_summary(datetime.now(ZONE), analyzed_total, chosen_view)
    _send_summary_safe(msg)
    logger.info("🧾 Varredura concluída — analisados=%d | selecionados=%d | salvos=%d",
                analyzed_total, len(chosen_view), stored_total)


async def send_reminder_job(game_id: int):
    with SessionLocal() as s:
        g = s.get(Game, game_id)
        if not g or not g.will_bet:
            return
        tg_send_message(fmt_reminder(g))
        logger.info("🔔 Lembrete enviado para jogo id=%s", game_id)

async def watch_game_until_end_job(game_id: int):
    """Watcher dummy: aguarda ~2h e sorteia resultado (trocar por scraping do evento/placar)."""
    with SessionLocal() as s:
        g = s.get(Game, game_id)
        if not g:
            return
        start_time_utc = g.start_time
        home, away, gid = g.team_home, g.team_away, g.id
        logger.info("👀 Monitorando: %s vs %s (id=%s)", home, away, gid)

    end_eta = start_time_utc + timedelta(hours=2)
    while datetime.now(tz=pytz.UTC) < end_eta:
        await asyncio.sleep(30)

    outcome = random.choice(["home", "draw", "away"])

    with SessionLocal() as s:
        g = s.get(Game, game_id)
        if not g:
            return
        g.status = "ended"
        g.outcome = outcome
        g.hit = (outcome == g.pick)
        s.commit()
        tg_send_message(fmt_result(g))
        logger.info("🏁 Encerrado id=%s | palpite=%s | resultado=%s | hit=%s", g.id, g.pick, g.outcome, g.hit)

    await maybe_send_daily_wrapup()

async def maybe_send_daily_wrapup():
    today = datetime.now(ZONE).date()
    with SessionLocal() as s:
        day_start = ZONE.localize(datetime(today.year, today.month, today.day, 0, 0)).astimezone(pytz.UTC)
        day_end = ZONE.localize(datetime(today.year, today.month, today.day, 23, 59)).astimezone(pytz.UTC)
        todays = (
            s.query(Game)
            .filter(Game.start_time >= day_start, Game.start_time <= day_end, Game.will_bet.is_(True))
            .all()
        )
        if not todays:
            return
        finished = [g for g in todays if g.status == "ended" and g.hit is not None]
        if len(finished) == len(todays):
            hits = sum(1 for g in finished if g.hit)
            total = len(finished)
            acc = (hits / total * 100) if total else 0.0
            gacc = global_accuracy(s) * 100
            lines = [
                f"📊 {h('Resumo do dia')} ({today.strftime('%d/%m/%Y')})",
                f"Palpites dados: {h(str(total))} | Acertos: {h(str(hits))} | Assertividade do dia: {h(f'{acc:.1f}%')}",
                f"Assertividade geral do script: {h(f'{gacc:.1f}%')}",
            ]
            tg_send_message("\n".join(lines))
            logger.info("📊 Wrap-up do dia enviado | total=%d hits=%d acc=%.1f%% geral=%.1f%%",
                        total, hits, acc, gacc)

def setup_scheduler():
    scheduler.add_job(
        morning_scan_and_publish,
        trigger=CronTrigger(hour=MORNING_HOUR, minute=0),
        id="morning_scan",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("✅ Scheduler ON — rotina diária às %02d:00 (%s).", MORNING_HOUR, APP_TZ)

# ================================
# Runner
# ================================
async def main():
    setup_scheduler()
    # dispara uma varredura no boot para testar
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
