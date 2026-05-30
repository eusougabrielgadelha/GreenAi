"""Funções de fetch de páginas web."""
import asyncio
import requests
from typing import Optional
from config.settings import (
    HAS_PLAYWRIGHT, SCRAPE_BACKEND, REQUESTS_TIMEOUT, HTML_TIMEOUT, USER_AGENT,
    PLAYWRIGHT_NAVIGATION_TIMEOUT, PLAYWRIGHT_SELECTOR_TIMEOUT, PLAYWRIGHT_NETWORKIDLE_TIMEOUT,
    PLAYWRIGHT_RESULT_TIMEOUT,
)
from utils.logger import logger
from scraping.betnacional import try_parse_events

HEADERS = {"User-Agent": USER_AGENT}


def fetch_requests(url: str, has_fallback: bool = True) -> str:
    """
    Baixa uma página usando requests simples (síncrono) - SEM bypass, apenas HTML.
    
    Args:
        url: URL para buscar
        has_fallback: Se True, indica que há fallback disponível (reduz verbosidade)
    
    Returns:
        HTML da página
    
    Raises:
        Exception: Se a requisição falhar após todas as tentativas
    """
    # Usar requests simples sem bypass
    response = requests.get(url, headers=HEADERS, timeout=HTML_TIMEOUT)
    response.raise_for_status()
    return response.text


async def _fetch_requests_async(url: str, has_fallback: bool = True) -> str:
    """
    Wrapper assíncrono para requests.get com rate limiting e retry.
    
    Args:
        url: URL para buscar
        has_fallback: Se True, indica que há fallback disponível (reduz verbosidade)
    
    Returns:
        HTML da página
    
    Raises:
        Exception: Se a requisição falhar após todas as tentativas
    """
    from utils.rate_limiter import html_rate_limiter, retry_with_backoff
    
    async def _fetch():
        # Usar rate limiter antes de fazer requisição
        await html_rate_limiter.acquire()
        
        # Executar requisição em thread separada
        return await asyncio.to_thread(fetch_requests, url, has_fallback)
    
    # Tentar com retry
    try:
        return await retry_with_backoff(
            _fetch,
            max_retries=3,
            initial_delay=1.0,
            max_delay=20.0,
            exponential_base=2.0,
            exceptions=(requests.exceptions.RequestException, Exception, asyncio.CancelledError),
            rate_limiter=None  # Já usamos dentro de _fetch
        )
    except asyncio.CancelledError:
        # Não logar erro se foi cancelado - apenas propagar
        logger.debug(f"Requisição para {url} foi cancelada (CancelledError)")
        raise
    except Exception as e:
        from utils.error_handler import log_error_with_context
        log_error_with_context(
            e,
            context={
                "url": url,
                "stage": "fetch_requests_async",
                "has_retry": True
            },
            level="warning",
            reraise=True
        )


async def fetch_playwright(url: str) -> str:
    """Baixa uma página usando Playwright (assíncrono)."""
    if not HAS_PLAYWRIGHT:
        raise RuntimeError("Playwright não disponível.")
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(user_agent=USER_AGENT)
        await page.goto(url, wait_until="networkidle", timeout=PLAYWRIGHT_NETWORKIDLE_TIMEOUT)
        html = await page.content()
        await browser.close()
        return html


def _backend_auto() -> str:
    """Escolhe o backend automaticamente: Playwright quando disponível, senão requests."""
    return "playwright" if HAS_PLAYWRIGHT else "requests"


async def _fetch_with_playwright(
    url: str,
    wait_for_selector: str = None,
    wait_time: int = 3000,
    selector_timeout: int = None,
) -> str:
    """
    Renderiza a página com Playwright e retorna o HTML.

    Args:
        url: URL para buscar
        wait_for_selector: Seletor CSS para aguardar (opcional)
        wait_time: Tempo adicional em ms para aguardar após carregamento (padrão: 3000ms)
        selector_timeout: Timeout em ms para aguardar o seletor (default: PLAYWRIGHT_SELECTOR_TIMEOUT)
    """
    if not HAS_PLAYWRIGHT:
        raise RuntimeError("Playwright não disponível no ambiente.")
    from playwright.async_api import async_playwright
    sel_timeout = selector_timeout if selector_timeout is not None else PLAYWRIGHT_SELECTOR_TIMEOUT
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0",
            locale="pt-BR",
        )
        page = await context.new_page()
        try:
            await page.goto(url, wait_until="networkidle", timeout=PLAYWRIGHT_NETWORKIDLE_TIMEOUT)

            # Aguarda seletor específico se fornecido
            if wait_for_selector:
                try:
                    await page.wait_for_selector(wait_for_selector, timeout=sel_timeout)
                except Exception as e:
                    logger.warning(
                        f"Timeout/erro aguardando seletor '{wait_for_selector}' em {url} ({sel_timeout}ms): {type(e).__name__}"
                    )

            # Aguarda tempo adicional para JavaScript carregar
            await page.wait_for_timeout(wait_time)

            html = await page.content()
            return html
        finally:
            await context.close()
            await browser.close()


async def fetch_events_from_link(url: str, backend: str):
    """
    Busca eventos de uma URL do BetNacional.

    Estratégia:
      1) XHR (API events-by-seasons) como caminho primário quando dá pra extrair
         (sport_id, category_id, tournament_id) da URL. Rápido, limpo e traz país.
      2) Fallback HTML (Playwright/requests + try_parse_events) se a API falhar
         ou se os IDs não puderem ser inferidos.
    """
    from utils.analytics_logger import log_extraction
    from scraping.betnacional import (
        try_parse_events,
        extract_ids_from_url,
        fetch_events_from_api_async,
        parse_events_from_api,
    )

    def _other(b: str) -> str:
        return "requests" if b == "playwright" else "playwright"

    from utils.logger import log_with_context
    log_with_context(
        "info",
        f"Varredura iniciada para {url}",
        url=url,
        stage="fetch_events",
        status="started"
    )

    # ── Caminho 1: XHR ────────────────────────────────────────────────────
    ids = extract_ids_from_url(url)
    if ids is not None:
        sport_id, category_id, tournament_id = ids
        logger.info(
            "🔌 Tentando XHR para %s (sport=%s, cat=%s, tour=%s)",
            url, sport_id, category_id, tournament_id,
        )
        try:
            json_data = await fetch_events_from_api_async(
                sport_id, category_id, tournament_id, market_id=1
            )
            if json_data:
                evs = parse_events_from_api(json_data, url)
                if evs:
                    logger.info("✅ XHR retornou %d eventos para %s", len(evs), url)
                    log_extraction(
                        url, len(evs), "xhr", success=True,
                        metadata={"attempt": 1, "method": "xhr"}
                    )
                    return evs
                logger.info("XHR respondeu mas parser não extraiu eventos; caindo pro HTML…")
            else:
                logger.info("XHR não retornou dados; caindo pro HTML…")
        except Exception as e:
            from utils.error_handler import log_error_with_context
            log_error_with_context(
                e,
                context={"url": url, "stage": "xhr_primary"},
                level="warning",
                reraise=False,
            )
    else:
        logger.info("URL %s não bate no padrão /events/sport/cat/tour; pulando XHR.", url)

    # ── Caminho 2: HTML scraping (fallback) ───────────────────────────────
    backend_sel = backend if backend != "auto" else _backend_auto()
    logger.info("🌐 Fallback HTML — backend=%s", backend_sel)

    for attempt, b in enumerate([backend_sel, _other(backend_sel)]):
        try:
            if b == "playwright":
                html = await _fetch_with_playwright(url)
            else:
                html = await _fetch_requests_async(url)
            evs = try_parse_events(html, url)
            if evs:
                log_extraction(url, len(evs), b, success=True, metadata={"attempt": attempt + 1, "method": "html"})
                return evs
            logger.info("Nenhum evento com backend=%s; tentando fallback…", b)
        except Exception as e:
            from utils.error_handler import log_error_with_context
            error_msg = str(e)[:500]  # Limita tamanho
            log_error_with_context(
                e,
                context={
                    "url": url,
                    "backend": b,
                    "attempt": attempt + 1,
                    "stage": "html_scraping"
                },
                level="warning",
                reraise=False
            )
            if attempt == 1:  # Última tentativa falhou
                log_extraction(url, 0, b, success=False, error=error_msg, metadata={"attempt": attempt + 1})

    log_extraction(url, 0, backend_sel, success=False, error="Nenhum evento encontrado após todas as tentativas")
    return []


async def fetch_game_result(ext_id: str, source_link: str) -> Optional[dict]:
    """
    Busca o resultado de um jogo específico.
    
    Usa cache para evitar múltiplas requisições para o mesmo jogo.
    Usa APENAS HTML scraping (XHR desativado).
    
    Args:
        ext_id: ID externo do jogo (event_id)
        source_link: URL do jogo
    
    Returns:
        Dict com keys: "outcome" (home/draw/away), "home_goals", "away_goals", "score" (formato "2-1")
        Ou None se não conseguir extrair
    """
    from scraping.betnacional import scrape_game_result
    from utils.cache import result_cache, negative_result_cache
    
    # ETAPA 0: Verificar cache primeiro
    cached_result = result_cache.get(ext_id)
    if cached_result:
        # Se cache retornar string (legado), converter para dict
        if isinstance(cached_result, str):
            logger.info(f"✅ Resultado encontrado no cache (legado) para jogo {ext_id}: {cached_result}")
            return {
                "outcome": cached_result,
                "home_goals": None,
                "away_goals": None,
                "score": None
            }
        logger.info(f"✅ Resultado encontrado no cache para jogo {ext_id}: {cached_result.get('outcome')}")
        return cached_result
    
    # ETAPA 0.5: Verificar cache negativo (jogo recém-pesquisado sem resultado)
    if negative_result_cache.get(ext_id) is not None:
        logger.debug(f"⏭️ Cache negativo HIT para jogo {ext_id} — pulando refetch (será tentado novamente após TTL)")
        return None

    # ETAPA 1: Usar APENAS HTML scraping (XHR desativado)
    try:
        logger.debug(f"🌐 Buscando resultado via HTML scraping para jogo {ext_id}")
        # Para jogos finalizados, usar Playwright com mais tempo de espera para garantir que o widget carregue
        if HAS_PLAYWRIGHT:
            # Aguardar por seletor do live-tracker ou scoreboard, ou aguardar mais tempo
            # Tentar múltiplos seletores em sequência
            # Primeiro aguarda o liveMatchTracker, depois o bloco de resultado, dando mais tempo para o widget carregar
            try:
                html = await _fetch_with_playwright(
                    source_link,
                    wait_for_selector="[data-testid='liveMatchTracker']",
                    wait_time=2500,
                    selector_timeout=PLAYWRIGHT_RESULT_TIMEOUT,
                )
            except Exception as e:
                logger.warning(f"⚠️ Falha aguardando liveMatchTracker para {ext_id}: {type(e).__name__}. Fallback wait-only.")
                html = await _fetch_with_playwright(source_link, wait_time=3500)
            # Segunda passada aguardando o bloco de resultado explícito (SportRadar tarda renderizar)
            try:
                html = await _fetch_with_playwright(
                    source_link,
                    wait_for_selector="#lmt-match-preview .sr-lmt-plus-scb__result",
                    wait_time=4000,
                    selector_timeout=PLAYWRIGHT_RESULT_TIMEOUT,
                )
            except Exception as e:
                logger.warning(
                    f"⚠️ Falha aguardando widget de resultado SportRadar para {ext_id}: {type(e).__name__}. Usando HTML da 1ª passada."
                )
        else:
            html = await _fetch_requests_async(source_link)
        result = scrape_game_result(html, ext_id)
        if result:
            logger.info(f"✅ Resultado encontrado via HTML: {result.get('outcome')} (placar: {result.get('score', 'N/A')})")
            # Salvar no cache
            result_cache.set(ext_id, result)
            return result
        else:
            logger.warning(f"⚠️ Resultado não encontrado no HTML para jogo {ext_id} — cacheado por TTL curto")
            negative_result_cache.set(ext_id, "_not_found_")
    except Exception as e:
        from utils.error_handler import log_error_with_context
        log_error_with_context(
            e,
            context={
                "ext_id": ext_id,
                "source_link": source_link,
                "stage": "fetch_game_result"
            },
            level="error",
            reraise=False
        )

    return None


async def fetch_game_full_markets(ext_id: str, game_url: Optional[str] = None) -> dict:
    """
    Busca markets completos de um jogo (todos os mercados disponíveis).

    Tenta primeiro XHR (fetch_event_odds_from_api_async → parse_event_odds_from_api).
    Cai pra HTML scraping (scrape_live_game_data) se XHR falhar ou vier sem markets.

    Args:
        ext_id: ID do jogo no BetNacional (string, pode conter dígitos)
        game_url: URL completa do jogo (usada no fallback HTML)

    Returns:
        dict {"stats": {...}, "markets": {...}}.
        Se ambos os caminhos falharem, retorna {"stats": {}, "markets": {}}.
    """
    from scraping.betnacional import (
        fetch_event_odds_from_api_async,
        parse_event_odds_from_api,
        scrape_live_game_data,
    )

    # XHR primary path (rate limiter + retry handled inside fetch_event_odds_from_api_async)
    try:
        ext_id_int = int(ext_id)
        json_data = await fetch_event_odds_from_api_async(ext_id_int)
        if json_data:
            data = parse_event_odds_from_api(json_data)
            markets = data.get("markets", {}) if isinstance(data, dict) else {}
            if markets and (markets.get("match_result") or markets.get("total_goals")):
                return data
            logger.debug(
                f"XHR retornou sem mercados relevantes pra ext_id={ext_id}; tentando fallback HTML"
            )
    except (TypeError, ValueError) as e:
        logger.debug(f"ext_id={ext_id} não conversível pra int: {e}")
    except Exception as e:
        logger.debug(f"XHR fetch falhou pra ext_id={ext_id}: {e}")

    # HTML scraping fallback
    if not game_url:
        logger.debug(f"Sem game_url pra fallback HTML em ext_id={ext_id}")
        return {"stats": {}, "markets": {}}

    try:
        html = await _fetch_requests_async(game_url, has_fallback=False)
        if html:
            data = scrape_live_game_data(html, ext_id, source_url=game_url)
            return {
                "stats": data.get("stats", {}) if isinstance(data, dict) else {},
                "markets": data.get("markets", {}) if isinstance(data, dict) else {},
            }
    except Exception as e:
        logger.debug(f"HTML fetch falhou pra ext_id={ext_id}: {e}")

    return {"stats": {}, "markets": {}}


async def fetch_events_via_api(
    sport_id: int = 1,
    category_id: int = 0,
    tournament_id: int = 0,
    market_id: int = 1,
) -> list:
    """
    Busca eventos via Playwright capturando a resposta XHR interna da BetNacional.

    Cloudflare bloqueia requests Python direto de IPs datacenter (mesmo com cookies),
    mas permite o XHR quando ele é disparado pelo contexto da página real. Por isso,
    navegamos via Playwright e interceptamos a resposta `events-by-seasons`.

    Args:
        sport_id: ID do esporte (1 = futebol)
        category_id: ID da categoria (0 = todas)
        tournament_id: ID do torneio (0 = todos)
        market_id: ignorado (a página decide o que pedir)

    Returns:
        list[EventDigest] agrupado por event_id, com 1x2 já extraído.
    """
    from scraping.betnacional import parse_events_from_api_json
    from playwright.async_api import async_playwright

    page_url = (
        f"https://betnacional.bet.br/events/{sport_id}/{category_id}/{tournament_id}"
    )
    UA = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )

    captured: list = []

    async def _on_response(resp):
        if "events-by-seasons" not in resp.url:
            return
        if resp.status != 200:
            return
        try:
            body = await resp.json()
            if isinstance(body, dict) and (body.get("odds") or body.get("scores")):
                captured.append(body)
        except Exception:
            pass

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            ctx = await browser.new_context(user_agent=UA, locale="pt-BR")
            page = await ctx.new_page()
            page.on("response", lambda r: asyncio.create_task(_on_response(r)))
            await page.goto(page_url, wait_until="networkidle", timeout=45000)
            await page.wait_for_timeout(4000)
            await browser.close()
    except Exception as exc:
        logger.exception(f"API fetch (Playwright XHR capture) falhou: {exc}")
        return []

    if not captured:
        logger.warning(
            f"API fetch: nenhuma resposta events-by-seasons capturada "
            f"(sport={sport_id}, cat={category_id}, tour={tournament_id})"
        )
        return []

    # Merge respostas se houver múltiplas
    merged_odds, merged_scores = [], []
    for body in captured:
        merged_odds.extend(body.get("odds", []))
        merged_scores.extend(body.get("scores", []))
    merged = {"odds": merged_odds, "outrights": [], "scores": merged_scores}

    events = parse_events_from_api_json(merged, source_link=page_url)
    logger.info(
        f"API fetch: {len(events)} eventos extraídos via Playwright XHR capture "
        f"(sport={sport_id}, cat={category_id}, tour={tournament_id})"
    )
    return events
