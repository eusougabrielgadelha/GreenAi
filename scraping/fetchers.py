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

