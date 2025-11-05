"""
Sistema de rate limiting para mensagens do Telegram.
Previne spam e melhora a experiência do usuário.
"""
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from collections import deque
import pytz
from utils.logger import logger
from models.database import SessionLocal, Stat


class TelegramRateLimiter:
    """
    Sistema de rate limiting para mensagens do Telegram.
    Limita quantidade de mensagens por janela de tempo.
    """
    
    def __init__(self):
        # Histórico de mensagens enviadas (timestamp)
        self._message_history: deque = deque(maxlen=1000)  # Mantém últimas 1000 mensagens
        
        # Limites padrão (configuráveis via env)
        self._max_per_minute = int(os.getenv("TELEGRAM_MAX_PER_MINUTE", "5"))  # Max 5 mensagens/min
        self._max_per_hour = int(os.getenv("TELEGRAM_MAX_PER_HOUR", "30"))  # Max 30 mensagens/hora
        self._min_interval_seconds = float(os.getenv("TELEGRAM_MIN_INTERVAL", "10"))  # Min 10s entre mensagens
        
        # Cooldown por tipo de mensagem
        self._type_cooldowns: Dict[str, datetime] = {}
        self._type_cooldown_minutes = {
            "live_opportunity": 8,  # 8 minutos entre oportunidades ao vivo
            "reminder": 5,  # 5 minutos entre lembretes
            "watch_upgrade": 3,  # 3 minutos entre upgrades
            "pick_now": 2,  # 2 minutos entre picks
            "summary": 30,  # 30 minutos entre resumos
            "results_batch": 5,  # 5 minutos entre batches de resultados
        }
        
        # Carrega configurações do banco
        self._load_config()
    
    def _load_config(self):
        """Carrega configurações persistentes do banco de dados."""
        try:
            with SessionLocal() as session:
                from watchlist.manager import stat_get
                
                # Carrega cooldowns por tipo
                for msg_type in self._type_cooldown_minutes.keys():
                    key = f"telegram_cooldown_{msg_type}"
                    last_sent_str = stat_get(session, key, None)
                    if last_sent_str:
                        try:
                            self._type_cooldowns[msg_type] = datetime.fromisoformat(last_sent_str)
                        except Exception:
                            pass
        except Exception as e:
            logger.debug(f"Erro ao carregar configurações de rate limiter: {e}")
    
    def _save_cooldown(self, message_type: str, timestamp: datetime):
        """Salva cooldown no banco de dados."""
        try:
            with SessionLocal() as session:
                from watchlist.manager import stat_set
                key = f"telegram_cooldown_{message_type}"
                stat_set(session, key, timestamp.isoformat())
        except Exception as e:
            logger.debug(f"Erro ao salvar cooldown de {message_type}: {e}")
    
    def can_send(self, message_type: Optional[str] = None) -> tuple[bool, str]:
        """
        Verifica se pode enviar uma mensagem agora.
        
        Args:
            message_type: Tipo da mensagem (opcional)
            
        Returns:
            Tuple (can_send: bool, reason: str)
        """
        now = datetime.now(pytz.UTC)
        
        # 1. Verificar intervalo mínimo entre qualquer mensagem
        if self._message_history:
            last_sent = self._message_history[-1]
            elapsed = (now - last_sent).total_seconds()
            if elapsed < self._min_interval_seconds:
                remaining = self._min_interval_seconds - elapsed
                return False, f"Aguarde {remaining:.1f}s (intervalo mínimo entre mensagens)"
        
        # 2. Verificar limite por minuto
        one_min_ago = now - timedelta(minutes=1)
        recent_count = sum(1 for ts in self._message_history if ts >= one_min_ago)
        if recent_count >= self._max_per_minute:
            return False, f"Limite de {self._max_per_minute} mensagens/minuto atingido"
        
        # 3. Verificar limite por hora
        one_hour_ago = now - timedelta(hours=1)
        hourly_count = sum(1 for ts in self._message_history if ts >= one_hour_ago)
        if hourly_count >= self._max_per_hour:
            return False, f"Limite de {self._max_per_hour} mensagens/hora atingido"
        
        # 4. Verificar cooldown específico por tipo
        if message_type:
            cooldown_min = self._type_cooldown_minutes.get(message_type)
            if cooldown_min:
                last_sent = self._type_cooldowns.get(message_type)
                if last_sent:
                    elapsed_min = (now - last_sent).total_seconds() / 60
                    if elapsed_min < cooldown_min:
                        remaining = cooldown_min - elapsed_min
                        return False, f"Cooldown de {message_type}: aguarde {remaining:.1f}min"
        
        return True, "OK"
    
    def record_sent(self, message_type: Optional[str] = None):
        """
        Registra que uma mensagem foi enviada.
        
        Args:
            message_type: Tipo da mensagem enviada
        """
        now = datetime.now(pytz.UTC)
        self._message_history.append(now)
        
        if message_type:
            self._type_cooldowns[message_type] = now
            self._save_cooldown(message_type, now)
    
    def get_stats(self) -> Dict[str, any]:
        """
        Retorna estatísticas do rate limiter.
        
        Returns:
            Dict com estatísticas
        """
        now = datetime.now(pytz.UTC)
        one_min_ago = now - timedelta(minutes=1)
        one_hour_ago = now - timedelta(hours=1)
        
        return {
            "total_messages": len(self._message_history),
            "messages_last_minute": sum(1 for ts in self._message_history if ts >= one_min_ago),
            "messages_last_hour": sum(1 for ts in self._message_history if ts >= one_hour_ago),
            "max_per_minute": self._max_per_minute,
            "max_per_hour": self._max_per_hour,
            "min_interval_seconds": self._min_interval_seconds,
            "active_cooldowns": {
                k: (now - v).total_seconds() / 60 
                for k, v in self._type_cooldowns.items() 
                if v > now - timedelta(hours=1)
            }
        }


# Instância global
_rate_limiter = TelegramRateLimiter()


def check_rate_limit(message_type: Optional[str] = None) -> tuple[bool, str]:
    """
    Verifica se pode enviar mensagem (rate limiting).
    
    Args:
        message_type: Tipo da mensagem
        
    Returns:
        Tuple (can_send: bool, reason: str)
    """
    return _rate_limiter.can_send(message_type)


def record_message_sent(message_type: Optional[str] = None):
    """
    Registra que uma mensagem foi enviada.
    
    Args:
        message_type: Tipo da mensagem
    """
    _rate_limiter.record_sent(message_type)


def get_rate_limit_stats() -> Dict[str, any]:
    """
    Retorna estatísticas do rate limiter.
    
    Returns:
        Dict com estatísticas
    """
    return _rate_limiter.get_stats()

