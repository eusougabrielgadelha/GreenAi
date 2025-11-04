"""Envio de mensagens via Telegram."""
from typing import Optional
import requests
from config.settings import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID
from utils.logger import logger


def tg_send_message(text: str, parse_mode: Optional[str] = "HTML", message_type: Optional[str] = None, game_id: Optional[int] = None, ext_id: Optional[str] = None) -> None:
    """
    Usa HTML por padrão; omite parse_mode se None para evitar 400.
    
    Args:
        text: Texto da mensagem
        parse_mode: Modo de parsing (HTML, Markdown, None)
        message_type: Tipo da mensagem para analytics (pick_now, watch_upgrade, reminder, etc)
        game_id: ID do jogo relacionado (opcional)
        ext_id: ID externo do jogo (opcional)
    """
    from utils.analytics_logger import log_telegram_send
    
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Telegram não configurado (TOKEN/CHAT_ID ausentes).")
        log_telegram_send(
            message_type or "unknown",
            game_id=game_id,
            ext_id=ext_id,
            success=False,
            error="Telegram não configurado"
        )
        return
    
    # Detecta tipo de mensagem automaticamente se não fornecido
    if not message_type:
        if "PICK" in text.upper() or "PALPITE" in text.upper():
            message_type = "pick_now"
        elif "WATCHLIST" in text.upper() or "UPGRADE" in text.upper():
            message_type = "watch_upgrade"
        elif "LEMBRETE" in text.upper() or "REMINDER" in text.upper():
            message_type = "reminder"
        elif "RESUMO" in text.upper() or "SUMMARY" in text.upper():
            message_type = "summary"
        elif "AO VIVO" in text.upper() or "LIVE" in text.upper():
            message_type = "live_opportunity"
        else:
            message_type = "unknown"
    
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "disable_web_page_preview": True,
    }
    if parse_mode:  # só inclui quando tem valor válido
        payload["parse_mode"] = parse_mode
    try:
        r = requests.post(url, json=payload, timeout=15)
        if r.status_code != 200:
            error_msg = f"HTTP {r.status_code}: {r.text[:300]}"
            logger.error("Telegram %s: %s", r.status_code, r.text[:300])
            log_telegram_send(
                message_type,
                game_id=game_id,
                ext_id=ext_id,
                success=False,
                error=error_msg
            )
        else:
            log_telegram_send(
                message_type,
                game_id=game_id,
                ext_id=ext_id,
                success=True,
                metadata={"message_length": len(text)}
            )
    except Exception as e:
        error_msg = str(e)[:500]
        logger.exception("Erro Telegram: %s", e)
        log_telegram_send(
            message_type,
            game_id=game_id,
            ext_id=ext_id,
            success=False,
            error=error_msg
        )


def h(b: str) -> str:
    """Helper para texto em negrito HTML."""
    return f"<b>{b}</b>"

