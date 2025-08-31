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

from sqlalchemy import (
    create_engine, Column, Integer, String, Float, Text, DateTime, Boolean, JSON, func
)
from sqlalchemy.orm import declarative_base, sessionmaker

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
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

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

    # 2) seus formatos legados
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

def try_parse_events(html: str) -> List[EventRow]:
    soup = BeautifulSoup(html, "html.parser")
    events: List[EventRow] = []

    # Mês PT-BR -> número (para compor dd/mm)
    MONTHS = {
        "janeiro": 1, "fevereiro": 2, "março": 3, "marco": 3, "abril": 4,
        "maio": 5, "junho": 6, "julho": 7, "agosto": 8, "setembro": 9,
        "outubro": 10, "novembro": 11, "dezembro": 12
    }

    # Container principal (um por liga). Se não achar, faz um fallback global.
    containers = soup.select("[data-testid^='eventsListByCategory-']")
    if not containers:
        containers = [soup]

    for cont in containers:
        current_label = None  # "Hoje" ou "DD mês"
        # Percorre os filhos mantendo o rótulo de data ativo
        for child in cont.children:
            if not getattr(child, "get", None):
                continue

            # Cabeçalho de data: "Hoje", "14 setembro", etc.
            if "text-odds-subheader-text" in (child.get("class") or []):
                current_label = child.get_text(" ", strip=True).lower()
                continue

            # Um card de jogo
            if child.get("data-testid") == "preMatchOdds":
                block = child

                # 1) Link e ext_id
                a = block.select_one("a[href^='/event/']")
                if not a:
                    continue
                href = a.get("href", "")
                m = re.search(r"/event/\d+/\d+/(\d+)", href)
                ext_id = m.group(1) if m else None

                # 2) Times
                title_text = a.get_text(" ", strip=True)
                title_text = re.sub(r"\bAo Vivo\b", "", title_text).strip()
                team_home = team_away = ""
                # Desktop costuma vir como "A x B"; mobile pode vir uma linha por time
                seps = [" x ", " X ", " vs ", " VS ", " v "]
                for sep in seps:
                    if sep in title_text:
                        p1, p2 = [p.strip() for p in title_text.split(sep, 1)]
                        team_home, team_away = p1, p2
                        break
                if not team_home:
                    # fallback mobile: dois spans com nomes
                    names = [s.get_text(strip=True) for s in block.select("a span.text-ellipsis")]
                    if len(names) >= 2:
                        team_home, team_away = names[0], names[1]

                # 3) Hora (ex.: 10:00). Pode estar em qualquer span do header do card
                start_hhmm = ""
                for sp in block.select("span"):
                    t = sp.get_text(strip=True)
                    if re.fullmatch(r"\d{1,2}:\d{2}", t):
                        start_hhmm = t
                        break

                # 4) Data: usa o rótulo atual ("Hoje" ou "DD mês") para montar "dd/mm HH:MM"
                start_local_str = start_hhmm
                if current_label:
                    if current_label.startswith("hoje") and start_hhmm:
                        # Usa dia de hoje
                        nowl = datetime.now(ZONE)
                        start_local_str = f"{start_hhmm} {nowl.day:02d}/{nowl.month:02d}/{nowl.year}"
                    else:
                        mdate = re.match(r"(\d{1,2})\s+([a-zç]+)", current_label, flags=re.I)
                        if mdate and start_hhmm:
                            d = int(mdate.group(1))
                            mon_name = mdate.group(2).lower()
                            mon = MONTHS.get(mon_name)
                            if mon:
                                nowl = datetime.now(ZONE)
                                start_local_str = f"{start_hhmm} {d:02d}/{mon:02d}/{nowl.year}"

                # 5) Odds (data-testid: odd-<id>_1_1_, odd-<id>_1_2_, odd-<id>_1_3_)
                def find_odd(col_code: int) -> Optional[float]:
                    # primeiro tenta com o id exato; depois, qualquer id
                    el = None
                    if ext_id:
                        el = block.find(attrs={"data-testid": f"odd-{ext_id}_1_{col_code}_"})
                    if not el:
                        el = block.find(attrs={"data-testid": re.compile(rf"^odd-.*_1_{col_code}_$")})
                    return num_from_text(el.get_text(strip=True)) if el else None

                # Colunas: 1 = casa, 2 = empate, 3 = fora
                odd_home = find_odd(1)
                odd_draw = find_odd(2)
                odd_away = find_odd(3)

                # 6) Competição (opcional) — tenta subir no header da página
                comp = ""
                header = soup.find(attrs={"data-testid": "odds-header"})
                if header:
                    comp = header.get_text(" ", strip=True)

                # Adiciona se tivermos pelo menos times
                if team_home or team_away:
                    events.append(EventRow(
                        competition=comp,
                        team_home=team_home, team_away=team_away,
                        start_local_str=start_local_str,
                        odds_home=odd_home, odds_draw=odd_draw, odds_away=odd_away,
                        ext_id=ext_id
                    ))

    # Fallbacks antigos (JSON-LD e genéricos) – mantidos caso o site mude:
    if not events:
        # (… aqui você pode manter seus blocos antigos de JSON-LD e seletores genéricos
        # se quiser; omiti por brevidade …)
        pass

    return events

async def fetch_events_from_link(url: str, backend: str) -> List[EventRow]:
    """Busca HTML e parseia eventos. Loga backend usado e contagem."""
    html = ""
    used = backend
    try:
        if backend == "playwright":
            html = await fetch_playwright(url)
        else:
            html = fetch_requests(url)
    except Exception as e:
        logger.warning("Falha no fetch (%s) %s: %s", backend, url, e)
        html = ""

    events = try_parse_events(html) if html else []

    # Fallback para 'auto'
    if backend == "auto" and not events:
        if HAS_PLAYWRIGHT:
            try:
                used = "playwright"
                html = await fetch_playwright(url)
                events = try_parse_events(html)
            except Exception as e:
                logger.warning("Fallback playwright falhou em %s: %s", url, e)

    logger.info("🔎 Varredura iniciada para %s — backend=%s", url, used)
    logger.info("🧮  → eventos extraídos: %d", len(events))
    return events

# ================================
# Regras simples de decisão
# ================================
#def decide_bet(odds_home: Optional[float], odds_draw: Optional[float], odds_away: Optional[float],
#               competition: str, teams: Tuple[str, str]) -> Tuple[bool, str, float, float, str]:
#    """Decisão simplificada (troque pelo seu analisador inteligente se quiser)."""
#    try:
#        odds = [odds_home or 0, odds_draw or 0, odds_away or 0]
#        if any(o < 1.01 for o in odds):
#            return False, "", 0.0, 0.0, "Odds insuficientes"
#        imp = [1.0/o for o in odds]
#        tot = sum(imp)
#        true = [p/tot for p in imp] if tot > 0 else [0, 0, 0]
#        evs = [(p*o - 1.0) for p, o in zip(true, odds)]
#        idx = max(range(3), key=lambda i: evs[i])
#        if evs[idx] < 0.02:
#            return False, "", true[idx], evs[idx], "EV baixo"
#        pick = ["home", "draw", "away"][idx]
#        return True, pick, true[idx], evs[idx], "EV positivo (regra simples)"
#    except Exception as e:
#        return False, "", 0.0, 0.0, f"erro: {e}"

# --- regra simples de decisão ---
def decide_bet(odds_home, odds_draw, odds_away, competition, teams):
    """
    Decide se vale selecionar o jogo.
    Retorna:
      will (bool), pick ('home'|'draw'|'away' ou ''), pprob(float), pev(float), reason(str)
    """
    # configurações mínimas
    MIN_ODD = 1.01
    MIN_EV = 0.02          # 2%
    MIN_PROB = 0.25        # 25%

    # odds válidas
    names = ("home", "draw", "away")
    odds = (
        float(odds_home or 0.0),
        float(odds_draw or 0.0),
        float(odds_away or 0.0),
    )
    avail = [(n, o) for n, o in zip(names, odds) if o >= MIN_ODD]
    if len(avail) < 2:
        return False, "", 0.0, 0.0, "Odds insuficientes (menos de 2 mercados)"

    # probabilidades implícitas normalizadas (remove a margem do book)
    inv = [(n, 1.0 / o) for n, o in avail]
    tot = sum(v for _, v in inv)
    if not tot or not (tot > 0):
        return False, "", 0.0, 0.0, "Probabilidades inválidas"

    true = {n: v / tot for n, v in inv}                 # probs verdadeiras somam 1
    ev_map = {n: true[n] * o - 1.0 for n, o in avail}   # EV por mercado

    # melhor mercado disponível
    pick, best_ev = max(ev_map.items(), key=lambda x: x[1])
    pprob = true[pick]

    # regras mínimas
    if best_ev < MIN_EV:
        return False, "", pprob, best_ev, f"EV baixo (<{int(MIN_EV*100)}%)"
    if pprob < MIN_PROB:
        return False, "", pprob, best_ev, f"Probabilidade baixa (<{int(MIN_PROB*100)}%)"

    return True, pick, pprob, best_ev, "EV positivo"

# ================================
# Links monitorados (do seu pedido)
# ================================
class BetAuto:
    def __init__(self):
        self.betting_links = {
            "UEFA Champions League": {
                "pais": "Europa", "campeonato": "UEFA Champions League",
                "link": "https://betnacional.bet.br/events/1/0/7"
            },
            "Espanha - LaLiga": {
                "pais": "Espanha", "campeonato": "LaLiga",
                "link": "https://betnacional.bet.br/events/1/0/8"
            },
            "Inglaterra - Premier League": {
                "pais": "Inglaterra", "campeonato": "Premier League",
                "link": "https://betnacional.bet.br/events/1/0/17"
            },
            "Brasil - Paulista": {
                "pais": "Brasil", "campeonato": "Paulista",
                "link": "https://betnacional.bet.br/events/1/0/15644"
            },
            "França - Ligue 1": {
                "pais": "França", "campeonato": "Ligue 1",
                "link": "https://betnacional.bet.br/events/1/0/34"
            },
            "Itália - Série A": {
                "pais": "Itália", "campeonato": "Série A",
                "link": "https://betnacional.bet.br/events/1/0/23"
            },
            "Alemanha - Bundesliga": {
                "pais": "Alemanha", "campeonato": "Bundesliga",
                "link": "https://betnacional.bet.br/events/1/0/38"
            },
            "Brasil - Série A": {
                "pais": "Brasil", "campeonato": "Brasileirão Série A",
                "link": "https://betnacional.bet.br/events/1/0/325"
            },
            "Brasil - Série B": {
                "pais": "Brasil", "campeonato": "Brasileirão Série B",
                "link": "https://betnacional.bet.br/events/1/0/390"
            },
            "Brasil - Série C": {
                "pais": "Brasil", "campeonato": "Brasileirão Série C",
                "link": "https://betnacional.bet.br/events/1/0/1281"
            },
            "Argentina - Série A": {
                "pais": "Argentina", "campeonato": "Argentina Série A",
                "link": "https://betnacional.bet.br/events/1/0/30106"
            },
            "Argentina - Série B": {
                "pais": "Argentina", "campeonato": "Argentina Série B",
                "link": "https://betnacional.bet.br/events/1/0/703"
            },
            "Estados Unidos - Major League Soccer": {
                "pais": "Estados Unidos", "campeonato": "Major League Soccer",
                "link": "https://betnacional.bet.br/events/1/0/242"
            },
        }

    def all_links(self) -> List[str]:
        base = [cfg["link"] for cfg in self.betting_links.values() if "link" in cfg]
        # complementa com .env se houver
        base.extend(EXTRA_LINKS)
        # dedup preservando ordem
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

# ================================
# Scheduler
# ================================
scheduler = AsyncIOScheduler(timezone=APP_TZ)
app = BetAuto()

async def morning_scan_and_publish():
    logger.info("🌅 Iniciando varredura matinal...")
    analyzed_total = 0
    stored_total = 0
    chosen: List[Game] = []

    # helper local para enviar msg ao Telegram sem estourar parse/markdown
    def _send_summary_safe(text: str) -> None:
        # 1) tenta com HTML
        try:
            tg_send_message(text, parse_mode="HTML")
            return
        except Exception:
            logger.exception("Falha com HTML; tentando sem parse_mode…")

        # 2) fallback: sem parse_mode (a função deve omitir a chave se None)
        try:
            tg_send_message(text, parse_mode=None)
        except TypeError:
            # caso a assinatura não tenha parse_mode
            try:
                tg_send_message(text)
            except Exception:
                logger.exception("Falha ao enviar resumo ao Telegram (fallback simples).")
        except Exception:
            logger.exception("Falha ao enviar resumo ao Telegram (fallback simples).")


    backend_cfg = SCRAPE_BACKEND if SCRAPE_BACKEND in ("requests", "playwright", "auto") else "requests"
    now_local = datetime.now(ZONE).date()

    with SessionLocal() as session:
        for url in app.all_links():
            evs = []
            active_backend = "requests" if backend_cfg in ("requests", "auto") else "playwright"

            try:
                evs = await fetch_events_from_link(url, active_backend)
            except Exception as e:
                logger.warning("Falha ao buscar %s com %s: %s", url, active_backend, e)

            if backend_cfg == "auto" and (not evs):
                try:
                    logger.info("🔁 Fallback para playwright em %s", url)
                    evs = await fetch_events_from_link(url, "playwright")
                    active_backend = "playwright"
                except Exception as e:
                    logger.warning("Fallback playwright também falhou em %s: %s", url, e)

            analyzed_total += len(evs)

            for ev in evs:
                try:
                    start_utc = parse_local_datetime(ev.start_local_str)
                    if not start_utc:
                        logger.info("Ignorado: data inválida | %s vs %s | raw='%s'",
                                    getattr(ev, "team_home", "?"), getattr(ev, "team_away", "?"),
                                    getattr(ev, "start_local_str", ""))
                        continue

                    if start_utc.astimezone(ZONE).date() != now_local:
                        continue

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

                    g = Game(
                        ext_id=ev.ext_id,
                        source_link=url,
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
                    )
                    session.add(g)
                    session.commit()
                    stored_total += 1
                    chosen.append(g)

                    logger.info(
                        "✅ SELECIONADO: %s vs %s | pick=%s | prob=%.1f%% | EV=%.1f%% | odds=(%.2f,%.2f,%.2f) | início=%s | url=%s",
                        ev.team_home, ev.team_away, pick, pprob * 100, pev * 100,
                        float(ev.odds_home or 0), float(ev.odds_draw or 0), float(ev.odds_away or 0),
                        ev.start_local_str, url
                    )

                    try:
                        reminder_at = (g.start_time - timedelta(minutes=15)).astimezone(pytz.UTC)
                        scheduler.add_job(
                            send_reminder_job,
                            trigger=DateTrigger(run_date=reminder_at),
                            args=[g.id],
                            id=f"rem_{g.id}",
                            replace_existing=True,
                        )
                    except Exception:
                        logger.exception("Falha ao agendar lembrete do jogo id=%s", g.id)

                    try:
                        scheduler.add_job(
                            watch_game_until_end_job,
                            trigger=DateTrigger(run_date=g.start_time),
                            args=[g.id],
                            id=f"watch_{g.id}",
                            replace_existing=True,
                        )
                    except Exception:
                        logger.exception("Falha ao agendar watcher do jogo id=%s", g.id)

                except Exception:
                    session.rollback()
                    logger.exception(
                        "Erro ao processar evento %s vs %s (url=%s)",
                        getattr(ev, "team_home", "?"),
                        getattr(ev, "team_away", "?"),
                        url,
                    )

            await asyncio.sleep(0.2)

    msg = fmt_morning_summary(datetime.now(ZONE), analyzed_total, chosen)
    _send_summary_safe(msg)
    logger.info("🧾 Varredura concluída — analisados=%d | selecionados=%d | salvos=%d",
                analyzed_total, len(chosen), stored_total)

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
        logger.info("👀 Monitorando: %s vs %s (id=%s)", g.team_home, g.team_away, g.id)

    end_eta = g.start_time + timedelta(hours=2)
    while datetime.now(tz=pytz.UTC) < end_eta:
        await asyncio.sleep(30)  # ajuste o polling quando implementar placar real

    outcome = random.choice(["home", "draw", "away"])
    hit = (outcome == g.pick)

    with SessionLocal() as s:
        g = s.get(Game, game_id)
        if not g:
            return
        g.status = "ended"
        g.outcome = outcome
        g.hit = hit
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
