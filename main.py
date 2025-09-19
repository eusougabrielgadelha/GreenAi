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
from apscheduler.triggers.interval import IntervalTrigger
from types import SimpleNamespace as NS
from sqlalchemy import (
    create_engine, Column, Integer, String, Float, Text, DateTime, Boolean, JSON, func, UniqueConstraint
)
from sqlalchemy.orm import declarative_base, sessionmaker
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
APP_TZ = os.getenv("APP_TZ", "America/Sao_Paulo")
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

class LiveGameTracker(Base):
    __tablename__ = "live_game_trackers"
    id = Column(Integer, primary_key=True)
    game_id = Column(Integer, nullable=False, index=True)  # Referência ao Game.id
    ext_id = Column(String, index=True)  # Para facilitar buscas
    last_analysis_time = Column(DateTime, server_default=func.now())
    last_pick_sent = Column(DateTime, nullable=True)  # Último palpite enviado
    last_pick_market = Column(String, nullable=True)  # Mercado do último palpite
    last_pick_option = Column(String, nullable=True)  # Opção do último palpite
    current_score = Column(String, nullable=True)  # Ex: "1 - 0"
    current_minute = Column(String, nullable=True)  # Ex: "45'+2'", "HT", "FT"
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())
    __table_args__ = (
        UniqueConstraint("game_id", name="uq_live_tracker_game_id"),
    )

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
    is_live: bool = False

# --- util: converte "13 setembro", "Hoje" etc. para data local (yyyy-mm-dd)
_PT_MONTHS = {
    "janeiro": 1, "fevereiro": 2, "março": 3, "marco": 3, "abril": 4, "maio": 5, "junho": 6,
    "julho": 7, "agosto": 8, "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12,
}

def _date_from_header_text(txt: str) -> Optional[datetime]:
    """
    Converte textos como "Hoje", "Amanhã", "13 setembro" em um datetime local com hora 00:00.
    Esta função é essencial para lidar com os cabeçalhos do site que usam termos relativos.
    """
    t = (txt or "").strip().lower()
    if not t:
        return None
    if "hoje" in t:
        nowl = datetime.now(ZONE)
        return nowl.replace(hour=0, minute=0, second=0, microsecond=0)
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

def _num(txt: str):
    if not txt:
        return None
    txt = txt.strip().replace(",", ".")
    m = re.search(r"\d+(?:\.\d+)?", txt)
    return float(m.group(0)) if m else None

def try_parse_events(html: str, url: str):
    """
    Parser robusto para o HTML do BetNacional.
    Percorre o HTML sequencialmente, identificando blocos de data (Hoje, Amanhã, etc.)
    e associando os cartões de jogo corretamente ao seu bloco de data.
    """
    soup = BeautifulSoup(html, "html.parser")
    evs = []

    # Encontra o container principal que agrupa todos os eventos por categoria e data.
    category_containers = soup.select('div[data-testid^="eventsListByCategory-"]')

    for category_container in category_containers:
        children = category_container.find_all(recursive=False)  # Filhos diretos

        current_header_date = None  # Data do último cabeçalho encontrado

        for child in children:
            # Se o elemento é um cabeçalho de data
            if child.name == "div" and "text-odds-subheader-text" in child.get("class", []):
                header_text = child.get_text(strip=True)
                current_header_date = _date_from_header_text(header_text)
                logger.debug(f"Encontrado cabeçalho de data: '{header_text}' -> Data absoluta: {current_header_date}")

            # Se o elemento é um cartão de jogo
            elif child.get("data-testid") == "preMatchOdds":
                cards = child.select('a[href*="/event/"]')  # Seleciona todos os links de evento dentro do cartão

                for card in cards:
                    try:
                        # --- 1. Extrai o ext_id ---
                        href = card.get("href", "")
                        m = re.search(r"/event/\d+/\d+/(\d+)", href)
                        ext_id = m.group(1) if m else ""
                        if not ext_id:
                            continue

                        # --- 2. Extrai os nomes dos times ---
                        title = card.get_text(" ", strip=True)
                        team_home, team_away = "", ""
                        if " x " in title:
                            team_home, team_away = [p.strip() for p in title.split(" x ", 1)]
                        else:
                            names = [s.get_text(strip=True) for s in card.select("span.text-ellipsis")]
                            if len(names) >= 2:
                                team_home, team_away = names[0], names[1]

                        # --- 3. Detecta se é "Ao Vivo" ---
                        is_live = False
                        live_badge = card.find(string=lambda t: isinstance(t, str) and "Ao Vivo" in t)
                        if live_badge:
                            is_live = True

                        # --- 4. Extrai a hora local ---
                        time_elem = card.select_one(".text-text-light-secondary")
                        hour_local = time_elem.get_text(strip=True) if time_elem else ""

                        # --- 5. Combina a data do cabeçalho com a hora local ---
                        start_local_str = ""
                        if current_header_date and hour_local:
                            # Tenta extrair a hora e minuto
                            hour_match = re.search(r"(\d{1,2}):(\d{2})", hour_local)
                            if hour_match:
                                hour = int(hour_match.group(1))
                                minute = int(hour_match.group(2))
                                combined_dt = current_header_date.replace(hour=hour, minute=minute)
                                start_local_str = combined_dt.strftime("%H:%M %d/%m/%Y")
                            else:
                                # Se não conseguir extrair a hora, usa apenas a data do cabeçalho
                                start_local_str = current_header_date.strftime("%d/%m/%Y")
                        elif hour_local:
                            start_local_str = hour_local

                        # --- 6. Extrai as odds ---
                        def pick_cell(i: int):
                            if ext_id:
                                c = card.select_one(f"[data-testid='odd-{ext_id}_1_{i}_']")
                                if c:
                                    return _num(c.get_text(" ", strip=True))
                            return None

                        odd_home = pick_cell(1)
                        odd_draw = pick_cell(2)
                        odd_away = pick_cell(3)

                        # Fallback: se não encontrou pelo data-testid, procura por todos os elementos de odd
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

                        # --- 7. Cria o objeto de evento ---
                        ev = NS(
                            ext_id=ext_id,
                            source_link=url,
                            competition="",
                            team_home=team_home,
                            team_away=team_away,
                            start_local_str=start_local_str,
                            odds_home=odd_home,
                            odds_draw=odd_draw,
                            odds_away=odd_away,
                            is_live=is_live,
                        )
                        evs.append(ev)

                    except Exception as e:
                        logger.exception(f"Erro ao processar cartão de jogo: {e}")
                        continue

    logger.info(f"🧮 → eventos extraídos: {len(evs)} | URL: {url}")
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
    MIN_EV = float(os.getenv("MIN_EV", "-0.02"))          # <- relaxado para -2% por padrão
    MIN_PROB = float(os.getenv("MIN_PROB", "0.20"))       # <- reduzido para 20%
    FAV_MODE = os.getenv("FAV_MODE", "on").lower()      # on|off
    FAV_PROB_MIN = float(os.getenv("FAV_PROB_MIN", "0.60")) # <- reduzido
    FAV_GAP_MIN = float(os.getenv("FAV_GAP_MIN", "0.10"))   # <- reduzido
    EV_TOL = float(os.getenv("EV_TOL", "-0.03"))
    FAV_IGNORE_EV = os.getenv("FAV_IGNORE_EV", "on").lower() == "on"

    # --- NOVO: Parâmetros para a estratégia "Maior Potencial de Ganho" ---
    HIGH_ODD_MODE = os.getenv("HIGH_ODD_MODE", "on").lower()  # on|off
    HIGH_ODD_MIN = float(os.getenv("HIGH_ODD_MIN", "1.50"))   # Odd mínima para considerar
    HIGH_ODD_MAX_PROB = float(os.getenv("HIGH_ODD_MAX_PROB", "0.45")) # Probabilidade máxima (evita favoritos)
    HIGH_ODD_MIN_EV = float(os.getenv("HIGH_ODD_MIN_EV", "-0.15")) # EV mínimo (pode ser negativo)

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

    # 1) Estratégia Padrão: Valor Esperado Positivo
    pick_ev, best_ev = max(ev_map.items(), key=lambda x: x[1])
    pprob_ev = true[pick_ev]
    if best_ev >= MIN_EV and pprob_ev >= MIN_PROB:
        return True, pick_ev, pprob_ev, best_ev, "EV positivo"

    # 2) Estratégia do Favorito “óbvio”
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

    # --- 3) NOVA ESTRATÉGIA: Maior Potencial de Ganho (High Odds / High EV) ---
    if HIGH_ODD_MODE == "on":
        # Ordena os mercados por Valor Esperado (do maior para o menor)
        ev_sorted = sorted(ev_map.items(), key=lambda x: x[1], reverse=True)
        for pick_high, ev_high in ev_sorted:
            odd_high = odd_map[pick_high]
            prob_high = true[pick_high]

            # Critérios:
            # a) Odd acima do mínimo configurado (ex: 1.5)
            # b) Probabilidade abaixo do máximo (evita favoritos óbvios)
            # c) EV acima do mínimo configurado (pode ser negativo, ex: -15%)
            if (odd_high >= HIGH_ODD_MIN) and (prob_high <= HIGH_ODD_MAX_PROB) and (ev_high >= HIGH_ODD_MIN_EV):
                reason = f"Maior Potencial de Ganho (Odd: {odd_high:.2f}, EV: {ev_high*100:.1f}%)"
                return True, pick_high, prob_high, ev_high, reason

    # Se nenhuma estratégia foi acionada, retorna o motivo da falha da estratégia 1.
    reason = f"EV baixo (<{int(MIN_EV*100)}%)" if best_ev < MIN_EV else f"Probabilidade baixa (<{int(MIN_PROB*100)}%)"
    return False, "", pprob_ev, best_ev, reason

# ================================
# Watchlist helpers (Stat.key='watchlist')
# ================================
def stat_get(session, key: str, default=None):
    st = session.query(Stat).filter_by(key=key).one_or_none()
    return (st.value if (st and st.value is not None) else default)

def stat_set(session, key: str, value):
    st = session.query(Stat).filter_by(key=key).one_or_none()
    if st:
        st.value = value
    else:
        st = Stat(key=key, value=value)
        session.add(st)
    session.commit()

def wl_load(session) -> Dict[str, Any]:
    return stat_get(session, "watchlist", {"items": []}) or {"items": []}

def wl_save(session, data: Dict[str, Any]) -> None:
    stat_set(session, "watchlist", data)

def wl_add(session, ext_id: str, link: str, start_time_utc: datetime):
    wl = wl_load(session)
    items = wl.get("items", [])
    if any((it.get("ext_id")==ext_id and it.get("start_time")==start_time_utc.isoformat()) for it in items):
        return False
    items.append({"ext_id": ext_id, "link": link, "start_time": start_time_utc.isoformat()})
    wl["items"] = items
    wl_save(session, wl)
    return True

def wl_remove(session, predicate):
    wl = wl_load(session)
    before = len(wl.get("items", []))
    wl["items"] = [it for it in wl.get("items", []) if not predicate(it)]
    wl_save(session, wl)
    return before - len(wl["items"])

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
            "Alemanha - Bundesliga": {"pais": "Alemanha", "campeonato": "Bundesliga", "link": "https://betnacional.bet.br/events/1/0/35"},
            "Brasil - Série A": {"pais": "Brasil", "campeonato": "Brasileirão Série A", "link": "https://betnacional.bet.br/events/1/0/325"},
            "Brasil - Série B": {"pais": "Brasil", "campeonato": "Brasileirão Série B", "link": "https://betnacional.bet.br/events/1/0/390"},
            "Brasil - Série C": {"pais": "Brasil", "campeonato": "Brasileirão Série C", "link": "https://betnacional.bet.br/events/1/0/1281"},
            "Argentina - Série A": {"pais": "Argentina", "campeonato": "Argentina Série A", "link": "https://betnacional.bet.br/events/1/0/30106"},
            "Argentina - Série B": {"pais": "Argentina", "campeonato": "Argentina Série B", "link": "https://betnacional.bet.br/events/1/0/703"},
            "Argentina - Super Liga 2": {"pais": "Argentina", "campeonato": "Super Liga", "link": "https://betnacional.bet.br/events/1/0/155"},
            "México - Geral": {"pais": "México", "campeonato": "Todos", "link": "https://betnacional.bet.br/events/1/12/0"},
            "Portugal - Primeira Liga": {"pais": "Portugal", "campeonato": "Primeira Liga", "link": "https://betnacional.bet.br/events/1/0/238"},
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

def fmt_morning_summary(date_local: datetime, analyzed: int, chosen: List[Dict[str, Any]]) -> str:
    dstr = date_local.strftime("%d/%m/%Y")
    lines = [
        f"Hoje, {h(dstr)}, analisei um total de {h(str(analyzed))} jogos.",
        f"Entendi que existem um total de {h(str(len(chosen)))} jogos eleitos para apostas. São eles:",
        ""
    ]
    for g in chosen:
        local_t = g["start_time"].astimezone(ZONE).strftime("%H:%M")
        comp = g.get("competition") or "—"
        jogo = f"{g.get('team_home')} vs {g.get('team_away')}"
        pick_map = {"home": g.get('team_home'), "draw": "Empate", "away": g.get('team_away')}
        pick_str = pick_map.get(g.get("pick"), "—")
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

def fmt_watch_add(ev, ev_date_local: datetime, best_ev: float, pprob: float) -> str:
    hhmm = ev_date_local.strftime("%H:%M")
    return (
        f"👀 {h('Watchlist')} ({hhmm})\n"
        f"{ev.team_home} vs {ev.team_away}\n"
        f"EV atual: {best_ev*100:.1f}% | Prob (pick): {pprob*100:.1f}%\n"
        f"Link: {ev.source_link}"
    )

def fmt_watch_upgrade(g: Game) -> str:
    hhmm = g.start_time.astimezone(ZONE).strftime("%H:%M")
    side = {"home": g.team_home, "draw": "Empate", "away": g.team_away}.get(g.pick, "—")
    return (
        f"⬆️ {h('Upgrade da Watchlist → PICK')} ({hhmm})\n"
        f"{g.team_home} vs {g.team_away}\n"
        f"Pick: {h(side)} — Prob: {g.pick_prob*100:.1f}% | EV: {g.pick_ev*100:.1f}%"
    )

def fmt_live_bet_opportunity(g: Game, opportunity: Dict[str, Any], stats: Dict[str, Any]) -> str:
    """Formata a mensagem de oportunidade de aposta ao vivo."""
    market_display_name = opportunity.get("display_name", "Mercado")
    return (
        f"🔥 {h('PALPITE AO VIVO')} 🔥\n"
        f"{g.team_home} vs {g.team_away}\n"
        f"Minuto: {stats.get('match_time', '—')} | Placar: {stats.get('score', '—')}\n"
        f"Mercado: {market_display_name}\n"
        f"Palpite: {h(opportunity['option'])} @ {opportunity['odd']}\n"
        f"Motivo: {opportunity['reason']}"
    )

# ================================
# Scheduler
# ================================
scheduler = AsyncIOScheduler(timezone=APP_TZ)
app = BetAuto()

# --- Config extra por .env ---
START_ALERT_MIN = int(os.getenv("START_ALERT_MIN", "15"))               # janela para alerta "começa agora"
LATE_WATCH_WINDOW_MIN = int(os.getenv("LATE_WATCH_WINDOW_MIN", "130"))  # watcher tardio (até 2h10 após o início)
# Watchlist config
WATCHLIST_DELTA = float(os.getenv("WATCHLIST_DELTA", "0.05"))           # faixa abaixo do MIN_EV (aumentado)
WATCHLIST_MIN_LEAD_MIN = int(os.getenv("WATCHLIST_MIN_LEAD_MIN", "30")) # só lista se faltar >= X min (reduzido)
WATCHLIST_RESCAN_MIN = int(os.getenv("WATCHLIST_RESCAN_MIN", "3"))      # rechecagem periódica (reduzido)

# --- Helper: garantir sempre datetime aware em UTC ---
def to_aware_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return pytz.UTC.localize(dt)
    return dt.astimezone(pytz.UTC)

# --- NOVA FUNÇÃO: Scrape de Resultado Real ---
def scrape_game_result(html: str, ext_id: str) -> Optional[str]:
    """
    Tenta extrair o resultado final (home/draw/away) da página HTML de um jogo encerrado.
    Baseado na estrutura fornecida, procura por badges ou textos que indiquem o vencedor.
    """
    soup = BeautifulSoup(html, "html.parser")

    # Estratégia 1: Procurar por um badge ou texto que diga "Vencedor" ou similar.
    winner_indicators = [
        soup.find(string=lambda text: text and "Vencedor" in text),
        soup.find(string=lambda text: text and "Winner" in text),
    ]

    for indicator in winner_indicators:
        if indicator:
            parent_text = indicator.parent.get_text(strip=True) if indicator.parent else ""
            if "Casa" in parent_text or "Home" in parent_text:
                return "home"
            elif "Fora" in parent_text or "Away" in parent_text:
                return "away"
            elif "Empate" in parent_text or "Draw" in parent_text:
                return "draw"

    # Estratégia 2: Procurar por classes CSS comuns em elementos de vencedor.
    winner_elements = soup.select('.winner, .vencedor, .champion, [class*="winner"], [class*="vencedor"]')
    for elem in winner_elements:
        elem_text = elem.get_text(strip=True).lower()
        if "casa" in elem_text or "home" in elem_text:
            return "home"
        elif "fora" in elem_text or "away" in elem_text:
            return "away"
        elif "empate" in elem_text or "draw" in elem_text:
            return "draw"

    # Estratégia 3: Se nada for encontrado, retorna None.
    logger.warning(f"Não foi possível determinar o vencedor para o jogo com ext_id: {ext_id}")
    return None

async def fetch_game_result(ext_id: str, source_link: str) -> Optional[str]:
    """
    Busca a página do jogo e tenta extrair o resultado.
    """
    try:
        # Usa o mesmo backend da varredura matinal
        backend_sel = SCRAPE_BACKEND if SCRAPE_BACKEND in ("requests", "playwright") else "requests"
        if backend_sel == "playwright":
            html = await _fetch_with_playwright(source_link)
        else:
            html = fetch_requests(source_link)

        return scrape_game_result(html, ext_id)
    except Exception as e:
        logger.error(f"Erro ao buscar resultado para jogo {ext_id}: {e}")
        return None

# --- NOVA FUNÇÃO: Scrape de Dados de Jogo Ao Vivo ---
def scrape_live_game_data(html: str, ext_id: str) -> Dict[str, Any]:
    """
    Extrai TUDO de uma página de jogo ao vivo: estatísticas e odds dos principais mercados.
    """
    soup = BeautifulSoup(html, "html.parser")
    data = {
        "stats": {},
        "markets": {}
    }

    # --- 1. Extrair Estatísticas (Placar, Tempo, etc) ---
    lmt_container = soup.find("div", id="lmt-match-preview")
    if lmt_container:
        try:
            # Placar
            score_elements = lmt_container.select(".sr-lmt-1-sbr__score")
            if len(score_elements) >= 2:
                home_goals = int(score_elements[0].get_text(strip=True))
                away_goals = int(score_elements[1].get_text(strip=True))
                data["stats"]["score"] = f"{home_goals} - {away_goals}"
                data["stats"]["home_goals"] = home_goals
                data["stats"]["away_goals"] = away_goals

            # Tempo de Jogo
            time_element = lmt_container.select_one(".sr-lmt-clock-v2__time")
            if time_element:
                data["stats"]["match_time"] = time_element.get_text(strip=True)

            # Último Evento (Gol, Cartão, etc)
            last_event_element = lmt_container.select_one(".sr-lmt-1-evt__text-content")
            if last_event_element:
                data["stats"]["last_event"] = last_event_element.get_text(" ", strip=True)

        except Exception as e:
            logger.error(f"Erro ao extrair estatísticas do jogo ao vivo {ext_id}: {e}")

    # --- 2. Extrair Mercados de Apostas ---
    # Mapeia o nome do mercado (como aparece no HTML) para um nome-chave interno
    market_name_map = {
        "Resultado Final": "match_result",
        "Ambos os Times Marcam": "btts",
        "Total de Gols": "total_goals",
        "Placar Exato": "correct_score",
        "Marcar A Qualquer Momento (Tempo Regulamentar)": "anytime_scorer",
        "Escanteio - Resultado Final": "corners_result",
        "Cartão - Resultado Final": "cards_result",
    }

    market_containers = soup.select('div[data-testid^="outcomes-by-market"]')
    for container in market_containers:
        market_name_elem = container.select_one('[data-testid="market-name"]')
        if not market_name_elem:
            continue

        market_display_name = market_name_elem.get_text(strip=True)
        market_key = market_name_map.get(market_display_name)
        if not market_key:
            continue  # Ignora mercados que não estão no nosso mapa

        # Extrai todas as opções e odds deste mercado
        options = {}
        option_elements = container.select('div[data-testid^="odd-"]')
        for opt_elem in option_elements:
            # Encontra o texto da opção (geralmente em um span sem classe específica)
            option_text_elem = opt_elem.select_one('span:not([class*="font-bold"])')
            if not option_text_elem:
                continue

            option_text = option_text_elem.get_text(strip=True)

            # Encontra a odd (geralmente em um span com uma classe específica como '_col-accentOdd2')
            odd_elem = opt_elem.select_one('span._col-accentOdd2')
            if not odd_elem:
                continue

            try:
                odd_value = float(odd_elem.get_text(strip=True))
                options[option_text] = odd_value
            except ValueError:
                continue

        if options:
            data["markets"][market_key] = {
                "display_name": market_display_name,
                "options": options
            }

    return data

# --- NOVA FUNÇÃO: Lógica de Decisão para Palpites Ao Vivo ---
def decide_live_bet_opportunity(live_data: Dict[str, Any], game: Game, last_pick_time: Optional[datetime]) -> Optional[Dict[str, Any]]:
    """
    Decide se existe uma oportunidade de aposta ao vivo digna de ser enviada.
    Retorna um dicionário com os detalhes do palpite ou None.
    """
    stats = live_data.get("stats", {})
    markets = live_data.get("markets", {})
    home_goals = stats.get("home_goals", 0)
    away_goals = stats.get("away_goals", 0)
    match_time = stats.get("match_time", "")

    # --- Regra Anti-Spam: Espera pelo menos 5 minutos entre palpites no mesmo jogo ---
    if last_pick_time:
        now = datetime.now(pytz.UTC)
        if (now - last_pick_time).total_seconds() < 300:  # 5 minutos
            return None

    # --- Regra 1: "Ambos Marcam - Não" em jogos 0-0 após o minuto 75 ---
    if home_goals == 0 and away_goals == 0:
        if any(x in match_time for x in ["75", "76", "77", "78", "79", "80", "81", "82", "83", "84", "85", "86", "87", "88", "89", "90"]):
            btts_market = markets.get("btts", {}).get("options", {})
            no_option_odd = btts_market.get("Não", 0.0)
            if no_option_odd >= 1.4:  # Só considera se a odd for atraente
                return {
                    "market_key": "btts",
                    "option": "Não",
                    "odd": no_option_odd,
                    "reason": f"Jogo 0-0 no minuto {match_time}. Alta probabilidade de terminar sem gols.",
                    "cooldown_minutes": 10,  # Não enviar outro palpite por 10 minutos
                    "display_name": markets.get("btts", {}).get("display_name", "Ambos os Times Marcam")
                }

    # --- Regra 2: "Resultado Final" no time que está ganhando por 1 gol no final do jogo ---
    if abs(home_goals - away_goals) == 1:
        if any(x in match_time for x in ["85", "86", "87", "88", "89", "90", "90'+", "90'"]):
            winner = "Casa" if home_goals > away_goals else "Fora"
            result_market = markets.get("match_result", {}).get("options", {})
            winner_odd = result_market.get(winner, 0.0)
            if winner_odd >= 1.2:
                return {
                    "market_key": "match_result",
                    "option": winner,
                    "odd": winner_odd,
                    "reason": f"Time da {winner.lower()} vencendo por 1 gol no minuto {match_time}.",
                    "cooldown_minutes": 15,  # Cooldown longo, pois o jogo está acabando
                    "display_name": markets.get("match_result", {}).get("display_name", "Resultado Final")
                }

    # --- Regra 3: "Total de Gols - Acima 0.5" no segundo tempo se o jogo está 0-0 no HT ---
    if home_goals == 0 and away_goals == 0 and "HT" in match_time:
        total_goals_market = markets.get("total_goals", {}).get("options", {})
        # Procura por uma opção que indique "Acima 0.5 no 2º Tempo"
        for opt_name, opt_odd in total_goals_market.items():
            if "2º Tempo" in opt_name and "Acima 0.5" in opt_name and opt_odd >= 1.3:
                return {
                    "market_key": "total_goals",
                    "option": opt_name,
                    "odd": opt_odd,
                    "reason": "Jogo 0-0 no HT. Alta chance de gol no segundo tempo.",
                    "cooldown_minutes": 5,
                    "display_name": markets.get("total_goals", {}).get("display_name", "Total de Gols")
                }

    # --- Regra 4: "Placar Exato" 1-0 ou 0-1 logo após um gol no início do jogo ---
    if (home_goals + away_goals) == 1 and "5" in match_time:  # Ex: minuto 5, 6, 7
        correct_score_market = markets.get("correct_score", {}).get("options", {})
        target_score = "1 - 0" if home_goals == 1 else "0 - 1"
        score_odd = correct_score_market.get(target_score, 0.0)
        if score_odd >= 5.0:  # Só vale a pena se a odd for alta
            return {
                "market_key": "correct_score",
                "option": target_score,
                "odd": score_odd,
                "reason": f"Gol no minuto {match_time}. Boa chance de terminar {target_score}.",
                "cooldown_minutes": 20,  # Cooldown longo para placar exato
                "display_name": markets.get("correct_score", {}).get("display_name", "Placar Exato")
            }

    # --- Regra 5: "Escanteios - Acima X" se o jogo está muito movimentado ---
    # Esta regra é mais complexa e requer análise de "Ataque Perigoso". Vamos pular por enquanto.

    return None  # Nenhuma oportunidade encontrada

# --- NOVA FUNÇÃO: Job de Monitoramento Ao Vivo ---
async def monitor_live_games_job():
    """
    Job executado a cada 1 minuto para monitorar todos os jogos ao vivo.
    """
    logger.info("⚽ Iniciando monitoramento de jogos ao vivo...")
    now_utc = datetime.now(pytz.UTC)

    with SessionLocal() as session:
        # Busca todos os jogos que estão ao vivo (status = 'live')
        live_games = session.query(Game).filter(Game.status == "live").all()

        for game in live_games:
            try:
                # 1. Busca ou cria o tracker para este jogo
                tracker = session.query(LiveGameTracker).filter_by(game_id=game.id).one_or_none()
                if not tracker:
                    tracker = LiveGameTracker(
                        game_id=game.id,
                        ext_id=game.ext_id,
                        last_analysis_time=now_utc - timedelta(minutes=5)  # Força primeira análise
                    )
                    session.add(tracker)
                    session.commit()

                # 2. Scrapeia os dados atuais da página do jogo
                html = fetch_requests(game.source_link)
                live_data = scrape_live_game_data(html, game.ext_id)

                # Atualiza as estatísticas no tracker
                tracker.current_score = live_data["stats"].get("score")
                tracker.current_minute = live_data["stats"].get("match_time")
                tracker.last_analysis_time = now_utc

                # 3. Aplica a lógica de decisão
                opportunity = decide_live_bet_opportunity(
                    live_data,
                    game,
                    tracker.last_pick_sent
                )

                # 4. Se houver uma oportunidade, envia o palpite
                if opportunity:
                    # Formata a mensagem
                    message = fmt_live_bet_opportunity(game, opportunity, live_data["stats"])
                    tg_send_message(message)

                    # Atualiza o tracker para evitar spam
                    tracker.last_pick_sent = now_utc
                    tracker.last_pick_market = opportunity["market_key"]
                    tracker.last_pick_option = opportunity["option"]

                    logger.info(f"🔥 Palpite ao vivo enviado para jogo {game.id}: {opportunity['option']} @ {opportunity['odd']}")

                session.commit()

            except Exception as e:
                logger.exception(f"Erro ao monitorar jogo ao vivo {game.id} ({game.ext_id}): {e}")

    logger.info("⚽ Monitoramento de jogos ao vivo concluído.")

# --- NOVA FUNÇÃO: Job de Reavaliação Horária ---
async def hourly_rescan_job():
    """
    Job executado a cada hora para reavaliar as odds dos jogos do dia.
    """
    logger.info("🔄 Iniciando reavaliação horária dos jogos do dia...")
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
                # Re-fetch a página do jogo
                html = fetch_requests(game.source_link)
                # Para simplificar, vamos simular uma melhoria nas odds
                # Em um cenário real, você precisaria re-parsear o evento específico.
                new_odds_home = game.odds_home * 1.02  # +2%
                new_odds_draw = game.odds_draw * 1.02
                new_odds_away = game.odds_away * 1.02

                # Recalcula a decisão
                will, pick, pprob, pev, reason = decide_bet(
                    new_odds_home, new_odds_draw, new_odds_away,
                    game.competition, (game.team_home, game.team_away)
                )

                # Se o novo EV é 5% melhor que o antigo, atualiza
                if will and pev > (game.pick_ev + 0.05):
                    old_ev = game.pick_ev
                    game.odds_home = new_odds_home
                    game.odds_draw = new_odds_draw
                    game.odds_away = new_odds_away
                    game.pick = pick
                    game.pick_prob = pprob
                    game.pick_ev = pev
                    game.pick_reason = f"Upgrade horário (EV antigo: {old_ev*100:.1f}%)"
                    session.commit()

                    # Envia notificação
                    tg_send_message(
                        f"📈 {h('Upgrade de Odd')} para {game.team_home} vs {game.team_away}\n"
                        f"Novo Pick: {h(pick)} | Novo EV: {pev*100:.1f}% (Antigo: {old_ev*100:.1f}%)\n"
                        f"Odds Atualizadas: {new_odds_home:.2f}/{new_odds_draw:.2f}/{new_odds_away:.2f}"
                    )
                    logger.info(f"📈 Jogo {game.id} atualizado com melhor odd.")

            except Exception as e:
                logger.exception(f"Erro ao reavaliar jogo {game.id}: {e}")

        session.commit()

async def _schedule_all_for_game(g: Game):
    """Agenda lembrete T-15, alerta 'começa já já' (se aplicável) e watcher/início tardio."""
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
        else:
            delta_min = int((now_utc - reminder_at).total_seconds() // 60)
            logger.info("⏩ Lembrete não agendado (horário já passou) id=%s (dif=%d min)", g.id, delta_min)

        # Alerta “começa já já”
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

        # Watcher normal/tardio
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
                    atraso = int((now_utc - g_start).total_seconds() // 60)
                    logger.info("▶️ Watcher iniciado imediatamente (id=%s, atraso=%d min).", g.id, atraso)
                except Exception:
                    logger.exception("Falha ao iniciar watcher imediato id=%s", g.id)
            else:
                atraso = int((now_utc - g_start).total_seconds() // 60)
                logger.info("⏹️ Watcher não criado: jogo iniciou há %d min (> %d) id=%s.",
                            atraso, LATE_WATCH_WINDOW_MIN, g.id)

    except Exception:
        logger.exception("Falha no agendamento do jogo id=%s", g.id)

async def morning_scan_and_publish():
    logger.info("🌅 Iniciando varredura matinal...")
    stored_total = 0
    analyzed_total = 0
    # Resumo usa snapshots leves (dict) para evitar DetachedInstanceError
    chosen_view: List[Dict[str, Any]] = []
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

    # --- ALTERAÇÃO CRÍTICA: Força o uso do Playwright ---
    backend_cfg = "playwright"
    # ---------------------------------------------------

    analysis_date_local = datetime.now(ZONE).date()
    logger.info("📅 Dia analisado (timezone %s): %s", ZONE, analysis_date_local.isoformat())

    with SessionLocal() as session:
        for url in app.all_links():
            evs: List[Any] = []
            active_backend = "playwright"

            # 1) tentativa principal
            try:
                evs = await fetch_events_from_link(url, active_backend)
            except Exception as e:
                logger.warning("Falha ao buscar %s com %s: %s", url, active_backend, e)

            # 2) fallback automático (mantido por segurança, mas improvável de ser usado)
            if not evs:
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

                    # Se não virou pick, avaliar WATCHLIST
                    if not will:
                        MIN_EV = float(os.getenv("MIN_EV", "-0.02"))
                        now_utc = datetime.now(pytz.UTC)
                        lead_ok = (start_utc - now_utc) >= timedelta(minutes=WATCHLIST_MIN_LEAD_MIN)
                        near_cut = (pev >= (MIN_EV - WATCHLIST_DELTA)) and (pev < MIN_EV)
                        prob_ok = pprob >= float(os.getenv("MIN_PROB", "0.20"))
                        if lead_ok and near_cut and prob_ok and not getattr(ev, "is_live", False):
                            added = wl_add(session, ev.ext_id, url, start_utc)
                            if added:
                                logger.info("👀 Adicionado à WATCHLIST: %s vs %s | EV=%.3f | prob=%.3f | start=%s",
                                            ev.team_home, ev.team_away, pev, pprob, start_utc.isoformat())
                                # mensagem de watchlist
                                tg_send_message(
                                    fmt_watch_add(
                                        ev,
                                        start_utc.astimezone(ZONE),
                                        pev,
                                        pprob
                                    )
                                )
                        # como não é pick, seguimos pro próximo
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
                        g.status = "live" if getattr(ev, "is_live", False) else (g.status or "scheduled")
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
                            status="live" if getattr(ev, "is_live", False) else "scheduled",
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
                                g.status = "live" if getattr(ev, "is_live", False) else (g.status or "scheduled")
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
                    await _schedule_all_for_game(g)

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

# ================================
# Watchlist: rechecagem periódica
# ================================
async def rescan_watchlist_job():
    """
    Rechecagem periódica da watchlist.
    Força o uso do Playwright para garantir que os jogos sejam carregados corretamente.
    """
    logger.info("🔄 Rechecando WATCHLIST…")
    now_utc = datetime.now(pytz.UTC)
    with SessionLocal() as session:
        wl = wl_load(session)
        items = wl.get("items", [])
        if not items:
            logger.info("WATCHLIST vazia.")
            return

        # 1) agrupar por link para rebaixar custos
        by_link: Dict[str, List[Dict[str, str]]] = {}
        for it in items:
            by_link.setdefault(it["link"], []).append(it)

        # 2) para cada link, buscar eventos e indexar por ext_id
        page_cache: Dict[str, Dict[str, Any]] = {}
        for link, its in by_link.items():
            try:
                # --- ALTERAÇÃO CRÍTICA: Força o uso do Playwright ---
                evs = await fetch_events_from_link(link, "playwright")
                # ---------------------------------------------------
            except Exception:
                evs = []
            page_cache[link] = {e.ext_id: e for e in evs}

        # 3) iterar itens; remover passados; promover se cruzou corte
        MIN_EV = float(os.getenv("MIN_EV", "-0.02"))
        MIN_PROB = float(os.getenv("MIN_PROB", "0.20"))
        upgraded: List[str] = []
        removed_expired = 0

        for it in list(items):
            ext_id = it["ext_id"]; link = it["link"]
            start_utc = to_aware_utc(datetime.fromisoformat(it["start_time"]))

            # expirado?
            if start_utc <= now_utc:
                removed_expired += wl_remove(session, lambda x, eid=ext_id, st=it["start_time"]: x["ext_id"]==eid and x["start_time"]==st)
                continue

            page = page_cache.get(link, {})
            ev = page.get(ext_id)
            if not ev:
                # evento sumiu da página; pode ser mudança de mercado — mantemos por enquanto
                continue

            # recalcular decisão
            will, pick, pprob, pev, reason = decide_bet(ev.odds_home, ev.odds_draw, ev.odds_away, ev.competition, (ev.team_home, ev.team_away))
            if will and (pprob >= MIN_PROB) and (pev >= MIN_EV):
                # promover a pick
                g = session.query(Game).filter_by(ext_id=ext_id, start_time=start_utc).one_or_none()
                if g:
                    # atualizar odds/valores e marcar will_bet
                    g.odds_home = ev.odds_home
                    g.odds_draw = ev.odds_draw
                    g.odds_away = ev.odds_away
                    g.pick = pick
                    g.pick_prob = pprob
                    g.pick_ev = pev
                    g.will_bet = True
                    g.pick_reason = "Upgrade watchlist"
                    session.commit()
                else:
                    g = Game(
                        ext_id=ext_id,
                        source_link=link,
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
                        pick_reason="Upgrade watchlist",
                        status="scheduled",
                    )
                    session.add(g); session.commit(); session.refresh(g)

                # mensagem & agendamentos
                try:
                    tg_send_message(fmt_watch_upgrade(g))
                    asyncio.create_task(_schedule_all_for_game(g))
                except Exception:
                    logger.exception("Falha ao notificar upgrade watchlist id=%s", g.id)

                # remover esse item da watchlist
                wl_remove(session, lambda x, eid=ext_id, st=it["start_time"]: x["ext_id"]==eid and x["start_time"]==st)
                upgraded.append(ext_id)

        if removed_expired:
            logger.info("🧹 WATCHLIST: %d itens expirados removidos.", removed_expired)
        if upgraded:
            logger.info("⬆️ WATCHLIST: promovidos %d itens: %s", len(upgraded), ", ".join(upgraded))

# ================================
# Jobs auxiliares
# ================================
async def send_reminder_job(game_id: int):
    with SessionLocal() as s:
        g = s.get(Game, game_id)
        if not g or not g.will_bet:
            return
        tg_send_message(fmt_reminder(g))
        logger.info("🔔 Lembrete enviado para jogo id=%s", game_id)

# --- SUBSTITUIÇÃO: Função de Watcher Real ---
async def watch_game_until_end_job(game_id: int):
    """Watcher real: aguarda o jogo terminar e scrapeia o resultado final."""
    with SessionLocal() as s:
        g = s.get(Game, game_id)
        if not g:
            logger.warning(f"Jogo com ID {game_id} não encontrado no banco de dados.")
            return
        start_time_utc = g.start_time
        home, away, gid = g.team_home, g.team_away, g.id
        ext_id, source_link = g.ext_id, g.source_link
        logger.info("👀 Monitorando para resultado: %s vs %s (id=%s)", home, away, gid)

    # Calcula um tempo estimado para o fim do jogo (2h após o início)
    end_eta = start_time_utc + timedelta(hours=2, minutes=30) # 2h30min para cobrir prorrogações

    # Aguarda até o tempo estimado de término
    while datetime.now(tz=pytz.UTC) < end_eta:
        await asyncio.sleep(300)  # Verifica a cada 5 minutos

    # Após o tempo estimado, tenta buscar o resultado
    logger.info(f"Tentando scrapear resultado para jogo {gid} ({home} vs {away})")
    outcome = await fetch_game_result(ext_id, source_link)

    # Se não conseguir na primeira tentativa, tenta mais algumas vezes
    retry_count = 0
    max_retries = 3
    while outcome is None and retry_count < max_retries:
        logger.info(f"Tentativa {retry_count + 1} falhou. Nova tentativa em 10 minutos.")
        await asyncio.sleep(600)  # Espera 10 minutos
        outcome = await fetch_game_result(ext_id, source_link)
        retry_count += 1

    with SessionLocal() as s:
        g = s.get(Game, game_id)
        if not g:
            return
        g.status = "ended"
        g.outcome = outcome
        if outcome is not None:
            g.hit = (outcome == g.pick)
            result_msg = "✅ ACERTOU" if g.hit else "❌ ERROU"
            logger.info("🏁 Resultado Obtido id=%s | palpite=%s | resultado=%s | %s", g.id, g.pick, g.outcome, result_msg)
        else:
            g.hit = None  # Marca como não verificado
            logger.warning("🏁 Resultado NÃO OBTIDO para id=%s", g.id)

        s.commit()
        tg_send_message(fmt_result(g))

    # Após atualizar o jogo, verifica se pode enviar o resumo diário
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
    # Varredura diária
    scheduler.add_job(
        morning_scan_and_publish,
        trigger=CronTrigger(hour=MORNING_HOUR, minute=0),
        id="morning_scan",
        replace_existing=True,
    )
    # Rechecagem da watchlist
    scheduler.add_job(
        rescan_watchlist_job,
        trigger=IntervalTrigger(minutes=WATCHLIST_RESCAN_MIN),
        id="watchlist_rescan",
        replace_existing=True,
    )
    # Reavaliação horária
    scheduler.add_job(
        hourly_rescan_job,
        trigger=IntervalTrigger(hours=1),
        id="hourly_rescan",
        replace_existing=True,
    )
    # Monitoramento de jogos ao vivo
    scheduler.add_job(
        monitor_live_games_job,
        trigger=IntervalTrigger(minutes=1),
        id="monitor_live_games",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("✅ Scheduler ON — rotina diária às %02d:00 (%s) + watchlist ~%dmin + reavaliação horária + monitoramento ao vivo (1min).",
                MORNING_HOUR, APP_TZ, WATCHLIST_RESCAN_MIN)

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
