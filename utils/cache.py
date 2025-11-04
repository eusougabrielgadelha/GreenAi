"""
Sistema de cache para resultados de jogos e outros dados.
"""
from datetime import datetime, timedelta
from typing import Optional, Dict, Tuple, Any
import threading
from utils.logger import logger


class ResultCache:
    """
    Cache em memória para resultados de jogos.
    
    Armazena resultados com TTL (Time To Live) para evitar
    múltiplas requisições para o mesmo jogo.
    """
    
    def __init__(self, ttl_minutes: int = 120):
        """
        Inicializa o cache.
        
        Args:
            ttl_minutes: Tempo de vida do cache em minutos (padrão: 120 = 2 horas)
        """
        self.cache: Dict[str, Tuple[str, datetime]] = {}  # {ext_id: (result, timestamp)}
        self.ttl = timedelta(minutes=ttl_minutes)
        self._lock = threading.Lock()
        self.stats = {
            'hits': 0,
            'misses': 0,
            'expired': 0,
            'total_requests': 0
        }
    
    def get(self, ext_id: str) -> Optional[str]:
        """
        Obtém resultado do cache se disponível e válido.
        
        Args:
            ext_id: ID externo do jogo
        
        Returns:
            Resultado ("home", "draw", "away") se encontrado e válido, None caso contrário
        """
        with self._lock:
            self.stats['total_requests'] += 1
            
            if ext_id not in self.cache:
                self.stats['misses'] += 1
                logger.debug(f"Cache MISS para jogo {ext_id}")
                return None
            
            result, timestamp = self.cache[ext_id]
            now = datetime.now()
            
            # Verificar se expirou
            if now - timestamp > self.ttl:
                del self.cache[ext_id]
                self.stats['expired'] += 1
                self.stats['misses'] += 1
                logger.debug(f"Cache EXPIRADO para jogo {ext_id} (cacheado há {now - timestamp})")
                return None
            
            # Cache hit
            self.stats['hits'] += 1
            age = now - timestamp
            logger.debug(f"Cache HIT para jogo {ext_id}: {result} (cacheado há {age.total_seconds():.0f}s)")
            return result
    
    def set(self, ext_id: str, result: str):
        """
        Armazena resultado no cache.
        
        Args:
            ext_id: ID externo do jogo
            result: Resultado ("home", "draw", "away")
        """
        with self._lock:
            self.cache[ext_id] = (result, datetime.now())
            logger.debug(f"Resultado cacheado para jogo {ext_id}: {result}")
    
    def clear(self):
        """Limpa todo o cache."""
        with self._lock:
            count = len(self.cache)
            self.cache.clear()
            logger.info(f"Cache limpo: {count} entradas removidas")
    
    def clear_expired(self):
        """
        Remove apenas entradas expiradas do cache.
        
        Returns:
            Número de entradas removidas
        """
        with self._lock:
            now = datetime.now()
            expired_keys = [
                key for key, (_, timestamp) in self.cache.items()
                if now - timestamp > self.ttl
            ]
            
            for key in expired_keys:
                del self.cache[key]
            
            if expired_keys:
                logger.debug(f"Removidas {len(expired_keys)} entradas expiradas do cache")
            
            return len(expired_keys)
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Retorna estatísticas do cache.
        
        Returns:
            Dict com estatísticas (hits, misses, expired, total, size, hit_rate)
        """
        with self._lock:
            total = self.stats['total_requests']
            hits = self.stats['hits']
            hit_rate = (hits / total * 100) if total > 0 else 0.0
            
            return {
                'hits': hits,
                'misses': self.stats['misses'],
                'expired': self.stats['expired'],
                'total_requests': total,
                'size': len(self.cache),
                'hit_rate': hit_rate
            }
    
    def get_size(self) -> int:
        """Retorna o número de entradas no cache."""
        with self._lock:
            return len(self.cache)


# Instância global do cache de resultados
# TTL de 2 horas (120 minutos) - resultados de jogos não mudam após terminar
result_cache = ResultCache(ttl_minutes=120)

