"""Scraper Betano — fetcher + parser + cache em memória.

Endpoint: /danae-webapi/api/live/overview/latest (queryLanguageId=5, queryOperatorId=8).

Estratégia: usa `requests` síncrono via `asyncio.to_thread` — NÃO Playwright.
Endpoint validado na Fase 0: HTTP 200 em ~0.4s, sem Cloudflare 403, sem 429
em 20 requests sequenciais.

Contrato público (estável — outros agentes dependem):
    - fetch_betano_overview() -> dict | None
    - fetch_events_via_betano_api(source_link) -> list[EventDigest]
    - parse_betano_overview(api_response, source_link) -> list[EventDigest]
    - build_game_data_from_event(event, overview) -> dict
    - extract_result_from_event(event) -> dict | None

EventDigest é SimpleNamespace com keys:
    ext_id, source_link, game_url, competition, country,
    team_home, team_away, start_local_str,
    odds_home, odds_draw, odds_away, is_live,
    betradar_match_id (extra), markets_dict (extra).
"""
from __future__ import annotations

import asyncio
import os
import re
import time
from datetime import datetime
from types import SimpleNamespace as NS
from typing import Any, Dict, List, Optional

import pytz
import requests

from utils.logger import logger


# ─── Config (via env, com defaults inline pra evitar acoplar) ─────────────────

OVERVIEW_URL = os.getenv(
    "BETANO_OVERVIEW_URL",
    "https://www.betano.bet.br/danae-webapi/api/live/overview/latest",
)
OVERVIEW_PARAMS = {
    "queryLanguageId": os.getenv("BETANO_QUERY_LANGUAGE_ID", "5"),
    "queryOperatorId": os.getenv("BETANO_QUERY_OPERATOR_ID", "8"),
}
TIMEOUT = float(os.getenv("BETANO_FETCH_TIMEOUT", "20"))
CACHE_TTL = int(os.getenv("BETANO_OVERVIEW_CACHE_TTL_SEC", "60"))
BETANO_BASE_URL = os.getenv("BETANO_BASE_URL", "https://www.betano.bet.br")

# User-Agent realista (Chrome 124 em macOS) — passou Cloudflare na Fase 0
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Heurística pra inferir jogo finalizado: startTime + 105min < now (UTC)
_DEFAULT_MATCH_DURATION_MIN = 105

# ardSportId = 1 → futebol (confirmado Fase 0)
_FOOTBALL_ARDSPORT_ID = 1

# Regex pra normalizar nome de Over/Under (compatível com decision.py:15)
_OU_NAME_RE = re.compile(
    r'^(Mais|Menos)\s+de\s+(\d+(?:[.,]\d+)?)\s*$',
    re.IGNORECASE,
)


# ─── Cache em memória ─────────────────────────────────────────────────────────

# Estrutura: {"entry": {"data": <overview_dict>, "ts": <epoch_seconds>}}
# Cache key único — overview é global, não tem filtro.
_OVERVIEW_CACHE: dict = {}


# ─── Fetcher (sync + async wrapper) ───────────────────────────────────────────

def _fetch_sync() -> Optional[dict]:
    """Fetcher síncrono. Chamado via asyncio.to_thread pelo wrapper async."""
    headers = {
        "User-Agent": UA,
        "Accept": "application/json",
        "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
        "Referer": f"{BETANO_BASE_URL}/",
    }
    try:
        r = requests.get(
            OVERVIEW_URL,
            params=OVERVIEW_PARAMS,
            headers=headers,
            timeout=TIMEOUT,
        )
        if r.status_code != 200:
            logger.warning(
                f"Betano overview HTTP {r.status_code} (body bytes={len(r.content)})"
            )
            return None
        return r.json()
    except requests.exceptions.RequestException as exc:
        logger.warning(f"Betano fetch RequestException: {exc}")
        return None
    except ValueError as exc:
        logger.warning(f"Betano fetch JSON parse falhou: {exc}")
        return None
    except Exception as exc:  # noqa: BLE001
        logger.exception(f"Betano fetch erro inesperado: {exc}")
        return None


async def fetch_betano_overview() -> Optional[dict]:
    """
    Fetch + cache em memória da overview Betano.

    Cache TTL configurável via env BETANO_OVERVIEW_CACHE_TTL_SEC (default 60s).
    Retorna dict completo ou None se falhar.
    """
    cached = _OVERVIEW_CACHE.get("entry")
    now = time.time()
    if cached and (now - cached["ts"]) < CACHE_TTL:
        logger.debug(
            f"Betano overview: cache HIT (age={int(now - cached['ts'])}s, "
            f"events={len(cached['data'].get('events', {}))})"
        )
        return cached["data"]

    data = await asyncio.to_thread(_fetch_sync)
    if data is not None:
        _OVERVIEW_CACHE["entry"] = {"data": data, "ts": time.time()}
        logger.debug(
            f"Betano overview: cache MISS — fetched "
            f"{len(data.get('events', {}))} events"
        )
    return data


# ─── Parsers — extração de mercados ───────────────────────────────────────────

def _is_valid_price(price: Any) -> bool:
    """True se price é numérico e >= 1.01 (odd válida)."""
    if not isinstance(price, (int, float)):
        return False
    if isinstance(price, bool):  # bool é subclasse de int
        return False
    return price >= 1.01


def _market_lookup(overview: dict, mid: Any) -> Optional[dict]:
    """Busca market no overview tolerando id como str ou int."""
    markets = overview.get("markets") or {}
    if not isinstance(markets, dict):
        return None
    m = markets.get(str(mid))
    if m is None:
        m = markets.get(mid)
    return m if isinstance(m, dict) else None


def _selection_lookup(overview: dict, sid: Any) -> Optional[dict]:
    """Busca selection no overview tolerando id como str ou int."""
    selections = overview.get("selections") or {}
    if not isinstance(selections, dict):
        return None
    s = selections.get(str(sid))
    if s is None:
        s = selections.get(sid)
    return s if isinstance(s, dict) else None


def _extract_match_result(event: dict, overview: dict) -> Optional[dict]:
    """
    Extrai mercado 1x2 (MRES) de um evento.

    selectionIdList vem em ordem fixa: [home_sel, draw_sel, away_sel]
    (validado Fase 0). Usar ORDEM, não confiar no `name`.

    Retorna dict no formato decide_picks ou None se mercado ausente/inválido.
    """
    for mid in event.get("marketIdList") or []:
        m = _market_lookup(overview, mid)
        if not m or m.get("type") != "MRES":
            continue
        sel_ids = m.get("selectionIdList") or []
        if len(sel_ids) != 3:
            continue

        odds: List[float] = []
        valid = True
        for sid in sel_ids:
            s = _selection_lookup(overview, sid)
            if not s:
                valid = False
                break
            price = s.get("price")
            if not _is_valid_price(price):
                valid = False
                break
            odds.append(float(price))

        if not valid or len(odds) != 3:
            continue

        # Ordem confirmada: [home, draw, away] → traduz pra Casa/Empate/Fora
        return {
            "display_name": m.get("name") or "Resultado Final",
            "options": {
                "Casa": odds[0],
                "Empate": odds[1],
                "Fora": odds[2],
            },
            "market_id": m.get("id"),
        }
    return None


def _extract_total_goals(event: dict, overview: dict) -> Optional[dict]:
    """
    Extrai mercado HCTG (Total de Gols Mais/Menos) de um evento.

    Selection.name vem como "Mais de 2.5" / "Menos de 2.5" — já compatível
    com regex existente em decision.py. Aceita apenas linhas terminadas em
    .0 ou .5 (descarta asiáticas .25/.75).

    Retorna dict no formato decide_picks ou None se mercado ausente.
    """
    options: Dict[str, float] = {}
    market_id: Optional[int] = None
    display_name = "Total de Gols Mais/Menos"

    for mid in event.get("marketIdList") or []:
        m = _market_lookup(overview, mid)
        if not m or m.get("type") != "HCTG":
            continue
        if market_id is None:
            market_id = m.get("id")
            if m.get("name"):
                display_name = m["name"]

        for sid in m.get("selectionIdList") or []:
            s = _selection_lookup(overview, sid)
            if not s:
                continue
            name = (s.get("name") or "").strip()
            if not name:
                continue
            price = s.get("price")
            if not _is_valid_price(price):
                continue

            # Normaliza vírgula → ponto (e.g. "Mais de 2,5" → "Mais de 2.5")
            normalized = re.sub(r'(\d),(\d)', r'\1.\2', name)
            match = _OU_NAME_RE.match(normalized)
            if not match:
                continue

            line_str = match.group(2)
            try:
                line_val = float(line_str)
            except ValueError:
                continue

            # Aceita só linhas .0 ou .5 (descarta asiáticas .25/.75)
            decimal = line_val - int(line_val)
            if abs(decimal - 0.5) > 1e-6 and abs(decimal) > 1e-6:
                continue

            side = match.group(1).capitalize()  # "Mais" | "Menos"
            key = f"{side} de {line_str}"
            # Em caso de duplicata (raro), preserva a 1ª odd
            if key not in options:
                options[key] = float(price)

    if not options:
        return None
    return {
        "display_name": display_name,
        "options": options,
        "market_id": market_id,
    }


# ─── Construção de EventDigest ────────────────────────────────────────────────

def _format_start_time(start_ms: Any) -> str:
    """
    Converte epoch ms → string ISO em horário de Brasília.

    Mantém formato compatível com o resto da pipeline ("%Y-%m-%d %H:%M:%S").
    Retorna "" se start_ms inválido.
    """
    try:
        ms = int(start_ms)
    except (TypeError, ValueError):
        return ""
    if ms <= 0:
        return ""
    try:
        dt_utc = datetime.fromtimestamp(ms / 1000, tz=pytz.UTC)
        dt_br = dt_utc.astimezone(pytz.timezone("America/Sao_Paulo"))
        return dt_br.strftime("%Y-%m-%d %H:%M:%S")
    except (OverflowError, OSError, ValueError):
        return ""


def _build_event_digest(
    event: dict, overview: dict, source_link: str
) -> Optional[NS]:
    """Constrói um EventDigest (NS) a partir de 1 evento + overview."""
    if event.get("ardSportId") != _FOOTBALL_ARDSPORT_ID:
        return None

    participants = event.get("participants") or []
    home: Optional[str] = None
    away: Optional[str] = None
    # Estrutura Betano: 1º participant tem isHome=True, 2º não traz a key.
    # Fallback: usa ordem do array se isHome estiver ausente.
    for p in participants:
        if not isinstance(p, dict):
            continue
        name = p.get("name")
        if not name:
            continue
        if p.get("isHome") is True:
            if home is None:
                home = name
        elif p.get("isHome") is False:
            if away is None:
                away = name
        else:
            # isHome ausente — tratar como away (padrão da API Betano)
            if away is None:
                away = name
    # Fallback final: se ainda faltar, usa ordem [0]=home [1]=away
    if not home and len(participants) >= 1 and isinstance(participants[0], dict):
        home = participants[0].get("name") or home
    if not away and len(participants) >= 2 and isinstance(participants[1], dict):
        away = participants[1].get("name") or away
    if not (home and away):
        return None

    mr = _extract_match_result(event, overview)
    if not mr:
        return None  # sem 1x2 → pula evento

    tg = _extract_total_goals(event, overview)
    markets_dict: Dict[str, Any] = {"match_result": mr}
    if tg:
        markets_dict["total_goals"] = tg

    leagues = overview.get("leagues") or {}
    zones = overview.get("zones") or {}
    league = leagues.get(str(event.get("leagueId"))) or {}
    zone = zones.get(str(event.get("zoneId"))) or {}
    if not isinstance(league, dict):
        league = {}
    if not isinstance(zone, dict):
        zone = {}

    start_str = _format_start_time(event.get("startTime"))

    url_path = event.get("url") or ""
    game_url = f"{BETANO_BASE_URL}{url_path}" if url_path else ""

    options = mr["options"]
    return NS(
        ext_id=str(event.get("id")),
        source_link=source_link,
        game_url=game_url,
        competition=league.get("name") or "",
        country=zone.get("name") or "",
        team_home=home,
        team_away=away,
        start_local_str=start_str,
        odds_home=float(options.get("Casa", 0.0)),
        odds_draw=float(options.get("Empate", 0.0)),
        odds_away=float(options.get("Fora", 0.0)),
        is_live=bool(event.get("isLive")),
        # Extras (não obrigatórios no contrato base, mas úteis downstream):
        betradar_match_id=event.get("betradarMatchId"),
        markets_dict=markets_dict,
    )


def parse_betano_overview(
    api_response: dict, source_link: str = ""
) -> List[NS]:
    """
    Converte overview Betano em lista de EventDigest.

    Filtra futebol (ardSportId=1). Pula eventos sem mercado 1x2 válido.
    """
    if not isinstance(api_response, dict):
        return []
    events = api_response.get("events") or {}
    if not isinstance(events, dict):
        return []

    digests: List[NS] = []
    for _eid, ev in events.items():
        if not isinstance(ev, dict):
            continue
        d = _build_event_digest(ev, api_response, source_link)
        if d:
            digests.append(d)
    return digests


# ─── Wrapper async pro pipeline ───────────────────────────────────────────────

async def fetch_events_via_betano_api(
    source_link: str = "betano_overview",
) -> List[NS]:
    """
    Equivalente Betano do fetch_events_via_api (BetNacional).

    Retorna list[EventDigest] de jogos de futebol com 1x2 válido.
    """
    data = await fetch_betano_overview()
    if not data:
        logger.warning("Betano overview falhou — retornando []")
        return []
    events = parse_betano_overview(data, source_link=source_link)
    logger.info(
        f"Betano fetch: {len(events)} eventos futebol extraídos "
        f"(cache TTL {CACHE_TTL}s)"
    )
    return events


# ─── Helpers downstream ───────────────────────────────────────────────────────

def build_game_data_from_event(event: dict, overview: dict) -> dict:
    """
    Constrói {"stats": {...}, "markets": {...}} pra 1 evento.

    Usado por fetch_game_full_markets quando rodar em modo Betano.
    Compatível com decide_picks.
    """
    mr = _extract_match_result(event, overview)
    tg = _extract_total_goals(event, overview)
    markets: Dict[str, Any] = {}
    if mr:
        markets["match_result"] = mr
    if tg:
        markets["total_goals"] = tg

    stats: Dict[str, Any] = {}
    live = event.get("liveData") or {}
    if isinstance(live, dict):
        score = live.get("score") or {}
        if isinstance(score, dict) and score:
            stats["home_score"] = score.get("home")
            stats["away_score"] = score.get("away")
            stats["match_time"] = live.get("periodDescription") or ""

    return {"stats": stats, "markets": markets}


def extract_result_from_event(event: dict) -> Optional[dict]:
    """
    Extrai resultado de um evento — se já terminou.

    Heurística pra jogo finalizado: startTime + 105min < now (UTC).
    Score vem como strings em liveData.score → converte pra int.

    Retorna {"outcome": "home"|"draw"|"away", "home_goals", "away_goals", "score"}
    ou None se ainda em andamento / sem score / pré-jogo.
    """
    live = event.get("liveData") or {}
    if not isinstance(live, dict):
        return None
    score = live.get("score") or {}
    if not isinstance(score, dict):
        return None

    home_s = score.get("home")
    away_s = score.get("away")
    if home_s is None or away_s is None:
        return None
    try:
        h = int(home_s)
        a = int(away_s)
    except (TypeError, ValueError):
        return None

    # Verifica heurística de jogo finalizado
    start_ms = event.get("startTime")
    if start_ms:
        try:
            start_sec = int(start_ms) / 1000
            elapsed_min = (time.time() - start_sec) / 60
            if elapsed_min < _DEFAULT_MATCH_DURATION_MIN:
                return None  # ainda em andamento
        except (TypeError, ValueError):
            pass

    if h > a:
        outcome = "home"
    elif a > h:
        outcome = "away"
    else:
        outcome = "draw"

    return {
        "outcome": outcome,
        "home_goals": h,
        "away_goals": a,
        "score": f"{h}-{a}",
    }
