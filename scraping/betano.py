"""Scraper Betano — fetcher + parser + cache em memória.

Endpoint: /danae-webapi/api/live/overview/latest (queryLanguageId=5, queryOperatorId=8).

Estratégia: Playwright XHR capture. Validado em produção: IPs datacenter
recebem HTTP 403 "Betano Splash Screen" em requests diretos (curl/requests),
mas Playwright headless navegando pra página de futebol passa pelo gate e
captura a resposta XHR `events-by-seasons`/`overview/latest` normalmente.
Cache 60s amortiza o custo extra do Playwright.

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

async def _fetch_via_playwright() -> Optional[dict]:
    """
    Fetcher via Playwright: navega pra /sport/futebol/jogos-de-hoje/ e
    intercepta a resposta XHR de overview/latest. Necessário porque IPs
    datacenter recebem HTTP 403 ("Splash Screen") em requests diretos.
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        logger.error(f"Playwright não disponível: {exc}")
        return None

    captured: List[dict] = []

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            ctx = await browser.new_context(user_agent=UA, locale="pt-BR")
            page = await ctx.new_page()

            async def _on_response(resp):
                if "overview/latest" not in resp.url:
                    return
                if resp.status != 200:
                    return
                try:
                    body = await resp.json()
                    if isinstance(body, dict) and body.get("events"):
                        captured.append(body)
                except Exception:
                    pass

            page.on(
                "response",
                lambda r: asyncio.create_task(_on_response(r)),
            )

            await page.goto(
                f"{BETANO_BASE_URL}/sport/futebol/jogos-de-hoje/",
                wait_until="networkidle",
                timeout=int(TIMEOUT * 1000) + 25000,
            )
            await page.wait_for_timeout(5000)
            await browser.close()
    except Exception as exc:
        logger.exception(f"Betano fetch (Playwright) falhou: {exc}")
        return None

    if not captured:
        logger.warning("Betano fetch: nenhuma resposta overview/latest capturada")
        return None

    # Se múltiplas respostas (refresh interno), pega a maior
    return max(captured, key=lambda d: len(d.get("events", {})))


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

    data = await _fetch_via_playwright()
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


# ─── Handicap Asiático — fetch por evento (HTML SSR) ──────────────────────────
#
# Background: o overview/latest traz somente ~6 markets DESTAQUE por evento;
# Handicap Asiático fica fora. A página individual /odds/<slug>/<id>/?bt=11
# embute o evento completo em <script>window["initial_state"]={...}</script>
# com markets ricos: AHRF (HA Resultado Final), AHRH (HA 1° Tempo),
# ASOU (Asiático Mais/Menos gols), AOH1 (idem 1° Tempo).
# Endpoints XHR específicos do evento (/danae-webapi/api/live/events/<id>/latest,
# /api/event/markets-offers/<id>) retornam 403 Splash ou {} — parseamos o SSR.

# Tipos de market do Betano para Handicap Asiático
_BETANO_AH_TYPES = {"AHRF", "AHRH", "ASOU", "AOH1"}

# Tipo principal solicitado (Resultado Final 90min) — preferido se disponível
_BETANO_AH_PRIMARY_TYPE = "AHRF"

# Regex pra extrair o JSON do bloco <script>window["initial_state"]=
_INITIAL_STATE_MARKERS = (
    'window["initial_state"]=',
    "window['initial_state']=",
)


def _extract_initial_state(html: str) -> Optional[dict]:
    """Extrai o objeto window["initial_state"] do HTML SSR.

    Usa parsing balanceado de chaves (regex não dá conta de JSON com strings
    contendo `}` escapadas). Tolera ambas as variantes de aspas.
    """
    import json as _json

    start = -1
    marker_len = 0
    for marker in _INITIAL_STATE_MARKERS:
        idx = html.find(marker)
        if idx >= 0:
            start = idx
            marker_len = len(marker)
            break
    if start < 0:
        return None

    json_start = start + marker_len
    if json_start >= len(html) or html[json_start] != "{":
        return None

    depth = 0
    in_string = False
    escape = False
    end = -1
    for i in range(json_start, len(html)):
        c = html[i]
        if escape:
            escape = False
            continue
        if c == "\\":
            escape = True
            continue
        if c == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end < 0:
        return None

    try:
        return _json.loads(html[json_start:end])
    except Exception as exc:
        logger.debug(f"_extract_initial_state JSON parse falhou: {exc}")
        return None


def _format_ah_line(handicap: float) -> str:
    """Formata handicap numérico no estilo da Betano (+0.5, -1.25, 0.0)."""
    # Trata -0.0 → 0.0
    if handicap == 0:
        return "0.0"
    sign = "+" if handicap > 0 else "-"
    val = abs(handicap)
    # Mantém 2 decimais se quarter-line, senão 1
    if abs(val - round(val * 2) / 2) > 1e-6:
        return f"{sign}{val:.2f}"
    return f"{sign}{val:.1f}"


def _parse_ah_market(market: dict, home: str, away: str) -> Dict[str, float]:
    """Transforma 1 market AHRF/AHRH em dict {label: price}.

    Mapeia via `columnIndex` (0=Casa, 1=Fora) — mais robusto que comparar
    `name` com o nome do time. Cada selection vira:
        "Casa <handicap_formatado>" | "Fora <handicap_formatado>" -> price

    Selections com price < 1.01 são descartadas.
    """
    options: Dict[str, float] = {}
    for s in market.get("selections", []) or []:
        if not isinstance(s, dict):
            continue
        price = s.get("price")
        if not _is_valid_price(price):
            continue
        col = s.get("columnIndex")
        h = s.get("handicap")
        if not isinstance(h, (int, float)) or isinstance(h, bool):
            continue
        if col == 0:
            side = "Casa"
        elif col == 1:
            side = "Fora"
        else:
            # Fallback: usa nome do time se columnIndex ausente
            name = (s.get("name") or "").strip()
            if home and name.startswith(home):
                side = "Casa"
            elif away and name.startswith(away):
                side = "Fora"
            else:
                continue
        line = _format_ah_line(float(h))
        key = f"{side} {line}"
        # Em caso de duplicata, preserva primeira ocorrência
        if key not in options:
            options[key] = float(price)
    return options


def _parse_ah_ou_market(market: dict) -> Dict[str, float]:
    """Transforma 1 market ASOU/AOH1 (Mais/Menos asiático) em dict {label: price}.

    Diferente do HCTG, aceita linhas quarter (.25/.75). Selections vêm como
    "Mais de 2.25" / "Menos de 2.25" — preserva o formato.
    """
    options: Dict[str, float] = {}
    for s in market.get("selections", []) or []:
        if not isinstance(s, dict):
            continue
        price = s.get("price")
        if not _is_valid_price(price):
            continue
        name = (s.get("name") or "").strip()
        if not name:
            continue
        # Normaliza vírgula → ponto
        normalized = re.sub(r"(\d),(\d)", r"\1.\2", name)
        if normalized not in options:
            options[normalized] = float(price)
    return options


def _extract_market_block_at(html: str, type_value: str) -> Optional[dict]:
    """Acha o 1º bloco JSON {...} que contém `"type":"<type_value>"` no HTML.

    Estratégia robusta: localiza `"type":"<type_value>"`, depois varre '{'
    para trás como candidatos. Pra cada candidato, faz parse forward balanced
    (string-aware com escape) até o '}' fechador. Se o range engloba o needle,
    parseia o JSON e retorna.

    Robusto contra parsing forward-only (não tenta inferir estado de string
    andando ao contrário — abordagem antiga falhava em HTML real).
    """
    import json as _json

    needle = f'"type":"{type_value}"'
    pos = html.find(needle)
    if pos < 0:
        return None

    # Limite de busca pra trás — markets Betano são tipicamente < 8 KB
    search_limit = max(0, pos - 16000)

    # Itera por '{' candidatos andando pra trás
    cand = pos
    while cand >= search_limit:
        cand = html.rfind("{", search_limit, cand)
        if cand < 0:
            break

        # Forward balanced parse a partir desse '{'
        depth = 0
        in_string = False
        escape = False
        end_idx = -1
        for j in range(cand, len(html)):
            c = html[j]
            if escape:
                escape = False
                continue
            if c == "\\":
                escape = True
                continue
            if c == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    end_idx = j + 1
                    break

        if end_idx > pos:
            try:
                return _json.loads(html[cand:end_idx])
            except Exception:
                # Esse candidato não fecha em JSON válido — tenta o próximo '{' anterior
                pass

        cand -= 1  # avança pra próxima iteração de rfind

    logger.debug(
        f"_extract_market_block_at({type_value}): nenhum bloco JSON válido envolvendo a posição {pos}"
    )
    return None


def _parse_handicap_from_html(
    html: str, home_hint: str = "", away_hint: str = ""
) -> Optional[dict]:
    """Parser HTML SSR → dict de mercado de Handicap Asiático.

    Estratégia: localiza blocos JSON com `"type":"AHRF"` (preferencial) ou
    `"type":"ASOU"` (fallback) diretamente no HTML via balanced braces
    isolado. Mais robusto que extrair window["initial_state"] inteiro.
    """
    # Inferir nomes de times — defaults
    home = home_hint or ""
    away = home_hint or ""
    # 1) AHRF (preferencial: Handicap Asiático Resultado Final)
    ahrf = _extract_market_block_at(html, _BETANO_AH_PRIMARY_TYPE)
    asou = _extract_market_block_at(html, "ASOU")

    # Fallback opcional pra extrair times via initial_state se hints vazios.
    if not (home and away):
        state = _extract_initial_state(html)
        ev = (state or {}).get("data", {}).get("event") or {}
        if not isinstance(ev, dict):
            ev = {}
        home = home_hint or ev.get("homeTeam") or home
        away = away_hint or ev.get("awayTeam") or away
        if not (home and away):
            short = ev.get("shortName") or ""
            m = re.match(r"^(.+?)\s+(?:vs|x|-)\s+(.+)$", short, re.IGNORECASE)
            if m:
                home = home or m.group(1).strip()
                away = away or m.group(2).strip()

    # Simula API antiga: encapsula em list pra reuso do código abaixo
    markets = [m for m in (ahrf, asou) if m]
    if not markets:
        return None

    # Inferir nomes de times se não vieram (campos do próprio event)
    home = home_hint or event.get("homeTeam") or ""
    away = away_hint or event.get("awayTeam") or ""
    if not (home and away):
        # Tenta extrair de shortName tipo "PSG vs Arsenal"
        short = event.get("shortName") or ""
        m = re.match(r"^(.+?)\s+(?:vs|x|-)\s+(.+)$", short, re.IGNORECASE)
        if m:
            home = home or m.group(1).strip()
            away = away or m.group(2).strip()

    # 1) AHRF (preferencial: Handicap Asiático Resultado Final)
    ahrf = next(
        (m for m in markets if isinstance(m, dict) and m.get("type") == _BETANO_AH_PRIMARY_TYPE),
        None,
    )
    if ahrf:
        opts = _parse_ah_market(ahrf, home, away)
        if opts:
            return {
                "display_name": ahrf.get("name") or "Handicap Asiático",
                "options": opts,
                "market_type": "handicap_asian",
                "market_id": ahrf.get("id"),
                "betano_type": "AHRF",
            }

    # 2) Fallback: ASOU (Asiático Mais/Menos Total de Gols)
    asou = next(
        (m for m in markets if isinstance(m, dict) and m.get("type") == "ASOU"),
        None,
    )
    if asou:
        opts = _parse_ah_ou_market(asou)
        if opts:
            return {
                "display_name": asou.get("name") or "Asiático (Mais/Menos) Total de Gols",
                "options": opts,
                "market_type": "handicap_asian",
                "market_id": asou.get("id"),
                "betano_type": "ASOU",
            }

    return None


async def _fetch_event_via_playwright(
    game_url: str, timeout_ms: int = 45000, settle_ms: int = 12000
) -> Optional[str]:
    """Carrega game_url via Playwright e retorna o HTML pós-render.

    Retorna None em qualquer erro (timeout, bloqueio, browser).
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        logger.warning(f"Playwright não disponível: {exc}")
        return None

    html: Optional[str] = None
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            ctx = await browser.new_context(user_agent=UA, locale="pt-BR")
            page = await ctx.new_page()
            try:
                await page.goto(game_url, wait_until="networkidle", timeout=timeout_ms)
            except Exception as exc:
                logger.debug(f"goto {game_url} timeout/erro tolerado: {exc}")
            await page.wait_for_timeout(settle_ms)
            try:
                html = await page.content()
            except Exception as exc:
                logger.debug(f"page.content() falhou: {exc}")
            await browser.close()
    except Exception as exc:
        logger.warning(f"_fetch_event_via_playwright falhou: {exc}")
        return None

    return html


def _normalize_event_url(game_url: str) -> str:
    """Converte URL /live/... em /odds/.../?bt=11.

    overview/latest devolve URLs no formato /live/<slug>/<id>/ para eventos
    pré-jogo. Essa rota é SPA-driven e o SSR retorna initial_state.markets=[].
    A rota /odds/<slug>/<id>/?bt=11 entrega SSR completo com markets ricos.
    """
    if not game_url:
        return game_url
    # Substitui só o primeiro segmento /live/
    fixed = re.sub(r"(://[^/]+)/live/", r"\1/odds/", game_url, count=1)
    # Garante ?bt=11
    if "bt=" not in fixed:
        sep = "&" if "?" in fixed else "?"
        fixed = f"{fixed}{sep}bt=11"
    return fixed


async def fetch_event_handicap_asian(
    ext_id: str, game_url: str
) -> Optional[dict]:
    """Busca mercado de Handicap Asiático de UM evento.

    Estratégia: Playwright → HTML SSR → extrai window["initial_state"] →
    pesca market AHRF (preferencial) ou ASOU (fallback).

    Retorna dict no formato compatível com markets_dict:
        {
            "display_name": str,
            "options": {"Casa -1.5": 2.10, "Fora +1.5": 1.75, ...},
            "market_type": "handicap_asian",
            "market_id": int,
            "betano_type": "AHRF" | "ASOU",
        }
    ou None se não conseguir extrair.
    """
    if not game_url:
        logger.warning(f"fetch_event_handicap_asian: game_url vazio (ext_id={ext_id})")
        return None

    target_url = _normalize_event_url(game_url)
    html = await _fetch_event_via_playwright(target_url)
    if not html:
        logger.warning(f"fetch_event_handicap_asian: HTML vazio (ext_id={ext_id})")
        return None

    result = _parse_handicap_from_html(html)
    if not result:
        logger.warning(
            f"fetch_event_handicap_asian: sem handicap asiático (ext_id={ext_id}, "
            f"html_len={len(html)})"
        )
        return None

    logger.debug(
        f"fetch_event_handicap_asian: ext_id={ext_id} "
        f"betano_type={result.get('betano_type')} "
        f"options={len(result['options'])}"
    )
    return result


# ─── Full markets — fetch por evento (HTML SSR) ───────────────────────────────
#
# Página individual /odds/<slug>/<id>/ embute TODOS os mercados no HTML SSR,
# muito antes do overview/latest expor (~2h antes do jogo). Estratégia:
# Playwright → HTML → _extract_market_block_at por tipo (MRES/HCTG/AHRF) →
# dict compatível com decide_picks. Substitui o fetch_event_handicap_asian
# como fonte de enrich pré-jogo (handicap fica como sub-mercado opcional).

def _parse_mres_market_from_block(market: dict) -> Optional[Dict[str, float]]:
    """Transforma 1 bloco MRES (Resultado Final 1x2) em {Casa/Empate/Fora: odd}.

    Estratégia: selection.name vem como "1" (home), "X" (draw), "2" (away)
    no SSR — validado empiricamente. Aceita também variantes "Casa"/"Empate"/
    "Fora" (caso a Betano mude pra label-friendly). Fallback: ordem das
    selections (home, draw, away) com price válido.
    """
    selections = market.get("selections", []) or []
    options: Dict[str, float] = {}

    for s in selections:
        if not isinstance(s, dict):
            continue
        price = s.get("price")
        if not _is_valid_price(price):
            continue
        raw_name = (s.get("name") or "").strip()
        key: Optional[str] = None
        if raw_name == "1":
            key = "Casa"
        elif raw_name in ("X", "x"):
            key = "Empate"
        elif raw_name == "2":
            key = "Fora"
        else:
            lower = raw_name.lower()
            if lower == "casa":
                key = "Casa"
            elif lower in ("empate", "draw"):
                key = "Empate"
            elif lower == "fora":
                key = "Fora"
        if key and key not in options:
            options[key] = float(price)

    # Fallback: usa ordem se faltar alguma key
    if len(options) < 3 and len(selections) >= 3:
        ordered_keys = ["Casa", "Empate", "Fora"]
        for idx, s in enumerate(selections[:3]):
            if not isinstance(s, dict):
                continue
            price = s.get("price")
            if not _is_valid_price(price):
                continue
            k = ordered_keys[idx]
            if k not in options:
                options[k] = float(price)

    if len(options) != 3:
        return None
    return options


def _parse_hctg_market_from_block(market: dict) -> Dict[str, float]:
    """Transforma 1 bloco HCTG (Total de Gols Mais/Menos) em dict {label: odd}.

    Reutiliza _OU_NAME_RE pra parsear "Mais de X.X" / "Menos de X.X". Aceita
    só linhas .0 ou .5 (descarta asiáticas .25/.75 — esses ficam em ASOU).
    """
    options: Dict[str, float] = {}
    for s in market.get("selections", []) or []:
        if not isinstance(s, dict):
            continue
        price = s.get("price")
        if not _is_valid_price(price):
            continue
        name = (s.get("name") or "").strip()
        if not name:
            continue
        normalized = re.sub(r"(\d),(\d)", r"\1.\2", name)
        match = _OU_NAME_RE.match(normalized)
        if not match:
            continue
        line_str = match.group(2)
        try:
            line_val = float(line_str)
        except ValueError:
            continue
        decimal = line_val - int(line_val)
        if abs(decimal - 0.5) > 1e-6 and abs(decimal) > 1e-6:
            continue
        side = match.group(1).capitalize()
        key = f"{side} de {line_str}"
        if key not in options:
            options[key] = float(price)
    return options


def _parse_full_markets_from_html(
    html: str, home_hint: str = "", away_hint: str = ""
) -> Optional[dict]:
    """Parser puro: HTML SSR da página individual → dict de markets.

    Localiza blocos JSON por tipo via _extract_market_block_at:
      - MRES (match_result, obrigatório)
      - HCTG (total_goals, opcional)
      - AHRF (handicap_asian, opcional)

    Retorna {"stats": {}, "markets": {...}} ou None se MRES ausente/inválido.
    Formato compatível com decide_picks.
    """
    if not html or len(html) < 5000 or "Splash Screen" in html:
        return None

    mres_block = _extract_market_block_at(html, "MRES")
    if not isinstance(mres_block, dict):
        return None

    mres_options = _parse_mres_market_from_block(mres_block)
    if not mres_options:
        return None

    markets: Dict[str, Any] = {
        "match_result": {
            "display_name": mres_block.get("name") or "Resultado Final",
            "options": mres_options,
            "market_id": mres_block.get("id"),
        }
    }

    # total_goals (opcional)
    hctg_block = _extract_market_block_at(html, "HCTG")
    if isinstance(hctg_block, dict):
        tg_options = _parse_hctg_market_from_block(hctg_block)
        if tg_options:
            markets["total_goals"] = {
                "display_name": hctg_block.get("name") or "Total de Gols Mais/Menos",
                "options": tg_options,
                "market_id": hctg_block.get("id"),
            }

    # handicap_asian (opcional)
    ahrf_block = _extract_market_block_at(html, _BETANO_AH_PRIMARY_TYPE)
    if isinstance(ahrf_block, dict):
        ah_options = _parse_ah_market(ahrf_block, home_hint, away_hint)
        if ah_options:
            markets["handicap_asian"] = {
                "display_name": ahrf_block.get("name") or "Handicap Asiático",
                "options": ah_options,
                "market_type": "handicap_asian",
                "market_id": ahrf_block.get("id"),
                "betano_type": _BETANO_AH_PRIMARY_TYPE,
            }

    return {"stats": {}, "markets": markets}


async def fetch_event_full_markets_from_page(
    ext_id: str,
    game_url: str,
    *,
    settle_ms: int = 6000,
    timeout_ms: int = 45000,
) -> Optional[dict]:
    """Extrai TODOS os mercados da página individual do jogo via HTML SSR.

    Retorna dict compatível com decide_picks:
        {
            "stats": {...},
            "markets": {
                "match_result": {"display_name": ..., "options": {Casa, Empate, Fora}},
                "total_goals": {...},       # opcional
                "handicap_asian": {...},    # opcional
            }
        }

    Se HTML retornar Splash Screen ou markets vazios: retorna None.
    """
    if not game_url:
        logger.warning(
            f"fetch_event_full_markets_from_page: game_url vazio (ext_id={ext_id})"
        )
        return None

    html = await _fetch_event_via_playwright(
        game_url, timeout_ms=timeout_ms, settle_ms=settle_ms
    )
    if not html:
        logger.warning(
            f"fetch_event_full_markets_from_page: HTML vazio (ext_id={ext_id})"
        )
        return None

    result = _parse_full_markets_from_html(html)
    if not result:
        logger.warning(
            f"fetch_event_full_markets_from_page: parse falhou (ext_id={ext_id}, "
            f"html_len={len(html)})"
        )
        return None

    mk = result.get("markets") or {}
    logger.debug(
        f"fetch_event_full_markets_from_page: ext_id={ext_id} "
        f"markets={list(mk.keys())}"
    )
    return result


# ─── Coleta proativa via páginas de liga (HTML SSR) ───────────────────────────
#
# Overview Betano só traz jogos AO VIVO + iminentes (~2h antes). Pra coletar
# jogos de campeonatos com horário fixo (ex: Brasileirão das 19h) horas antes,
# usamos as páginas de liga (/sport/futebol/brasil/brasileirao-serie-a-betano/10016/).
# Elas embutem no HTML SSR:
#   1) <script type="application/ld+json"> com @type=SportsEvent (padrão Schema.org)
#   2) Bloco JSON `participants` com team_ids da Betano (8 dígitos)
#
# Estratégia: regex pra extrair ambos, match por nome (home/away), monta EventDigest
# sem odds (overview enriquece depois quando o evento entrar ao vivo).

_JSON_LD_RE = re.compile(
    r'<script type="application/ld\+json">(.*?)</script>',
    re.DOTALL,
)
_PARTICIPANTS_RE = re.compile(r'"participants":\[([^\]]+)\]')
_TEAM_RE = re.compile(
    r'\{"name":"([^"]+)","url":"([^"]+)","color":"[^"]*","id":"(\d+)"\}'
)
_EXT_ID_RE = re.compile(r'/(\d{6,10})/?$')


def _parse_league_html(html: str, source_url: str) -> List[NS]:
    """Parser síncrono: HTML da página de liga Betano → List[EventDigest].

    Reutilizável tanto pela versão single-URL quanto pela batch. Não toca em
    Playwright nem em I/O — só processa string HTML. Sem estado mutável global.

    Args:
        html: HTML completo da página de liga (já carregado via Playwright).
        source_url: URL original da liga (usado pra preencher EventDigest.source_link).

    Returns:
        List[NS] com EventDigests. Vazio se HTML inválido/Splash/sem JSON-LD.
    """
    if not html or len(html) < 5000 or "Splash Screen" in html:
        logger.warning(
            f"League page bloqueada ou vazia: {source_url} (html_len={len(html)})"
        )
        return []

    # ── 1) Extrai eventos JSON-LD do tipo SportsEvent ─────────────────────
    import json as _json

    events_meta: List[dict] = []
    for m in _JSON_LD_RE.finditer(html):
        try:
            data = _json.loads(m.group(1))
        except Exception:
            continue
        items = data if isinstance(data, list) else [data]
        for item in items:
            if not isinstance(item, dict):
                continue
            if item.get("@type") != "SportsEvent":
                continue
            events_meta.append(item)

    if not events_meta:
        logger.warning(f"Nenhum SportsEvent em JSON-LD: {source_url}")
        return []

    # ── 2) Extrai team_ids via bloco participants ─────────────────────────
    name_to_team_id: Dict[str, dict] = {}
    for pm in _PARTICIPANTS_RE.finditer(html):
        for tm in _TEAM_RE.finditer(pm.group(1)):
            t_name, t_url, t_id = tm.group(1), tm.group(2), int(tm.group(3))
            # Extrai league_id da URL: /sport/futebol/competicoes/brasil/10016/...
            lm = re.search(r'/competicoes/[^/]+/(\d+)/', t_url)
            league_id = int(lm.group(1)) if lm else None
            slug_m = re.search(r'/([^/]+)/\d+-t/?$', t_url)
            name_to_team_id[t_name.strip()] = {
                "betano_team_id": t_id,
                "url": t_url,
                "league_id": league_id,
                "slug": slug_m.group(1) if slug_m else None,
            }

    # ── 3) Constrói EventDigests ──────────────────────────────────────────
    digests: List[NS] = []
    for ev in events_meta:
        ev_url = ev.get("url") or ""
        em = _EXT_ID_RE.search(ev_url.rstrip("/") + "/")
        if not em:
            continue
        ext_id = em.group(1)

        home_team_obj = ev.get("homeTeam") or {}
        away_team_obj = ev.get("awayTeam") or {}
        home = home_team_obj.get("name") if isinstance(home_team_obj, dict) else None
        away = away_team_obj.get("name") if isinstance(away_team_obj, dict) else None
        if not (home and away):
            continue

        start = ev.get("startDate") or ""
        # ISO 8601 → "YYYY-MM-DD HH:MM:SS" (UTC, sem timezone — alinha c/ schema Game.start_time)
        try:
            start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
            start_str = start_dt.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            start_str = start

        home_info = name_to_team_id.get(home.strip(), {})
        away_info = name_to_team_id.get(away.strip(), {})

        # Competition: pega location.name do JSON-LD se houver
        loc = ev.get("location") or {}
        competition = loc.get("name") if isinstance(loc, dict) else None

        digests.append(NS(
            ext_id=ext_id,
            source_link=source_url,
            game_url=ev_url,
            competition=competition or "",
            country="Brasil",  # heurística: páginas /brasil/... — refinar via parser se quiser
            team_home=home,
            team_away=away,
            start_local_str=start_str,
            odds_home=0.0,
            odds_draw=0.0,
            odds_away=0.0,
            is_live=False,
            betradar_match_id=None,
            markets_dict={},  # sem odds inicialmente — overview enriquece
            home_team_id=home_info.get("betano_team_id"),
            away_team_id=away_info.get("betano_team_id"),
            _teams_meta=(home_info, away_info),  # interno — pra persistir Team
        ))

    logger.info(f"League page {source_url}: {len(digests)} eventos extraídos")
    return digests


async def fetch_events_from_league_pages_batch(
    urls: List[str],
    *,
    concurrency: int = 3,
    settle_ms: int = 4000,
    timeout_ms: int = 45000,
) -> Dict[str, List[NS]]:
    """Coleta proativa BATCH de múltiplas páginas de liga Betano.

    Performance:
        - 1 browser chromium reutilizado pra TODAS as URLs (evita N startups).
        - `concurrency` contexts em paralelo (default 3) via asyncio.Semaphore.
        - settle_ms reduzido pra 4s (suficiente pra Schema.org JSON-LD).

    Args:
        urls: Lista de URLs de páginas de liga Betano.
        concurrency: Quantos contexts paralelos. Default 3.
        settle_ms: Tempo após networkidle pra deixar o JSON-LD assentar. Default 4000.
        timeout_ms: Timeout do goto. Default 45000.

    Returns:
        dict {url: List[NS]} — chave por URL original, valor é a lista de
        EventDigests extraídos daquela URL (vazia se falhou).

    Idempotente. Tolera falha em URL individual (loga warning, continua).
    """
    result: Dict[str, List[NS]] = {url: [] for url in urls}
    if not urls:
        return result

    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        logger.error(f"Playwright não disponível: {exc}")
        return result

    sem = asyncio.Semaphore(max(1, concurrency))

    async def _process_one(browser, url: str) -> None:
        async with sem:
            try:
                ctx = await browser.new_context(user_agent=UA, locale="pt-BR")
                try:
                    page = await ctx.new_page()
                    try:
                        await page.goto(url, wait_until="networkidle", timeout=timeout_ms)
                    except Exception as exc:
                        logger.debug(f"batch goto {url} timeout/erro tolerado: {exc}")
                    await page.wait_for_timeout(settle_ms)
                    try:
                        html = await page.content()
                    except Exception as exc:
                        logger.debug(f"batch page.content() falhou ({url}): {exc}")
                        html = ""
                    if not html or len(html) < 5000 or "Splash Screen" in html:
                        logger.warning(
                            f"batch: page bloqueada/vazia {url} (html_len={len(html)})"
                        )
                        return
                    digests = _parse_league_html(html, url)
                    result[url] = digests
                    logger.info(f"batch: {len(digests)} eventos | {url}")
                finally:
                    try:
                        await ctx.close()
                    except Exception:
                        pass
            except Exception as exc:
                logger.warning(f"batch: falha em {url}: {exc}")

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                tasks = [_process_one(browser, u) for u in urls]
                await asyncio.gather(*tasks, return_exceptions=True)
            finally:
                try:
                    await browser.close()
                except Exception:
                    pass
    except Exception as exc:
        logger.exception(f"fetch_events_from_league_pages_batch falhou: {exc}")

    return result


async def fetch_events_from_league_page(url: str) -> List[NS]:
    """Wrapper single-URL — delega pra `fetch_events_from_league_pages_batch`.

    Mantido por compatibilidade com chamadas existentes. Use o batch
    diretamente quando tiver múltiplas URLs pra colher (ganho ~3-5x).

    Returns:
        List[NS] com EventDigests da URL. Vazia se falhou ou Splash Screen.
    """
    results = await fetch_events_from_league_pages_batch([url], concurrency=1)
    return results.get(url, [])


def upsert_team(
    session,
    betano_team_id: int,
    name: str,
    country: Optional[str] = None,
    league_id: Optional[int] = None,
    slug: Optional[str] = None,
):
    """Upsert idempotente de Team.

    Cria se não existir. Se já existir, atualiza name (sempre) e os outros
    campos APENAS se ainda vazios — não sobrescreve dados curados.

    Returns: Team ou None se betano_team_id falsy.
    """
    from models.database import Team
    if not betano_team_id:
        return None
    team = session.query(Team).filter_by(betano_team_id=betano_team_id).first()
    if team:
        if name and team.name != name:
            team.name = name
        if country and not team.country:
            team.country = country
        if league_id and not team.league_id:
            team.league_id = league_id
        if slug and not team.slug:
            team.slug = slug
    else:
        team = Team(
            betano_team_id=betano_team_id,
            name=name,
            country=country,
            league_id=league_id,
            slug=slug,
        )
        session.add(team)
        session.flush()
    return team
