"""Configuração de logging."""
import os
import json
import logging
from logging.handlers import RotatingFileHandler
from typing import Any, Dict, Optional
from config.settings import LOG_DIR

logger = logging.getLogger("betauto")
logger.setLevel(logging.INFO)


class StructuredFormatter(logging.Formatter):
    """
    Formatter que adiciona contexto estruturado aos logs.
    """
    def format(self, record: logging.LogRecord) -> str:
        # Formato básico
        base_msg = super().format(record)
        
        # Adicionar contexto estruturado se presente
        context = {}
        
        # Extrair campos de contexto do record.extra (atributos do LogRecord)
        # Python logging adiciona campos de 'extra' como atributos do record
        extra_fields = ['game_id', 'ext_id', 'url', 'duration_ms', 'status', 'stage', 
                       'backend', 'attempt', 'sport_id', 'category_id', 'tournament_id',
                       'events_count', 'method', 'outcome', 'hit', 'result_msg', 'games_count']
        
        for field in extra_fields:
            if hasattr(record, field):
                value = getattr(record, field)
                if value is not None:
                    context[field] = value
        
        # Adicionar outros campos dinâmicos (que não são atributos padrão do LogRecord)
        # Excluir atributos padrão do logging
        standard_attrs = {'name', 'msg', 'args', 'levelname', 'levelno', 'pathname', 'filename',
                         'module', 'lineno', 'funcName', 'created', 'msecs', 'relativeCreated',
                         'thread', 'threadName', 'processName', 'process', 'message', 'exc_info',
                         'exc_text', 'stack_info', 'getMessage'}
        
        for attr_name in dir(record):
            if not attr_name.startswith('_') and attr_name not in standard_attrs and attr_name not in extra_fields:
                try:
                    value = getattr(record, attr_name)
                    if value is not None and not callable(value):
                        context[attr_name] = value
                except AttributeError:
                    pass
        
        # Se houver contexto, adicionar ao log
        if context:
            context_str = " | ".join([f"{k}={v}" for k, v in sorted(context.items()) if v is not None])
            return f"{base_msg} | {context_str}"
        
        return base_msg


# Formatter padrão com suporte a contexto estruturado
_fmt = StructuredFormatter("%(asctime)s | %(levelname)s | %(message)s")

h_file = RotatingFileHandler(
    os.path.join(LOG_DIR, "betauto.log"),
    maxBytes=2_000_000,
    backupCount=5,
    encoding="utf-8"
)
h_file.setFormatter(_fmt)
h_file.setLevel(logging.INFO)

h_out = logging.StreamHandler()
h_out.setFormatter(_fmt)
h_out.setLevel(logging.INFO)

if not logger.handlers:
    logger.addHandler(h_file)
    logger.addHandler(h_out)


def log_with_context(
    level: str,
    message: str,
    game_id: Optional[int] = None,
    ext_id: Optional[str] = None,
    url: Optional[str] = None,
    duration_ms: Optional[float] = None,
    status: Optional[str] = None,
    stage: Optional[str] = None,
    backend: Optional[str] = None,
    attempt: Optional[int] = None,
    **extra_fields
) -> None:
    """
    Loga uma mensagem com contexto estruturado.
    
    Args:
        level: Nível do log (info, warning, error, debug, critical)
        message: Mensagem do log
        game_id: ID do jogo relacionado
        ext_id: ID externo do jogo
        url: URL relacionada
        duration_ms: Duração em milissegundos
        status: Status do processo
        stage: Etapa do processo
        backend: Backend usado
        attempt: Número da tentativa
        **extra_fields: Campos adicionais de contexto (serão expandidos diretamente)
    """
    extra = {}
    
    # Adicionar campos padrão
    if game_id is not None:
        extra['game_id'] = game_id
    if ext_id is not None:
        extra['ext_id'] = ext_id
    if url is not None:
        extra['url'] = url
    if duration_ms is not None:
        extra['duration_ms'] = duration_ms
    if status is not None:
        extra['status'] = status
    if stage is not None:
        extra['stage'] = stage
    if backend is not None:
        extra['backend'] = backend
    if attempt is not None:
        extra['attempt'] = attempt
    
    # Adicionar campos customizados (expandir extra_fields diretamente)
    for key, value in extra_fields.items():
        if value is not None:
            extra[key] = value
    
    if level == "debug":
        logger.debug(message, extra=extra)
    elif level == "info":
        logger.info(message, extra=extra)
    elif level == "warning":
        logger.warning(message, extra=extra)
    elif level == "error":
        logger.error(message, extra=extra)
    elif level == "critical":
        logger.critical(message, extra=extra)
    else:
        logger.info(message, extra=extra)

