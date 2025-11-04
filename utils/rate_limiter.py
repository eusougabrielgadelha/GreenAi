"""
Sistema de rate limiting e retry com backoff exponencial.
"""
import asyncio
from time import time
from typing import Optional, Callable, Any
from functools import wraps
from utils.logger import logger


class RateLimiter:
    """
    Rate limiter para controlar número de requisições por janela de tempo.
    
    Evita fazer muitas requisições simultâneas que podem causar 403 errors.
    """
    
    def __init__(self, max_requests: int = 10, window_seconds: int = 60):
        """
        Inicializa o rate limiter.
        
        Args:
            max_requests: Número máximo de requisições por janela
            window_seconds: Tamanho da janela em segundos
        """
        self.max_requests = max_requests
        self.window = window_seconds
        self.requests: list = []
        self._lock = asyncio.Lock()
        self.stats = {
            'total_waits': 0,
            'total_wait_time': 0.0
        }
    
    async def acquire(self):
        """
        Aguarda até que seja possível fazer uma requisição dentro do limite.
        
        Remove requisições antigas da janela e espera se necessário.
        """
        async with self._lock:
            now = time()
            
            # Remove requisições antigas (fora da janela)
            self.requests = [r for r in self.requests if now - r < self.window]
            
            # Se já atingiu o limite, calcular tempo de espera
            if len(self.requests) >= self.max_requests:
                # Calcular quanto tempo falta para a requisição mais antiga sair da janela
                oldest_request = min(self.requests)
                sleep_time = self.window - (now - oldest_request) + 0.1  # +0.1s para margem
                
                if sleep_time > 0:
                    logger.debug(
                        f"⏳ Rate limit atingido ({len(self.requests)}/{self.max_requests}). "
                        f"Aguardando {sleep_time:.1f}s..."
                    )
                    
                    self.stats['total_waits'] += 1
                    self.stats['total_wait_time'] += sleep_time
                    
                    await asyncio.sleep(sleep_time)
                    
                    # Recalcular após espera
                    now = time()
                    self.requests = [r for r in self.requests if now - r < self.window]
            
            # Registrar nova requisição
            self.requests.append(now)
    
    def get_stats(self) -> dict:
        """
        Retorna estatísticas do rate limiter.
        
        Returns:
            Dict com estatísticas (total_waits, total_wait_time, current_requests)
        """
        async def _get_stats():
            async with self._lock:
                now = time()
                self.requests = [r for r in self.requests if now - r < self.window]
                return {
                    'total_waits': self.stats['total_waits'],
                    'total_wait_time': self.stats['total_wait_time'],
                    'current_requests': len(self.requests),
                    'max_requests': self.max_requests,
                    'window_seconds': self.window
                }
        
        # Para uso síncrono, retornar stats atuais
        return {
            'total_waits': self.stats['total_waits'],
            'total_wait_time': self.stats['total_wait_time'],
            'current_requests': len([r for r in self.requests if time() - r < self.window]),
            'max_requests': self.max_requests,
            'window_seconds': self.window
        }


async def retry_with_backoff(
    func: Callable,
    max_retries: int = 3,
    initial_delay: float = 1.0,
    max_delay: float = 60.0,
    exponential_base: float = 2.0,
    exceptions: tuple = (Exception,),
    rate_limiter: Optional[RateLimiter] = None
) -> Any:
    """
    Executa uma função com retry e backoff exponencial.
    
    Args:
        func: Função a executar (pode ser async ou sync)
        max_retries: Número máximo de tentativas
        initial_delay: Delay inicial em segundos
        max_delay: Delay máximo em segundos
        exponential_base: Base para cálculo exponencial (padrão: 2.0)
        exceptions: Tupla de exceções que devem triggerar retry
        rate_limiter: Rate limiter opcional para usar antes de cada tentativa
    
    Returns:
        Resultado da função
    
    Raises:
        A última exceção se todas as tentativas falharem
    """
    delay = initial_delay
    last_exception = None
    
    for attempt in range(max_retries):
        try:
            # Usar rate limiter se fornecido
            if rate_limiter:
                await rate_limiter.acquire()
            
            # Executar função (async ou sync)
            if asyncio.iscoroutinefunction(func):
                return await func()
            else:
                return func()
                
        except exceptions as e:
            last_exception = e
            
            if attempt < max_retries - 1:
                error_msg = str(e)[:200]  # Limitar tamanho
                logger.warning(
                    f"⚠️ Tentativa {attempt + 1}/{max_retries} falhou: {error_msg}. "
                    f"Tentando novamente em {delay:.1f}s..."
                )
                
                await asyncio.sleep(delay)
                
                # Calcular próximo delay (backoff exponencial)
                delay = min(delay * exponential_base, max_delay)
            else:
                # Última tentativa falhou
                logger.error(f"❌ Todas as {max_retries} tentativas falharam. Último erro: {e}")
                raise
    
    # Se chegou aqui, todas as tentativas falharam
    if last_exception:
        raise last_exception
    raise Exception("Número máximo de tentativas excedido")


def with_retry(
    max_retries: int = 3,
    initial_delay: float = 1.0,
    max_delay: float = 60.0,
    exponential_base: float = 2.0,
    exceptions: tuple = (Exception,),
    rate_limiter: Optional[RateLimiter] = None
):
    """
    Decorator para adicionar retry com backoff exponencial a uma função.
    
    Args:
        max_retries: Número máximo de tentativas
        initial_delay: Delay inicial em segundos
        max_delay: Delay máximo em segundos
        exponential_base: Base para cálculo exponencial
        exceptions: Tupla de exceções que devem triggerar retry
        rate_limiter: Rate limiter opcional
    
    Exemplo:
        @with_retry(max_retries=3, initial_delay=2.0)
        async def fetch_data():
            # código que pode falhar
            pass
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            async def _func():
                if asyncio.iscoroutinefunction(func):
                    return await func(*args, **kwargs)
                else:
                    return func(*args, **kwargs)
            
            return await retry_with_backoff(
                _func,
                max_retries=max_retries,
                initial_delay=initial_delay,
                max_delay=max_delay,
                exponential_base=exponential_base,
                exceptions=exceptions,
                rate_limiter=rate_limiter
            )
        return wrapper
    return decorator


# Instâncias globais de rate limiters
# Para API XHR: 8 requisições por minuto (mais conservador para evitar bloqueios)
api_rate_limiter = RateLimiter(max_requests=8, window_seconds=60)

# Para HTML scraping: 3 requisições por minuto (muito conservador)
html_rate_limiter = RateLimiter(max_requests=3, window_seconds=60)

