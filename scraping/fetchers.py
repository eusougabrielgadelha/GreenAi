"""Funções de fetch de páginas web."""
import asyncio
import requests
from typing import Optional
from config.settings import (
    HAS_PLAYWRIGHT, SCRAPE_BACKEND, REQUESTS_TIMEOUT, HTML_TIMEOUT, USER_AGENT,
    PLAYWRIGHT_NAVIGATION_TIMEOUT, PLAYWRIGHT_SELECTOR_TIMEOUT, PLAYWRIGHT_NETWORKIDLE_TIMEOUT
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


async def _fetch_with_playwright(url: str, wait_for_selector: str = None, wait_time: int = 3000) -> str:
    """
    Renderiza a página com Playwright e retorna o HTML.
    
    Args:
        url: URL para buscar
        wait_for_selector: Seletor CSS para aguardar (opcional)
        wait_time: Tempo adicional em ms para aguardar após carregamento (padrão: 3000ms)
    """
    if not HAS_PLAYWRIGHT:
        raise RuntimeError("Playwright não disponível no ambiente.")
    from playwright.async_api import async_playwright
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
                    await page.wait_for_selector(wait_for_selector, timeout=PLAYWRIGHT_SELECTOR_TIMEOUT)
                except:
                    pass  # Continua mesmo se não encontrar
            
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
    Prioriza API XHR (mais eficiente), depois fallback para HTML scraping.
    """
    from utils.analytics_logger import log_extraction
    from scraping.betnacional import (
        extract_ids_from_url, fetch_events_from_api_async, 
        parse_events_from_api, try_parse_events
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
    
    # ETAPA 1: Tentar API XHR primeiro (mais eficiente) - APENAS SE NÃO ESTIVER DESABILITADO
    from utils.xhr_status import is_xhr_disabled, disable_xhr
    
    if not is_xhr_disabled():
        ids = extract_ids_from_url(url)
        if ids:
            sport_id, category_id, tournament_id = ids
            log_with_context(
                "info",
                f"Tentando buscar via API XHR (sport_id={sport_id}, category_id={category_id}, tournament_id={tournament_id})",
                url=url,
                stage="api_xhr",
                status="attempting",
                extra_fields={
                    "sport_id": sport_id,
                    "category_id": category_id,
                    "tournament_id": tournament_id
                }
            )
            
            try:
                json_data = await fetch_events_from_api_async(sport_id, category_id, tournament_id)
                if json_data:
                    evs = parse_events_from_api(json_data, url)
                    if evs:
                        log_extraction(url, len(evs), "api_xhr", success=True, metadata={"method": "api"})
                        log_with_context(
                            "info",
                            f"Eventos extraídos via API XHR: {len(evs)} eventos",
                            url=url,
                            stage="api_xhr",
                            status="success",
                            extra_fields={"events_count": len(evs), "method": "api"}
                        )
                        return evs
                    logger.info("API retornou dados mas nenhum evento válido encontrado")
                else:
                    # API não retornou dados - desabilitar XHR permanentemente
                    disable_xhr("API não retornou dados")
                    logger.info("API não retornou dados, desabilitando XHR e usando HTML scraping...")
            except Exception as e:
                # API falhou - desabilitar XHR permanentemente
                disable_xhr(f"Erro na API: {type(e).__name__}")
                from utils.error_handler import log_error_with_context
                log_error_with_context(
                    e,
                    context={
                        "url": url,
                        "sport_id": sport_id,
                        "category_id": category_id,
                        "tournament_id": tournament_id,
                        "stage": "api_xhr"
                    },
                    level="warning",
                    reraise=False
                )
                logger.info("Erro na API, desabilitando XHR e usando HTML scraping...")
    else:
        # XHR já está desabilitado - pular direto para HTML scraping
        logger.debug("XHR desabilitado, usando HTML scraping diretamente")
    
    # ETAPA 2: Fallback para HTML scraping
    backend_sel = backend if backend != "auto" else _backend_auto()
    logger.info("🌐 Fallback para HTML scraping — backend=%s", backend_sel)

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


async def fetch_game_result(ext_id: str, source_link: str) -> Optional[str]:
    """
    Busca o resultado de um jogo específico.
    
    Usa cache para evitar múltiplas requisições para o mesmo jogo.
    Tenta primeiro via API XHR (se disponível), depois fallback para HTML scraping.
    
    Args:
        ext_id: ID externo do jogo (event_id)
        source_link: URL do jogo
    
    Returns:
        "home", "draw", ou "away" se encontrou resultado, None caso contrário
    """
    from scraping.betnacional import (
        scrape_game_result, extract_event_id_from_url,
        fetch_event_odds_from_api, parse_event_odds_from_api
    )
    from utils.cache import result_cache
    
    # ETAPA 0: Verificar cache primeiro
    cached_result = result_cache.get(ext_id)
    if cached_result:
        logger.info(f"✅ Resultado encontrado no cache para jogo {ext_id}: {cached_result}")
        return cached_result
    
    # ETAPA 1: Tentar buscar via API XHR primeiro - APENAS SE NÃO ESTIVER DESABILITADO
    from utils.xhr_status import is_xhr_disabled, disable_xhr
    
    if not is_xhr_disabled():
        event_id = None
        try:
            # Tentar extrair event_id da URL
            if source_link:
                event_id = extract_event_id_from_url(source_link)
            # Se não conseguir, tentar usar ext_id diretamente
            if not event_id and ext_id:
                try:
                    event_id = int(ext_id)
                except (ValueError, TypeError):
                    pass
            
            if event_id:
                logger.info(f"📡 Tentando buscar resultado via API para evento {event_id}")
                try:
                    json_data = fetch_event_odds_from_api(event_id)
                    if json_data:
                        # Verificar se conseguimos extrair resultado da API
                        events = json_data.get('events', [])
                        if events:
                            event = events[0]
                            event_status_id = event.get('event_status_id', 0)
                            
                            # event_status_id: 0 = agendado, 1 = ao vivo, 2 = finalizado
                            if event_status_id == 2:
                                # Jogo terminado - tentar extrair resultado
                                # Verificar se há informações de resultado no evento
                                # Por enquanto, a API não retorna resultado diretamente,
                                # mas podemos verificar se há placar ou outras informações
                                # Se não encontrar, fazer fallback para HTML scraping
                                logger.debug(f"API indica que jogo {event_id} terminou (status_id=2), mas resultado não disponível na API. Tentando HTML...")
                            elif event_status_id == 1:
                                logger.debug(f"Jogo {event_id} ainda está ao vivo (status_id=1). Não é possível obter resultado ainda.")
                                return None
                            else:
                                logger.debug(f"Jogo {event_id} ainda não começou (status_id={event_status_id}). Não é possível obter resultado ainda.")
                                return None
                        else:
                            # API não retornou eventos - desabilitar XHR
                            disable_xhr("API não retornou eventos para resultado")
                    else:
                        # API não retornou dados - desabilitar XHR
                        disable_xhr("API não retornou dados para resultado")
                except Exception as e:
                    # API falhou - desabilitar XHR
                    disable_xhr(f"Erro na API ao buscar resultado: {type(e).__name__}")
                    logger.debug(f"Erro ao buscar resultado via API: {e}. Desabilitando XHR e usando HTML scraping...")
        except Exception as e:
            logger.debug(f"Erro ao processar API: {e}. Tentando HTML scraping...")
    else:
        logger.debug("XHR desabilitado, usando HTML scraping diretamente para resultado")
    
    # ETAPA 2: Fallback para HTML scraping
    try:
        logger.debug(f"🌐 Buscando resultado via HTML scraping para jogo {ext_id}")
        html = await _fetch_with_playwright(source_link) if HAS_PLAYWRIGHT else await _fetch_requests_async(source_link)
        result = scrape_game_result(html, ext_id)
        if result:
            logger.info(f"✅ Resultado encontrado via HTML: {result}")
            # Salvar no cache
            result_cache.set(ext_id, result)
            return result
        else:
            logger.warning(f"⚠️ Resultado não encontrado no HTML para jogo {ext_id}")
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

