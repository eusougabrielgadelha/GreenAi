"""
BetNacional Auto Analyst
------------------------
Roda 24/7 em um VPS (Ubuntu) analisando jogos em links da BetNacional,
envia palpites para um canal do Telegram, dispara lembretes a -15min,
acompanha o status dos jogos e calcula assertividade.

⚠️ Observações importantes
- Este arquivo é auto-contido e focado em orquestração. O módulo de
  análise de probabilidade (EV/Kelly etc.) foi simplificado. Você pode
  plugar seu `SmartProbabilityAnalyzer` aqui (ver TODO marcados).
- A BetNacional pode exigir login e/ou renderização JS. Para isso, há
  um modo Playwright opcional. Se suas páginas funcionarem só com
  requests+BeautifulSoup, deixe `SCRAPE_BACKEND="requests"`.
- Para enviar mensagens no Telegram, crie um bot com @BotFather, adicione
  o bot como admin do canal, e preencha TOKEN/CHAT_ID no .env.

Dependências sugeridas (requirements.txt):
    APScheduler==3.10.4
    SQLAlchemy==2.0.32
    python-dotenv==1.0.1
    requests==2.32.3
    beautifulsoup4==4.12.3
    pytz==2025.1
    rich==13.7.1
    # Opcional para páginas dinâmicas:
    playwright==1.47.0
    # Depois: playwright install

Como rodar como serviço (resumo):
1) python3 -m venv venv && source venv/bin/activate
2) pip install -r requirements.txt
3) playwright install  # se for usar backend playwright
4) crie um arquivo .env (ver .env.example ao fim desse arquivo)
5) systemd unit (ver exemplo ao fim) -> sudo systemctl enable --now betauto
"""
from __future__ import annotations

import asyncio
import json
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

# Opcional: Playwright para páginas dinâmicas
try:
    from playwright.async_api import async_playwright
    HAS_PLAYWRIGHT = True
except Exception:
    HAS_PLAYWRIGHT = False

# ================================
# Configuração
# ================================
load_dotenv()
console = Console()

TZ = os.getenv("APP_TZ", "America/Fortaleza")
ZONE = pytz.timezone(TZ)
MORNING_HOUR = int(os.getenv("MORNING_HOUR", "6"))  # 06:00 horário de Fortaleza

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")  # ex: @meu_canal ou id numérico

DB_URL = os.getenv("DB_URL", "sqlite:///betauto.sqlite3")
SCRAPE_BACKEND = os.getenv("SCRAPE_BACKEND", "requests").lower()  # "requests" ou "playwright"
REQUESTS_TIMEOUT = float(os.getenv("REQUESTS_TIMEOUT", "20"))
USER_AGENT = os.getenv(
    "USER_AGENT",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123 Safari/537.36",
)

# --- Lista oficial de ligas/links que o script varrerá por padrão ---
BETTING_LINKS: Dict[str, Dict[str, str]] = {
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

# Mapa rápido para recuperar o nome do campeonato a partir do link
COMP_BY_LINK = {v["link"]: v["campeonato"] for v in BETTING_LINKS.values()}

# Links adicionais (opcional) vindos do .env (se quiser somar algo fora da lista acima)
_ENV_LINKS = [s.strip() for s in os.getenv("BETNACIONAL_LINKS", "").split(",") if s.strip()]

# LINKS finais = dicionário oficial + extras do .env (sem duplicar e mantendo ordem)
LINKS: List[str] = list(dict.fromkeys([*(v["link"] for v in BETTING_LINKS.values()), *_ENV_LINKS]))

if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
    console.print("[red]⚠️ Configure TELEGRAM_TOKEN e TELEGRAM_CHAT_ID no .env[/red]")

# ================================
# DB / Modelos
# ================================
Base = declarative_base()
engine = create_engine(DB_URL, echo=False, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

class Game(Base):
    __tablename__ = "games"
    id = Column(Integer, primary_key=True)
    ext_id = Column(String, index=True)          # identificador extraído do site (se existir)
    source_link = Column(Text)
    competition = Column(String)
    team_home = Column(String)
    team_away = Column(String)
    start_time = Column(DateTime, index=True)    # timezone-aware em UTC
    odds_home = Column(Float)
    odds_draw = Column(Float)
    odds_away = Column(Float)
    pick = Column(String)                        # "home" | "draw" | "away"
    pick_reason = Column(Text)
    pick_prob = Column(Float)                    # probabilidade estimada do pick
    pick_ev = Column(Float)                      # EV estimado
    will_bet = Column(Boolean, default=False)    # recomendado apostar?
    status = Column(String, default="scheduled")# scheduled|live|ended
    outcome = Column(String, nullable=True)      # home|draw|away
    hit = Column(Boolean, nullable=True)         # True/False
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

def local_today(dt_tz=ZONE) -> datetime:
    d = datetime.now(dt_tz).replace(hour=0, minute=0, second=0, microsecond=0)
    return d

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
# Scraper (requests ou playwright)
# ================================

HEADERS = {"User-Agent": USER_AGENT}

async def fetch_page_playwright(url: str) -> str:
    if not HAS_PLAYWRIGHT:
        raise RuntimeError("Playwright não instalado. Instale e rode 'playwright install'.")
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
    """Extrai eventos de um link.
    Retorna uma lista de dicts com chaves mínimas:
    - competition, team_home, team_away
    - start_time_local (string), odds_home, odds_draw, odds_away
    - ext_id (opcional)
    TODO: Ajustar parsing específico da BetNacional (seletores reais).
    """
    try:
        if SCRAPE_BACKEND == "playwright":
            html = await fetch_page_playwright(link)
        else:
            html = fetch_page_requests(link)
    except Exception as e:
        console.print(f"[red]Erro ao buscar {link}: {e}[/red]")
        return []

    soup = BeautifulSoup(html, "html.parser")

    # TODO: Este parsing é fictício; adapte aos seletores reais do site.
    events: List[Dict[str, Any]] = []
    for card in soup.select(".event-card"):
        comp_el = card.select_one(".competition")
        comp = comp_el.get_text(strip=True) if comp_el else ""

        teams = card.select(".team-name")
        if len(teams) < 2:
            continue
        t_home = teams[0].get_text(strip=True)
        t_away = teams[1].get_text(strip=True)

        st_el = card.select_one(".start-time")
        start_str = st_el.get_text(strip=True) if st_el else ""

        def _num(sel: str) -> Optional[float]:
            el = card.select_one(sel)
            if not el:
                return None
            raw = el.get_text(strip=True).replace(",", ".")
            try:
                return float("".join(ch for ch in raw if ch.isdigit() or ch in "."))
            except:
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

    return events

# ================================
# Conversões / Normalização
# ================================

def parse_local_datetime(s: str) -> Optional[datetime]:
    """Converte string de horário do site (no fuso de Brasília) para datetime UTC.
    Ajuste o parser conforme o formato real.
    Exemplo esperado: "16:00 31/08/2025" ou "31/08 16:00".
    """
    if not s:
        return None
    for fmt in ("%H:%M %d/%m/%Y", "%d/%m %H:%M", "%d/%m/%y %H:%M"):
        try:
            dt_local = datetime.strptime(s, fmt)
            # Se o formato não tiver ano, assume ano atual
            if "%Y" not in fmt and "%y" not in fmt:
                now_local = datetime.now(ZONE)
                dt_local = dt_local.replace(year=now_local.year)
            dt_local = ZONE.localize(dt_local)
            return dt_local.astimezone(pytz.UTC)
        except Exception:
            continue
    return None

# ================================
# Regra de decisão (simplificada)
# ================================

def decide_bet(odds_home: Optional[float], odds_draw: Optional[float], odds_away: Optional[float],
               competition: str, teams: Tuple[str, str]) -> Tuple[bool, str, float, float, str]:
    """Devolve (will_bet, pick, pick_prob, pick_ev, reason).
    Regra simples: calcula prob implícita, normaliza e escolhe o melhor EV.
    ⚠️ Substitua por seu SmartProbabilityAnalyzer para mais precisão (TODO).
    """
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
        if evs[idx] < 0.02:  # limiar conservador
            return False, "", float(true[idx]), float(evs[idx]), "EV insuficiente"
        return True, PICKS[idx], float(true[idx]), float(evs[idx]), "EV positivo (regra simples)"
    except Exception as e:
        return False, "", 0.0, 0.0, f"Erro na decisão: {e}"

# ================================
# Persistência de assertividade
# ================================

def get_global_accuracy(session) -> float:
    total = session.query(Game).filter(Game.hit.isnot(None)).count()
    if total == 0:
        return 0.0
    hits = session.query(Game).filter(Game.hit.is_(True)).count()
    return hits / total

# ================================
# Mensagens formatadas
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
        pick_str = {
            "home": g.team_home,
            "draw": "Empate",
            "away": g.team_away,
        }.get(g.pick, "—")
        lines.append(f"{hhmm} | {comp} | {jogo} | Apostar em *{pick_str}*")
    lines.append("")
    # taxa atual
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
# Workflow principal
# ================================

async def morning_scan_and_publish():
    """Executa às 06:00 (horário de Fortaleza):
    - percorre LINKS
    - extrai eventos do dia
    - decide apostas
    - salva no DB
    - agenda lembretes e watchers
    - envia resumo no Telegram
    """
    console.print("[cyan]🌅 Iniciando varredura matinal...[/cyan]")
    analyzed = 0
    chosen: List[Game] = []

    with SessionLocal() as session:
        for link in LINKS:
            events = await fetch_events_from_link(link)
            analyzed += len(events)
            for ev in events:
                start_utc = parse_local_datetime(ev.get("start_time_local", ""))
                if not start_utc:
                    continue
                # Apenas jogos do dia (no timezone local)
                day_local = start_utc.astimezone(ZONE).date()
                if day_local != datetime.now(ZONE).date():
                    continue

                # Fallback do nome do campeonato a partir do link oficial
                ev_competition = ev.get("competition") or COMP_BY_LINK.get(link, "")

                will, pick, pprob, pev, reason = decide_bet(
                    ev.get("odds_home"), ev.get("odds_draw"), ev.get("odds_away"),
                    ev_competition, (ev.get("team_home", ""), ev.get("team_away", ""))
                )
                game = Game(
                    ext_id=ev.get("ext_id"),
                    source_link=link,
                    competition=ev_competition,
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
                    # Agenda watcher de resultado (começa no horário do jogo)
                    start_at = game.start_time
                    scheduler.add_job(
                        watch_game_until_end_job,
                        trigger=DateTrigger(run_date=start_at),
                        args=[game.id],
                        id=f"watch_{game.id}",
                        replace_existing=True,
                    )

        # Envia resumo da manhã
        summary = fmt_morning_summary(datetime.now(ZONE), analyzed, chosen)
        tg_send_message(summary)

async def send_reminder_job(game_id: int):
    with SessionLocal() as s:
        g = s.get(Game, game_id)
        if not g or not g.will_bet:
            return
        tg_send_message(fmt_reminder(g))

async def watch_game_until_end_job(game_id: int):
    """Monitora o jogo até finalizar e publica resultado.
    A implementação de status/resultados precisa de scraping específico
    da página do evento. Abaixo, um polling fictício para demonstrar fluxo.
    """
    with SessionLocal() as s:
        g = s.get(Game, game_id)
        if not g:
            return

    console.print(f"[blue]👀 Monitorando jogo {g.team_home} vs {g.team_away}[/blue]")

    # Polling fake: aguarda 2h e marca como ended com outcome aleatório.
    # TODO: Substituir por scraper da página de resultados da BetNacional.
    kickoff = g.start_time
    end_eta = kickoff + timedelta(hours=2)
    while now_utc() < end_eta:
        await asyncio.sleep(30)  # ajuste o intervalo de polling real
        # Aqui você checaria o status da página e quebraria quando finalizado

    # Simular resultado aleatório (substitua pelo real)
    outcome = random.choice(["home", "draw", "away"])  # TODO real
    hit = (outcome == g.pick)

    with SessionLocal() as s:
        g = s.get(Game, game_id)
        if g:
            g.status = "ended"
            g.outcome = outcome
            g.hit = hit
            s.commit()
            tg_send_message(fmt_result(g))

    # Checa se todos os jogos do dia finalizaram para enviar recap do dia
    await maybe_send_daily_wrapup()

async def maybe_send_daily_wrapup():
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
            acc = (hits/total*100) if total else 0.0
            gacc = get_global_accuracy(s) * 100
            lines = [
                f"📊 *Resumo do dia* ({today.strftime('%d/%m/%Y')})",
                f"Palpites dados: *{total}* | Acertos: *{hits}* | Assertividade do dia: *{acc:.1f}%*",
                f"Assertividade geral do script: *{gacc:.1f}%*",
            ]
            tg_send_message("\n".join(lines))

# ================================
# Scheduler / Runner
# ================================

scheduler = AsyncIOScheduler(timezone=str(ZONE))

def setup_scheduler():
    # Tarefa diária às 06:00 (horário de Fortaleza)
    scheduler.add_job(
        morning_scan_and_publish,
        trigger=CronTrigger(hour=MORNING_HOUR, minute=0),
        id="morning_scan",
        replace_existing=True,
    )
    scheduler.start()
    console.print(f"[green]✅ Scheduler iniciado. Rotina diária às {MORNING_HOUR:02d}:00 ({TZ}).[/green]")

async def main():
    setup_scheduler()
    # Opcional: rodar o scan imediatamente no boot
    await morning_scan_and_publish()

    # Aguardar para sempre, com shutdown elegante
    loop = asyncio.get_running_loop()
    stop = asyncio.Event()

    def _sig(*_):
        console.print("[yellow]Recebido sinal de parada. Encerrando...[/yellow]")
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

# ================================
# .env.example (copie para .env)
# ================================
"""
APP_TZ=America/Fortaleza
MORNING_HOUR=6
DB_URL=sqlite:///betauto.sqlite3

# Telegram
TELEGRAM_TOKEN=123456:ABC-DEF...
TELEGRAM_CHAT_ID=@seu_canal

# Scraping
SCRAPE_BACKEND=requests  # ou playwright
REQUESTS_TIMEOUT=20
USER_AGENT=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123 Safari/537.36

# Links adicionais da BetNacional (separe por vírgula). Opcional:
# BETNACIONAL_LINKS=https://betnacional.bet.br/events/1/0/999,https://betnacional.bet.br/events/1/0/111
"""

# ================================
# systemd unit (exemplo): /etc/systemd/system/betauto.service
# ================================
"""
[Unit]
Description=BetNacional Auto Analyst
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/betauto
ExecStart=/home/ubuntu/betauto/venv/bin/python /home/ubuntu/betauto/main.py
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
"""
