"""
Gerenciador de status do XHR API.
Controla se o XHR deve ser usado ou se deve usar apenas HTML scraping.

Quando o XHR falha, ele é desabilitado permanentemente até o script ser reiniciado.
"""
from typing import Optional
from utils.logger import logger

# Flag global: True = XHR desabilitado (usar apenas HTML), False = XHR habilitado
_xhr_disabled: bool = False


def is_xhr_disabled() -> bool:
    """
    Verifica se o XHR está desabilitado.
    
    Returns:
        True se XHR está desabilitado (deve usar apenas HTML scraping)
        False se XHR está habilitado (pode tentar usar XHR)
    """
    return _xhr_disabled


def disable_xhr(reason: Optional[str] = None):
    """
    Desabilita o XHR permanentemente até o script ser reiniciado.
    
    Args:
        reason: Motivo da desabilitação (opcional, para logs)
    """
    global _xhr_disabled
    
    if not _xhr_disabled:
        _xhr_disabled = True
        reason_msg = f" - {reason}" if reason else ""
        logger.warning(f"XHR API desabilitado permanentemente até reiniciar o script{reason_msg}")
        logger.info("Sistema agora usará apenas HTML scraping (método 1)")


def enable_xhr():
    """
    Habilita o XHR novamente.
    
    Nota: Esta função geralmente não é chamada durante a execução normal.
    O XHR só é reabilitado quando o script é reiniciado (módulo recarregado).
    """
    global _xhr_disabled
    
    if _xhr_disabled:
        _xhr_disabled = False
        logger.info("XHR API reabilitado")


def get_xhr_status() -> dict:
    """
    Retorna o status atual do XHR para diagnóstico.
    
    Returns:
        Dict com informações de status
    """
    return {
        'disabled': _xhr_disabled,
        'using_html_only': _xhr_disabled,
        'will_retry_xhr': not _xhr_disabled
    }

