"""
Sistema de tratamento de erros com contexto detalhado.
"""
import traceback
from typing import Any, Optional, Dict
from functools import wraps
from utils.logger import logger


def log_error_with_context(
    error: Exception,
    context: Optional[Dict[str, Any]] = None,
    level: str = "error",
    reraise: bool = False
) -> None:
    """
    Loga um erro com contexto detalhado.
    
    Args:
        error: Exceção que ocorreu
        context: Dict com informações de contexto (url, ext_id, etc)
        level: Nível do log (error, warning, critical)
        reraise: Se True, re-levanta a exceção após logar
    """
    context = context or {}
    
    # Informações básicas do erro
    error_info = {
        "error_type": type(error).__name__,
        "error_message": str(error)[:500],  # Limitar tamanho
        "traceback": traceback.format_exc()
    }
    
    # Combinar com contexto fornecido
    full_context = {**context, **error_info}
    
    # Construir mensagem
    base_msg = f"Erro: {error_info['error_type']}"
    if context:
        context_str = ", ".join([f"{k}={v}" for k, v in context.items() if v])
        base_msg += f" | Contexto: {context_str}"
    
    # Logar com nível apropriado
    if level == "critical":
        logger.critical(base_msg, extra=full_context)
    elif level == "warning":
        logger.warning(base_msg, extra=full_context)
    else:
        logger.error(base_msg, extra=full_context)
    
    # Logar traceback completo apenas em nível error ou critical
    if level in ["error", "critical"]:
        logger.debug(f"Traceback completo:\n{error_info['traceback']}")
    
    # Re-levantar se solicitado
    if reraise:
        raise


def with_error_context(**default_context):
    """
    Decorator para adicionar contexto de erro automaticamente.
    
    Args:
        **default_context: Contexto padrão a ser incluído em todos os erros
    
    Exemplo:
        @with_error_context(module="scraping", function="fetch_data")
        async def fetch_data(url: str):
            # código que pode falhar
            pass
    """
    def decorator(func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            context = dict(default_context)
            context["function"] = func.__name__
            context["args_count"] = len(args)
            context["kwargs_keys"] = list(kwargs.keys())
            
            # Tentar extrair informações úteis dos argumentos
            if args:
                # Se primeiro arg é string (pode ser URL ou ext_id)
                if isinstance(args[0], str):
                    if args[0].startswith("http"):
                        context["url"] = args[0]
                    else:
                        context["ext_id"] = args[0]
            
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                log_error_with_context(e, context=context, reraise=True)
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            context = dict(default_context)
            context["function"] = func.__name__
            context["args_count"] = len(args)
            context["kwargs_keys"] = list(kwargs.keys())
            
            # Tentar extrair informações úteis dos argumentos
            if args:
                if isinstance(args[0], str):
                    if args[0].startswith("http"):
                        context["url"] = args[0]
                    else:
                        context["ext_id"] = args[0]
            
            try:
                return func(*args, **kwargs)
            except Exception as e:
                log_error_with_context(e, context=context, reraise=True)
        
        # Retornar wrapper apropriado
        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
    
    return decorator


def safe_execute(func, *args, context: Optional[Dict[str, Any]] = None, 
                 default_return=None, **kwargs):
    """
    Executa uma função de forma segura, logando erros com contexto.
    
    Args:
        func: Função a executar
        *args: Argumentos posicionais
        context: Contexto adicional para logs
        default_return: Valor a retornar em caso de erro
        **kwargs: Argumentos nomeados
    
    Returns:
        Resultado da função ou default_return se erro
    """
    try:
        return func(*args, **kwargs)
    except Exception as e:
        error_context = context or {}
        error_context["function"] = func.__name__
        log_error_with_context(e, context=error_context, level="error", reraise=False)
        return default_return


async def safe_execute_async(func, *args, context: Optional[Dict[str, Any]] = None,
                             default_return=None, **kwargs):
    """
    Executa uma função assíncrona de forma segura, logando erros com contexto.
    
    Args:
        func: Função async a executar
        *args: Argumentos posicionais
        context: Contexto adicional para logs
        default_return: Valor a retornar em caso de erro
        **kwargs: Argumentos nomeados
    
    Returns:
        Resultado da função ou default_return se erro
    """
    try:
        return await func(*args, **kwargs)
    except Exception as e:
        error_context = context or {}
        error_context["function"] = func.__name__
        log_error_with_context(e, context=error_context, level="error", reraise=False)
        return default_return

