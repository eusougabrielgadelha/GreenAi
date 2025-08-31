# main.py
"""
BetNacional Auto Analyst — com logs para PM2
--------------------------------------------
- Varre páginas da BetNacional (links .bet.br/events/...), extrai jogos do dia,
  decide apostas, agenda lembretes e monitora resultados.
- Envia mensagens para Telegram e grava assertividade no banco.

LOGS:
- Mostra qual página está sendo varrida, quantos jogos encontrou por link,
  total analisado e selecionado, além de agendamentos e resultados.
- Ative LOG_VERBOSE=true no .env para logar cada jogo analisado (palpite/EV).

Backends de scraping:
- requests (páginas estáticas)
- playwright (páginas dinâmicas carregadas via JS)  -> exige: pip install playwright && playwright install
"""
from __future__ import annotations

import asyncio
import os
import random
import signal
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import pytz
import requests
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from rich.console import Console
from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    create_engine,
    func,
)
from sqlalchemy.orm import declarative_base, sessionmaker

# Playwright opcional
try:
    from playwright.async_api import async_playwright
    HAS_PLAYWRIGHT = True
except Exception:
    HAS_PLAYWRIGHT = False

# ================================
# Configuração / ENV
# ================================
load_dotenv()
console = Console()

TZ = os.getenv("APP_TZ", "America/Fortaleza")
ZONE = pytz.timezone(TZ)
MORNING_HOUR = int(os.getenv("MORNING_HOUR", "6"))  # 06:00 horário local

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

DB_URL = os.getenv("DB_URL", "sqlite:///betauto.sqlite3")
SCRAPE_BACKEND = os.getenv("SCRAPE_BACKEND", "requests").lower()
REQUESTS_TIMEOUT = float(os.getenv("REQUESTS_TIMEOUT", "20"))
USER_AGENT = os.getenv(
    "USER_AGENT",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123 Safari/537.36",
)

LOG_VERBOSE = os.getenv("LOG_VERBOSE", "false").strip().lower() in ("1", "true", "yes", "y")

# Links via .env
ENV_LINKS = [s.strip() for s in os.getenv("BETNACIONAL_LINKS", "").split(",") if s.strip()]

# Fallback interno com seus links oficiais (events/1/0/*)
BETTING_LINKS = {
    "UEFA Champions League": "https://betnacional.bet.br/events/1/0/7",
    "Espanha - LaLiga": "https://betnacional.bet.br/events/1/0/8",
    "Inglaterra - Premier League": "https://betnacional.bet.br/events/1/0/17",
    "Brasil - Paulista": "https://betnacional.bet.br/events/1/0/15644",
    "França - Ligue 1": "https://betnacional.bet.br/events/1/0/34",
    "Itália - Série A": "https://betnacional.bet.br/events/1/0/23",
    "Alemanha - Bundesliga": "https://betnacional.bet.br/events/1/0/38",
    "Brasil - Série A": "https://betnacional.bet.br/events/1/0/325",
    "Brasil - Série B": "https://betnacional.bet.br/events/1/0/390",
    "Brasil - Série C": "https://betnacional.bet.br/events/1/0/1281",
    "Argentina - Série A": "https://betnacional.bet.br/events/1/0/30106",
    "Argentina - Série B": "https://betnacional.bet.br/events/1/0/703",
    "Estados Unidos - Major League Soccer": "https://betnacional.bet.br/events/1/0/242",
}
DEFAULT_LINKS = list(BETTING_LINKS.values())

LINKS = ENV_LINKS if ENV_LINKS else DEFAULT_LINKS

if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
    console.print("[red]⚠️ Configure TELEGRAM_TOKEN e TELEGRAM_CHAT_ID no .env[/red]")

if not LINKS:
    console.print("[yellow]⚠️ Sem links — o scanner matinal não encontrará jogos[/yellow]")

# ================================
# DB / Modelos
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
    start_time = Column(DateTime, index=True)    # timezone-aware UTC
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
# Utils de Tempo
# ================================
def now_utc() -> datetime:
    return datetime.now(tz=pytz.UTC)

# ================================
# Telegram
# ================================
TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"

def tg_send_message(text: str, parse_mode: str = "Markdown") -> None:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        console.print("[red]Telegram não configurado. Mensagem não enviada.[/red]")
        return
    url = TELEGRAM_API.format(token=TELEGRAM_TOKEN, method="sendMessage")
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }
    try:
        r = requests.post(url, json=payload, timeout=15)
        if r.status_code != 200:
            console.print(f"[red]Falha Telegram {r.status_code}: {r.text[:200]}[/red]")
    except Exception as e:
        console.print(f"[red]Erro Telegram: {e}[/red]")

# ================================
# Scraper (requests / playwright)
# ================================
HEADERS = {"User-Agent": USER_AGENT}

async def fetch_page_playwright(url: str) -> str:
    if not HAS_PLAYWRIGHT:
        raise RuntimeError("Playwright não instalado. Rode: pip install playwright && playwright install")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(url, wait_until="networkidle")
        html = await page.content()
        await browser.close()
        return html

def fetch_page_requests(url: str) -> str:
    resp = requests.get(url, headers=HEADERS, timeout=REQUESTS_TIMEOUT)
    resp.raise_for_status()
    return resp.text

async def fetch_events_from_link(link: str) -> List[Dict[str, Any]]:
    """Extrai eventos de um link. Adapte os seletores ao HTML real da BetNacional."""
    console.log(f"🔎 Varredura iniciada para [bold]{link}[/bold] — backend={SCRAPE_BACKEND}")
    try:
        html: str
        if SCRAPE_BACKEND == "playwright":
            html = await fetch_page_playwright(link)
        else:
            html = fetch_page_requests(link)
    except Exception as e:
        console.log(f"[red]Erro ao buscar {link}: {e}[/red]")
        return []

    soup = BeautifulSoup(html, "html.parser")

    # TODO: Ajustar os seletores conforme a página real
    events: List[Dict[str, Any]] = []
    for card in soup.select(".event-card"):
        comp_el = card.select_one(".competition")
        comp = comp_el.get_text(strip=True) if comp_el else ""

        teams = card.select(".team-name")
        if len(teams) < 2:
            continue
        t_home = teams[0].get_text(strip=True)
        t_away = teams[1].get_text(strip=True)

        start_el = card.select_one(".start-time")
        start_str = start_el.get_text(strip=True) if start_el else ""

        def _num(sel: str) -> Optional[float]:
            el = card.select_one(sel)
            if not el:
                return None
            raw = el.get_text(strip=True).replace(",", ".")
            try:
                return float("".join(ch for ch in raw if ch.isdigit() or ch == "."))  # simples
            except Exception:
                return None

        o_home = _num(".odd-home")
        o_draw = _num(".odd-draw")
        o_away = _num(".odd-away")

        events.append({
            "ext_id": card.get("data-event-id"),
            "competition": comp,
            "team_home": t_home,
            "team_away": t_away,
            "start_time_local": start_str,
            "odds_home": o_home,
            "odds_draw": o_draw,
            "odds_away": o_away,
        })

    console.log(f"🧮 [{link}] → eventos extraídos: [bold]{len(events)}[/bold]")
    return events

# ================================
# Conversão de horário (exemplo)
# ================================
def parse_local_datetime(s: str) -> Optional[datetime]:
    """Converte string tipo '16:00 31/08/2025' ou '31/08 16:00' (fuso Brasília) para UTC."""
    if not s:
        return None
    for fmt in ("%H:%M %d/%m/%Y", "%d/%m %H:%M", "%d/%m/%y %H:%M"):
        try:
            dt_local = datetime.strptime(s, fmt)
            # se não tem ano, usa ano atual
            if "%Y" not in fmt and "%y" not in fmt:
                now_local = datetime.now(ZONE)
                dt_local = dt_local.replace(year=now_local.year)
            dt_local = ZONE.localize(dt_local)
            return dt_local.astimezone(pytz.UTC)
        except Exception:
            continue
    return None

# ================================
# Regra simples de decisão (EV)
# ================================
def decide_bet(odds_home: Optional[float], odds_draw: Optional[float], odds_away: Optional[float],
               competition: str, teams: Tuple[str, str]) -> Tuple[bool, str, float, float, str]:
    """Retorna (will_bet, pick, pick_prob, pick_ev, reason). Substitua por seu analisador avançado se quiser."""
    try:
        odds = [odds_home or 0, odds_draw or 0, odds_away or 0]
        if any(o < 1.01 for o in odds):
            return False, "", 0.0, 0.0, "Odds inválidas"
        impl = [1.0/o for o in odds]
        total = sum(impl)
        if total <= 0:
            return False, "", 0.0, 0.0, "Prob total inválida"
        true = [p/total for p in impl]
        evs = [(p*o - 1.0) for p, o in zip(true, odds)]
        idx = max(range(3), key=lambda i: evs[i])
        PICKS = ["home", "draw", "away"]
        if evs[idx] < 0.02:  # limiar conservador de EV
            return False, "", float(true[idx]), float(evs[idx]), "EV insuficiente"
        return True, PICKS[idx], float(true[idx]), float(evs[idx]), "EV positivo"
    except Exception as e:
        return False, "", 0.0, 0.0, f"Erro na decisão: {e}"

# ================================
# Assertividade global
# ================================
def get_global_accuracy(session) -> float:
    total = session.query(Game).filter(Game.hit.isnot(None)).count()
    if total == 0:
        return 0.0
    hits = session.query(Game).filter(Game.hit.is_(True)).count()
    return hits / total

# ================================
# Mensagens Telegram
# ================================
def fmt_morning_summary(date_local: datetime, analyzed: int, chosen: List[Game]) -> str:
    dstr = date_local.strftime("%d/%m/%Y")
    lines = [
        f"Hoje, *{dstr}*, analisei um total de *{analyzed}* jogos.",
        f"Entendi que existem um total de *{len(chosen)}* jogos eleitos para apostas. São eles:",
        ""
    ]
    for g in chosen:
        local_t = g.start_time.astimezone(ZONE)
        hhmm = local_t.strftime("%H:%M")
        comp = g.competition or "—"
        jogo = f"{g.team_home} vs {g.team_away}"
        pick_str = {"home": g.team_home, "draw": "Empate", "away": g.team_away}.get(g.pick, "—")
        lines.append(f"{hhmm} | {comp} | {jogo} | Apostar em *{pick_str}*")
    lines.append("")
    with SessionLocal() as s:
        acc = get_global_accuracy(s) * 100
    lines.append(f"Taxa de assertividade atual: *{acc:.1f}%*")
    return "\n".join(lines)

def fmt_reminder(g: Game) -> str:
    local_t = g.start_time.astimezone(ZONE).strftime("%H:%M")
    pick_str = {"home": g.team_home, "draw": "Empate", "away": g.team_away}.get(g.pick, "—")
    return (
        f"⏰ *Lembrete*: {local_t} vai começar\n"
        f"{g.competition or 'Jogo'} — {g.team_home} vs {g.team_away}\n"
        f"Aposta: *{pick_str}*"
    )

def fmt_result(g: Game) -> str:
    status = "✅ ACERTOU" if g.hit else "❌ ERROU"
    return (
        f"🏁 *Finalizado* — {g.team_home} vs {g.team_away}\n"
        f"Palpite: {g.pick} | Resultado: {g.outcome or '—'}\n"
        f"{status} | EV estimado: {g.pick_ev*100:.1f}%"
    )

# ================================
# Tarefas
# ================================
async def morning_scan_and_publish():
    console.log(f"🌅 Iniciando varredura matinal — backend={SCRAPE_BACKEND} — links={len(LINKS)}")
    analyzed_total = 0
    chosen: List[Game] = []

    with SessionLocal() as session:
        for link in LINKS:
            events = await fetch_events_from_link(link)
            analyzed_total += len(events)

            for ev in events:
                start_utc = parse_local_datetime(ev.get("start_time_local", ""))
                if not start_utc:
                    if LOG_VERBOSE:
                        console.log(f"[yellow]Descartado (sem horário válido): {ev.get('team_home','?')} vs {ev.get('team_away','?')}[/yellow]")
                    continue

                # Filtra jogos do dia no fuso local
                if start_utc.astimezone(ZONE).date() != datetime.now(ZONE).date():
                    if LOG_VERBOSE:
                        console.log(f"[dim]Fora do dia corrente: {ev.get('team_home','?')} vs {ev.get('team_away','?')}[/dim]")
                    continue

                will, pick, pprob, pev, reason = decide_bet(
                    ev.get("odds_home"), ev.get("odds_draw"), ev.get("odds_away"),
                    ev.get("competition", ""), (ev.get("team_home", ""), ev.get("team_away", ""))
                )

                game = Game(
                    ext_id=ev.get("ext_id"),
                    source_link=link,
                    competition=ev.get("competition", ""),
                    team_home=ev.get("team_home", ""),
                    team_away=ev.get("team_away", ""),
                    start_time=start_utc,  # UTC
                    odds_home=ev.get("odds_home"),
                    odds_draw=ev.get("odds_draw"),
                    odds_away=ev.get("odds_away"),
                    pick=pick,
                    pick_prob=pprob,
                    pick_ev=pev,
                    will_bet=will,
                    pick_reason=reason
                )
                session.add(game)
                session.commit()

                if LOG_VERBOSE:
                    lt = start_utc.astimezone(ZONE).strftime("%H:%M")
                    console.log(
                        f"📄 {lt} | {game.competition or '—'} | {game.team_home} vs {game.team_away} "
                        f"| will_bet={will} pick={pick or '—'} ev={pev:.3f} prob={pprob:.3f} ({reason})"
                    )

                if will:
                    chosen.append(game)
                    # Agenda lembrete -15min
                    reminder_at = (game.start_time - timedelta(minutes=15)).astimezone(pytz.UTC)
                    scheduler.add_job(
                        send_reminder_job,
                        trigger=DateTrigger(run_date=reminder_at),
                        args=[game.id],
                        id=f"reminder_{game.id}",
                        replace_existing=True,
                    )
                    console.log(
                        f"⏰ Lembrete agendado (-15min) para jogo #{game.id} — "
                        f"{game.team_home} vs {game.team_away} | "
                        f"início local: {game.start_time.astimezone(ZONE).strftime('%H:%M')}"
                    )

                    # Agenda watcher do resultado (início no pontapé)
                    start_at = game.start_time
                    scheduler.add_job(
                        watch_game_until_end_job,
                        trigger=DateTrigger(run_date=start_at),
                        args=[game.id],
                        id=f"watch_{game.id}",
                        replace_existing=True,
                    )
                    console.log(
                        f"🛰️ Watcher agendado para jogo #{game.id} às "
                        f"{game.start_time.astimezone(ZONE).strftime('%H:%M')} (hora local)"
                    )

        # Resumo de varredura
        console.log(
            f"🧾 Varredura concluída — analisados={analyzed_total} | selecionados={len(chosen)}"
        )

        # Envia resumo da manhã
        from_zone_now = datetime.now(ZONE)
        summary = fmt_morning_summary(from_zone_now, analyzed_total, chosen)
        tg_send_message(summary)

async def send_reminder_job(game_id: int):
    with SessionLocal() as s:
        g = s.get(Game, game_id)
        if not g or not g.will_bet:
            return
        console.log(f"🔔 Enviando lembrete para jogo #{game_id} — {g.team_home} vs {g.team_away}")
        tg_send_message(fmt_reminder(g))

async def watch_game_until_end_job(game_id: int):
    with SessionLocal() as s:
        g = s.get(Game, game_id)
        if not g:
            return
    console.log(f"👀 Monitorando jogo #{game_id} — {g.team_home} vs {g.team_away}")

    # POLLING EXEMPLO (substitua pelo scraping de status real)
    kickoff = g.start_time
    end_eta = kickoff + timedelta(hours=2)
    while now_utc() < end_eta:
        await asyncio.sleep(30)
        # Aqui você checaria a página do evento para saber se terminou

    # Simulação de resultado
    outcome = random.choice(["home", "draw", "away"])
    hit = (outcome == g.pick)

    with SessionLocal() as s:
        g = s.get(Game, game_id)
        if g:
            g.status = "ended"
            g.outcome = outcome
            g.hit = hit
            s.commit()
            console.log(f"🏁 Finalizado jogo #{game_id} — outcome={outcome} | hit={hit}")
            tg_send_message(fmt_result(g))

    await maybe_send_daily_wrapup()

async def maybe_send_daily_wrapup():
    today_local = datetime.now(ZONE).date()
    with SessionLocal() as s:
        day_start = ZONE.localize(datetime(today_local.year, today_local.month, today_local.day, 0, 0)).astimezone(pytz.UTC)
        day_end = ZONE.localize(datetime(today_local.year, today_local.month, today_local.day, 23, 59)).astimezone(pytz.UTC)
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
            acc = (hits / total * 100) if total else 0.0
            gacc = get_global_accuracy(s) * 100
            console.log(
                f"📊 Wrap-up do dia — palpites={total} | acertos={hits} | "
                f"assertividade_dia={acc:.1f}% | assertividade_geral={gacc:.1f}%"
            )
            lines = [
                f"📊 *Resumo do dia* ({today_local.strftime('%d/%m/%Y')})",
                f"Palpites dados: *{total}* | Acertos: *{hits}* | Assertividade do dia: *{acc:.1f}%*",
                f"Assertividade geral do script: *{gacc:.1f}%*",
            ]
            tg_send_message("\n".join(lines))

# ================================
# Scheduler
# ================================
scheduler = AsyncIOScheduler(timezone=str(ZONE))

def setup_scheduler():
    scheduler.add_job(
        morning_scan_and_publish,
        trigger=CronTrigger(hour=MORNING_HOUR, minute=0),
        id="morning_scan",
        replace_existing=True,
    )
    scheduler.start()
    console.print(f"[green]✅ Scheduler iniciado. Rotina diária às {MORNING_HOUR:02d}:00 ({TZ}).[/green]")

# ================================
# Runner
# ================================
async def main():
    console.log(f"🟢 Bot iniciando… TZ={TZ} backend={SCRAPE_BACKEND} verbose={LOG_VERBOSE}")
    setup_scheduler()
    # roda uma varredura já no boot
    await morning_scan_and_publish()

    # aguarda sinais
    loop = asyncio.get_running_loop()
    stop = asyncio.Event()

    def _sig(*_):
        console.print("[yellow]Sinal de parada recebido. Encerrando…[/yellow]")
        stop.set()

    for sgn in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sgn, _sig)
        except NotImplementedError:
            pass

    await stop.wait()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
