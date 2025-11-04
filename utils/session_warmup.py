"""
Sistema de warm-up de sessão para melhorar taxa de sucesso da API.
Visita a página HTML primeiro para criar cookies/sessão antes de tentar API.
"""
import asyncio
from typing import Optional
from utils.logger import logger
from scraping.fetchers import _fetch_with_playwright, _fetch_requests_async
from config.settings import HAS_PLAYWRIGHT
from utils.cookie_manager import get_cookie_manager


async def warmup_session_for_api(base_url: str = "https://betnacional.bet.br/") -> bool:
    """
    Faz warm-up da sessão visitando a página principal antes de tentar API.
    
    Isso ajuda a criar cookies e estabelecer uma sessão válida.
    
    Args:
        base_url: URL base para visitar (padrão: página principal)
    
    Returns:
        True se warm-up foi bem-sucedido
    """
    try:
        logger.debug(f"Fazendo warm-up de sessão visitando {base_url}")
        
        # Visitar página principal para criar cookies/sessão
        if HAS_PLAYWRIGHT:
            html = await _fetch_with_playwright(base_url)
        else:
            html = await _fetch_requests_async(base_url)
        
        if html and len(html) > 1000:  # Verificar se obteve conteúdo válido
            logger.debug(f"Warm-up bem-sucedido: {len(html)} bytes obtidos")
            
            # Verificar se cookies foram criados
            manager = get_cookie_manager()
            stats = manager.get_stats()
            if stats['total_cookies'] > 0:
                logger.debug(f"Cookies criados durante warm-up: {stats['total_cookies']}")
            
            return True
        else:
            logger.debug("Warm-up retornou conteúdo inválido")
            return False
            
    except Exception as e:
        logger.debug(f"Erro durante warm-up de sessão: {e}")
        return False


async def warmup_session_if_needed() -> bool:
    """
    Faz warm-up de sessão se necessário (sem cookies ou cookies expirados).
    
    Returns:
        True se warm-up foi feito, False caso contrário
    """
    manager = get_cookie_manager()
    stats = manager.get_stats()
    
    # Se não há cookies válidos, fazer warm-up
    if stats['valid_cookies'] == 0:
        logger.debug("Nenhum cookie válido encontrado, fazendo warm-up...")
        return await warmup_session_for_api()
    
    return False

