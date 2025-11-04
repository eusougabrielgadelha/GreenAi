"""Funções de fetch de páginas web."""
import asyncio
import requests
from typing import Optional
from config.settings import (
    HAS_PLAYWRIGHT, SCRAPE_BACKEND, REQUESTS_TIMEOUT, USER_AGENT
)
from utils.logger import logger
from scraping.betnacional import try_parse_events

HEADERS = {"User-Agent": USER_AGENT}


def fetch_requests(url: str) -> str:
    """Baixa uma página usando requests (síncrono)."""
    r = requests.get(url, headers=HEADERS, timeout=REQUESTS_TIMEOUT)
    r.raise_for_status()
    return r.text


async def _fetch_requests_async(url: str) -> str:
    """Wrapper assíncrono para não travar o loop ao usar requests."""
    return await asyncio.to_thread(fetch_requests, url)


async def fetch_playwright(url: str) -> str:
    """Baixa uma página usando Playwright (assíncrono)."""
    if not HAS_PLAYWRIGHT:
        raise RuntimeError("Playwright não disponível.")
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(user_agent=USER_AGENT)
        await page.goto(url, wait_until="networkidle", timeout=60_000)
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
            await page.goto(url, wait_until="networkidle", timeout=60000)
            
            # Aguarda seletor específico se fornecido
            if wait_for_selector:
                try:
                    await page.wait_for_selector(wait_for_selector, timeout=15000)
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
    Baixa a página (via requests ou playwright) e parseia os eventos.
    Tenta o backend escolhido; se falhar ou vier vazio, tenta o outro.
    """
    from utils.analytics_logger import log_extraction
    
    def _other(b: str) -> str:
        return "requests" if b == "playwright" else "playwright"

    backend_sel = backend if backend != "auto" else _backend_auto()
    logger.info("🔎 Varredura iniciada para %s — backend=%s", url, backend_sel)

    for attempt, b in enumerate([backend_sel, _other(backend_sel)]):
        try:
            if b == "playwright":
                html = await _fetch_with_playwright(url)
            else:
                html = await _fetch_requests_async(url)
            evs = try_parse_events(html, url)
            if evs:
                log_extraction(url, len(evs), b, success=True, metadata={"attempt": attempt + 1})
                return evs
            logger.info("Nenhum evento com backend=%s; tentando fallback…", b)
        except Exception as e:
            error_msg = str(e)[:500]  # Limita tamanho
            logger.warning("Falha ao buscar %s com %s (tentativa %d): %s", url, b, attempt+1, e)
            if attempt == 1:  # Última tentativa falhou
                log_extraction(url, 0, b, success=False, error=error_msg, metadata={"attempt": attempt + 1})

    log_extraction(url, 0, backend_sel, success=False, error="Nenhum evento encontrado após todas as tentativas")
    return []


async def fetch_game_result(ext_id: str, source_link: str) -> Optional[str]:
    """Busca o resultado de um jogo específico."""
    from scraping.betnacional import scrape_game_result
    
    try:
        html = await _fetch_with_playwright(source_link) if HAS_PLAYWRIGHT else await _fetch_requests_async(source_link)
        return scrape_game_result(html, ext_id)
    except Exception as e:
        logger.exception("Erro ao buscar resultado do jogo %s: %s", ext_id, e)
        return None

